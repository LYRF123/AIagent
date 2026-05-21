from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from uuid import uuid4

from .models import ConversationMessage, SessionDetail, SessionSummary


def default_session_path() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "sessions.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def normalize_preview(value: str, limit: int = 96) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


def build_session_title(question: str, limit: int = 36) -> str:
    compact = " ".join(question.split())
    if not compact:
        return "New Session"
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "..."


class SessionStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_session_path()
        self._lock = Lock()
        self._sessions = self._load_sessions()

    def _load_sessions(self) -> dict[str, SessionDetail]:
        if not self.path.exists():
            return {}
        with self.path.open("r", encoding="utf-8-sig") as handle:
            raw = json.load(handle)
        sessions = {}
        for item in raw:
            detail = SessionDetail.model_validate(item)
            sessions[detail.session_id] = detail
        return sessions

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(
            self._sessions.values(),
            key=lambda item: (item.updated_at, item.session_id),
            reverse=True,
        )
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump([item.model_dump() for item in ordered], handle, ensure_ascii=False, indent=2)

    def _copy_session(self, session: SessionDetail) -> SessionDetail:
        return SessionDetail.model_validate(session.model_dump())

    def _build_summary(self, session: SessionDetail) -> SessionSummary:
        return SessionSummary(
            session_id=session.session_id,
            title=session.title,
            turn_count=session.turn_count,
            updated_at=session.updated_at,
            preview=session.preview,
        )

    def list_sessions(self) -> list[SessionSummary]:
        with self._lock:
            ordered = sorted(
                self._sessions.values(),
                key=lambda item: (item.updated_at, item.session_id),
                reverse=True,
            )
            return [self._build_summary(item) for item in ordered]

    def create_session(self, title: str = "New Session") -> SessionDetail:
        with self._lock:
            session = SessionDetail(
                session_id=uuid4().hex,
                title=title,
                turn_count=0,
                updated_at=utc_now_iso(),
                preview="",
                messages=[],
            )
            self._sessions[session.session_id] = session
            self._persist()
            return self._copy_session(session)

    def get_session(self, session_id: str) -> SessionDetail:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("会话不存在。")
            return self._copy_session(session)

    def delete_session(self, session_id: str) -> SessionSummary:
        with self._lock:
            session = self._sessions.pop(session_id, None)
            if session is None:
                raise ValueError("会话不存在。")
            self._persist()
            return self._build_summary(session)

    def append_turn(self, session_id: str, question: str, answer: str) -> SessionDetail:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("会话不存在。")
            if session.turn_count == 0 and session.title == "New Session":
                session.title = build_session_title(question)
            session.messages.append(ConversationMessage(role="user", content=question))
            session.messages.append(ConversationMessage(role="assistant", content=answer))
            session.turn_count += 1
            session.updated_at = utc_now_iso()
            session.preview = normalize_preview(answer or question)
            self._persist()
            return self._copy_session(session)

    def truncate_session(self, session_id: str, message_index: int) -> SessionDetail:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise ValueError("会话不存在。")
            # Truncate messages list
            session.messages = session.messages[:message_index]
            session.turn_count = len(session.messages) // 2
            session.updated_at = utc_now_iso()
            if session.messages:
                # Use the content of the last message for the preview
                session.preview = normalize_preview(session.messages[-1].content)
            else:
                session.preview = ""
            self._persist()
            return self._copy_session(session)
