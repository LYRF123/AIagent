from __future__ import annotations

import json
import re
from .models import Evidence, ToolTrace


class Contradiction:
    """A detected contradiction between two evidence items."""

    def __init__(
        self,
        evidence_a: int,
        evidence_b: int,
        description: str,
        severity: str = "moderate",
    ) -> None:
        self.evidence_a = evidence_a
        self.evidence_b = evidence_b
        self.description = description
        self.severity = severity

    def to_dict(self) -> dict:
        return {
            "evidence_a": self.evidence_a,
            "evidence_b": self.evidence_b,
            "description": self.description,
            "severity": self.severity,
        }


def detect_contradictions(
    evidence: list[Evidence],
    llm_client,
    trace: list[ToolTrace],
) -> list[dict]:
    """Detect contradictions between evidence from different papers.

    Only triggers when evidence comes from 2+ distinct papers.
    Returns list of contradiction dicts. Returns empty list if LLM unavailable.
    """
    if not llm_client or not getattr(llm_client, "enabled", False):
        return []

    # Check if evidence comes from multiple papers
    paper_ids = set(e.paper_id for e in evidence)
    if len(paper_ids) < 2:
        return []

    # Build evidence summary for LLM
    evidence_lines = []
    for idx, e in enumerate(evidence, start=1):
        evidence_lines.append(
            f"[{idx}] paper={e.paper_id}, title={e.title}, section={e.section}\n"
            f"Text: {e.text[:500]}"
        )
    evidence_text = "\n\n".join(evidence_lines)

    system_prompt = (
        "You are a research contradiction detector. "
        "Given evidence from multiple papers, identify any contradictions or conflicting claims. "
        "Return a JSON array of objects with keys: evidence_a (int), evidence_b (int), description (string), severity (string: 'minor', 'moderate', or 'major'). "
        "If no contradictions are found, return an empty array []. "
        "Only flag genuine contradictions, not complementary or tangential information."
    )
    user_prompt = (
        f"Evidence items:\n{evidence_text}\n\n"
        "Identify any contradictions between evidence from different papers. "
        "Return ONLY a JSON array."
    )

    try:
        response = llm_client.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        raw = response.text.strip()

        # Parse JSON array from response
        contradictions = _parse_contradictions(raw, len(evidence))

        trace.append(
            ToolTrace(
                tool="contradiction_detector",
                input=f"check {len(evidence)} evidence items from {len(paper_ids)} papers",
                output=f"found {len(contradictions)} contradiction(s)",
            )
        )
        return contradictions
    except Exception as exc:
        trace.append(
            ToolTrace(
                tool="contradiction_detector",
                input=f"check {len(evidence)} evidence items",
                output=f"error: {exc}",
            )
        )
        return []


def _parse_contradictions(text: str, evidence_count: int) -> list[dict]:
    """Parse contradiction JSON array from LLM response."""
    text = text.strip()

    # Strip markdown code fences if present (```json ... ```)
    fence_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try direct parse
    if text.startswith("["):
        try:
            items = json.loads(text)
            if isinstance(items, list):
                return _validate_contradictions(items, evidence_count)
        except (json.JSONDecodeError, ValueError):
            pass

    # Try to find array in text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            items = json.loads(text[start:end + 1])
            if isinstance(items, list):
                return _validate_contradictions(items, evidence_count)
        except (json.JSONDecodeError, ValueError):
            pass

    return []


def _validate_contradictions(items: list, evidence_count: int) -> list[dict]:
    """Validate and normalize contradiction items."""
    valid = []
    for item in items:
        if not isinstance(item, dict):
            continue
        a = item.get("evidence_a")
        b = item.get("evidence_b")
        desc = item.get("description", "")
        severity = item.get("severity", "moderate")
        if a is None or b is None or not desc:
            continue
        if not isinstance(a, int) or not isinstance(b, int):
            continue
        if a < 1 or a > evidence_count or b < 1 or b > evidence_count:
            continue
        if severity not in ("minor", "moderate", "major"):
            severity = "moderate"
        valid.append({
            "evidence_a": a,
            "evidence_b": b,
            "description": str(desc),
            "severity": severity,
        })
    return valid
