from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .agent import ResearchAssistant
from .evaluation import load_eval_cases
from .models import EvalCase, Evidence


LAB_METRICS = ("hit_at_k", "recall_like_at_k", "mrr", "keyword_coverage")
DEFAULT_TOP_K = 5
_RERANK_VERDICTS = {"helped", "hurt", "no_op", "unavailable", "failed"}


@dataclass(frozen=True)
class RagLabConfig:
    config_id: str
    top_k: int = DEFAULT_TOP_K
    candidate_k: int = 20
    use_rerank: bool = True
    chunk_size: int | None = None
    chunk_overlap: int | None = None
    split_mode: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return {
            "config_id": self.config_id,
            "top_k": self.top_k,
            "candidate_k": self.candidate_k,
            "use_rerank": self.use_rerank,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "split_mode": self.split_mode,
        }


def _parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "y", "on"}:
            return True
        if normalized in {"false", "0", "no", "n", "off"}:
            return False
    return default


def _parse_optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_positive_int(value: Any, default: int, minimum: int = 1) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(parsed, minimum)


def normalize_lab_configs(
    configs: Sequence[Mapping[str, Any]] | None = None,
    default_top_k: int = DEFAULT_TOP_K,
    default_candidate_k: int | None = None,
) -> list[RagLabConfig]:
    top_k = _parse_positive_int(default_top_k, DEFAULT_TOP_K)
    candidate_k = _parse_positive_int(default_candidate_k, max(top_k * 4, top_k), minimum=top_k)

    raw_configs: list[Mapping[str, Any]]
    if configs:
        raw_configs = list(configs)
    else:
        raw_configs = [
            {
                "config_id": f"fusion_top{top_k}",
                "top_k": top_k,
                "candidate_k": candidate_k,
                "use_rerank": False,
            },
            {
                "config_id": f"rerank_top{top_k}",
                "top_k": top_k,
                "candidate_k": candidate_k,
                "use_rerank": True,
            },
        ]

    normalized: list[RagLabConfig] = []
    seen_ids: dict[str, int] = {}
    for index, raw in enumerate(raw_configs, start=1):
        config_top_k = _parse_positive_int(raw.get("top_k"), top_k)
        config_candidate_k = _parse_positive_int(
            raw.get("candidate_k"),
            max(config_top_k * 4, config_top_k),
            minimum=config_top_k,
        )
        base_id = str(
            raw.get("config_id")
            or raw.get("id")
            or raw.get("name")
            or f"config_{index}"
        ).strip() or f"config_{index}"
        duplicate_count = seen_ids.get(base_id, 0)
        seen_ids[base_id] = duplicate_count + 1
        config_id = base_id if duplicate_count == 0 else f"{base_id}_{duplicate_count + 1}"
        normalized.append(
            RagLabConfig(
                config_id=config_id,
                top_k=config_top_k,
                candidate_k=config_candidate_k,
                use_rerank=_parse_bool(raw.get("use_rerank", raw.get("rerank")), default=True),
                chunk_size=_parse_optional_int(raw.get("chunk_size")),
                chunk_overlap=_parse_optional_int(raw.get("chunk_overlap")),
                split_mode=str(raw.get("split_mode")).strip() if raw.get("split_mode") not in (None, "") else None,
            )
        )
    return normalized


def load_lab_cases(
    eval_path: str | Path | None = None,
    cases: Iterable[EvalCase | Mapping[str, Any]] | None = None,
) -> list[EvalCase]:
    if cases is None:
        return load_eval_cases(eval_path)
    return [
        item if isinstance(item, EvalCase) else EvalCase.model_validate(item)
        for item in cases
    ]


def compact_preview(value: str, limit: int = 220) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _matched_keywords(text: str, expected_keywords: Sequence[str]) -> list[str]:
    lowered = text.lower()
    matches: list[str] = []
    for keyword in expected_keywords:
        normalized = keyword.strip().lower()
        if normalized and normalized in lowered:
            matches.append(keyword)
    return matches


