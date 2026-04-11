from research_agent.agent import ResearchAssistant
from research_agent.app_service import ResearchApp
from research_agent.models import AnswerResult, ConversationMessage
from research_agent.session_store import SessionStore


def test_session_store_persists_turns(tmp_path) -> None:
    session_path = tmp_path / "sessions.json"
    store = SessionStore(path=session_path)

    created = store.create_session()
    updated = store.append_turn(created.session_id, "How does ReAct use observations?", "It interleaves reasoning and acting.")

    assert updated.turn_count == 1
    assert updated.title.startswith("How does ReAct use observations?")
    assert updated.preview == "It interleaves reasoning and acting."
    assert [item.role for item in updated.messages] == ["user", "assistant"]

    reloaded = SessionStore(path=session_path).get_session(created.session_id)
    assert reloaded.turn_count == 1
    assert reloaded.messages[0].content == "How does ReAct use observations?"


def test_app_ask_creates_and_reuses_session(tmp_path) -> None:
    app = ResearchApp(
        agent=ResearchAssistant(),
        session_store=SessionStore(path=tmp_path / "sessions.json"),
    )

    first = app.ask("How does ReAct use external observations?", top_k=3)
    second = app.ask("How does ReAct use external observations?", top_k=3, session_id=first.session_id)

    assert first.session_id
    assert first.session_title
    assert len(first.history) == 2
    assert second.session_id == first.session_id
    assert second.session_title == first.session_title
    assert len(second.history) == 4
    assert app.get_session(first.session_id).turn_count == 2


def test_delete_session_removes_it_from_listing(tmp_path) -> None:
    app = ResearchApp(
        agent=ResearchAssistant(),
        session_store=SessionStore(path=tmp_path / "sessions.json"),
    )

    session = app.create_session()
    deleted = app.delete_session(session.session_id)

    assert deleted.session_id == session.session_id
    assert app.list_sessions() == []


def test_app_ask_passes_existing_history_to_agent(tmp_path) -> None:
    class DummyAgent:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def answer_question(self, question: str, top_k: int = 5, strict_grounded: bool = True, history: list[ConversationMessage] | None = None) -> AnswerResult:
            self.calls.append(
                {
                    "question": question,
                    "top_k": top_k,
                    "strict_grounded": strict_grounded,
                    "history": list(history or []),
                }
            )
            return AnswerResult(question=question, answer=f"Answer for {question}", evidence=[], trace=[])

    agent = DummyAgent()
    app = ResearchApp(
        agent=agent,
        session_store=SessionStore(path=tmp_path / "sessions.json"),
    )

    first = app.ask("What is ReAct?", top_k=2)
    app.ask("How does it use observations?", top_k=2, session_id=first.session_id)

    assert agent.calls[0]["history"] == []
    assert [item.content for item in agent.calls[1]["history"]] == [
        "What is ReAct?",
        "Answer for What is ReAct?",
    ]


def test_app_ask_stream_emits_events_and_persists_session(tmp_path) -> None:
    class DummyAgent:
        def answer_question_stream(self, question: str, top_k: int = 5, strict_grounded: bool = True, history: list[ConversationMessage] | None = None):
            yield {"type": "chunk", "delta": "Hello "}
            yield {"type": "chunk", "delta": "world"}
            yield {
                "type": "final",
                "data": AnswerResult(question=question, answer="Hello world", evidence=[], trace=[]).model_dump(),
            }

    app = ResearchApp(
        agent=DummyAgent(),
        session_store=SessionStore(path=tmp_path / "sessions.json"),
    )

    events = list(app.ask_stream("Stream this", top_k=2))

    assert events[0]["type"] == "session"
    assert events[1]["type"] == "chunk"
    assert events[2]["type"] == "chunk"
    assert events[-1]["type"] == "final"
    assert events[-1]["data"]["answer"] == "Hello world"
    session_id = events[0]["data"]["session_id"]
    assert app.get_session(session_id).turn_count == 1
