from __future__ import annotations

import cgi
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import uuid4

from .agent import ResearchAssistant
from .evaluation import run_evaluation


AGENT = ResearchAssistant()
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class Handler(BaseHTTPRequestHandler):
    def _json_response(self, payload: dict | list, status: int = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = unquote(parsed.path)
        if route == "/health":
            self._json_response({"status": "ok"})
            return
        if route == "/documents":
            self._json_response({"items": AGENT.list_imported_documents()})
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
        try:
            if self.path == "/import-document":
                filename, file_bytes = self._read_multipart_file()
                saved_path = self._save_upload(filename, file_bytes)
                imported = AGENT.import_document(saved_path, original_name=filename)
                result = {
                    "message": "导入成功，知识库已刷新。",
                    "document": imported,
                    "documents": AGENT.list_imported_documents(),
                }
            elif self.path == "/delete-document":
                payload = self._read_json()
                deleted = AGENT.delete_document(payload["paper_id"])
                result = {
                    "message": "文档已删除，知识库已刷新。",
                    "document": deleted,
                    "documents": AGENT.list_imported_documents(),
                }
            else:
                payload = self._read_json()
                if self.path == "/search":
                    result = AGENT.search_papers(payload["query"], top_k=int(payload.get("top_k", 5)))
                elif self.path == "/ask":
                    result = AGENT.answer_question(payload["question"], top_k=int(payload.get("top_k", 5))).model_dump()
                elif self.path == "/compare":
                    result = AGENT.compare_papers(
                        paper_ids=payload.get("paper_ids"),
                        query=payload.get("query"),
                        focus=payload.get("focus", "methods, findings, and limitations"),
                    ).model_dump()
                elif self.path == "/review":
                    result = AGENT.generate_review(payload["topic"], top_k=int(payload.get("top_k", 5))).model_dump()
                elif self.path == "/evaluate":
                    result = run_evaluation(AGENT, top_k=int(payload.get("top_k", 5)))
                else:
                    self._json_response({"error": "not found"}, status=HTTPStatus.NOT_FOUND)
                    return
        except Exception as exc:
            self._json_response({"error": str(exc)}, status=HTTPStatus.BAD_REQUEST)
            return

        self._json_response(result)


def main() -> None:
    server = HTTPServer(("127.0.0.1", 8000), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()
