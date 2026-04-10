from __future__ import annotations

import json
from pathlib import Path

from .agent import ResearchAssistant
from .models import EvalCase


def default_eval_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "demo_eval.json"


def load_eval_cases(path: str | Path | None = None) -> list[EvalCase]:
    target = Path(path) if path else default_eval_path()
    with target.open("r", encoding="utf-8-sig") as handle:
        raw = json.load(handle)
    return [EvalCase.model_validate(item) for item in raw]


def run_evaluation(agent: ResearchAssistant, eval_path: str | Path | None = None, top_k: int = 5) -> dict:
    cases = load_eval_cases(eval_path)
    results = []
    total_paper_hit = 0
    total_keyword_hit = 0
    total_answer_length = 0

    for case in cases:
        answer = agent.answer_question(case.question, top_k=top_k)
        cited_ids = {item.paper_id for item in answer.evidence}
        answer_lower = answer.answer.lower()
        paper_hit = int(any(paper_id in cited_ids for paper_id in case.expected_paper_ids))
        keyword_hit = int(all(keyword.lower() in answer_lower for keyword in case.expected_keywords))
        evidence_count = len(answer.evidence)
        total_paper_hit += paper_hit
        total_keyword_hit += keyword_hit
        total_answer_length += len(answer.answer)
        results.append(
            {
                "case_id": case.case_id,
                "question": case.question,
                "paper_hit": paper_hit,
                "keyword_hit": keyword_hit,
                "expected_paper_ids": case.expected_paper_ids,
                "expected_keywords": case.expected_keywords,
                "cited_ids": sorted(cited_ids),
                "evidence_count": evidence_count,
                "answer": answer.answer,
                "trace": [item.model_dump() for item in answer.trace],
            }
        )

    total = max(len(cases), 1)
    failed_cases = [item for item in results if not (item["paper_hit"] and item["keyword_hit"])]
    return {
        "num_cases": len(cases),
        "paper_hit_rate": round(total_paper_hit / total, 4),
        "keyword_hit_rate": round(total_keyword_hit / total, 4),
        "avg_answer_length": round(total_answer_length / total, 2),
        "passed_cases": len(results) - len(failed_cases),
        "failed_cases": len(failed_cases),
        "results": results,
        "failures": failed_cases,
    }