def calculate_retrieval_metrics(case: EvalCase, evidence: Sequence[Evidence]) -> dict[str, Any]:
    expected_ids = set(case.expected_paper_ids)
    ranked_ids = [item.paper_id for item in evidence]
    expected_best_rank: int | None = None
    for index, paper_id in enumerate(ranked_ids, start=1):
        if paper_id in expected_ids:
            expected_best_rank = index
            break

    present_expected_ids = expected_ids.intersection(ranked_ids)
    joined_text = " ".join(item.text for item in evidence)
    keyword_matches = _matched_keywords(joined_text, case.expected_keywords)
    keyword_total = len(case.expected_keywords)
    keyword_coverage = 1.0 if keyword_total == 0 else len(set(keyword_matches)) / keyword_total

    return {
        "hit_at_k": 1.0 if expected_best_rank is not None else 0.0,
        "recall_like_at_k": round(len(present_expected_ids) / max(len(expected_ids), 1), 4),
        "mrr": round((1.0 / expected_best_rank) if expected_best_rank else 0.0, 4),
        "keyword_coverage": round(keyword_coverage, 4),
        "keyword_matches": sorted(set(keyword_matches), key=lambda item: case.expected_keywords.index(item)),
        "keyword_total": keyword_total,
        "expected_best_rank": expected_best_rank,
    }


def build_evidence_preview(case: EvalCase, evidence: Sequence[Evidence]) -> list[dict[str, Any]]:
    expected_ids = set(case.expected_paper_ids)
    return [
        {
            "rank": rank,
            "paper_id": item.paper_id,
            "title": item.title,
            "section": item.section,
            "score": item.score,
            "expected_paper": item.paper_id in expected_ids,
            "keyword_hits": _matched_keywords(item.text, case.expected_keywords),
            "text_preview": compact_preview(item.text),
        }
        for rank, item in enumerate(evidence, start=1)
    ]


def _flight_evidence_preview(evidence: Sequence[Evidence], limit: int = 8) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for rank, item in enumerate(evidence[:limit], start=1):
        preview.append(
            {
                "rank": rank,
                "paper_id": item.paper_id,
                "title": item.title,
                "section": item.section,
                "score": item.score,
                "text_preview": compact_preview(item.text, limit=160),
            }
        )
    return preview


def _trace_tool_to_stage(tool: str) -> str:
    mapping = {
        "query_expansion": "query_expansion",
        "tfidf_retriever": "tfidf",
        "bm25_retriever": "bm25",
        "vector_retriever": "vector",
        "vector_retriever_error": "vector",
        "hybrid_fusion": "fusion",
        "dashscope_rerank": "rerank",
        "dashscope_rerank_error": "rerank",
        "fusion_rank": "final_rank",
    }
    return mapping.get(tool, tool or "unknown")


def _parse_trace_top(output: str, limit: int = 8) -> list[dict[str, Any]]:
    top: list[dict[str, Any]] = []
    normalized = output.replace("||", ",")
    for raw_part in normalized.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "=>" in part:
            part = part.split("=>", 1)[1].strip()
        if not part:
            continue
        token = part.split()[0].strip()
        if not token:
            continue
        if ":" in token:
            paper_id, section = token.split(":", 1)
        else:
            paper_id, section = token, ""
        top.append(
            {
                "rank": len(top) + 1,
                "paper_id": paper_id,
                "section": section,
                "score": None,
            }
        )
        if len(top) >= limit:
            break
    return top


