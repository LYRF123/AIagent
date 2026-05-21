from __future__ import annotations


def format_answer_markdown(result: dict) -> str:
    """Format an AnswerResult dict as a Markdown document."""
    lines: list[str] = []

    # Question
    lines.append(f"# {result.get('question', 'Untitled Question')}")
    lines.append("")

    # Answer
    lines.append("## Answer")
    lines.append("")
    lines.append(result.get("answer", ""))
    lines.append("")

    # Evidence
    evidence = result.get("evidence") or []
    if evidence:
        lines.append("## Evidence")
        lines.append("")
        for idx, item in enumerate(evidence, start=1):
            title = item.get("title", "")
            section = item.get("section", "")
            score = item.get("score", 0)
            text = item.get("text", "")
            source_label = item.get("source_label", "")
            page = item.get("page")
            lines.append(f"### [{idx}] {title}")
            meta_parts = []
            if section:
                meta_parts.append(f"section: {section}")
            if score:
                meta_parts.append(f"score: {score:.4f}")
            if source_label:
                meta_parts.append(f"source: {source_label}")
            if page is not None:
                meta_parts.append(f"page: {page}")
            if meta_parts:
                lines.append(f"*{' | '.join(meta_parts)}*")
            lines.append("")
            lines.append(f"> {text}")
            lines.append("")

    # Claim Audit
    claim_audit = result.get("claim_audit") or []
    if claim_audit:
        lines.append("## Claim Audit")
        lines.append("")
        for item in claim_audit:
            status = item.get("status", "unknown")
            claim = item.get("claim", "")
            reason = item.get("reason", "")
            lines.append(f"- **[{status}]** {claim}")
            if reason:
                lines.append(f"  - {reason}")
        lines.append("")

    # Metadata
    lines.append("---")
    question_type = result.get("question_type", "")
    if question_type:
        lines.append(f"*question_type: {question_type}*")
    confidence = result.get("retrieval_confidence", 0)
    if confidence > 0:
        lines.append(f"*retrieval_confidence: {confidence:.2%}*")
    insufficient = result.get("insufficient_evidence", False)
    if insufficient:
        lines.append("*insufficient_evidence: true*")
    lines.append("")

    return "\n".join(lines)
