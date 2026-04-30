from __future__ import annotations

import os
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any

from .llm import DashScopeLangChainClient, resolve_setting
from .logging_config import logger
from .models import Evidence
from .rag import LangChainVectorRAG
from .retrieval import BM25Retriever, QueryExpander, TfidfRetriever

TFIDF_WEIGHT = float(resolve_setting("HYBRID_TFIDF_WEIGHT") or 0.28)
BM25_WEIGHT = float(resolve_setting("HYBRID_BM25_WEIGHT") or 0.34)
VECTOR_WEIGHT = float(resolve_setting("HYBRID_VECTOR_WEIGHT") or 0.38)
QUERY_EXPANSION_DISCOUNT_STEP = float(resolve_setting("QUERY_EXPANSION_DISCOUNT_STEP") or 0.15)
QUERY_EXPANSION_DISCOUNT_FLOOR = float(resolve_setting("QUERY_EXPANSION_DISCOUNT_FLOOR") or 0.55)


@dataclass
class HybridResult:
    evidence: list[Evidence]
    trace: list[dict[str, str]]
    rerank_failed: bool = field(default=False)
    diagnostics: dict[str, Any] = field(default_factory=dict)


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

    def _elapsed_ms(self, started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 3)

    def _preview_evidence(self, evidence: list[Evidence], limit: int = 8) -> list[dict[str, Any]]:
        preview: list[dict[str, Any]] = []
        for rank, item in enumerate(evidence[:limit], start=1):
            compact_text = " ".join(item.text.split())
            preview.append(
                {
                    "rank": rank,
                    "paper_id": item.paper_id,
                    "title": item.title,
                    "section": item.section,
                    "score": item.score,
                    "text_preview": compact_text[:157].rstrip() + "..." if len(compact_text) > 160 else compact_text,
                }
            )
        return preview

    def _stage_record(
        self,
        name: str,
        *,
        status: str,
        input_value: str,
        top: list[Evidence] | None = None,
        enabled: bool = True,
        queries: list[str] | None = None,
        output_preview: list[str] | None = None,
        latency_ms: float | None = None,
        error: str = "",
        reason: str = "",
        method: str = "",
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "name": name,
            "status": status,
            "enabled": enabled,
            "input": input_value,
            "top": self._preview_evidence(top or []),
        }
        if queries is not None:
            record["queries"] = queries
        if output_preview is not None:
            record["output_preview"] = output_preview
        if latency_ms is not None:
            record["latency_ms"] = latency_ms
        if error:
            record["error"] = error
        if reason:
            record["reason"] = reason
        if method:
            record["method"] = method
        return record

    def _collect_keyword_hits(
        self,
        retriever: TfidfRetriever | BM25Retriever,
        queries: list[str],
        top_k: int,
        tool_name: str,
    ) -> tuple[list[Evidence], dict[str, str]]:
        merged: dict[tuple[str, str, str, int | None, str], Evidence] = {}
        trace_parts: list[str] = []

        for query_index, variant in enumerate(queries):
            discount = max(1.0 - QUERY_EXPANSION_DISCOUNT_STEP * query_index, QUERY_EXPANSION_DISCOUNT_FLOOR)
            hits = retriever.search_evidence(variant, top_k=top_k)
            trace_parts.append(f"{variant} => {', '.join(f'{item.paper_id}:{item.section}' for item in hits[:6])}")
            for hit in hits:
                key = (hit.paper_id, hit.section, hit.text, hit.page, hit.locator)
                adjusted_score = round(hit.score * discount, 6)
                existing = merged.get(key)
                if existing is None:
                    merged[key] = hit.model_copy(update={"score": adjusted_score})
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
        merged: dict[tuple[str, str, str, int | None, str], Evidence] = {}

        def add_hit(hit: Evidence, weight: float) -> None:
            key = (hit.paper_id, hit.section, hit.text, hit.page, hit.locator)
            adjusted_score = round(float(hit.score) * weight, 6)
            existing = merged.get(key)
            if existing is None:
                merged[key] = hit.model_copy(update={"score": adjusted_score})
                return
            existing.score = round(existing.score + adjusted_score, 6)

        for hit in tfidf_hits:
            add_hit(hit, TFIDF_WEIGHT)
        for hit in bm25_hits:
            add_hit(hit, BM25_WEIGHT)
        for hit in vector_hits:
            add_hit(hit, VECTOR_WEIGHT)

        return sorted(merged.values(), key=lambda item: item.score, reverse=True)

    def _rerank(self, query: str, candidates: list[Evidence], top_k: int) -> list[Evidence]:
        if not self.llm_client.rerank_enabled or not candidates:
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
            ordered.append(candidate.model_copy(update={"score": round(item.relevance_score, 4)}))
        return ordered[:top_k]

    def search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 12,
        use_rerank: bool = True,
    ) -> HybridResult:
        search_started_at = perf_counter()
        trace: list[dict[str, str]] = []
        stages: list[dict[str, Any]] = []
        diagnostics: dict[str, Any] = {
            "original_query": query,
            "requested_top_k": top_k,
            "candidate_k": candidate_k,
            "use_rerank": use_rerank,
            "pipeline_stages": stages,
            "fusion": {
                "enabled": True,
                "status": "pending",
                "failed": False,
                "skipped": False,
            },
            "rerank": {
                "requested": use_rerank,
                "enabled": bool(use_rerank and self.llm_client.rerank_enabled),
                "failed": False,
                "skipped": False,
                "status": "pending" if use_rerank else "skipped",
                "reason": "" if use_rerank else "use_rerank=false",
            },
        }

        stage_started_at = perf_counter()
        expanded_queries = self.query_expander.expand(query)
        stages.append(
            self._stage_record(
                "query_expansion",
                status="completed",
                input_value=query,
                queries=expanded_queries,
                output_preview=expanded_queries,
                latency_ms=self._elapsed_ms(stage_started_at),
            )
        )
        trace.append(
            {
                "tool": "query_expansion",
                "input": query,
                "output": " | ".join(expanded_queries),
            }
        )

        stage_started_at = perf_counter()
        tfidf_hits, tfidf_trace = self._collect_keyword_hits(
            self.tfidf_retriever,
            expanded_queries,
            top_k=candidate_k,
            tool_name="tfidf_retriever",
        )
        stages.append(
            self._stage_record(
                "tfidf",
                status="completed",
                input_value=" | ".join(expanded_queries),
                top=tfidf_hits,
                queries=expanded_queries,
                latency_ms=self._elapsed_ms(stage_started_at),
            )
        )
        trace.append(tfidf_trace)

        stage_started_at = perf_counter()
        bm25_hits, bm25_trace = self._collect_keyword_hits(
            self.bm25_retriever,
            expanded_queries,
            top_k=candidate_k,
            tool_name="bm25_retriever",
        )
        stages.append(
            self._stage_record(
                "bm25",
                status="completed",
                input_value=" | ".join(expanded_queries),
                top=bm25_hits,
                queries=expanded_queries,
                latency_ms=self._elapsed_ms(stage_started_at),
            )
        )
        trace.append(bm25_trace)

        vector_hits: list[Evidence] = []
        if self.vector_retriever.enabled:
            stage_started_at = perf_counter()
            try:
                vector_hits = self.vector_retriever.search_evidence(query, top_k=candidate_k)
                stages.append(
                    self._stage_record(
                        "vector",
                        status="completed",
                        input_value=query,
                        top=vector_hits,
                        latency_ms=self._elapsed_ms(stage_started_at),
                    )
                )
                trace.append(
                    {
                        "tool": "vector_retriever",
                        "input": query,
                        "output": ", ".join(f"{item.paper_id}:{item.section}" for item in vector_hits),
                    }
                )
            except Exception as exc:
                stages.append(
                    self._stage_record(
                        "vector",
                        status="failed",
                        input_value=query,
                        enabled=True,
                        latency_ms=self._elapsed_ms(stage_started_at),
                        error=str(exc),
                    )
                )
                trace.append(
                    {
                        "tool": "vector_retriever_error",
                        "input": query,
                        "output": str(exc),
                    }
                )
        else:
            stages.append(
                self._stage_record(
                    "vector",
                    status="skipped",
                    input_value=query,
                    enabled=False,
                    reason="vector_retriever_disabled",
                )
            )

        stage_started_at = perf_counter()
        merged = self._merge_candidates(tfidf_hits, bm25_hits, vector_hits)
        fusion_latency_ms = self._elapsed_ms(stage_started_at)
        diagnostics["fusion"] = {
            "enabled": True,
            "status": "completed",
            "failed": False,
            "skipped": False,
            "latency_ms": fusion_latency_ms,
        }
        stages.append(
            self._stage_record(
                "fusion",
                status="completed",
                input_value=query,
                top=merged[:candidate_k],
                latency_ms=fusion_latency_ms,
            )
        )
        trace.append(
            {
                "tool": "hybrid_fusion",
                "input": query,
                "output": ", ".join(f"{item.paper_id}:{item.section}" for item in merged[:candidate_k]),
            }
        )

        if not use_rerank:
            fusion_ranked = merged[:top_k]
            diagnostics["rerank"] = {
                "requested": False,
                "enabled": False,
                "failed": False,
                "skipped": True,
                "status": "skipped",
                "reason": "use_rerank=false",
            }
            stages.append(
                self._stage_record(
                    "final_rank",
                    status="completed",
                    input_value=query,
                    top=fusion_ranked,
                    method="fusion_rank",
                )
            )
            trace.append(
                {
                    "tool": "fusion_rank",
                    "input": query,
                    "output": ", ".join(f"{item.paper_id}:{item.section}" for item in fusion_ranked),
                }
            )
            diagnostics["latency_ms"] = self._elapsed_ms(search_started_at)
            return HybridResult(evidence=fusion_ranked, trace=trace, diagnostics=diagnostics)

        if not self.llm_client.rerank_enabled:
            fusion_ranked = merged[:top_k]
            diagnostics["rerank"] = {
                "requested": True,
                "enabled": False,
                "failed": False,
                "skipped": True,
                "status": "skipped",
                "reason": "rerank_disabled",
            }
            stages.append(
                self._stage_record(
                    "final_rank",
                    status="completed",
                    input_value=query,
                    top=fusion_ranked,
                    method="fusion_rank",
                    reason="rerank_unavailable",
                )
            )
            trace.append(
                {
                    "tool": "fusion_rank",
                    "input": query,
                    "output": ", ".join(f"{item.paper_id}:{item.section}" for item in fusion_ranked),
                }
            )
            diagnostics["latency_ms"] = self._elapsed_ms(search_started_at)
            return HybridResult(evidence=fusion_ranked, trace=trace, diagnostics=diagnostics)

        stage_started_at = perf_counter()
        try:
            reranked = self._rerank(query, merged[:candidate_k], top_k=top_k)
            if reranked:
                rerank_latency_ms = self._elapsed_ms(stage_started_at)
                diagnostics["rerank"] = {
                    "requested": True,
                    "enabled": True,
                    "failed": False,
                    "skipped": False,
                    "status": "completed",
                    "latency_ms": rerank_latency_ms,
                }
                stages.append(
                    self._stage_record(
                        "rerank",
                        status="completed",
                        input_value=query,
                        top=reranked,
                        latency_ms=rerank_latency_ms,
                        method="dashscope_rerank",
                    )
                )
                trace.append(
                    {
                        "tool": "dashscope_rerank",
                        "input": query,
                        "output": ", ".join(f"{item.paper_id}:{item.section}" for item in reranked),
                    }
                )
                diagnostics["latency_ms"] = self._elapsed_ms(search_started_at)
                return HybridResult(evidence=reranked, trace=trace, diagnostics=diagnostics)
        except Exception as exc:
            logger.warning(f"Rerank failed, falling back to fusion rank: {exc}")
            fallback = merged[:top_k]
            rerank_latency_ms = self._elapsed_ms(stage_started_at)
            diagnostics["rerank"] = {
                "requested": True,
                "enabled": True,
                "failed": True,
                "skipped": False,
                "status": "failed",
                "error": str(exc),
                "latency_ms": rerank_latency_ms,
            }
            stages.append(
                self._stage_record(
                    "rerank",
                    status="failed",
                    input_value=query,
                    top=fallback,
                    latency_ms=rerank_latency_ms,
                    error=str(exc),
                    method="dashscope_rerank",
                )
            )
            stages.append(
                self._stage_record(
                    "final_rank",
                    status="completed",
                    input_value=query,
                    top=fallback,
                    method="fusion_fallback",
                )
            )
            trace.append(
                {
                    "tool": "dashscope_rerank_error",
                    "input": query,
                    "output": str(exc),
                }
            )
            diagnostics["latency_ms"] = self._elapsed_ms(search_started_at)
            return HybridResult(evidence=fallback, trace=trace, rerank_failed=True, diagnostics=diagnostics)

        fallback = merged[:top_k]
        diagnostics["rerank"] = {
            "requested": True,
            "enabled": True,
            "failed": False,
            "skipped": True,
            "status": "skipped",
            "reason": "no_rerank_results",
        }
        stages.append(
            self._stage_record(
                "final_rank",
                status="completed",
                input_value=query,
                top=fallback,
                method="fusion_rank",
                reason="no_rerank_results",
            )
        )
        diagnostics["latency_ms"] = self._elapsed_ms(search_started_at)
        return HybridResult(evidence=fallback, trace=trace, diagnostics=diagnostics)

