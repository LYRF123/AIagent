from __future__ import annotations

import cgi
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .app_service import ResearchApp
from .evaluation import run_evaluation


APP = ResearchApp()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def import_saved_document(saved_path: Path, original_name: str, app: ResearchApp = APP) -> dict:
    try:
        imported = app.agent.import_document(saved_path, original_name=original_name)
    except Exception:
        if saved_path.exists():
            saved_path.unlink()
        raise
    return {
        "message": "导入成功，知识库已刷新。",
        "document": imported,
        "documents": app.agent.list_imported_documents(),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _json_response(self, payload: dict | list, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def _begin_event_stream(self) -> None:
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _write_sse_event(self, event_type: str, payload: dict) -> bool:
        body = f"event: {event_type}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")
        try:
            self.wfile.write(body)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _read_multipart_file(self) -> tuple[str, bytes]:
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            },
        )
        if "file" not in form:
            raise ValueError("请求里没有 file 字段。")
        file_item = form["file"]
        filename = Path(file_item.filename or "uploaded-file").name
        file_bytes = file_item.file.read()
        if not file_bytes:
            raise ValueError("上传文件为空。")
        return filename, file_bytes

    def _save_upload(self, filename: str, file_bytes: bytes) -> Path:
        safe_name = Path(filename).name
        target = UPLOAD_DIR / f"{uuid4().hex[:10]}-{safe_name}"
        target.write_bytes(file_bytes)
        return target

    def _serve_file(self, target: Path) -> None:
        try:
            resolved = target.resolve(strict=True)
        except FileNotFoundError:
            self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return

        if FRONTEND_DIR not in resolved.parents and resolved != INDEX_FILE.resolve():
            self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            return

        content_type, _ = mimetypes.guess_type(str(resolved))
        body = resolved.read_bytes()
        self.close_connection = True
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route == "/health":
            self._json_response({"status": "ok"})
            return
        if route == "/sessions":
            self._json_response({"items": [item.model_dump() for item in APP.list_sessions()]})
            return
        if route.startswith("/sessions/"):
            try:
                session_id = route.removeprefix("/sessions/")
                self._json_response(APP.get_session(session_id).model_dump())
            except Exception as exc:
                self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return
        if route == "/documents":
            self._json_response({"items": APP.agent.list_imported_documents()})
            return
        if route in {"/", "/index.html"}:
            self._serve_file(INDEX_FILE)
            return
        if route.startswith("/static/"):
            relative = route.removeprefix("/static/")
            self._serve_file(FRONTEND_DIR / relative)
            return
        self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/ask-stream":
            self._handle_ask_stream()
            return

        try:
            if self.path == "/sessions":
                payload = self._read_json()
                session = APP.create_session(title=payload.get("title") or "New Session")
                result = {
                    "session": session.model_dump(),
                    "sessions": [item.model_dump() for item in APP.list_sessions()],
                }
            elif self.path == "/delete-session":
                payload = self._read_json()
                deleted = APP.delete_session(payload["session_id"])
                result = {
                    "message": "会话已删除。",
                    "session": deleted.model_dump(),
                    "sessions": [item.model_dump() for item in APP.list_sessions()],
                }
            elif self.path == "/import-document":
                filename, file_bytes = self._read_multipart_file()
                saved_path = self._save_upload(filename, file_bytes)
                result = import_saved_document(saved_path, filename, app=APP)
            elif self.path == "/delete-document":
                payload = self._read_json()
                deleted = APP.agent.delete_document(payload["paper_id"])
                result = {
                    "message": "文档已删除，知识库已刷新。",
                    "document": deleted,
                    "documents": APP.agent.list_imported_documents(),
                }
            else:
                payload = self._read_json()
                if self.path == "/search":
                    result = APP.agent.search_papers(payload["query"], top_k=int(payload.get("top_k", 5)))
                elif self.path == "/ask":
                    result = APP.ask(
                        payload["question"],
                        top_k=int(payload.get("top_k", 5)),
                        session_id=payload.get("session_id"),
                        strict_grounded=bool(payload.get("strict_grounded", True)),
                    ).model_dump()
                elif self.path == "/compare":
                    result = APP.agent.compare_papers(
                        paper_ids=payload.get("paper_ids"),
                        query=payload.get("query"),
                        focus=payload.get("focus", "methods, findings, and limitations"),
                    ).model_dump()
                elif self.path == "/review":
                    result = APP.agent.generate_review(payload["topic"], top_k=int(payload.get("top_k", 5))).model_dump()
                elif self.path == "/evaluate":
                    result = run_evaluation(APP.agent, top_k=int(payload.get("top_k", 5)))
                else:
                    self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
        except Exception as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._json_response(result)

    def _handle_ask_stream(self) -> None:
        try:
            payload = self._read_json()
        except Exception as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._begin_event_stream()
        try:
            for event in APP.ask_stream(
                payload["question"],
                top_k=int(payload.get("top_k", 5)),
                session_id=payload.get("session_id"),
                strict_grounded=bool(payload.get("strict_grounded", True)),
            ):
                event_type = str(event.get("type", "message"))
                event_data = event.get("data") if "data" in event else {"delta": event.get("delta", "")}
                if not isinstance(event_data, dict):
                    event_data = {"value": event_data}
                if not self._write_sse_event(event_type, event_data):
                    return
        except Exception as exc:
            self._write_sse_event("error", {"error": str(exc)})


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
