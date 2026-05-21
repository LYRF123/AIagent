from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .agent import ResearchAssistant
from .models import AnswerResult, EvalCase, Evidence


RAGAS_SAMPLE_COLUMNS = {
    "user_input",
    "response",
    "retrieved_contexts",
    "reference",
}
RAGAS_CONTEXT_LIMIT = 1200
RAGAS_REFERENCE_LIMIT = 4000

SECTIONS_TO_COVER = ["summary", "methods", "findings", "limitations"]

UNANSWERABLE_CASES: list[dict[str, str]] = [
    {"case_id": "unanswerable-01", "question": "What is the capital of France?"},
    {"case_id": "unanswerable-02", "question": "Who won the 2024 Nobel Prize in Physics?"},
    {"case_id": "unanswerable-03", "question": "What is the population of China in 2025?"},
    {"case_id": "unanswerable-04", "question": "What is the chemical formula for table salt?"},
    {"case_id": "unanswerable-05", "question": "Who discovered penicillin?"},
]


def default_eval_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "demo_eval.json"


def load_eval_cases(path: str | Path | None = None) -> list[EvalCase]:
    target = Path(path) if path else default_eval_path()
    with target.open("r", encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    return [EvalCase.model_validate(item) for item in raw]


def _llm_reference(agent: ResearchAssistant, case: EvalCase) -> str:
    """Generate a concise reference answer via LLM from the expected paper's content."""
    paper_texts: list[str] = []
    for paper_id in case.expected_paper_ids:
        paper = agent.corpus.paper_by_id.get(paper_id)
        if paper is None:
            continue
        sections = [f"Title: {paper.title}", f"Summary: {paper.summary}"]
        if paper.methods:
            sections.append(f"Methods: {'; '.join(paper.methods)}")
        if paper.findings:
            sections.append(f"Findings: {'; '.join(paper.findings)}")
        paper_texts.append("\n".join(sections))

    full_text = "\n\n".join(paper_texts)
    if not full_text.strip():
        return " ".join(case.expected_keywords)

    system_prompt = (
        "You are a research assistant. Given a question and the full text of the "
        "paper(s) that contain the answer, write a concise one-sentence ground-truth "
        "answer. Only use information from the provided paper content."
    )
    user_prompt = (
        f"Question:\n{case.question}\n\n"
        f"Paper content:\n{compact_text(full_text, 6000)}\n\n"
        "Write a one-sentence reference answer:"
    )
    try:
        response = agent.llm.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        return response.text.strip()
    except Exception:
        # LLM failed; fall back to keywords as the reference.
        return " ".join(case.expected_keywords)


def build_reference_text(agent: ResearchAssistant, case: EvalCase) -> str:
    if case.reference.strip():
        return case.reference.strip()

    # Use LLM to generate a concise reference when available,
    # instead of concatenating all paper metadata (which produces a
    # multi-thousand-character blob that is useless for Ragas
    # context_recall / context_precision).
    if agent.llm.enabled:
        return _llm_reference(agent, case)

    # Fallback when no LLM and no explicit reference: metadata concatenation.
    parts = []
    for paper_id in case.expected_paper_ids:
        paper = agent.corpus.paper_by_id.get(paper_id)
        if paper is None:
            continue
        sections = [
            f"Title: {paper.title}",
            f"Summary: {paper.summary}",
        ]
        if paper.methods:
            sections.append(f"Methods: {'; '.join(paper.methods)}")
        if paper.findings:
            sections.append(f"Findings: {'; '.join(paper.findings)}")
        if paper.limitations:
            sections.append(f"Limitations: {'; '.join(paper.limitations)}")
        parts.append("\n".join(sections))

    if parts:
        return "\n\n".join(parts)
    return " ".join(case.expected_keywords)


def compact_text(value: str, limit: int) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def build_ragas_sample(agent: ResearchAssistant, case: EvalCase, answer: AnswerResult) -> dict[str, Any]:
    return {
        "user_input": case.question,
        "response": answer.answer,
        "retrieved_contexts": [
            compact_text(item.text, RAGAS_CONTEXT_LIMIT)
            for item in answer.evidence
        ],
        "reference": compact_text(build_reference_text(agent, case), RAGAS_REFERENCE_LIMIT),
    }


def _clean_ragas_value(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        try:
            return _clean_ragas_value(value.item())
        except Exception:
            pass
    try:
        if value != value:
            return None
    except Exception:
        pass
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, list):
        return [_clean_ragas_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _clean_ragas_value(item) for key, item in value.items()}
    return value


def _summarize_ragas_scores(rows: list[dict[str, Any]]) -> dict[str, float]:
    summary: dict[str, float] = {}
    if not rows:
        return summary
    metric_names = [
        name
        for name in rows[0]
        if name not in RAGAS_SAMPLE_COLUMNS and name != "case_id"
    ]
    for metric_name in metric_names:
        values = [
            float(row[metric_name])
            for row in rows
            if isinstance(row.get(metric_name), int | float)
        ]
        if values:
            summary[metric_name] = round(sum(values) / len(values), 4)
    return summary


def run_ragas_evaluation(
    agent: ResearchAssistant,
    samples: Iterable[dict[str, Any]],
    case_ids: Iterable[str],
) -> dict[str, Any]:
    if not agent.llm.enabled:
        return {
            "enabled": False,
            "skipped": True,
            "reason": "未配置 DASHSCOPE_API_KEY，已跳过 Ragas 的 LLM 指标评估。",
            "metrics": [],
            "summary": {},
            "per_case": [],
        }

    try:
        # --------------------------------------------------------------
        # We import from ragas.metrics._* (private modules) instead of
        # ragas.metrics.collections (public API) because Ragas 0.4.3's
        # public API enforces stricter LLM typing that conflicts with
        # our pattern of injecting the LLM through evaluate(llm=...).
        # The private modules accept optional LLM at init time.
        # Keep the ragas version pinned to <0.5 (see pyproject.toml).
        # When upgrading Ragas, verify that:
        #   1. The private module paths still exist and export the same
        #      classes.
        #   2. The metric .name values haven't changed.
        #   3. evaluate(llm=...) still accepts an external LLM.
        # --------------------------------------------------------------
        from ragas import EvaluationDataset, evaluate
        from ragas.metrics._answer_relevance import ResponseRelevancy
        from ragas.metrics._context_precision import LLMContextPrecisionWithReference
        from ragas.metrics._context_recall import LLMContextRecall
        from ragas.metrics._faithfulness import Faithfulness
    except ImportError as exc:
        return {
            "enabled": False,
            "skipped": True,
            "reason": f"未安装 ragas 或导入失败：{exc}",
            "metrics": [],
            "summary": {},
            "per_case": [],
        }

    metrics = [
        Faithfulness(),
        LLMContextPrecisionWithReference(),
        LLMContextRecall(),
        ResponseRelevancy(),
    ]
    metric_names = [metric.name for metric in metrics]

    try:
        result = evaluate(
            dataset=EvaluationDataset.from_list(list(samples)),
            metrics=metrics,
            llm=agent.llm.chat_model(),
            embeddings=agent.llm.embedding_client(),
            raise_exceptions=False,
            show_progress=False,
        )
        frame = result.to_pandas()
    except Exception as exc:
        return {
            "enabled": True,
            "skipped": True,
            "reason": f"Ragas 评估失败：{exc}",
            "metrics": metric_names,
            "summary": {},
            "per_case": [],
        }

    rows = []
    for case_id, row in zip(case_ids, frame.to_dict(orient="records"), strict=False):
        scores = {
            key: _clean_ragas_value(value)
            for key, value in row.items()
            if key not in RAGAS_SAMPLE_COLUMNS
        }
        rows.append({"case_id": case_id, **scores})

    return {
        "enabled": True,
        "skipped": False,
        "metrics": metric_names,
        "summary": _summarize_ragas_scores(rows),
        "per_case": rows,
    }


# ---------------------------------------------------------------------------
# Phase 1 helpers: noise, section coverage, difficulty breakdown,
# unanswerable detection
# ---------------------------------------------------------------------------


def _is_declined_answer(answer: str) -> bool:
    """Check whether the answer indicates inability to answer."""
    decline_phrases = [
        "i don't know",
        "i do not know",
        "cannot answer",
        "can't answer",
        "insufficient evidence",
        "not found",
        "no information",
        "unable to",
        "not available",
        "do not have",
        "don't have",
        "not provided",
        "cannot determine",
        "no relevant",
    ]
    lower = answer.lower()
    return any(phrase in lower for phrase in decline_phrases)


def compute_noise_ratio(cited_ids: set[str], expected_ids: list[str]) -> float:
    """Fraction of retrieved paper IDs that are NOT in the expected set."""
    expected_set = set(expected_ids)
    if not cited_ids:
        return 0.0
    noise_count = sum(1 for pid in cited_ids if pid not in expected_set)
    return round(noise_count / len(cited_ids), 4)


def compute_section_coverage(
    evidence: list[Evidence],
    expected_ids: list[str],
) -> dict[str, bool]:
    """Check which sections of expected papers are covered by retrieved evidence."""
    expected_set = set(expected_ids)
    covered = {section: False for section in SECTIONS_TO_COVER}
    for item in evidence:
        if item.paper_id in expected_set and item.section in covered:
            covered[item.section] = True
    return covered


def run_unanswerable_test(
    agent: ResearchAssistant,
    top_k: int = 5,
) -> dict[str, Any]:
    """Test whether the system correctly declines out-of-domain questions."""
    results: list[dict[str, Any]] = []
    correct = 0
    for case in UNANSWERABLE_CASES:
        answer = agent.answer_question(case["question"], top_k=top_k)
        declined = answer.insufficient_evidence or _is_declined_answer(answer.answer)
        if declined:
            correct += 1
        results.append({
            "case_id": case["case_id"],
            "question": case["question"],
            "correctly_declined": declined,
            "answer": answer.answer,
            "insufficient_evidence": answer.insufficient_evidence,
        })
    total = max(len(UNANSWERABLE_CASES), 1)
    return {
        "enabled": True,
        "num_cases": len(UNANSWERABLE_CASES),
        "correctly_declined": correct,
        "unanswerable_accuracy": round(correct / total, 4),
        "results": results,
    }


# ---------------------------------------------------------------------------
# main evaluation pipeline
# ---------------------------------------------------------------------------


def run_evaluation(
    agent: ResearchAssistant,
    eval_path: str | Path | None = None,
    top_k: int = 5,
    use_ragas: bool = False,
) -> dict:
    cases = load_eval_cases(eval_path)
    results = []
    ragas_samples = []
    case_ids = []
    total_paper_hit = 0
    total_keyword_hit = 0
    total_keyword_matches = 0
    total_keyword_count = 0
    total_answer_length = 0

    for case in cases:
        answer = agent.answer_question(case.question, top_k=top_k)
        cited_ids = {item.paper_id for item in answer.evidence}
        answer_lower = answer.answer.lower()
        paper_hit = int(any(paper_id in cited_ids for paper_id in case.expected_paper_ids))
        kw_match_count = sum(1 for kw in case.expected_keywords if kw.lower() in answer_lower)
        kw_total = max(len(case.expected_keywords), 1)
        kw_match_rate = kw_match_count / kw_total
        # Legacy all-or-nothing flag (one missing keyword -> 0).
        keyword_hit = int(kw_match_count == kw_total)
        evidence_count = len(answer.evidence)
        total_paper_hit += paper_hit
        total_keyword_hit += keyword_hit
        total_keyword_matches += kw_match_count
        total_keyword_count += kw_total
        total_answer_length += len(answer.answer)
        ragas_samples.append(build_ragas_sample(agent, case, answer))
        case_ids.append(case.case_id)

        # Phase 1 per-case metrics
        section_coverage = compute_section_coverage(answer.evidence, case.expected_paper_ids)
        noise_ratio = compute_noise_ratio(cited_ids, case.expected_paper_ids)

        results.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "paper_hit": paper_hit,
                "keyword_hit": keyword_hit,
                "keyword_matches": kw_match_count,
                "keyword_total": kw_total,
                "keyword_match_rate": round(kw_match_rate, 4),
                "expected_paper_ids": case.expected_paper_ids,
                "expected_keywords": case.expected_keywords,
                "cited_ids": sorted(cited_ids),
                "evidence_count": evidence_count,
                "answer": answer.answer,
                "trace": [item.model_dump() for item in answer.trace],
                # Phase 1 fields
                "difficulty": case.difficulty or "unknown",
                "noise_ratio_in_results": noise_ratio,
                "section_coverage": section_coverage,
            }
        )

    total = max(len(cases), 1)
    # A case is considered failed when: wrong paper OR fewer than half of keywords matched.
    failed_cases = [
        item for item in results
        if not (item["paper_hit"] and item["keyword_match_rate"] >= 0.5)
    ]
    payload = {
        "num_cases": len(cases),
        "paper_hit_rate": round(total_paper_hit / total, 4),
        "keyword_hit_rate": round(total_keyword_hit / total, 4),
        "keyword_match_rate": round(total_keyword_matches / max(total_keyword_count, 1), 4),
        "avg_answer_length": round(total_answer_length / total, 2),
        "passed_cases": len(results) - len(failed_cases),
        "failed_cases": len(failed_cases),
        "results": results,
        "failures": failed_cases,
    }

    # --- Phase 1: noise metrics summary ---
    noise_ratios = [r["noise_ratio_in_results"] for r in results]
    payload["noise_metrics"] = {
        "avg_noise_ratio": round(sum(noise_ratios) / max(len(noise_ratios), 1), 4),
        "min_noise_ratio": min(noise_ratios) if noise_ratios else 0.0,
        "max_noise_ratio": max(noise_ratios) if noise_ratios else 0.0,
    }

    # --- Phase 1: section coverage summary ---
    section_totals: dict[str, int] = {s: 0 for s in SECTIONS_TO_COVER}
    for r in results:
        for section, covered in r["section_coverage"].items():
            if covered:
                section_totals[section] += 1
    payload["section_coverage_summary"] = {
        section: round(count / total, 4) for section, count in section_totals.items()
    }

    # --- Phase 1: difficulty-grouped breakdown ---
    difficulty_groups: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        d = r.get("difficulty", "unknown")
        difficulty_groups.setdefault(d, []).append(r)

    difficulty_breakdown: dict[str, dict[str, Any]] = {}
    for group_id, group_results in difficulty_groups.items():
        n = len(group_results)
        difficulty_breakdown[group_id] = {
            "count": n,
            "paper_hit_rate": round(
                sum(r["paper_hit"] for r in group_results) / n, 4
            ),
            "keyword_match_rate": round(
                sum(r["keyword_matches"] for r in group_results)
                / max(sum(r["keyword_total"] for r in group_results), 1),
                4,
            ),
            "avg_answer_length": round(
                sum(len(r["answer"]) for r in group_results) / n, 2
            ),
        }
    payload["difficulty_breakdown"] = difficulty_breakdown

    # --- Phase 1: unanswerable detection ---
    payload["unanswerable_test"] = run_unanswerable_test(agent, top_k=top_k)

    if use_ragas:
        payload["ragas"] = run_ragas_evaluation(agent, ragas_samples, case_ids)
    return payload
