from __future__ import annotations

from .llm import build_context_block
from .models import ReviewResult, ToolTrace


def generate_review(corpus, paper_ids, topic, top_k=5, llm_client=None, trace=None):
    papers = corpus.get_papers(paper_ids)
    if trace is None:
        trace = [
            ToolTrace(
                tool="search_papers",
                input=topic,
                output=", ".join(paper_ids),
            )
        ]
    if not papers:
        return ReviewResult(
            topic=topic,
            overview="No representative papers were found in the local corpus.",
            trends=[],
            representative_papers=[],
            reading_order=[],
            open_problems=[],
            trace=trace,
        )

    trends = []
    open_problems = []
    for paper in papers[:3]:
        if paper.methods:
            trends.append(f"{paper.title}: {paper.methods[0]}")
        if paper.limitations:
            open_problems.append(paper.limitations[0])

    overview = (
        f"The topic '{topic}' is represented by {len(papers)} local papers. "
        "The literature moves from retrieval or tool augmentation toward more explicit "
        "self-reflection, multi-agent coordination, and domain-specific execution."
    )
    representative = [paper.title for paper in papers]
    reading_order = [paper.title for paper in sorted(papers, key=lambda paper: paper.year)]

    if llm_client is not None and llm_client.enabled:
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
                system_prompt="You are a research assistant. Produce a concise topic review from the provided papers only. Reply in the same language as the user's topic.",
                user_prompt=(
                    f"Topic: {topic}\n\nContext:\n{context}\n\n"
                    "Return a compact overview, key trends, and open problems in plain text."
                ),
            )
            overview = llm_response.text
            trace.append(ToolTrace(tool="langchain_chat_qwen", input=topic, output=f"provider={llm_response.provider}, model={llm_response.model}"))
        except Exception as exc:
            trace.append(ToolTrace(tool="langchain_chat_error", input=topic, output=str(exc)))

    return ReviewResult(
        topic=topic,
        overview=overview,
        trends=trends,
        representative_papers=representative,
        reading_order=reading_order,
        open_problems=open_problems[:5],
        trace=trace,
    )
