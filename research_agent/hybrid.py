from __future__ import annotations

from dataclasses import dataclass

from .llm import DashScopeLangChainClient
from .models import Evidence
from .rag import LangChainVectorRAG
from .retrieval import BM25Retriever, QueryExpander, TfidfRetriever


@dataclass
class HybridResult:
    evidence: list[Evidence]
    trace: list[dict[str, str]]


class HybridRetriever:
    def __init__(
        self,
        tfidf_retriever: TfidfRetriever,
        bm25_retriever: BM25Retriever,
        vector_retriever: LangChainVectorRAG,
        llm_client: DashScopeLangChainClient,
        query_expander: QueryExpander,
    ) -> None:
        self.tfidf_retriever = tfidf_retriever
        self.bm25_retriever = bm25_retriever
        self.vector_retriever = vector_retriever
        self.llm_client = llm_client
        self.query_expander = query_expander

    def _collect_keyword_hits(
        self,
        retriever: TfidfRetriever | BM25Retriever,
        queries: list[str],
        top_k: int,
        tool_name: str,
    ) -> tuple[list[Evidence], dict[str, str]]:
        merged: dict[tuple[str, str, str], Evidence] = {}
        trace_parts: list[str] = []

        for query_index, variant in enumerate(queries):
            discount = max(1.0 - 0.15 * query_index, 0.55)
            hits = retriever.search_evidence(variant, top_k=top_k)
            trace_parts.append(f"{variant} => {', '.join(f'{item.paper_id}:{item.section}' for item in hits[:6])}")
            for hit in hits:
                key = (hit.paper_id, hit.section, hit.text)
                adjusted_score = round(hit.score * discount, 6)
                existing = merged.get(key)
                if existing is None:
                    merged[key] = Evidence(
                        paper_id=hit.paper_id,
                        title=hit.title,
                        section=hit.section,
                        text=hit.text,
                        score=adjusted_score,
                    )
                    continue
                existing.score = round(max(existing.score, adjusted_score), 6)

        ranked = sorted(merged.values(), key=lambda item: item.score, reverse=True)
        trace = {
            "tool": tool_name,
            "input": " | ".join(queries),
            "output": " || ".join(trace_parts[:4]),
        }
        return ranked[:top_k], trace

    def _merge_candidates(
        self,
        tfidf_hits: list[Evidence],
        bm25_hits: list[Evidence],
        vector_hits: list[Evidence],
    ) -> list[Evidence]:
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

        for hit in tfidf_hits:
            add_hit(hit, 0.28)
        for hit in bm25_hits:
            add_hit(hit, 0.34)
        for hit in vector_hits:
            add_hit(hit, 0.38)

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
        expanded_queries = self.query_expander.expand(query)
        trace.append(
            {
                "tool": "query_expansion",
                "input": query,
                "output": " | ".join(expanded_queries),
            }
        )

        tfidf_hits, tfidf_trace = self._collect_keyword_hits(
            self.tfidf_retriever,
            expanded_queries,
            top_k=candidate_k,
            tool_name="tfidf_retriever",
        )
        trace.append(tfidf_trace)

        bm25_hits, bm25_trace = self._collect_keyword_hits(
            self.bm25_retriever,
            expanded_queries,
            top_k=candidate_k,
            tool_name="bm25_retriever",
        )
        trace.append(bm25_trace)

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

        merged = self._merge_candidates(tfidf_hits, bm25_hits, vector_hits)
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
                        "tool": "dashscope_rerank" if self.llm_client.enabled else "fusion_rank",
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

