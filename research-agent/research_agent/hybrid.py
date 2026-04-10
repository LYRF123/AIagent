from __future__ import annotations

from dataclasses import dataclass

from .llm import DashScopeLangChainClient
from .models import Evidence
from .rag import LangChainVectorRAG
from .retrieval import TfidfRetriever


@dataclass
class HybridResult:
    evidence: list[Evidence]
    trace: list[dict[str, str]]


class HybridRetriever:
    def __init__(
        self,
        keyword_retriever: TfidfRetriever,
        vector_retriever: LangChainVectorRAG,
        llm_client: DashScopeLangChainClient,
    ) -> None:
        self.keyword_retriever = keyword_retriever
        self.vector_retriever = vector_retriever
        self.llm_client = llm_client

    def _merge_candidates(self, keyword_hits: list[Evidence], vector_hits: list[Evidence]) -> list[Evidence]:
        merged: dict[tuple[str, str, str], Evidence] = {}

        def add_hit(hit: Evidence, weight: float) -> None:
            key = (hit.paper_id, hit.section, hit.text)
            adjusted_score = round(float(hit.score) * weight, 6)
            existing = merged.get(key)
            if existing is None:
                merged[key] = Evidence(
                    paper_id=hit.paper_id,
                    title=hit.title,
                    section=hit.section,
                    text=hit.text,
                    score=adjusted_score,
                )
                return
            existing.score = round(existing.score + adjusted_score, 6)

        for hit in keyword_hits:
            add_hit(hit, 0.45)
        for hit in vector_hits:
            add_hit(hit, 0.55)

        return sorted(merged.values(), key=lambda item: item.score, reverse=True)

    def _rerank(self, query: str, candidates: list[Evidence], top_k: int) -> list[Evidence]:
        if not self.llm_client.enabled or not candidates:
            return candidates[:top_k]
        documents = [f"Title: {item.title}\nSection: {item.section}\nText: {item.text}" for item in candidates]
        reranked = self.llm_client.rerank(query, documents, top_n=min(top_k, len(documents)))
        if not reranked:
            return candidates[:top_k]

        ordered: list[Evidence] = []
        for item in reranked:
            if item.index >= len(candidates):
                continue
            candidate = candidates[item.index]
            ordered.append(
                Evidence(
                    paper_id=candidate.paper_id,
                    title=candidate.title,
                    section=candidate.section,
                    text=candidate.text,
                    score=round(item.relevance_score, 4),
                )
            )
        return ordered[:top_k]

    def search(self, query: str, top_k: int = 5, candidate_k: int = 12) -> HybridResult:
        trace: list[dict[str, str]] = []
        keyword_hits = self.keyword_retriever.search_evidence(query, top_k=candidate_k)
        trace.append(
            {
                "tool": "keyword_retriever",
                "input": query,
                "output": ", ".join(f"{item.paper_id}:{item.section}" for item in keyword_hits),
            }
        )

        vector_hits: list[Evidence] = []
        if self.vector_retriever.enabled:
            try:
                vector_hits = self.vector_retriever.search_evidence(query, top_k=candidate_k)
                trace.append(
                    {
                        "tool": "vector_retriever",
                        "input": query,
                        "output": ", ".join(f"{item.paper_id}:{item.section}" for item in vector_hits),
                    }
                )
            except Exception as exc:
                trace.append(
                    {
                        "tool": "vector_retriever_error",
                        "input": query,
                        "output": str(exc),
                    }
                )

        merged = self._merge_candidates(keyword_hits, vector_hits)
        trace.append(
            {
                "tool": "hybrid_fusion",
                "input": query,
                "output": ", ".join(f"{item.paper_id}:{item.section}" for item in merged[:candidate_k]),
            }
        )

        try:
            reranked = self._rerank(query, merged[:candidate_k], top_k=top_k)
            if reranked:
                trace.append(
                    {
                        "tool": "dashscope_rerank",
                        "input": query,
                        "output": ", ".join(f"{item.paper_id}:{item.section}" for item in reranked),
                    }
                )
                return HybridResult(evidence=reranked, trace=trace)
        except Exception as exc:
            trace.append(
                {
                    "tool": "dashscope_rerank_error",
                    "input": query,
                    "output": str(exc),
                }
            )

        return HybridResult(evidence=merged[:top_k], trace=trace)