def _normalize_stage_record(stage: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(stage)
    record.setdefault("name", record.get("tool", "unknown"))
    record.setdefault("status", "completed")
    record.setdefault("enabled", True)
    record.setdefault("top", [])
    return record


def _stage_placeholder(name: str, question: str) -> dict[str, Any]:
    return {
        "name": name,
        "status": "unavailable",
        "enabled": False,
        "input": question,
        "top": [],
        "reason": "stage_not_reported",
    }


def _ensure_flight_stage_order(stages: Sequence[Mapping[str, Any]], question: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for stage in stages:
        record = _normalize_stage_record(stage)
        name = str(record.get("name") or "unknown")
        buckets.setdefault(name, []).append(record)

    ordered: list[dict[str, Any]] = []
    for name in ("query_expansion", "tfidf", "bm25"):
        ordered.extend(buckets.pop(name, []) or [_stage_placeholder(name, question)])

    vector_stages = buckets.pop("vector", [])
    if vector_stages:
        ordered.extend(vector_stages)

    ordered.extend(buckets.pop("fusion", []) or [_stage_placeholder("fusion", question)])

    for name in list(buckets):
        if name not in {"rerank", "final_rank"}:
            ordered.extend(buckets.pop(name))
    ordered.extend(buckets.pop("rerank", []))
    ordered.extend(buckets.pop("final_rank", []))

    for remaining in buckets.values():
        ordered.extend(remaining)
    return ordered


def _stages_from_trace(trace: Sequence[Mapping[str, Any]], evidence: Sequence[Evidence]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for item in trace:
        tool = str(item.get("tool", ""))
        stage_name = _trace_tool_to_stage(tool)
        output = str(item.get("output", ""))
        top = _parse_trace_top(output)
        if stage_name in {"rerank", "final_rank"} and evidence:
            top = _flight_evidence_preview(evidence)
        stage = {
            "name": stage_name,
            "tool": tool,
            "status": "failed" if tool.endswith("_error") else "completed",
            "enabled": not tool.endswith("_error"),
            "input": str(item.get("input", "")),
            "top": top,
        }
        if stage_name == "query_expansion":
            stage["queries"] = [part.strip() for part in output.split("|") if part.strip()]
            stage["output_preview"] = stage["queries"]
        if tool.endswith("_error"):
            stage["error"] = output
        stages.append(stage)
    return stages


def build_flight_recorder(
    case: EvalCase,
    config: RagLabConfig,
    retrieval: Any | None,
    evidence: Sequence[Evidence],
    *,
    rerank_enabled: bool,
    rerank_failed: bool,
    error: str = "",
) -> dict[str, Any]:
    diagnostics = getattr(retrieval, "diagnostics", {}) or {}
    trace = list(getattr(retrieval, "trace", []) or [])
    raw_stages = diagnostics.get("pipeline_stages") or diagnostics.get("stages") or []
    stages = (
        [_normalize_stage_record(stage) for stage in raw_stages if isinstance(stage, Mapping)]
        if raw_stages
        else _stages_from_trace(trace, evidence)
    )

    if error:
        stages.append(
            {
                "name": "search",
                "status": "failed",
                "enabled": True,
                "input": case.question,
                "top": [],
                "error": error,
            }
        )

    stage_names = {str(stage.get("name", "")) for stage in stages}
    if evidence and not ({"rerank", "final_rank"} & stage_names):
        stages.append(
            {
                "name": "final_rank",
                "status": "completed",
                "enabled": True,
                "input": case.question,
                "top": _flight_evidence_preview(evidence),
                "method": "trace_fallback",
            }
        )

    stages = _ensure_flight_stage_order(stages, case.question)

    fusion = {
        "enabled": True,
        "status": "failed" if error else "completed",
        "failed": bool(error),
        "skipped": False,
    }
    if isinstance(diagnostics.get("fusion"), Mapping):
        fusion.update(dict(diagnostics["fusion"]))

    rerank = {
        "requested": config.use_rerank,
        "enabled": rerank_enabled,
        "failed": rerank_failed,
        "skipped": (not config.use_rerank) or (config.use_rerank and not rerank_enabled),
        "status": "failed" if rerank_failed else ("completed" if rerank_enabled else "skipped"),
        "unavailable": bool(config.use_rerank and not rerank_enabled),
    }
    if isinstance(diagnostics.get("rerank"), Mapping):
        rerank.update(dict(diagnostics["rerank"]))
        rerank["unavailable"] = bool(config.use_rerank and not bool(rerank.get("enabled", rerank_enabled)))

    recorder = {
        "original_question": case.question,
        "original_query": case.question,
        "question": case.question,
        "config": config.model_dump(),
        "pipeline_stages": stages,
        "stages": stages,
        "fusion": fusion,
        "rerank": rerank,
        "trace_preview": trace[-4:],
    }
    if diagnostics.get("latency_ms") is not None:
        recorder["latency_ms"] = diagnostics["latency_ms"]
    return recorder


def _rank_score(rank: int | None, top_k: int) -> int:
    return int(rank) if rank is not None else top_k + 1


def _round_delta(after: float, before: float) -> float:
    return round(float(after) - float(before), 4)


def _reason_for_verdict(verdict: str, rank_delta: int, mrr_delta: float, coverage_delta: float) -> str:
    if verdict == "helped":
        if rank_delta > 0:
            return "Rerank moved an expected paper closer to rank 1."
        if mrr_delta > 0:
            return "Rerank improved reciprocal rank for the expected paper."
        return "Rerank improved expected keyword coverage."
    if verdict == "hurt":
        if rank_delta < 0:
            return "Rerank pushed the expected paper lower or out of the top-k results."
        if mrr_delta < 0:
            return "Rerank reduced reciprocal rank for the expected paper."
        return "Rerank reduced expected keyword coverage."
    return "Rerank produced no measurable gain over the fusion baseline."


def _compare_rerank_rows(
    before: dict[str, Any] | None,
    after: dict[str, Any],
    before_config: RagLabConfig | None,
    after_config: RagLabConfig,
) -> dict[str, Any]:
    top_k = max(after_config.top_k, before_config.top_k if before_config else after_config.top_k)
    before_rank = before.get("expected_best_rank") if before else None
    after_rank = after.get("expected_best_rank")
    before_metrics = before.get("metrics", {}) if before else {}
    after_metrics = after.get("metrics", {})

    rank_delta = (
        _rank_score(before_rank, top_k) - _rank_score(after_rank, top_k)
        if before is not None
        else None
    )
    mrr_delta = _round_delta(after_metrics.get("mrr", 0.0), before_metrics.get("mrr", 0.0))
    coverage_delta = _round_delta(
        after_metrics.get("keyword_coverage", 0.0),
        before_metrics.get("keyword_coverage", 0.0),
    )

    verdict = "no_op"
    reason = ""
    if before is None:
        verdict = "unavailable"
        reason = "No matching use_rerank=false config was available for this case."
    elif after.get("error"):
        verdict = "failed"
        reason = f"Rerank config failed during search: {after.get('error')}"
    elif after.get("rerank_failed"):
        verdict = "failed"
        rerank_status = after.get("flight_recorder", {}).get("rerank", {})
        reason = str(rerank_status.get("error") or "Rerank failed and fell back to fusion rank.")
    elif after.get("rerank_requested") and not after.get("rerank_enabled"):
        verdict = "unavailable"
        reason = "Rerank was requested but the reranker was unavailable, so fusion rank was used."
    elif rank_delta is not None and rank_delta > 0:
        verdict = "helped"
    elif rank_delta is not None and rank_delta < 0:
        verdict = "hurt"
    elif mrr_delta > 0 or coverage_delta > 0:
        verdict = "helped"
    elif mrr_delta < 0 or coverage_delta < 0:
        verdict = "hurt"

    if not reason:
        reason = _reason_for_verdict(verdict, int(rank_delta or 0), mrr_delta, coverage_delta)

    return {
        "verdict": verdict if verdict in _RERANK_VERDICTS else "no_op",
        "config_id_before": before_config.config_id if before_config else "",
        "config_id_after": after_config.config_id,
        "expected_rank_before": before_rank,
        "expected_rank_after": after_rank,
        "rank_delta": rank_delta,
        "mrr_delta": mrr_delta,
        "keyword_coverage_delta": coverage_delta,
        "reason": reason,
    }


def _config_pair_key(config: RagLabConfig) -> tuple[Any, ...]:
    return (
        config.top_k,
        config.candidate_k,
        config.chunk_size,
        config.chunk_overlap,
        config.split_mode,
    )


def _build_rerank_courtroom(
    case_results: Sequence[dict[str, Any]],
    configs_by_id: Mapping[str, RagLabConfig],
) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], dict[str, list[dict[str, Any]]]] = {}
    for row in case_results:
        config = configs_by_id.get(str(row.get("config_id", "")))
        if config is None:
            continue
        bucket = groups.setdefault(_config_pair_key(config), {"on": [], "off": []})
        bucket["on" if config.use_rerank else "off"].append(row)

    verdicts: list[dict[str, Any]] = []
    for rows in groups.values():
        off_rows = rows["off"]
        for after in rows["on"]:
            after_config = configs_by_id[str(after["config_id"])]
            before = off_rows[0] if off_rows else None
            before_config = configs_by_id[str(before["config_id"])] if before else None
            verdict = _compare_rerank_rows(before, after, before_config, after_config)
            after["rerank_courtroom"] = verdict
            verdicts.append(verdict)
    return verdicts


def _has_context_noise(result: Mapping[str, Any]) -> bool:
    metrics = result.get("metrics", {})
    if metrics.get("hit_at_k", 0.0) < 1.0:
        return False
    preview = result.get("evidence_preview", [])
    if not isinstance(preview, Sequence) or len(preview) <= 1:
        return False

    expected_count = 0
    non_expected_count = 0
    for item in preview:
        if not isinstance(item, Mapping):
            continue
        if item.get("expected_paper"):
            expected_count += 1
        else:
            non_expected_count += 1
    if expected_count <= 0:
        return False
    if result.get("expected_best_rank") and int(result["expected_best_rank"]) > 1:
        return True
    return non_expected_count >= max(2, expected_count * 2)


def _failure_reasons(case: EvalCase, result: dict[str, Any]) -> list[str]:
    if result.get("error"):
        return ["error"]
    metrics = result.get("metrics", {})
    reasons: list[str] = []
    if metrics.get("hit_at_k", 0.0) < 1.0:
        reasons.append("retrieval_miss")
    if case.expected_keywords and metrics.get("keyword_coverage", 0.0) < 0.5:
        reasons.append("low_keyword_coverage")
    courtroom = result.get("rerank_courtroom", {})
    if isinstance(courtroom, Mapping):
        verdict = courtroom.get("verdict")
        if verdict == "hurt":
            reasons.append("rerank_hurt")
        elif verdict == "no_op":
            reasons.append("rerank_no_gain")
    if _has_context_noise(result):
        reasons.append("context_noise")
    return reasons


def _summarize_results(config: RagLabConfig, rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    valid_rows = [row for row in rows if not row.get("error")]
    summary: dict[str, Any] = {
        **config.model_dump(),
        "num_cases": len(rows),
        "error_cases": len(rows) - len(valid_rows),
    }
    for metric_name in LAB_METRICS:
        values = [float(row["metrics"][metric_name]) for row in valid_rows]
        summary[metric_name] = round(sum(values) / max(len(values), 1), 4)
    ranks = [
        int(row["expected_best_rank"])
        for row in valid_rows
        if row.get("expected_best_rank") is not None
    ]
    summary["avg_expected_best_rank"] = round(sum(ranks) / len(ranks), 4) if ranks else None
    summary["missed_cases"] = sum(1 for row in valid_rows if row["metrics"]["hit_at_k"] < 1.0)
    return summary


def _build_comparison(summary: Sequence[dict[str, Any]]) -> dict[str, Any]:
    if not summary:
        return {"baseline_config_id": "", "metric_deltas": []}
    baseline = summary[0]
    deltas: list[dict[str, Any]] = []
    for row in summary[1:]:
        delta = {"config_id": row["config_id"]}
        for metric_name in LAB_METRICS:
            delta[f"{metric_name}_delta"] = round(
                float(row.get(metric_name, 0.0)) - float(baseline.get(metric_name, 0.0)),
                4,
            )
        deltas.append(delta)
    return {
        "baseline_config_id": baseline["config_id"],
        "metric_deltas": deltas,
    }


def run_rag_lab_evaluation(
    agent: ResearchAssistant,
    eval_path: str | Path | None = None,
    cases: Iterable[EvalCase | Mapping[str, Any]] | None = None,
    configs: Sequence[Mapping[str, Any]] | None = None,
    default_top_k: int = DEFAULT_TOP_K,
    default_candidate_k: int | None = None,
) -> dict[str, Any]:
    eval_cases = load_lab_cases(eval_path=eval_path, cases=cases)
    lab_configs = normalize_lab_configs(
        configs=configs,
        default_top_k=default_top_k,
        default_candidate_k=default_candidate_k,
    )

    rows_by_config: dict[str, list[dict[str, Any]]] = {config.config_id: [] for config in lab_configs}
    configs_by_id: dict[str, RagLabConfig] = {config.config_id: config for config in lab_configs}
    per_case: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for case in eval_cases:
        case_results: list[dict[str, Any]] = []
        for config in lab_configs:
            try:
                retrieval = agent.hybrid_retriever.search(
                    case.question,
                    top_k=config.top_k,
                    candidate_k=config.candidate_k,
                    use_rerank=config.use_rerank,
                )
                evidence = list(retrieval.evidence)
                metrics = calculate_retrieval_metrics(case, evidence)
                rerank_enabled = bool(config.use_rerank and getattr(agent.llm, "rerank_enabled", False))
                rerank_failed = bool(getattr(retrieval, "rerank_failed", False))
                flight_recorder = build_flight_recorder(
                    case,
                    config,
                    retrieval,
                    evidence,
                    rerank_enabled=rerank_enabled,
                    rerank_failed=rerank_failed,
                )
                rerank_status = flight_recorder.get("rerank", {})
                row = {
                    "config_id": config.config_id,
                    "config": config.model_dump(),
                    "metrics": {name: metrics[name] for name in LAB_METRICS},
                    "keyword_matches": metrics["keyword_matches"],
                    "keyword_total": metrics["keyword_total"],
                    "ranked_ids": [item.paper_id for item in evidence],
                    "expected_best_rank": metrics["expected_best_rank"],
                    "rerank_enabled": bool(rerank_status.get("enabled", rerank_enabled)),
                    "rerank_requested": bool(rerank_status.get("requested", config.use_rerank)),
                    "rerank_failed": bool(rerank_status.get("failed", rerank_failed)),
                    "evidence_preview": build_evidence_preview(case, evidence),
                    "trace_preview": list(getattr(retrieval, "trace", []))[-4:],
                    "flight_recorder": flight_recorder,
                }
            except Exception as exc:
                rerank_enabled = bool(config.use_rerank and getattr(agent.llm, "rerank_enabled", False))
                flight_recorder = build_flight_recorder(
                    case,
                    config,
                    None,
                    [],
                    rerank_enabled=rerank_enabled,
                    rerank_failed=False,
                    error=str(exc),
                )
                row = {
                    "config_id": config.config_id,
                    "config": config.model_dump(),
                    "metrics": {name: 0.0 for name in LAB_METRICS},
                    "keyword_matches": [],
                    "keyword_total": len(case.expected_keywords),
                    "ranked_ids": [],
                    "expected_best_rank": None,
                    "rerank_enabled": rerank_enabled,
                    "rerank_requested": config.use_rerank,
                    "rerank_failed": False,
                    "evidence_preview": [],
                    "trace_preview": [],
                    "flight_recorder": flight_recorder,
                    "error": str(exc),
                }

            rows_by_config[config.config_id].append(row)
            case_results.append(row)

        courtroom = _build_rerank_courtroom(case_results, configs_by_id)
        for row in case_results:
            reasons = _failure_reasons(case, row)
            row["failure_reasons"] = reasons
            if reasons:
                failures.append(
                    {
                        "case_id": case.case_id,
                        "config_id": row["config_id"],
                        "reasons": reasons,
                        "expected_paper_ids": case.expected_paper_ids,
                        "expected_keywords": case.expected_keywords,
                        "ranked_ids": row["ranked_ids"],
                        "metrics": row["metrics"],
                    }
                )

        per_case.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "expected_paper_ids": case.expected_paper_ids,
                "expected_keywords": case.expected_keywords,
                "tags": case.tags,
                "rerank_courtroom": courtroom,
                "results": case_results,
            }
        )

    summary = [
        _summarize_results(config, rows_by_config[config.config_id])
        for config in lab_configs
    ]

    return {
        "num_cases": len(eval_cases),
        "configs": [config.model_dump() for config in lab_configs],
        "metrics": list(LAB_METRICS),
        "summary": summary,
        "comparison": _build_comparison(summary),
        "per_case": per_case,
        "failures": failures,
    }
