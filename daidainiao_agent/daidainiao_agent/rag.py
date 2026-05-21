from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .corpus import PaperCorpus
from .llm import DashScopeLangChainClient
from .models import Evidence, Passage


INDEX_METADATA_VERSION = 2

BATCH_SAVE_THRESHOLD = 5


class LangChainVectorRAG:
    def __init__(
        self,
        corpus: PaperCorpus,
        llm_client: DashScopeLangChainClient,
        persist_dir: str | Path | None = None,
    ) -> None:
        self.corpus = corpus
        self.llm_client = llm_client
        self._vectorstore: FAISS | None = None
        self._lock = Lock()
        self.persist_dir = Path(persist_dir) if persist_dir else None
        self._loaded_from_disk = False
        self._pending_saves = 0
        self._local_documents: list[Document] = []
        self._local_matrix = None
        self._local_vectorizer: TfidfVectorizer | None = None

        if self.persist_dir:
            self.index_dir = self.persist_dir / "faiss_index"
            self.meta_path = self.persist_dir / "index_meta.json"
        else:
            self.index_dir = None
            self.meta_path = None

        # Try loading from disk on init if persist_dir is configured and index exists
        if self.persist_dir and self.index_dir and self.index_dir.exists() and self.enabled:
            try:
                embeddings = self.llm_client.embedding_client()
                self._vectorstore = FAISS.load_local(
                    str(self.index_dir), embeddings, allow_dangerous_deserialization=True
                )
                self._loaded_from_disk = True
            except Exception:
                self._loaded_from_disk = False

        # If loaded from disk but metadata is stale, rebuild from scratch
        if self._loaded_from_disk and self.needs_rebuild():
            try:
                self.build_index()
            except Exception:
                # Keep existing on-disk index when remote embedding is unavailable
                pass

    @property
    def enabled(self) -> bool:
        return True

    @property
    def remote_enabled(self) -> bool:
        return self.llm_client.embedding_enabled

    def reset(self) -> None:
        with self._lock:
            self._vectorstore = None
            self._loaded_from_disk = False
            self._local_documents = []
            self._local_matrix = None
            self._local_vectorizer = None

    def _document_for_passage(self, passage: Passage) -> Document:
        metadata = {
            "paper_id": passage.paper_id,
            "title": passage.title,
            "section": passage.section,
            "raw_text": passage.text,
            "source_url": passage.source_url,
            "source_label": passage.source_label,
            "page": passage.page,
            "locator": passage.locator,
        }
        return Document(
            page_content=f"Title: {passage.title}\nSection: {passage.section}\nText: {passage.text}",
            metadata=metadata,
        )

    def _evidence_from_document(self, document: Document, score: float) -> Evidence:
        page_value = document.metadata.get("page")
        try:
            page = int(page_value) if page_value not in (None, "") else None
        except (TypeError, ValueError):
            page = None
        return Evidence(
            paper_id=str(document.metadata.get("paper_id", "")),
            title=str(document.metadata.get("title", "")),
            section=str(document.metadata.get("section", "chunk")),
            text=str(document.metadata.get("raw_text") or document.page_content),
            score=round(float(score), 4),
            source_url=str(document.metadata.get("source_url", "")),
            source_label=str(document.metadata.get("source_label", "")),
            page=page,
            locator=str(document.metadata.get("locator", "")),
        )

    def _build_documents(self) -> list[Document]:
        return [self._document_for_passage(passage) for passage in self.corpus.passages]

    def _save_metadata(self) -> None:
        if not self.persist_dir:
            return
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "schema_version": INDEX_METADATA_VERSION,
            "num_documents": len(self._build_documents()),
            "doc_ids": [p.paper_id for p in self.corpus.papers],
        }
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def needs_rebuild(self) -> bool:
        if not self.meta_path or not self.meta_path.exists():
            return True
        try:
            with open(self.meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            saved_ids = set(meta.get("doc_ids", []))
            current_ids = {p.paper_id for p in self.corpus.papers}
            return (
                meta.get("schema_version") != INDEX_METADATA_VERSION
                or saved_ids != current_ids
                or int(meta.get("num_documents", -1)) != len(self.corpus.passages)
            )
        except Exception:
            return True

    def build_index(self) -> FAISS:
        if not self.remote_enabled:
            raise RuntimeError("DashScope embeddings are not available")
        with self._lock:
            documents = self._build_documents()
            embeddings = self.llm_client.embedding_client()
            self._vectorstore = FAISS.from_documents(documents, embeddings)
            self._loaded_from_disk = False
            if self.persist_dir and self.index_dir:
                self._vectorstore.save_local(str(self.index_dir))
                self._save_metadata()
            return self._vectorstore

    def _ensure_vectorstore(self) -> FAISS:
        if self._vectorstore is not None:
            return self._vectorstore
        if not self.remote_enabled:
            raise RuntimeError("DashScope embeddings are not available")
        with self._lock:
            if self._vectorstore is not None:
                return self._vectorstore
            documents = self._build_documents()
            embeddings = self.llm_client.embedding_client()
            self._vectorstore = FAISS.from_documents(documents, embeddings)
            if self.persist_dir and self.index_dir:
                self._vectorstore.save_local(str(self.index_dir))
                self._save_metadata()
            return self._vectorstore

    def build_documents_for_paper(self, paper_id: str) -> list[Document]:
        return [
            self._document_for_passage(passage)
            for passage in self.corpus.passages
            if passage.paper_id == paper_id
        ]

    def add_documents(self, documents: list[Document]) -> None:
        self._local_vectorizer = None
        self._local_matrix = None
        if not self.remote_enabled:
            return
        try:
            if self._vectorstore is None:
                self.build_index()
                return
            with self._lock:
                self._vectorstore.add_documents(documents)
                self._pending_saves += 1
                if self._pending_saves >= BATCH_SAVE_THRESHOLD:
                    if self.persist_dir and self.index_dir:
                        self._vectorstore.save_local(str(self.index_dir))
                        self._save_metadata()
                    self._pending_saves = 0
        except Exception:
            # Embedding API may be blocked on custom proxies; corpus import still succeeds.
            return

    def flush(self) -> None:
        """Force save index to disk regardless of batch threshold."""
        if not self.remote_enabled or self._vectorstore is None:
            return
        if not self.persist_dir or not self.index_dir:
            return
        with self._lock:
            if self._vectorstore is None:
                return
            self._vectorstore.save_local(str(self.index_dir))
            self._save_metadata()
            self._pending_saves = 0

    def _ensure_local_index(self) -> None:
        if self._local_vectorizer is not None and self._local_matrix is not None:
            return
        self._local_documents = self._build_documents()
        texts = [document.page_content for document in self._local_documents]
        self._local_vectorizer = TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 5),
            lowercase=True,
        )
        self._local_matrix = self._local_vectorizer.fit_transform(texts)

    def search_local_evidence(self, query: str, top_k: int = 5) -> list[Evidence]:
        with self._lock:
            self._ensure_local_index()
            if self._local_vectorizer is None or self._local_matrix is None:
                return []
            query_vec = self._local_vectorizer.transform([query])
            scores = cosine_similarity(query_vec, self._local_matrix).ravel()
            ranked_indexes = scores.argsort()[::-1]
            evidence: list[Evidence] = []
            for index in ranked_indexes:
                score = float(scores[index])
                if score <= 0:
                    continue
                evidence.append(self._evidence_from_document(self._local_documents[index], score))
                if len(evidence) >= top_k:
                    break
            return evidence

    def search_evidence(self, query: str, top_k: int = 5) -> list[Evidence]:
        if not self.remote_enabled:
            return self.search_local_evidence(query, top_k=top_k)
        vectorstore = self._ensure_vectorstore()
        try:
            hits = vectorstore.similarity_search_with_relevance_scores(query, k=top_k)
            evidence = []
            for document, score in hits:
                evidence.append(self._evidence_from_document(document, float(score)))
            return evidence
        except Exception:
            hits = vectorstore.similarity_search_with_score(query, k=top_k)
            evidence = []
            for document, distance in hits:
                score = 1.0 / (1.0 + float(distance))
                evidence.append(self._evidence_from_document(document, score))
            return evidence
