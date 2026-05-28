from __future__ import annotations

from email import policy
from email.parser import BytesParser
import json
import mimetypes
import os
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse
from uuid import uuid4

from .app_service import ResearchApp
from .agent import ResearchAssistant
from .evaluation import default_eval_path, run_evaluation
from .rag_lab import run_rag_lab_evaluation
from .server_utils import resolve_data_path


CORPUS_PATH = os.getenv("DAIDAINIAO_AGENT_CORPUS") or os.getenv("RESEARCH_AGENT_CORPUS")
EVAL_PATH = os.getenv("DAIDAINIAO_AGENT_EVAL_PATH") or os.getenv("RESEARCH_AGENT_EVAL_PATH")
MAX_JSON_BODY = 1 * 1024 * 1024       # 1 MB
MAX_UPLOAD_BODY = 50 * 1024 * 1024    # 50 MB
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_APP: ResearchApp | None = None


def get_app() -> ResearchApp:
    global _APP
    if _APP is None:
        _APP = ResearchApp(agent=ResearchAssistant(corpus_path=CORPUS_PATH))
    return _APP


def set_app(app: ResearchApp) -> None:
    global _APP
    _APP = app


def parse_multipart_file(content_type: str, body: bytes) -> tuple[str, bytes]:
    if "multipart/form-data" not in content_type:
        raise ValueError("请求不是 multipart/form-data。")

    raw_message = (
        f"Content-Type: {content_type}\r\n"
        "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        if part.get_param("name", header="content-disposition") != "file":
            continue
        filename = Path(part.get_filename() or "uploaded-file").name
        file_bytes = part.get_payload(decode=True) or b""
        if not file_bytes:
            raise ValueError("上传文件为空。")
        return filename, file_bytes

    raise ValueError("请求里没有 file 字段。")


def import_saved_document(saved_path: Path, original_name: str, app: ResearchApp | None = None) -> dict:
    if app is None:
        app = get_app()
    try:
        imported = app.agent.import_document(saved_path, original_name=original_name)
    except Exception:
        if saved_path.exists():
            saved_path.unlink()
        raise
    message = "导入成功，知识库已刷新。"
    if imported.get("vector_warning"):
        message = f"{message} {imported['vector_warning']}"
    return {
        "message": message,
        "document": imported,
        "documents": app.agent.list_imported_documents(),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # --- rate limiting ---
    _rate_limits: dict[str, list[float]] = {}
    _rate_lock = threading.Lock()

    def _check_rate_limit(self) -> bool:
        """Return True if the request is allowed, False if rate-limited (429 sent)."""
        now = time.time()
        ip = self.client_address[0]
        with Handler._rate_lock:
            timestamps = Handler._rate_limits.get(ip)
            if timestamps is None:
                timestamps = []
                Handler._rate_limits[ip] = timestamps
            # Purge entries older than 60 seconds
            timestamps[:] = [t for t in timestamps if now - t <= 60.0]
            if len(timestamps) >= 30:
                return False
            timestamps.append(now)
        return True

    def _send_rate_limit_response(self) -> None:
        body = json.dumps(
            {"error": "rate_limit_exceeded", "message": "Too many requests. Please slow down."},
            ensure_ascii=False,
        ).encode("utf-8")
        self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
        self._send_cors_headers()
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

    def _send_cors_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json_response(self, payload: dict | list, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.close_connection = True
        self.send_response(status)
        self._send_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:
        if not self._check_rate_limit():
            self._send_rate_limit_response()
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_JSON_BODY:
            raise ValueError(f"请求体超过限制（最大 {MAX_JSON_BODY // 1024} KB）。")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _read_multipart_file(self) -> tuple[str, bytes]:
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_UPLOAD_BODY:
            raise ValueError(f"上传文件超过限制（最大 {MAX_UPLOAD_BODY // (1024 * 1024)} MB）。")
        body = self.rfile.read(length) if length else b""
        return parse_multipart_file(self.headers.get("Content-Type", ""), body)

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
        if resolved == INDEX_FILE.resolve() or resolved.suffix in {".js", ".css", ".html"}:
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if not self._check_rate_limit():
            self._send_rate_limit_response()
            return
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        app = get_app()
        if route == "/health":
            self._json_response({"status": "ok"})
            return
        if route == "/sessions":
            self._json_response({"items": [item.model_dump() for item in app.list_sessions()]})
            return
        if route.startswith("/sessions/"):
            try:
                session_id = route.removeprefix("/sessions/")
                self._json_response(app.get_session(session_id).model_dump())
            except ValueError:
                self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
            except Exception:
                self._json_response({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
            return
        if route == "/documents":
            self._json_response({"items": app.agent.list_imported_documents()})
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
        if not self._check_rate_limit():
            self._send_rate_limit_response()
            return
        if self.path == "/ask-stream":
            self._handle_ask_stream()
            return

        app = get_app()
        try:
            if self.path == "/sessions":
                payload = self._read_json()
                session = app.create_session(title=payload.get("title") or "New Session")
                result = {
                    "session": session.model_dump(),
                    "sessions": [item.model_dump() for item in app.list_sessions()],
                }
            elif self.path == "/delete-session":
                payload = self._read_json()
                deleted = app.delete_session(payload["session_id"])
                result = {
                    "message": "会话已删除。",
                    "session": deleted.model_dump(),
                    "sessions": [item.model_dump() for item in app.list_sessions()],
                }
            elif self.path == "/import-document":
                filename, file_bytes = self._read_multipart_file()
                saved_path = self._save_upload(filename, file_bytes)
                result = import_saved_document(saved_path, filename, app=app)
            elif self.path == "/delete-document":
                payload = self._read_json()
                deleted = app.agent.delete_document(payload["paper_id"])
                result = {
                    "message": "文档已删除，知识库已刷新。",
                    "document": deleted,
                    "documents": app.agent.list_imported_documents(),
                }
            elif self.path == "/search":
                payload = self._read_json()
                result = app.agent.search_papers(payload["query"], top_k=int(payload.get("top_k", 5)))
            elif self.path == "/ask":
                payload = self._read_json()
                result = app.ask(
                    payload["question"],
                    top_k=int(payload.get("top_k", 5)),
                    session_id=payload.get("session_id"),
                    strict_grounded=bool(payload.get("strict_grounded", True)),
                    use_rerank=bool(payload.get("use_rerank", True)),
                ).model_dump()
            elif self.path == "/compare":
                payload = self._read_json()
                result = app.agent.compare_papers(
                    paper_ids=payload.get("paper_ids"),
                    query=payload.get("query"),
                    focus=payload.get("focus", "methods, findings, and limitations"),
                ).model_dump()
            elif self.path == "/review":
                payload = self._read_json()
                result = app.agent.generate_review(payload["topic"], top_k=int(payload.get("top_k", 5))).model_dump()
            elif self.path == "/evaluate" or self.path.startswith("/evaluate?"):
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                top_k = int(qs.get("top_k", [5])[0])
                use_ragas = qs.get("ragas", ["false"])[0].lower() in ("true", "1", "yes")
                include_imported = qs.get("include_imported", ["false"])[0].lower() in ("true", "1", "yes")

                eval_path = EVAL_PATH if EVAL_PATH else None
                if eval_path is not None:
                    if not Path(eval_path).exists():
                        self._json_response({"error": "evaluation not configured"}, status=HTTPStatus.NOT_FOUND)
                        return
                else:
                    if not default_eval_path().exists():
                        self._json_response({"error": "evaluation not configured"}, status=HTTPStatus.NOT_FOUND)
                        return

                if include_imported:
                    eval_agent = ResearchAssistant(corpus_path=CORPUS_PATH, include_imported=True)
                else:
                    eval_agent = app.agent

                result = run_evaluation(
                    eval_agent,
                    eval_path=eval_path,
                    top_k=top_k,
                    use_ragas=use_ragas,
                )
            elif self.path == "/rag-lab/evaluate":
                payload = self._read_json()
                raw_eval_path = payload.get("eval_path") or (EVAL_PATH if EVAL_PATH else None)
                eval_path_resolved = None
                if raw_eval_path:
                    try:
                        eval_path_resolved = resolve_data_path(str(raw_eval_path), must_exist=True)
                    except ValueError as exc:
                        self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
                        return
                include_imported_value = payload.get("include_imported", True)
                include_imported = (
                    include_imported_value
                    if isinstance(include_imported_value, bool)
                    else str(include_imported_value).strip().lower() not in ("false", "0", "no", "off")
                )
                eval_agent = app.agent if include_imported else ResearchAssistant(corpus_path=CORPUS_PATH, include_imported=False)
                result = run_rag_lab_evaluation(
                    eval_agent,
                    eval_path=eval_path_resolved,
                    cases=payload.get("cases"),
                    configs=payload.get("configs"),
                    default_top_k=int(payload.get("top_k", 5)),
                    default_candidate_k=payload.get("candidate_k"),
                )
            else:
                self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                return
        except (KeyError, ValueError, TypeError) as exc:
            self._json_response({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
            return
        except Exception:
            self._json_response({"error": "internal server error"}, status=HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        self._json_response(result)

    def _handle_ask_stream(self) -> None:
        app = get_app()
        try:
            payload = self._read_json()
        except Exception:
            self._json_response({"error": "bad request"}, status=HTTPStatus.BAD_REQUEST)
            return

        self._begin_event_stream()
        try:
            for event in app.ask_stream(
                payload["question"],
                top_k=int(payload.get("top_k", 5)),
                session_id=payload.get("session_id"),
                strict_grounded=bool(payload.get("strict_grounded", True)),
                use_rerank=bool(payload.get("use_rerank", True)),
            ):
                event_type = str(event.get("type", "message"))
                event_data = event.get("data") if "data" in event else {"delta": event.get("delta", "")}
                if not isinstance(event_data, dict):
                    event_data = {"value": event_data}
                if not self._write_sse_event(event_type, event_data):
                    return
        except Exception:
            self._write_sse_event("error", {"error": "internal server error"})


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 8000), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
