from __future__ import annotations

from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .corpus import PaperCorpus
from .models import Evidence, Passage


@dataclass
class SearchHit:
    passage: Passage
    score: float


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
        return [
            Evidence(
                paper_id=hit.passage.paper_id,
                title=hit.passage.title,
                section=hit.passage.section,
                text=hit.passage.text,
                score=round(hit.score, 4),
            )
            for hit in self.search(query, top_k=top_k)
        ]
