from pathlib import Path

from research_agent.agent import ResearchAssistant
from research_agent.models import AnswerResult, ConversationMessage, Evidence
from research_agent.server import import_saved_document


def reset_import_state(agent: ResearchAssistant, imported_path: Path) -> None:
    agent.corpus.imported_path = imported_path
    agent.corpus.imported_papers = []
    agent.corpus._refresh_state()
    agent._rebuild_retrievers()


def test_answer_without_evidence_is_blocked_by_default(monkeypatch) -> None:
    agent = ResearchAssistant()
    agent.llm.api_key = "test-key"
    monkeypatch.setattr(agent, "_retrieve_evidence", lambda question, top_k, trace: [])

    def unexpected_call(question: str, trace: list) -> AnswerResult:
        raise AssertionError("general LLM fallback should not run in strict mode")

    monkeypatch.setattr(agent, "_llm_general_answer", unexpected_call)
    answer = agent.answer_question("A completely unsupported question")

    assert answer.insufficient_evidence is True
    assert "can't answer this reliably" in answer.answer
    assert any(item.tool == "grounded_answer_guard" for item in answer.trace)


def test_answer_without_evidence_can_fallback_when_opted_out(monkeypatch) -> None:
    agent = ResearchAssistant()
    agent.llm.api_key = "test-key"
    monkeypatch.setattr(agent, "_retrieve_evidence", lambda question, top_k, trace: [])
    monkeypatch.setattr(
        agent,
        "_llm_general_answer",
        lambda question, trace: AnswerResult(
            question=question,
            answer="Fallback answer.",
            evidence=[],
            trace=trace,
        ),
    )

    answer = agent.answer_question("A completely unsupported question", strict_grounded=False)

    assert answer.answer == "Fallback answer."
    assert answer.insufficient_evidence is False


def test_import_saved_document_cleans_up_failed_upload(tmp_path) -> None:
    saved_path = tmp_path / "bad-upload.txt"
    saved_path.write_text("broken", encoding="utf-8")

    class DummyAgent:
        def import_document(self, path: Path, original_name: str | None = None) -> dict:
            raise ValueError("parse failed")

        def list_imported_documents(self) -> list[dict]:
            return []

    class DummyApp:
        agent = DummyAgent()

    try:
        import_saved_document(saved_path, "bad-upload.txt", app=DummyApp())
    except ValueError as exc:
        assert str(exc) == "parse failed"
    else:
        raise AssertionError("expected import failure")

    assert not saved_path.exists()


def test_delete_document_only_removes_managed_upload_file(tmp_path) -> None:
    agent = ResearchAssistant()
    reset_import_state(agent, tmp_path / "imported_papers.json")
    agent.managed_upload_dir = tmp_path / "uploads"
    agent.managed_upload_dir.mkdir(parents=True, exist_ok=True)

    managed_file = agent.managed_upload_dir / "managed.txt"
    managed_file.write_text("This managed note discusses ReAct and retrieval.", encoding="utf-8")
    managed_doc = agent.import_document(managed_file, original_name="managed.txt")
    agent.delete_document(managed_doc["paper_id"])
    assert not managed_file.exists()

    external_file = tmp_path / "external.txt"
    external_file.write_text("This external note should stay on disk.", encoding="utf-8")
    external_doc = agent.import_document(external_file, original_name="external.txt")
    agent.delete_document(external_doc["paper_id"])
    assert external_file.exists()


def test_follow_up_question_uses_session_history_in_retrieval(monkeypatch) -> None:
    agent = ResearchAssistant()
    captured: dict[str, str] = {}

    def fake_retrieve(query: str, top_k: int, trace: list) -> list:
        captured["query"] = query
        return []

    monkeypatch.setattr(agent, "_retrieve_evidence", fake_retrieve)
    answer = agent.answer_question(
        "How does it use observations?",
        history=[
            ConversationMessage(role="user", content="How does ReAct work?"),
            ConversationMessage(role="assistant", content="ReAct combines reasoning with tool use."),
        ],
    )

    assert answer.insufficient_evidence is True
    assert "ReAct" in captured["query"]
    assert "How does it use observations?" in captured["query"]


def test_answer_question_stream_emits_chunks_and_final(monkeypatch) -> None:
    agent = ResearchAssistant()
    monkeypatch.setattr(
        agent,
        "_retrieve_evidence",
        lambda query, top_k, trace: [
            Evidence(
                paper_id="react",
                title="ReAct",
                section="summary",
                text="ReAct combines reasoning with acting via external observations.",
                score=0.92,
            )
        ],
    )

    events = list(agent.answer_question_stream("How does ReAct work?", top_k=1))

    assert any(event["type"] == "chunk" for event in events)
    assert events[-1]["type"] == "final"
    assert events[-1]["data"]["evidence"][0]["paper_id"] == "react"
    assert "ReAct" in events[-1]["data"]["answer"]


def test_rule_based_answer_matches_chinese_question_language(monkeypatch) -> None:
    agent = ResearchAssistant()
    monkeypatch.setattr(
        agent,
        "_retrieve_evidence",
        lambda query, top_k, trace: [
            Evidence(
                paper_id="react",
                title="ReAct",
                section="summary",
                text="ReAct 通过交替进行推理和动作来利用外部观察。",
                score=0.95,
            )
        ],
    )

    agent.llm.api_key = None
    answer = agent.answer_question("ReAct 是如何把推理和工具调用结合起来的？", top_k=1)

    assert "表明" in answer.answer
    assert "indicates that" not in answer.answer
