from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
import gc
import threading
from time import perf_counter
from typing import Any, Callable
import re

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
FUSION_METHOD = (resolve_setting("HYBRID_FUSION_METHOD", default="rrf") or "rrf").strip().lower()
RRF_K = float(resolve_setting("HYBRID_RRF_K") or 60)
LOCAL_RERANK_MODEL_PATH = resolve_setting("LOCAL_RERANK_MODEL_PATH", default="data/models/bge-reranker-base")
LOCAL_RERANK_IDLE_TTL_SECONDS = float(resolve_setting("LOCAL_RERANK_IDLE_TTL_SECONDS") or 300)


_LOCAL_RERANKER: Any | None = None
_LOCAL_RERANKER_TIMER: threading.Timer | None = None
_LOCAL_RERANKER_LOCK = threading.Lock()


class LocalCrossEncoderReranker:
    def __init__(self, model_path: str | Path) -> None:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        import torch

        self.torch = torch
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path, local_files_only=True)
        self.model.to(self.device)
        self.model.eval()
        self.method = "local_cross_encoder_rerank"

    def score(self, query: str, candidates: list[Evidence]) -> list[float]:
        texts = [f"{item.title}\n{item.section}\n{item.text}" for item in candidates]
        inputs = self.tokenizer(
            [query] * len(texts),
            texts,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.no_grad():
            logits = self.model(**inputs).logits
        return logits.view(-1).detach().cpu().tolist()

    def close(self) -> None:
        model = getattr(self, "model", None)
        if model is not None:
            model.to("cpu")
        self.model = None
        self.tokenizer = None
        torch = getattr(self, "torch", None)
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()


def get_local_reranker() -> LocalCrossEncoderReranker | None:
    global _LOCAL_RERANKER
    model_path = Path(LOCAL_RERANK_MODEL_PATH or "")
    if not model_path.is_absolute():
        model_path = Path(__file__).resolve().parent.parent / model_path
    if not model_path.exists():
        return None
    with _LOCAL_RERANKER_LOCK:
        if _LOCAL_RERANKER is None:
            _LOCAL_RERANKER = LocalCrossEncoderReranker(model_path)
        return _LOCAL_RERANKER


def schedule_local_reranker_unload() -> None:
    global _LOCAL_RERANKER_TIMER
    with _LOCAL_RERANKER_LOCK:
        if _LOCAL_RERANKER is None:
            return
        if _LOCAL_RERANKER_TIMER is not None:
            _LOCAL_RERANKER_TIMER.cancel()
        _LOCAL_RERANKER_TIMER = threading.Timer(LOCAL_RERANK_IDLE_TTL_SECONDS, unload_local_reranker)
        _LOCAL_RERANKER_TIMER.daemon = True
        _LOCAL_RERANKER_TIMER.start()


def unload_local_reranker() -> None:
    global _LOCAL_RERANKER, _LOCAL_RERANKER_TIMER
    with _LOCAL_RERANKER_LOCK:
        reranker = _LOCAL_RERANKER
        _LOCAL_RERANKER = None
        if _LOCAL_RERANKER_TIMER is not None:
            _LOCAL_RERANKER_TIMER.cancel()
        _LOCAL_RERANKER_TIMER = None
    if reranker is not None:
        reranker.close()


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
        if FUSION_METHOD == "score_sum":
            return self._merge_candidates_by_score(tfidf_hits, bm25_hits, vector_hits)

        merged: dict[tuple[str, str, str, int | None, str], Evidence] = {}

        def add_ranked_hits(hits: list[Evidence], weight: float) -> None:
            max_source_score = max((abs(float(hit.score)) for hit in hits), default=0.0)
            for rank, hit in enumerate(hits, start=1):
                key = (hit.paper_id, hit.section, hit.text, hit.page, hit.locator)
                normalized_source_score = 0.0
                if max_source_score > 0:
                    normalized_source_score = max(0.0, min(1.0, float(hit.score) / max_source_score))
                rank_component = 1.0 / (RRF_K + rank)
                score_component = weight * rank_component * (0.7 + 0.3 * normalized_source_score)
                existing = merged.get(key)
                if existing is None:
                    merged[key] = hit.model_copy(update={"score": round(score_component, 8)})
                    continue
                existing.score = round(existing.score + score_component, 8)

        add_ranked_hits(tfidf_hits, TFIDF_WEIGHT)
        add_ranked_hits(bm25_hits, BM25_WEIGHT)
        add_ranked_hits(vector_hits, VECTOR_WEIGHT)

        max_merged_score = max((item.score for item in merged.values()), default=0.0)
        normalized = [
            item.model_copy(update={"score": round(item.score / max_merged_score, 6)})
            if max_merged_score > 0
            else item
            for item in merged.values()
        ]
        return sorted(normalized, key=lambda item: item.score, reverse=True)

    def _merge_candidates_by_score(
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

    def _local_rerank(self, query: str, candidates: list[Evidence], top_k: int) -> list[Evidence]:
        cross_encoder = get_local_reranker()
        if cross_encoder is not None:
            return self._local_cross_encoder_rerank(query, candidates, top_k, cross_encoder)
        return self._heuristic_rerank(query, candidates, top_k)

    def _local_cross_encoder_rerank(
        self,
        query: str,
        candidates: list[Evidence],
        top_k: int,
        cross_encoder: LocalCrossEncoderReranker,
    ) -> list[Evidence]:
        if not candidates:
            return []
        try:
            scores = cross_encoder.score(query, candidates)
        finally:
            schedule_local_reranker_unload()
        ranked = sorted(zip(candidates, scores), key=lambda item: item[1], reverse=True)
        best = ranked[0][1]
        worst = ranked[-1][1]
        spread = best - worst
        reranked: list[Evidence] = []
        for item, score in ranked[:top_k]:
            normalized = 1.0 if spread <= 1e-9 else (score - worst) / spread
            reranked.append(item.model_copy(update={"score": round(float(normalized), 6)}))
        return reranked

    def _heuristic_rerank(self, query: str, candidates: list[Evidence], top_k: int) -> list[Evidence]:
        if not candidates:
            return []
        query_tokens = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", query.lower()))
        query_chars = {char for char in query.lower() if not char.isspace()}
        section_rank = {"summary": 0, "methods": 1, "findings": 2, "limitations": 3, "topics": 4}

        def local_score(item: Evidence) -> float:
            text = f"{item.title} {item.section} {item.text}".lower()
            text_tokens = set(re.findall(r"[a-z0-9\u4e00-\u9fff]+", text))
            token_overlap = len(query_tokens & text_tokens) / max(len(query_tokens), 1)
            char_overlap = len(query_chars & set(text)) / max(len(query_chars), 1)
            source_score = max(0.0, min(1.0, float(item.score)))
            section_bonus = max(0.0, 0.08 - 0.02 * section_rank.get(item.section, 4))
            return 0.58 * source_score + 0.28 * token_overlap + 0.12 * char_overlap + section_bonus

        ranked = sorted(candidates, key=local_score, reverse=True)
        best = local_score(ranked[0]) or 1.0
        return [
            item.model_copy(update={"score": round(local_score(item) / best, 6)})
            for item in ranked[:top_k]
        ]

    def _notify_stage(
        self,
        on_stage: Callable[[str, str], None] | None,
        name: str,
        status: str = "completed",
    ) -> None:
        if on_stage is not None:
            on_stage(name, status)

    def search(
        self,
        query: str,
        top_k: int = 5,
        candidate_k: int = 12,
        use_rerank: bool = True,
        on_stage: Callable[[str, str], None] | None = None,
    ) -> HybridResult:
        search_started_at = perf_counter()
        trace: list[dict[str, str]] = []
        stages: list[dict[str, Any]] = []
        diagnostics: dict[str, Any] = {
            "original_query": query,
            "requested_top_k": top_k,
            "candidate_k": candidate_k,
            "use_rerank": use_rerank,
            "fusion_method": FUSION_METHOD,
            "pipeline_stages": stages,
            "fusion": {
                "enabled": True,
                "status": "pending",
                "failed": False,
                "skipped": False,
                "method": FUSION_METHOD,
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
        self._notify_stage(on_stage, "tfidf")

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
        self._notify_stage(on_stage, "bm25")

        vector_hits: list[Evidence] = []
        if self.vector_retriever.enabled:
            stage_started_at = perf_counter()
            try:
                vector_hits = self.vector_retriever.search_evidence(query, top_k=candidate_k)
                vector_method = "remote_embedding" if getattr(self.vector_retriever, "remote_enabled", False) else "local_tfidf_vector"
                stages.append(
                    self._stage_record(
                        "vector",
                        status="completed",
                        input_value=query,
                        top=vector_hits,
                        latency_ms=self._elapsed_ms(stage_started_at),
                        method=vector_method,
                    )
                )
                trace.append(
                    {
                        "tool": "vector_retriever",
                        "input": query,
                        "output": f"{vector_method}: " + ", ".join(f"{item.paper_id}:{item.section}" for item in vector_hits),
                    }
                )
                self._notify_stage(on_stage, "vector")
            except Exception as exc:
                remote_error = str(exc)
                try:
                    vector_hits = self.vector_retriever.search_local_evidence(query, top_k=candidate_k)
                    stages.append(
                        self._stage_record(
                            "vector",
                            status="completed",
                            input_value=query,
                            top=vector_hits,
                            latency_ms=self._elapsed_ms(stage_started_at),
                            method="local_tfidf_vector",
                            reason=f"remote_failed: {remote_error}",
                        )
                    )
                    trace.append(
                        {
                            "tool": "local_vector_retriever",
                            "input": query,
                            "output": ", ".join(f"{item.paper_id}:{item.section}" for item in vector_hits),
                        }
                    )
                    self._notify_stage(on_stage, "vector")
                except Exception as local_exc:
                    stages.append(
                        self._stage_record(
                            "vector",
                            status="failed",
                            input_value=query,
                            enabled=True,
                            latency_ms=self._elapsed_ms(stage_started_at),
                            error=f"{remote_error}; local fallback failed: {local_exc}",
                        )
                    )
                    trace.append(
                        {
                            "tool": "vector_retriever_error",
                            "input": query,
                            "output": f"{remote_error}; local fallback failed: {local_exc}",
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
            self._notify_stage(on_stage, "vector", "skipped")

        stage_started_at = perf_counter()
        merged = self._merge_candidates(tfidf_hits, bm25_hits, vector_hits)
        fusion_latency_ms = self._elapsed_ms(stage_started_at)
        diagnostics["fusion"] = {
            "enabled": True,
            "status": "completed",
            "failed": False,
            "skipped": False,
            "method": FUSION_METHOD,
            "latency_ms": fusion_latency_ms,
        }
        stages.append(
            self._stage_record(
                "fusion",
                status="completed",
                input_value=query,
                top=merged[:candidate_k],
                latency_ms=fusion_latency_ms,
                method=FUSION_METHOD,
            )
        )
        trace.append(
            {
                "tool": "hybrid_fusion",
                "input": query,
                "output": ", ".join(f"{item.paper_id}:{item.section}" for item in merged[:candidate_k]),
            }
        )
        self._notify_stage(on_stage, "fusion")

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
            self._notify_stage(on_stage, "rerank", "skipped")
            return HybridResult(evidence=fusion_ranked, trace=trace, diagnostics=diagnostics)

        if not self.llm_client.rerank_enabled:
            stage_started_at = perf_counter()
            fusion_ranked = self._local_rerank(query, merged[:candidate_k], top_k=top_k)
            rerank_latency_ms = self._elapsed_ms(stage_started_at)
            rerank_method = "local_cross_encoder_rerank" if _LOCAL_RERANKER is not None else "local_heuristic_rerank"
            diagnostics["rerank"] = {
                "requested": True,
                "enabled": True,
                "failed": False,
                "skipped": False,
                "status": "completed",
                "reason": "local_fallback_rerank",
                "latency_ms": rerank_latency_ms,
            }
            stages.append(
                self._stage_record(
                    "rerank",
                    status="completed",
                    input_value=query,
                    top=fusion_ranked,
                    latency_ms=rerank_latency_ms,
                    method=rerank_method,
                    reason="remote_rerank_disabled",
                )
            )
            trace.append(
                {
                    "tool": "local_rerank",
                    "input": query,
                    "output": ", ".join(f"{item.paper_id}:{item.section}" for item in fusion_ranked),
                }
            )
            diagnostics["latency_ms"] = self._elapsed_ms(search_started_at)
            self._notify_stage(on_stage, "rerank")
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
                self._notify_stage(on_stage, "rerank")
                return HybridResult(evidence=reranked, trace=trace, diagnostics=diagnostics)
        except Exception as exc:
            logger.warning(f"Rerank failed, falling back to local rerank: {exc}")
            fallback = self._local_rerank(query, merged[:candidate_k], top_k=top_k)
            rerank_latency_ms = self._elapsed_ms(stage_started_at)
            rerank_method = "local_cross_encoder_rerank" if _LOCAL_RERANKER is not None else "local_heuristic_rerank"
            diagnostics["rerank"] = {
                "requested": True,
                "enabled": True,
                "failed": False,
                "skipped": False,
                "status": "completed",
                "reason": f"remote_failed_local_fallback: {exc}",
                "latency_ms": rerank_latency_ms,
            }
            stages.append(
                self._stage_record(
                    "rerank",
                    status="completed",
                    input_value=query,
                    top=fallback,
                    latency_ms=rerank_latency_ms,
                    method=rerank_method,
                    reason=f"remote_failed: {exc}",
                )
            )
            trace.append(
                {
                    "tool": "local_rerank",
                    "input": query,
                    "output": ", ".join(f"{item.paper_id}:{item.section}" for item in fallback),
                }
            )
            diagnostics["latency_ms"] = self._elapsed_ms(search_started_at)
            self._notify_stage(on_stage, "rerank")
            return HybridResult(evidence=fallback, trace=trace, rerank_failed=False, diagnostics=diagnostics)

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
