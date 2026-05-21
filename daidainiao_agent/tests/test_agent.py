import pytest

from daidainiao_agent.agent import ResearchAssistant
from daidainiao_agent.answer_generator import AnswerGenerator
from daidainiao_agent.evaluation import run_evaluation
from daidainiao_agent.corpus import PaperCorpus
from daidainiao_agent.llm import LLMResponse
from daidainiao_agent.models import AnswerResult, Evidence, Paper, Passage
from daidainiao_agent.retrieval import QueryExpander


def reset_import_state(agent: ResearchAssistant, imported_path) -> None:
    agent.llm.api_key = None
    agent.corpus.imported_path = imported_path
    agent.corpus.imported_papers = []
    agent.corpus._refresh_state()
    agent._rebuild_retrievers()


def _pdf_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def write_text_pdf(path, pages: list[str]) -> None:
    page_ids = [3 + index * 2 for index in range(len(pages))]
    content_ids = [4 + index * 2 for index in range(len(pages))]
    font_id = 3 + len(pages) * 2
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>",
    ]
    for page_id, content_id, text in zip(page_ids, content_ids, pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({_pdf_literal(text)}) Tj ET"
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    pdf = "%PDF-1.4\n"
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n{body}\nendobj\n"
    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n"
    pdf += "0000000000 65535 f \n"
    for offset in offsets[1:]:
        pdf += f"{offset:010d} 00000 n \n"
    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    path.write_bytes(pdf.encode("ascii"))


@pytest.mark.slow
def test_search_returns_self_rag_for_reflection_query(daidainiao_agent) -> None:
    results = daidainiao_agent.search_papers("self reflection retrieval critique", top_k=3)
    assert results
    assert results[0]["paper_id"] == "self-rag"


@pytest.mark.slow
def test_answer_contains_evidence(daidainiao_agent) -> None:
    answer = daidainiao_agent.answer_question("How does ReAct use external observations?", top_k=3)
    cited_ids = {item.paper_id for item in answer.evidence}
    assert "react" in cited_ids
    assert "observations" in answer.answer.lower()


def test_compare_by_ids(daidainiao_agent) -> None:
    result = daidainiao_agent.compare_papers(paper_ids=["autogen", "metagpt"])
    row_ids = [row.paper_id for row in result.rows]
    assert row_ids == ["autogen", "metagpt"]


@pytest.mark.slow
def test_eval_pipeline_runs(daidainiao_agent) -> None:
    metrics = run_evaluation(daidainiao_agent)
    assert metrics["num_cases"] == 4
    assert metrics["paper_hit_rate"] >= 0.75


def test_question_classifier_avoids_hi_substring_false_positive() -> None:
    assert AnswerGenerator.classify_question("Which paper adds self reflection to retrieval augmented generation?") == "research"
    assert AnswerGenerator.classify_question("hi there") == "greeting"


def test_system_question_uses_chat_api_probe(daidainiao_agent, monkeypatch) -> None:
    daidainiao_agent.llm.api_key = "fake-key"
    daidainiao_agent.llm.model = "mock-model"
    daidainiao_agent.llm.base_url = "https://example.test/v1"
    daidainiao_agent.llm.embedding_model = "mock-embedding"
    daidainiao_agent.llm.rerank_model = "mock-rerank"

    def fake_complete(system_prompt: str, user_prompt: str, temperature: float = 0.2) -> LLMResponse:
        return LLMResponse(
            text="This response was produced by the configured chat API. The model answering right now is: mock-model.",
            model="mock-model",
            provider="mock",
        )

    monkeypatch.setattr(daidainiao_agent.llm, "complete", fake_complete)

    answer = daidainiao_agent.answer_question("what model are you?", self_correct=False)

    assert answer.question_type == "system"
    assert "mock-model" in answer.answer
    assert [item.tool for item in answer.trace] == ["system_info", "chat_api_probe"]


def test_chinese_acronym_query_expands_to_definition() -> None:
    paper = Paper(
        paper_id="nepa",
        title="Next-Embedding Prediction Makes Strong Vision Learners",
        year=2026,
        venue="Test",
        authors=["Tester"],
        topics=[],
        summary=(
            "Models learn to predict future patch embeddings, which we refer to as "
            "Next-Embedding Predictive Autoregression (NEPA)."
        ),
    )

    expander = QueryExpander(PaperCorpus([paper]))

    for query in [
        "什么是NEPA",
        "NEPA是什么",
        "nepa 是啥",
        "NEPA这个方法是干嘛的",
        "what's NEPA",
        "N.E.P.A 是什么",
        "N E P A 是什么",
        "N-E-P-A 是什么",
    ]:
        variants = expander.expand(query)
        assert any("Next Embedding Predictive Autoregression" in variant for variant in variants)


def test_definition_question_prefers_definition_evidence() -> None:
    definition = Evidence(
        paper_id="nepa",
        title="Next-Embedding Prediction Makes Strong Vision Learners",
        section="summary",
        text=(
            "Abstract. Specifically, models learn to predict future patch embeddings "
            "conditioned on past ones, which we refer to as "
            "Next-Embedding Predictive Autoregression (NEPA)."
        ),
        score=0.89,
        page=1,
    )
    later_mention = Evidence(
        paper_id="nepa",
        title="Next-Embedding Prediction Makes Strong Vision Learners",
        section="summary",
        text="NEPA performs poorly under standard linear probing in this evaluation section.",
        score=1.0,
        page=10,
    )

    ranked = AnswerGenerator._rank_evidence_for_answer(
        [later_mention, definition],
        top_k=1,
        question="什么是NEPA",
    )

    assert ranked == [definition]


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


def test_models_accept_legacy_source_metadata() -> None:
    paper = Paper.model_validate(
        {
            "paper_id": "legacy",
            "title": "Legacy Paper",
            "year": 2024,
            "venue": "Demo",
            "authors": ["Tester"],
            "topics": [],
            "summary": "legacy summary",
        }
    )
    passage = Passage.model_validate(
        {
            "passage_id": "legacy:summary",
            "paper_id": "legacy",
            "title": "Legacy Paper",
            "section": "summary",
            "text": "legacy summary",
        }
    )
    evidence = Evidence.model_validate(
        {
            "paper_id": "legacy",
            "title": "Legacy Paper",
            "section": "summary",
            "text": "legacy summary",
            "score": 1.0,
        }
    )
    answer = AnswerResult.model_validate(
        {
            "question": "legacy question",
            "answer": "legacy answer",
            "evidence": [],
            "trace": [],
        }
    )

    assert paper.source_url == ""
    assert paper.source_passages == []
    assert passage.page is None
    assert evidence.source_label == ""
    assert answer.claim_audit == []


def test_claim_audit_marks_supported_and_weak_citations() -> None:
    evidence = [
        Evidence(
            paper_id="react",
            title="ReAct",
            section="summary",
            text="ReAct combines reasoning and acting via external observations.",
            score=0.92,
        )
    ]

    audit = AnswerGenerator.audit_claims(
        "ReAct uses external observations [1]. Transformers improve protein folding [1].",
        evidence,
    )

    assert [item.status for item in audit] == ["supported", "weak"]
    assert audit[0].evidence_numbers == [1]
    assert "external" in audit[0].matched_terms
    assert audit[0].supporting_quotes == [evidence[0].text]


def test_claim_audit_marks_mismatch_and_unsupported() -> None:
    evidence = [
        Evidence(
            paper_id="react",
            title="ReAct",
            section="summary",
            text="ReAct combines reasoning and acting via external observations.",
            score=0.92,
        )
    ]

    audit = AnswerGenerator.audit_claims(
        "ReAct uses observations [2]. It also solves protein folding.",
        evidence,
    )

    assert [item.status for item in audit] == ["citation_mismatch", "unsupported"]
    assert audit[0].evidence_numbers == [2]
    assert audit[1].evidence_numbers == []


def test_llm_answer_post_processing_adds_claim_audit() -> None:
    class DummyLLM:
        enabled = True

        def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
            return LLMResponse(
                text="ReAct uses external observations [1]. Transformers improve protein folding [1].",
                model="mock",
                provider="mock",
            )

    evidence = [
        Evidence(
            paper_id="react",
            title="ReAct",
            section="summary",
            text="ReAct combines reasoning and acting via external observations.",
            score=0.92,
        )
    ]
    result = AnswerGenerator(DummyLLM())._llm_answer("How does ReAct work?", evidence, trace=[])

    assert [item.status for item in result.claim_audit] == ["supported", "weak"]


def test_import_text_evidence_includes_source_label(daidainiao_agent, tmp_path) -> None:
    reset_import_state(daidainiao_agent, tmp_path / "imported_papers.json")
    text_file = tmp_path / "source-note.txt"
    text_file.write_text(
        "This source note contains a calibration marker for retrieval evidence.",
        encoding="utf-8",
    )

    imported = daidainiao_agent.import_document(text_file, original_name="source-note.txt")
    hits = daidainiao_agent.tfidf_retriever.search_evidence("calibration marker retrieval", top_k=5)
    match = next(item for item in hits if item.paper_id == imported["paper_id"])

    assert match.source_label == "source-note.txt"
    assert match.source_url == str(text_file)
    assert match.page is None


def test_import_pdf_evidence_retains_page_metadata(daidainiao_agent, tmp_path) -> None:
    reset_import_state(daidainiao_agent, tmp_path / "imported_papers.json")
    pdf_file = tmp_path / "paged-paper.pdf"
    write_text_pdf(
        pdf_file,
        [
            "The first page discusses background context.",
            "The second page contains crystalline retrieval evidence.",
        ],
    )

    imported = daidainiao_agent.import_document(pdf_file, original_name="paged-paper.pdf")
    passages = [
        item
        for item in daidainiao_agent.corpus.passages
        if item.paper_id == imported["paper_id"] and item.section == "summary"
    ]
    hits = daidainiao_agent.bm25_retriever.search_evidence("crystalline retrieval evidence", top_k=5)
    match = next(item for item in hits if item.paper_id == imported["paper_id"])

    assert {item.page for item in passages} == {1, 2}
    assert match.source_label == "paged-paper.pdf"
    assert match.page == 2
    assert match.locator == "page 2"


def test_answer_prompt_includes_source_metadata() -> None:
    class DummyLLM:
        enabled = False

    generator = AnswerGenerator(DummyLLM())
    _, user_prompt = generator._build_answer_prompts(
        "What is the evidence?",
        [
            Evidence(
                paper_id="imported",
                title="Imported Paper",
                section="summary",
                text="A grounded claim from the source.",
                score=0.9,
                source_label="paper.pdf",
                page=3,
                locator="page 3",
            )
        ],
    )

    assert "source=paper.pdf" in user_prompt
    assert "page=3" in user_prompt


def test_ragas_eval_is_skipped_without_model_key(daidainiao_agent) -> None:
    daidainiao_agent.llm.api_key = None
    metrics = run_evaluation(daidainiao_agent, use_ragas=True)
    assert metrics["ragas"]["skipped"] is True
    assert "DASHSCOPE_API_KEY" in metrics["ragas"]["reason"]


@pytest.mark.slow
def test_ragas_evaluation_produces_correct_structure(daidainiao_agent) -> None:
    """Ragas evaluation with mocked LLM returns correct payload structure."""
    import sys
    import pandas as pd
    from unittest.mock import MagicMock

    # Make LLM appear enabled so we reach the ragas code path
    daidainiao_agent.llm.api_key = "fake-key"

    # Build fake scores that the mocked ragas.evaluate() will return.
    # One row per eval case (demo_eval.json has 4 cases).
    fake_df = pd.DataFrame({
        "user_input": ["q1", "q2", "q3", "q4"],
        "response": ["a1", "a2", "a3", "a4"],
        "retrieved_contexts": [["c1"], ["c2"], ["c3"], ["c4"]],
        "reference": ["r1", "r2", "r3", "r4"],
        "faithfulness": [0.92, 0.85, 0.78, 0.91],
        "llm_context_precision_with_reference": [0.81, 0.72, 0.69, 0.80],
        "context_recall": [0.73, 0.65, 0.60, 0.71],
        "answer_relevancy": [0.88, 0.82, 0.76, 0.84],
    })

    fake_result = MagicMock()
    fake_result.to_pandas.return_value = fake_df

    fake_ragas = MagicMock()
    fake_ragas.evaluate.return_value = fake_result
    fake_ragas.EvaluationDataset.from_list.return_value = MagicMock()

    # Fake metric classes so the private-module imports succeed
    class FakeFaithfulness:
        name = "faithfulness"

    class FakeContextPrecision:
        name = "llm_context_precision_with_reference"

    class FakeContextRecall:
        name = "context_recall"

    class FakeResponseRelevancy:
        name = "answer_relevancy"

    # Save original modules before injecting fakes
    ragas_keys = [
        "ragas",
        "ragas.metrics",
        "ragas.metrics._faithfulness",
        "ragas.metrics._context_precision",
        "ragas.metrics._context_recall",
        "ragas.metrics._answer_relevance",
    ]
    orig = {k: sys.modules.get(k) for k in ragas_keys}

    try:
        sys.modules["ragas"] = fake_ragas
        sys.modules["ragas.metrics"] = MagicMock()
        sys.modules["ragas.metrics._faithfulness"] = MagicMock(
            Faithfulness=FakeFaithfulness,
        )
        sys.modules["ragas.metrics._context_precision"] = MagicMock(
            LLMContextPrecisionWithReference=FakeContextPrecision,
        )
        sys.modules["ragas.metrics._context_recall"] = MagicMock(
            LLMContextRecall=FakeContextRecall,
        )
        sys.modules["ragas.metrics._answer_relevance"] = MagicMock(
            ResponseRelevancy=FakeResponseRelevancy,
        )

        # Mock LLM so answer_question() doesn't try to call DashScope
        daidainiao_agent.llm.complete = MagicMock(
            return_value=type("LLMResponse", (), {"text": "Mocked answer.", "model": "mock", "provider": "test"})()
        )

        payload = run_evaluation(daidainiao_agent, use_ragas=True)

        # 1. ragas key exists and is not skipped
        assert "ragas" in payload
        ragas = payload["ragas"]
        assert ragas["enabled"] is True
        assert ragas["skipped"] is False

        # 2. metric names are correct
        assert set(ragas["metrics"]) == {
            "faithfulness",
            "llm_context_precision_with_reference",
            "context_recall",
            "answer_relevancy",
        }

        # 3. per_case and summary have correct structure
        assert len(ragas["per_case"]) == payload["num_cases"]
        first = ragas["per_case"][0]
        assert "case_id" in first
        assert first["faithfulness"] == 0.92
        assert first["answer_relevancy"] == 0.88

        # summary = average across 4 cases
        assert ragas["summary"]["faithfulness"] == 0.865
        assert ragas["summary"]["answer_relevancy"] == 0.825
        assert isinstance(ragas["summary"]["faithfulness"], float)

    finally:
        # Restore original modules
        for k in ragas_keys:
            if orig[k] is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = orig[k]


def test_self_correct_disabled_without_llm(daidainiao_agent) -> None:
    """When LLM is disabled, self_correct must degrade gracefully (return normal results)."""
    daidainiao_agent.llm.api_key = None
    answer = daidainiao_agent.answer_question(
        "What is ReAct?", top_k=3, self_correct=True
    )
    assert answer.answer
    assert isinstance(answer.evidence, list)


def test_answer_question_accepts_self_correct_param(daidainiao_agent) -> None:
    """Self-correct parameter is accepted and doesn't crash."""
    answer = daidainiao_agent.answer_question(
        "How does ReAct use external observations?",
        top_k=3,
        self_correct=False
    )
    cited_ids = {item.paper_id for item in answer.evidence}
    assert "react" in cited_ids
    assert "observations" in answer.answer.lower()


@pytest.mark.slow
def test_answer_question_includes_retrieval_diagnostics(daidainiao_agent) -> None:
    answer = daidainiao_agent.answer_question(
        "How does ReAct use external observations?",
        top_k=2,
        self_correct=False,
    )

    assert answer.diagnostics["original_query"]
    assert answer.diagnostics["fusion"]["status"] == "completed"
    assert answer.diagnostics["pipeline_stages"]


def test_self_correct_evidence_evaluator_with_mock() -> None:
    """EvidenceEvaluator uses heuristic pre-check for high retrieval scores."""
    from daidainiao_agent.self_correct import EvidenceEvaluator
    from daidainiao_agent.models import Evidence, ToolTrace
    from unittest.mock import MagicMock
    from daidainiao_agent.llm import LLMResponse

    mock_llm = MagicMock()
    mock_llm.enabled = True
    mock_llm.complete.return_value = LLMResponse(
        text="[0.9, 0.3, 0.7, 0.1]",
        model="mock",
        provider="mock"
    )

    evaluator = EvidenceEvaluator(mock_llm)
    evidence = [
        Evidence(paper_id="p1", title="t1", section="summary", text="text1", score=0.9),
        Evidence(paper_id="p2", title="t2", section="methods", text="text2", score=0.8),
        Evidence(paper_id="p3", title="t3", section="findings", text="text3", score=0.7),
        Evidence(paper_id="p4", title="t4", section="limitations", text="text4", score=0.6),
    ]
    trace = []
    result = evaluator.evaluate("test question", evidence, trace)

    assert "scores" in result
    # high retrieval scores (avg=0.75 >= 0.7) trigger heuristic pre-check,
    # using retrieval scores directly instead of LLM
    assert result["scores"] == [0.9, 0.8, 0.7, 0.6]
    assert result["average"] == pytest.approx(0.75)  # (0.9+0.8+0.7+0.6)/4
    assert len(trace) > 0
    assert trace[0].tool == "evidence_evaluator"


def test_self_correct_query_rewriter_with_mock() -> None:
    """QueryRewriter returns rewritten query (heuristic on attempt=1, LLM on attempt>=2)."""
    from daidainiao_agent.self_correct import QueryRewriter
    from daidainiao_agent.models import Evidence, ToolTrace
    from unittest.mock import MagicMock
    from daidainiao_agent.llm import LLMResponse

    mock_llm = MagicMock()
    mock_llm.enabled = True
    mock_llm.complete.return_value = LLMResponse(
        text="What architectures does the MaIR model use for image restoration?",
        model="mock",
        provider="mock"
    )

    rewriter = QueryRewriter(mock_llm)
    evidence = [Evidence(paper_id="p1", title="t1", section="summary", text="irrelevant text", score=0.3)]
    trace = []
    result = rewriter.rewrite("What is MaIR?", evidence, attempt=1, trace=trace)

    assert isinstance(result, str)
    assert len(result) > 0
    assert len(trace) > 0
    assert trace[0].tool == "query_rewriter"


def test_import_and_delete_text_document(daidainiao_agent, tmp_path) -> None:
    baseline_count = len(daidainiao_agent.list_imported_documents())

    daidainiao_agent.corpus.imported_path = tmp_path / "imported_papers.json"
    text_file = tmp_path / "sample.txt"
    text_file.write_text("This imported note discusses retrieval augmented generation and agent planning.", encoding="utf-8")
    imported = daidainiao_agent.import_document(text_file, original_name="sample.txt")
    documents = daidainiao_agent.list_imported_documents()
    assert any(item["paper_id"] == imported["paper_id"] for item in documents)

    deleted = daidainiao_agent.delete_document(imported["paper_id"])
    assert deleted["paper_id"] == imported["paper_id"]
    remaining = daidainiao_agent.list_imported_documents()
    assert not any(item["paper_id"] == imported["paper_id"] for item in remaining)
    assert len(remaining) == baseline_count
