from research_agent.app_service import ResearchApp
from research_agent.models import AnswerResult, ConversationMessage
from research_agent.session_store import SessionStore


def test_session_store_persists_turns(session_store) -> None:
    created = session_store.create_session()
    updated = session_store.append_turn(created.session_id, "How does ReAct use observations?", "It interleaves reasoning and acting.")

    assert updated.turn_count == 1
    assert updated.title.startswith("How does ReAct use observations?")
    assert updated.preview == "It interleaves reasoning and acting."
    assert [item.role for item in updated.messages] == ["user", "assistant"]

    reloaded = SessionStore(path=session_store.path).get_session(created.session_id)
    assert reloaded.turn_count == 1
    assert reloaded.messages[0].content == "How does ReAct use observations?"


def test_app_ask_creates_and_reuses_session(app_service) -> None:
    first = app_service.ask("How does ReAct use external observations?", top_k=3)
    second = app_service.ask("How does ReAct use external observations?", top_k=3, session_id=first.session_id)

    assert first.session_id
    assert first.session_title
    assert len(first.history) == 2
    assert second.session_id == first.session_id
    assert second.session_title == first.session_title
    assert len(second.history) == 4
    assert app_service.get_session(first.session_id).turn_count == 2


def test_delete_session_removes_it_from_listing(app_service) -> None:
    session = app_service.create_session()
    deleted = app_service.delete_session(session.session_id)

    assert deleted.session_id == session.session_id
    assert app_service.list_sessions() == []


def test_app_ask_passes_existing_history_to_agent(session_store) -> None:
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
        session_store=session_store,
    )

    first = app.ask("What is ReAct?", top_k=2)
    app.ask("How does it use observations?", top_k=2, session_id=first.session_id)

    assert agent.calls[0]["history"] == []
    assert [item.content for item in agent.calls[1]["history"]] == [
        "What is ReAct?",
        "Answer for What is ReAct?",
    ]


def test_app_ask_stream_emits_events_and_persists_session(session_store) -> None:
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
        session_store=session_store,
    )

    events = list(app.ask_stream("Stream this", top_k=2))

    assert events[0]["type"] == "session"
    assert events[1]["type"] == "chunk"
    assert events[2]["type"] == "chunk"
    assert events[-1]["type"] == "final"
    assert events[-1]["data"]["answer"] == "Hello world"
    session_id = events[0]["data"]["session_id"]
    assert app.get_session(session_id).turn_count == 1
