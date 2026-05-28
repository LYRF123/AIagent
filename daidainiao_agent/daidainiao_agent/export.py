from __future__ import annotations


def _safe_filename(question: str, suffix: str) -> str:
    title = (question or "answer")[:40].strip() or "answer"
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in title)
    return f"{safe}.{suffix}"


def format_answer_markdown(result: dict) -> str:
    """Format an AnswerResult dict as a Markdown document."""
    lines: list[str] = []
    lines.append(f"# {result.get('question', 'Untitled Question')}")
    lines.append("")
    lines.append("## Answer")
    lines.append("")
    lines.append(result.get("answer", ""))
    lines.append("")
    evidence = result.get("evidence") or []
    if evidence:
        lines.append("## Evidence")
        lines.append("")
        for idx, item in enumerate(evidence, start=1):
            lines.extend(_evidence_block_lines(item, idx))
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
    lines.append("---")
    question_type = result.get("question_type", "")
    if question_type:
        lines.append(f"*question_type: {question_type}*")
    confidence = result.get("retrieval_confidence", 0)
    if confidence > 0:
        lines.append(f"*retrieval_confidence: {confidence:.2%}*")
    if result.get("insufficient_evidence", False):
        lines.append("*insufficient_evidence: true*")
    lines.append("")
    return "\n".join(lines)


def format_obsidian_markdown(result: dict) -> str:
    """Obsidian-friendly note with frontmatter and footnote citations."""
    question = result.get("question", "Untitled Question")
    evidence = result.get("evidence") or []
    lines: list[str] = [
        "---",
        f'title: "{question.replace(chr(34), chr(39))}"',
        "tags: [daidainiao, research]",
        "source: daidainiao-agent",
        "---",
        "",
        f"# {question}",
        "",
    ]
    answer = result.get("answer", "")
    if evidence:
        for idx, item in enumerate(evidence, start=1):
            pid = item.get("paper_id") or item.get("title") or f"ref{idx}"
            answer = answer.replace(f"[{idx}]", f"[^{idx}]")
        lines.append(answer)
        lines.append("")
        lines.append("## References")
        lines.append("")
        for idx, item in enumerate(evidence, start=1):
            pid = item.get("paper_id") or "unknown"
            title = item.get("title") or pid
            section = item.get("section") or ""
            lines.append(f"[^{idx}]: {title} (`{pid}`)" + (f" — {section}" if section else ""))
        lines.append("")
    else:
        lines.append(answer)
        lines.append("")
    if evidence:
        lines.append("## Evidence")
        lines.append("")
        for idx, item in enumerate(evidence, start=1):
            lines.extend(_evidence_block_lines(item, idx))
    return "\n".join(lines)


def format_bibtex(result: dict, papers: dict[str, dict] | None = None) -> str:
    """BibTeX entries for papers cited in evidence."""
    papers = papers or {}
    evidence = result.get("evidence") or []
    seen: set[str] = set()
    entries: list[str] = []
    for item in evidence:
        paper_id = str(item.get("paper_id") or "").strip()
        if not paper_id or paper_id in seen:
            continue
        seen.add(paper_id)
        meta = papers.get(paper_id) or {}
        title = meta.get("title") or item.get("title") or paper_id
        authors = meta.get("authors") or []
        author_str = " and ".join(authors) if authors else "Unknown"
        year = meta.get("year") or ""
        venue = meta.get("venue") or ""
        url = meta.get("source_url") or ""
        key = paper_id.replace("-", "_")
        block = [
            f"@misc{{{key},",
            f"  title = {{{title}}},",
            f"  author = {{{author_str}}},",
        ]
        if year:
            block.append(f"  year = {{{year}}},")
        if venue:
            block.append(f"  howpublished = {{{venue}}},")
        if url:
            block.append(f"  url = {{{url}}},")
        block.append("}")
        entries.append("\n".join(block))
    if not entries:
        return "% No paper_id found in evidence.\n"
    return "\n\n".join(entries) + "\n"


def _evidence_block_lines(item: dict, idx: int) -> list[str]:
    lines: list[str] = []
    title = item.get("title", "")
    section = item.get("section", "")
    score = item.get("score", 0)
    text = item.get("text", "")
    source_label = item.get("source_label", "")
    page = item.get("page")
    paper_id = item.get("paper_id", "")
    lines.append(f"### [{idx}] {title}")
    meta_parts = []
    if paper_id:
        meta_parts.append(f"paper_id: {paper_id}")
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
    return lines
