from __future__ import annotations

from .llm import build_context_block
from .models import ComparisonResult, ComparisonRow, ToolTrace


def compare_papers(corpus, paper_ids, focus="methods, findings, and limitations", llm_client=None, trace=None):
    papers = corpus.get_papers(paper_ids)
    if trace is None:
        trace = [
            ToolTrace(
                tool="load_by_id",
                input=", ".join(paper_ids),
                output=", ".join(paper.paper_id for paper in papers),
            )
        ]

    rows = [
        ComparisonRow(
            paper_id=paper.paper_id,
            title=paper.title,
            year=paper.year,
            methods=paper.methods,
            findings=paper.findings,
            limitations=paper.limitations,
        )
        for paper in papers
    ]
    titles = ", ".join(paper.title for paper in papers)
    narrative = f"This comparison focuses on {focus}. Included papers: {titles}."
    if llm_client is not None and llm_client.enabled and papers:
        context = build_context_block(
            [
                {
                    "paper_id": paper.paper_id,
                    "title": paper.title,
                    "section": "summary",
                    "score": 1.0,
                    "text": f"Summary: {paper.summary} Methods: {'; '.join(paper.methods)} Findings: {'; '.join(paper.findings)} Limitations: {'; '.join(paper.limitations)}",
                }
                for paper in papers
            ]
        )
        try:
            llm_response = llm_client.complete(
                system_prompt="You are a research assistant. Compare the papers only using the provided context. Reply in the same language as the user's focus description.",
                user_prompt=f"Focus: {focus}\n\nContext:\n{context}\n\nWrite a concise comparison.",
            )
            narrative = llm_response.text
            trace.append(ToolTrace(tool="langchain_chat_qwen", input=focus, output=f"provider={llm_response.provider}, model={llm_response.model}"))
        except Exception as exc:
            trace.append(ToolTrace(tool="langchain_chat_error", input=focus, output=str(exc)))
    return ComparisonResult(focus=focus, narrative=narrative, rows=rows, trace=trace)
