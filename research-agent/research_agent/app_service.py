from __future__ import annotations

from collections.abc import Iterator

from .agent import ResearchAssistant
from .models import AnswerResult, ConversationMessage, SessionDetail, SessionSummary
from .session_store import SessionStore


class ResearchApp:
    def __init__(
        self,
        agent: ResearchAssistant | None = None,
        session_store: SessionStore | None = None,
    ) -> None:
        self.agent = agent or ResearchAssistant()
        self.session_store = session_store or SessionStore()

    def list_sessions(self) -> list[SessionSummary]:
        return self.session_store.list_sessions()

    def get_session(self, session_id: str) -> SessionDetail:
        return self.session_store.get_session(session_id)

    def create_session(self, title: str = "New Session") -> SessionDetail:
        return self.session_store.create_session(title=title)

    def delete_session(self, session_id: str) -> SessionSummary:
        return self.session_store.delete_session(session_id)

    def ask(self, question: str, top_k: int = 5, session_id: str | None = None, strict_grounded: bool = True) -> AnswerResult:
        prior_history: list[ConversationMessage] = []
        if session_id:
            active_session = self.session_store.get_session(session_id)
            prior_history = list(active_session.messages)
        else:
            active_session = self.session_store.create_session()
        answer = self.agent.answer_question(
            question,
            top_k=top_k,
            strict_grounded=strict_grounded,
            history=prior_history,
        )
        updated_session = self.session_store.append_turn(active_session.session_id, question, answer.answer)
        answer.session_id = updated_session.session_id
        answer.session_title = updated_session.title
        answer.history = list(updated_session.messages)
        return answer

    def ask_stream(self, question: str, top_k: int = 5, session_id: str | None = None, strict_grounded: bool = True) -> Iterator[dict]:
        prior_history: list[ConversationMessage] = []
        if session_id:
            active_session = self.session_store.get_session(session_id)
            prior_history = list(active_session.messages)
        else:
            active_session = self.session_store.create_session()

        yield {
            "type": "session",
            "data": {
                "session_id": active_session.session_id,
                "session_title": active_session.title,
            },
        }

        for event in self.agent.answer_question_stream(
            question,
            top_k=top_k,
            strict_grounded=strict_grounded,
            history=prior_history,
        ):
            if event.get("type") != "final":
                yield event
                continue

            answer = AnswerResult.model_validate(event["data"])
            updated_session = self.session_store.append_turn(active_session.session_id, question, answer.answer)
            answer.session_id = updated_session.session_id
            answer.session_title = updated_session.title
            answer.history = list(updated_session.messages)
            yield {
                "type": "final",
                "data": answer.model_dump(),
            }
            return

        raise RuntimeError("ask stream finished without a final payload")
