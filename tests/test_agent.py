from research_agent.agent import ResearchAssistant
from research_agent.evaluation import run_evaluation
from research_agent.corpus import PaperCorpus
from research_agent.models import Paper


def test_search_returns_self_rag_for_reflection_query(research_agent) -> None:
    results = research_agent.search_papers("self reflection retrieval critique", top_k=3)
    assert results
    assert results[0]["paper_id"] == "self-rag"


def test_answer_contains_evidence(research_agent) -> None:
    answer = research_agent.answer_question("How does ReAct use external observations?", top_k=3)
    cited_ids = {item.paper_id for item in answer.evidence}
    assert "react" in cited_ids
    assert "observations" in answer.answer.lower()


def test_compare_by_ids(research_agent) -> None:
    result = research_agent.compare_papers(paper_ids=["autogen", "metagpt"])
    row_ids = [row.paper_id for row in result.rows]
    assert row_ids == ["autogen", "metagpt"]


def test_eval_pipeline_runs(research_agent) -> None:
    metrics = run_evaluation(research_agent)
    assert metrics["num_cases"] == 4
    assert metrics["paper_hit_rate"] >= 0.75


def test_assistant_can_exclude_imported_documents(tmp_path) -> None:
    imported_path = tmp_path / "imported_papers.json"
    imported_path.write_text(
        """[
          {
            "paper_id": "import-noise",
            "title": "main",
            "year": 2026,
            "venue": "Imported Document",
            "authors": ["Local Upload"],
            "source_url": "noise.txt",
            "topics": ["main"],
            "summary": "main idea unrelated imported document",
            "methods": [],
            "findings": [],
            "limitations": []
          }
        ]""",
        encoding="utf-8",
    )

    agent = ResearchAssistant(imported_path=imported_path, include_imported=False)

    assert "import-noise" not in agent.corpus.paper_by_id


def test_corpus_chunks_long_summaries_and_skips_generic_topics() -> None:
    paper = Paper(
        paper_id="long-doc",
        title="Long Document",
        year=2026,
        venue="Test",
        authors=["Tester"],
        source_url="local",
        topics=["main", "specific retrieval topic"],
        summary=" ".join(["retrieval"] * 400),
    )

    corpus = PaperCorpus([paper])
    summary_passages = [item for item in corpus.passages if item.section == "summary"]
    topic_texts = [item.text for item in corpus.passages if item.section == "topics"]

    assert len(summary_passages) > 1
    assert all(len(item.text) <= 900 for item in summary_passages)
    assert "main" not in topic_texts
    assert "specific retrieval topic" in topic_texts


def test_ragas_eval_is_skipped_without_model_key(research_agent) -> None:
    research_agent.llm.api_key = None
    metrics = run_evaluation(research_agent, use_ragas=True)
    assert metrics["ragas"]["skipped"] is True
    assert "DASHSCOPE_API_KEY" in metrics["ragas"]["reason"]


def test_import_and_delete_text_document(research_agent, tmp_path) -> None:
    baseline_count = len(research_agent.list_imported_documents())

    research_agent.corpus.imported_path = tmp_path / "imported_papers.json"
    text_file = tmp_path / "sample.txt"
    text_file.write_text("This imported note discusses retrieval augmented generation and agent planning.", encoding="utf-8")
    imported = research_agent.import_document(text_file, original_name="sample.txt")
    documents = research_agent.list_imported_documents()
    assert any(item["paper_id"] == imported["paper_id"] for item in documents)

    deleted = research_agent.delete_document(imported["paper_id"])
    assert deleted["paper_id"] == imported["paper_id"]
    remaining = research_agent.list_imported_documents()
    assert not any(item["paper_id"] == imported["paper_id"] for item in remaining)
    assert len(remaining) == baseline_count
