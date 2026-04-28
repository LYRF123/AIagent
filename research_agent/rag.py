from __future__ import annotations

from threading import Lock

from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document

from .corpus import PaperCorpus
from .llm import DashScopeLangChainClient
from .models import Evidence


class LangChainVectorRAG:
    def __init__(self, corpus: PaperCorpus, llm_client: DashScopeLangChainClient) -> None:
        self.corpus = corpus
        self.llm_client = llm_client
        self._vectorstore: FAISS | None = None
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return self.llm_client.enabled

    def reset(self) -> None:
        with self._lock:
            self._vectorstore = None

    def _build_documents(self) -> list[Document]:
        docs = []
        for passage in self.corpus.passages:
            docs.append(
                Document(
                    page_content=f"Title: {passage.title}\nSection: {passage.section}\nText: {passage.text}",
                    metadata={
                        "paper_id": passage.paper_id,
                        "title": passage.title,
                        "section": passage.section,
                        "raw_text": passage.text,
                    },
                )
            )
        return docs

    def _ensure_vectorstore(self) -> FAISS:
        if self._vectorstore is not None:
            return self._vectorstore
        if not self.enabled:
            raise RuntimeError("DashScope embeddings are not available")
        with self._lock:
            if self._vectorstore is not None:
                return self._vectorstore
            documents = self._build_documents()
            embeddings = self.llm_client.embedding_client()
            self._vectorstore = FAISS.from_documents(documents, embeddings)
            return self._vectorstore

    def search_evidence(self, query: str, top_k: int = 5) -> list[Evidence]:
        vectorstore = self._ensure_vectorstore()
        try:
            hits = vectorstore.similarity_search_with_relevance_scores(query, k=top_k)
            evidence = []
            for document, score in hits:
                evidence.append(
                    Evidence(
                        paper_id=str(document.metadata.get("paper_id", "")),
                        title=str(document.metadata.get("title", "")),
                        section=str(document.metadata.get("section", "chunk")),
                        text=str(document.metadata.get("raw_text") or document.page_content),
                        score=round(float(score), 4),
                    )
                )
            return evidence
        except Exception:
            hits = vectorstore.similarity_search_with_score(query, k=top_k)
            evidence = []
            for document, distance in hits:
                score = 1.0 / (1.0 + float(distance))
                evidence.append(
                    Evidence(
                        paper_id=str(document.metadata.get("paper_id", "")),
                        title=str(document.metadata.get("title", "")),
                        section=str(document.metadata.get("section", "chunk")),
                        text=str(document.metadata.get("raw_text") or document.page_content),
                        score=round(score, 4),
                    )
                )
            return evidence
