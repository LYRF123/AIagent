from __future__ import annotations

from dataclasses import dataclass
from math import log
import re

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .corpus import PaperCorpus
from .models import Evidence, Passage


@dataclass
class SearchHit:
    passage: Passage
    score: float


TOKEN_PATTERN = re.compile(r"[a-z0-9\u4e00-\u9fff]+")
QUERY_SYNONYMS = {
    "rag": "retrieval augmented generation",
    "qa": "question answering",
    "llm": "language model",
    "api": "tool use",
    "multiagent": "multi agent",
    "multi-agent": "multi agent",
    "react": "reasoning and acting",
}


def tokenize_text(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(value.lower())


def evidence_from_hit(hit: SearchHit) -> Evidence:
    passage = hit.passage
    return Evidence(
        paper_id=passage.paper_id,
        title=passage.title,
        section=passage.section,
        text=passage.text,
        score=round(hit.score, 4),
        source_url=passage.source_url,
        source_label=passage.source_label,
        page=passage.page,
        locator=passage.locator,
    )


class QueryExpander:
    def __init__(self, corpus: PaperCorpus) -> None:
        self.topic_phrases = sorted(
            {
                topic
                for paper in corpus.papers
                for topic in paper.topics
                if len(topic.split()) >= 2
            }
        )

    def expand(self, query: str, limit: int = 4) -> list[str]:
        normalized = " ".join(query.split())
        if not normalized:
            return [query]

        variants: list[str] = [normalized]
        tokens = tokenize_text(normalized)

        for token in tokens:
            synonym = QUERY_SYNONYMS.get(token)
            if synonym:
                variants.append(f"{normalized} {synonym}".strip())

        token_set = set(tokens)
        for phrase in self.topic_phrases:
            phrase_tokens = set(tokenize_text(phrase))
            if not phrase_tokens:
                continue
            if token_set & phrase_tokens and phrase not in normalized.lower():
                variants.append(f"{normalized} {phrase}".strip())
            if len(variants) >= limit:
                break

        deduped: list[str] = []
        seen: set[str] = set()
        for variant in variants:
            compact = " ".join(variant.split())
            if compact.lower() in seen:
                continue
            deduped.append(compact)
            seen.add(compact.lower())
            if len(deduped) >= limit:
                break
        return deduped


class TfidfRetriever:
    def __init__(self, corpus: PaperCorpus) -> None:
        self.corpus = corpus
        self.vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        self.texts = [
            f"{passage.title} {passage.section} {passage.text}"
            for passage in corpus.passages
        ]
        self.matrix = self.vectorizer.fit_transform(self.texts)

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        query_vec = self.vectorizer.transform([query])
        scores = cosine_similarity(query_vec, self.matrix).ravel()
        ranked_indexes = scores.argsort()[::-1]
        hits: list[SearchHit] = []
        for index in ranked_indexes:
            score = float(scores[index])
            if score <= 0:
                continue
            hits.append(SearchHit(passage=self.corpus.passages[index], score=score))
            if len(hits) >= top_k:
                break
        return hits

    def search_evidence(self, query: str, top_k: int = 5) -> list[Evidence]:
        return [evidence_from_hit(hit) for hit in self.search(query, top_k=top_k)]

    def add_passages(self, passages: list[Passage]) -> None:
        """Incrementally add new passages without full rebuild."""
        new_texts = [
            f"{passage.title} {passage.section} {passage.text}"
            for passage in passages
        ]
        if not new_texts:
            return
        new_matrix = self.vectorizer.transform(new_texts)
        import scipy.sparse
        self.matrix = scipy.sparse.vstack([self.matrix, new_matrix])
        self.texts.extend(new_texts)


class BM25Retriever:
    def __init__(self, corpus: PaperCorpus, k1: float = 1.5, b: float = 0.75) -> None:
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.documents = [
            tokenize_text(f"{passage.title} {passage.section} {passage.text}")
            for passage in corpus.passages
        ]
        self.doc_lengths = [max(len(doc), 1) for doc in self.documents]
        self.avg_doc_length = sum(self.doc_lengths) / max(len(self.doc_lengths), 1)
        self.term_frequencies: list[dict[str, int]] = []
        self.document_frequencies: dict[str, int] = {}

        for doc in self.documents:
            frequencies: dict[str, int] = {}
            for token in doc:
                frequencies[token] = frequencies.get(token, 0) + 1
            self.term_frequencies.append(frequencies)
            for token in frequencies:
                self.document_frequencies[token] = self.document_frequencies.get(token, 0) + 1

    def _idf(self, token: str) -> float:
        total_docs = max(len(self.documents), 1)
        doc_freq = self.document_frequencies.get(token, 0)
        return log(1 + ((total_docs - doc_freq + 0.5) / (doc_freq + 0.5)))

    def search(self, query: str, top_k: int = 5) -> list[SearchHit]:
        query_tokens = tokenize_text(query)
        if not query_tokens:
            return []

        scored_hits: list[SearchHit] = []
        for index, frequencies in enumerate(self.term_frequencies):
            score = 0.0
            doc_length = self.doc_lengths[index]
            for token in query_tokens:
                term_freq = frequencies.get(token, 0)
                if term_freq <= 0:
                    continue
                numerator = term_freq * (self.k1 + 1)
                denominator = term_freq + self.k1 * (1 - self.b + self.b * (doc_length / self.avg_doc_length))
                score += self._idf(token) * (numerator / denominator)
            if score <= 0:
                continue
            scored_hits.append(SearchHit(passage=self.corpus.passages[index], score=score))

        ranked = sorted(scored_hits, key=lambda item: item.score, reverse=True)[:top_k]
        if not ranked:
            return []

        max_score = max(item.score for item in ranked) or 1.0
        return [SearchHit(passage=item.passage, score=float(item.score / max_score)) for item in ranked]

    def search_evidence(self, query: str, top_k: int = 5) -> list[Evidence]:
        return [evidence_from_hit(hit) for hit in self.search(query, top_k=top_k)]

    def add_passages(self, passages: list[Passage]) -> None:
        """Incrementally add new passages without full rebuild."""
        for passage in passages:
            doc = tokenize_text(f"{passage.title} {passage.section} {passage.text}")
            self.documents.append(doc)
            doc_len = max(len(doc), 1)
            self.doc_lengths.append(doc_len)

            frequencies: dict[str, int] = {}
            for token in doc:
                frequencies[token] = frequencies.get(token, 0) + 1
            self.term_frequencies.append(frequencies)
            for token in frequencies:
                self.document_frequencies[token] = self.document_frequencies.get(token, 0) + 1

            total = max(len(self.documents), 1)
            self.avg_doc_length = sum(self.doc_lengths) / total
