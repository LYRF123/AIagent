from research_agent.agent import ResearchAssistant
from research_agent.evaluation import run_evaluation


def test_search_returns_self_rag_for_reflection_query() -> None:
    agent = ResearchAssistant()
    results = agent.search_papers("self reflection retrieval critique", top_k=3)
    assert results
    assert results[0]["paper_id"] == "self-rag"


def test_answer_contains_evidence() -> None:
    agent = ResearchAssistant()
    answer = agent.answer_question("How does ReAct use external observations?", top_k=3)
    cited_ids = {item.paper_id for item in answer.evidence}
    assert "react" in cited_ids
    assert "observations" in answer.answer.lower()


def test_compare_by_ids() -> None:
    agent = ResearchAssistant()
    result = agent.compare_papers(paper_ids=["autogen", "metagpt"])
    row_ids = [row.paper_id for row in result.rows]
    assert row_ids == ["autogen", "metagpt"]


def test_eval_pipeline_runs() -> None:
    agent = ResearchAssistant()
    metrics = run_evaluation(agent)
    assert metrics["num_cases"] == 4
    assert metrics["paper_hit_rate"] >= 0.75


def test_import_and_delete_text_document(tmp_path) -> None:
    agent = ResearchAssistant()
    baseline_count = len(agent.list_imported_documents())

    agent.corpus.imported_path = tmp_path / "imported_papers.json"
    text_file = tmp_path / "sample.txt"
    text_file.write_text("This imported note discusses retrieval augmented generation and agent planning.", encoding="utf-8")
    imported = agent.import_document(text_file, original_name="sample.txt")
    documents = agent.list_imported_documents()
    assert any(item["paper_id"] == imported["paper_id"] for item in documents)

    deleted = agent.delete_document(imported["paper_id"])
    assert deleted["paper_id"] == imported["paper_id"]
    remaining = agent.list_imported_documents()
    assert not any(item["paper_id"] == imported["paper_id"] for item in remaining)
    assert len(remaining) == baseline_count
