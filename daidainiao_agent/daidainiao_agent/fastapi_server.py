from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from starlette.responses import Response
from fastapi.staticfiles import StaticFiles

from .app_service import ResearchApp
from .agent import ResearchAssistant
from .evaluation import default_eval_path, run_evaluation
from .logging_config import logger
from .rag_lab import run_rag_lab_evaluation
from .model_profiles import (
    apply_model_settings,
    find_profile,
    load_profile_store,
    public_profile,
    resolve_active_profile_id,
)
from .export import format_answer_markdown, format_bibtex, format_obsidian_markdown
from .server_utils import (
    MAX_JSON_BODY_BYTES,
    MAX_UPLOAD_BYTES,
    PROJECT_ROOT,
    api_token_required,
    cors_allow_credentials,
    default_cors_origins,
    import_saved_document,
    rate_limit_exempt,
    resolve_data_path,
    verify_api_token,
)

CORPUS_PATH = os.getenv("DAIDAINIAO_AGENT_CORPUS") or os.getenv("RESEARCH_AGENT_CORPUS")
EVAL_PATH = os.getenv("DAIDAINIAO_AGENT_EVAL_PATH") or os.getenv("RESEARCH_AGENT_EVAL_PATH")
FRONTEND_DIR = PROJECT_ROOT / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MODEL_PROFILES_PATH = PROJECT_ROOT / "data" / "model_profiles.json"
ENV_PATH = PROJECT_ROOT / ".env"
MAX_TOP_K = 12

_app_instance = None


def get_app() -> ResearchApp:
    global _app_instance
    if _app_instance is None:
        _app_instance = ResearchApp(agent=ResearchAssistant(corpus_path=CORPUS_PATH))
    return _app_instance


def _resolve_eval_path(path_value: str | None) -> Path | None:
    if not path_value:
        return None
    return resolve_data_path(path_value, must_exist=True)


def _sanitize_request_id(value: str | None) -> str:
    cleaned = "".join(ch for ch in (value or "") if ch.isalnum() or ch in "-_")[:64]
    return cleaned or uuid4().hex[:12]


def _request_id(request: Request) -> str:
    existing = getattr(request.state, "request_id", "")
    if existing:
        return existing
    request.state.request_id = _sanitize_request_id(request.headers.get("x-request-id"))
    return request.state.request_id


def _error_code(status_code: int) -> str:
    if status_code == 400:
        return "invalid_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 404:
        return "not_found"
    if status_code == 413:
        return "payload_too_large"
    if status_code == 422:
        return "validation_error"
    if status_code == 429:
        return "rate_limit_exceeded"
    if status_code >= 500:
        return "internal_server_error"
    return "request_failed"


def _error_payload(request: Request, status_code: int, detail=None, *, code: str | None = None, message: str | None = None) -> dict:
    if isinstance(detail, dict):
        code = str(detail.get("error") or detail.get("code") or code or _error_code(status_code))
        message = str(detail.get("message") or detail.get("detail") or message or code)
    elif isinstance(detail, list):
        code = code or _error_code(status_code)
        message = message or "请求参数校验失败。"
    else:
        code = code or _error_code(status_code)
        message = message or str(detail or code)
    return {
        "error": code,
        "message": message,
        "detail": detail if detail is not None else message,
        "request_id": _request_id(request),
    }


def _json_error_response(
    request: Request,
    status_code: int,
    detail=None,
    *,
    code: str | None = None,
    message: str | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response = JSONResponse(
        status_code=status_code,
        content=_error_payload(request, status_code, detail, code=code, message=message),
        headers=headers,
    )
    response.headers["X-Request-ID"] = _request_id(request)
    return response


async def read_json_payload(request: Request, *, max_bytes: int = MAX_JSON_BODY_BYTES) -> dict:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="请求体过大。")
        except ValueError:
            raise HTTPException(status_code=400, detail="Content-Length 无效。")

    body = await request.body()
    if len(body) > max_bytes:
        raise HTTPException(status_code=413, detail="请求体过大。")
    if not body:
        return {}

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="请求体不是有效 JSON。") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="请求体必须是 JSON 对象。")
    return payload


def _text_field(payload: dict, key: str, *, required: bool = False, max_chars: int = 4000) -> str:
    value = payload.get(key, "")
    if value is None:
        value = ""
    text = str(value).strip()
    if required and not text:
        raise HTTPException(status_code=400, detail=f"{key} 不能为空。")
    if len(text) > max_chars:
        raise HTTPException(status_code=400, detail=f"{key} 不能超过 {max_chars} 个字符。")
    return text


def _int_field(payload: dict, key: str, default: int, *, min_value: int = 1, max_value: int = MAX_TOP_K) -> int:
    raw = payload.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"{key} 必须是整数。") from exc
    if value < min_value or value > max_value:
        raise HTTPException(status_code=400, detail=f"{key} 必须在 {min_value} 到 {max_value} 之间。")
    return value


def _bool_field(payload: dict, key: str, default: bool = False) -> bool:
    raw = payload.get(key, default)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return default
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        value = raw.strip().lower()
        if value in ("1", "true", "yes", "on"):
            return True
        if value in ("0", "false", "no", "off"):
            return False
    raise HTTPException(status_code=400, detail=f"{key} 必须是布尔值。")


def _ask_payload(payload: dict) -> dict:
    return {
        "question": _text_field(payload, "question", required=True),
        "top_k": _int_field(payload, "top_k", 5),
        "session_id": _text_field(payload, "session_id") or None,
        "strict_grounded": _bool_field(payload, "strict_grounded", True),
        "use_rerank": _bool_field(payload, "use_rerank", True),
        "self_correct": _bool_field(payload, "self_correct", True),
    }


app = FastAPI(title="Research Agent")


class NoCacheStaticFiles(StaticFiles):
    def file_response(self, full_path, stat_result, scope, status_code: int = 200) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        path = str(scope.get("path") or "")
        if path.startswith("/static/") and path.endswith((".js", ".css", ".html")):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(
    CORSMiddleware,
    allow_origins=default_cors_origins(),
    allow_credentials=cors_allow_credentials(),
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return _json_error_response(
        request,
        exc.status_code,
        exc.detail,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _json_error_response(
        request,
        422,
        exc.errors(),
        code="validation_error",
        message="请求参数校验失败。",
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("unhandled request failed")
    detail = str(exc) if os.getenv("DAIDAINIAO_DEBUG", "").strip().lower() in ("1", "true", "yes") else "internal server error"
    return _json_error_response(request, 500, detail)


# In-memory rate limit (per process; not shared across workers)
_rate_limits: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


@app.middleware("http")
async def api_token_middleware(request: Request, call_next):
    _request_id(request)
    if api_token_required() and request.method != "OPTIONS":
        auth = request.headers.get("authorization")
        if not verify_api_token(auth):
            return _json_error_response(request, 401, "unauthorized")
    response = await call_next(request)
    response.headers["X-Request-ID"] = _request_id(request)
    return response


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if not rate_limit_exempt(request.url.path):
        now = time.time()
        ip = request.client.host if request.client else "unknown"
        with _rate_lock:
            timestamps = _rate_limits.get(ip, [])
            timestamps[:] = [t for t in timestamps if now - t <= 60.0]
            if len(timestamps) >= 30:
                return _json_error_response(
                    request,
                    429,
                    "Too many requests. Please slow down.",
                    code="rate_limit_exceeded",
                    message="Too many requests. Please slow down.",
                )
            timestamps.append(now)
            _rate_limits[ip] = timestamps
    response = await call_next(request)
    return response


# ----- GET endpoints -----

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/sessions")
def list_sessions():
    return {"items": [item.model_dump() for item in get_app().list_sessions()]}


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    try:
        return get_app().get_session(session_id).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/documents")
def list_documents():
    return {"items": get_app().agent.list_imported_documents()}


@app.get("/knowledge-documents")
def list_knowledge_documents(include_base: bool = True):
    return {"items": get_app().agent.list_knowledge_documents(include_base=include_base)}


@app.get("/documents/{paper_id}/brief")
def get_document_brief(paper_id: str):
    try:
        return get_app().agent.build_reading_brief(paper_id)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/documents/{paper_id}")
def get_document_detail(paper_id: str, passage_limit: int = 12):
    try:
        return get_app().agent.get_document_detail(paper_id, passage_limit=passage_limit)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.get("/status")
def get_status():
    return get_app().agent.get_system_status()


@app.get("/settings/model")
def get_model_settings():
    agent = get_app().agent
    llm = agent.llm
    store = load_profile_store(MODEL_PROFILES_PATH)
    active_id = resolve_active_profile_id(store, llm)
    active = find_profile(store, active_id) if active_id else None
    base_url = getattr(llm, "base_url", "") or ""
    provider = (active or {}).get("provider") or ("dashscope" if "dashscope" in base_url.lower() else "openai_compatible")
    return {
        "api_key": ("*" * 8) if getattr(llm, "api_key", "") else "",
        "base_url": base_url,
        "model": getattr(llm, "model", "") or "",
        "provider": provider,
        "embedding_model": getattr(llm, "embedding_model", ""),
        "rerank_model": getattr(llm, "rerank_model", ""),
        "chat_enabled": getattr(llm, "enabled", True),
        "embedding_enabled": getattr(llm, "embedding_enabled", False),
        "rerank_enabled": getattr(llm, "rerank_enabled", False),
        "active_profile_id": active_id,
        "profiles": [public_profile(item) for item in store.get("profiles") or []],
        "profile": public_profile(active) if active else None,
    }


@app.get("/")
def serve_index():
    return FileResponse(INDEX_FILE)


# ----- POST endpoints -----

@app.post("/ask")
async def ask(request: Request):
    payload = _ask_payload(await read_json_payload(request))
    result = get_app().ask(
        payload["question"],
        top_k=payload["top_k"],
        session_id=payload.get("session_id"),
        strict_grounded=payload["strict_grounded"],
        use_rerank=payload["use_rerank"],
        self_correct=payload["self_correct"],
    ).model_dump()
    return result


@app.post("/ask-stream")
async def ask_stream(request: Request):
    payload = _ask_payload(await read_json_payload(request))
    request_id = _request_id(request)

    async def event_generator():
        app_instance = get_app()
        try:
            yield f"event: meta\ndata: {json.dumps({'request_id': request_id}, ensure_ascii=False)}\n\n"
            for event in app_instance.ask_stream(
                payload["question"],
                top_k=payload["top_k"],
                session_id=payload.get("session_id"),
                strict_grounded=payload["strict_grounded"],
                use_rerank=payload["use_rerank"],
                self_correct=payload["self_correct"],
            ):
                event_type = str(event.get("type", "message"))
                if event_type == "step":
                    event_data = {"step": event.get("step", "")}
                elif "data" in event:
                    event_data = event["data"]
                else:
                    event_data = {"delta": event.get("delta", "")}
                if not isinstance(event_data, dict):
                    event_data = {"value": event_data}
                yield f"event: {event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
        except Exception as exc:
            logger.exception("ask-stream failed")
            detail = str(exc) if os.getenv("DAIDAINIAO_DEBUG", "").strip().lower() in ("1", "true", "yes") else "internal server error"
            error_data = {
                "error": "internal_server_error",
                "message": detail,
                "request_id": request_id,
            }
            yield f"event: error\ndata: {json.dumps(error_data, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/sessions")
async def create_session(request: Request):
    payload = await read_json_payload(request)
    session = get_app().create_session(title=_text_field(payload, "title", max_chars=120) or "New Session")
    return {
        "session": session.model_dump(),
        "sessions": [item.model_dump() for item in get_app().list_sessions()],
    }


@app.post("/delete-session")
async def delete_session(request: Request):
    payload = await read_json_payload(request)
    try:
        deleted = get_app().delete_session(_text_field(payload, "session_id", required=True, max_chars=120))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "message": "会话已删除。",
        "session": deleted.model_dump(),
        "sessions": [item.model_dump() for item in get_app().list_sessions()],
    }


@app.post("/sessions/{session_id}/truncate")
async def truncate_session(session_id: str, request: Request):
    payload = await read_json_payload(request)
    message_index = _int_field(payload, "message_index", 0, min_value=0, max_value=10000)
    try:
        updated = get_app().truncate_session(session_id, message_index)
        return {
            "session": updated.model_dump(),
            "sessions": [item.model_dump() for item in get_app().list_sessions()],
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/import-document")
async def import_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="未选择文件")
    file_bytes = await file.read()
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="上传文件超过 50MB 限制。")
    if not file_bytes:
        raise HTTPException(status_code=400, detail="上传文件为空")
    safe_name = Path(file.filename).name
    saved_path = UPLOAD_DIR / f"{uuid4().hex[:10]}-{safe_name}"
    saved_path.write_bytes(file_bytes)
    try:
        return import_saved_document(saved_path, file.filename, get_app())
    except ValueError as exc:
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        if saved_path.exists():
            saved_path.unlink()
        raise HTTPException(status_code=500, detail=str(exc) or "导入失败") from exc


@app.post("/delete-document")
async def delete_document(request: Request):
    payload = await read_json_payload(request)
    try:
        deleted = get_app().agent.delete_document(_text_field(payload, "paper_id", required=True, max_chars=240))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "message": "文档已删除，知识库已刷新。",
        "document": deleted,
        "documents": get_app().agent.list_imported_documents(),
    }


@app.post("/search")
async def search(request: Request):
    payload = await read_json_payload(request)
    return get_app().agent.search_papers(
        _text_field(payload, "query", required=True),
        top_k=_int_field(payload, "top_k", 5),
    )


@app.post("/compare")
async def compare(request: Request):
    payload = await read_json_payload(request)
    return get_app().agent.compare_papers(
        paper_ids=payload.get("paper_ids"),
        query=payload.get("query"),
        focus=_text_field(payload, "focus", max_chars=600) or "methods, findings, and limitations",
    ).model_dump()


@app.post("/review")
async def review(request: Request):
    payload = await read_json_payload(request)
    return get_app().agent.generate_review(
        _text_field(payload, "topic", required=True),
        top_k=_int_field(payload, "top_k", 5),
    ).model_dump()


@app.post("/evaluate")
@app.get("/evaluate")
async def evaluate(request: Request):
    params = dict(request.query_params)
    if request.method == "POST":
        body = await read_json_payload(request)
        params.update(body)
    top_k = _int_field(params, "top_k", 5)
    use_ragas = str(params.get("ragas", "false")).lower() in ("true", "1", "yes")
    include_imported = str(params.get("include_imported", "false")).lower() in ("true", "1", "yes")

    eval_path: Path | None = None
    if EVAL_PATH:
        try:
            eval_path = _resolve_eval_path(EVAL_PATH)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    elif not default_eval_path().exists():
        raise HTTPException(status_code=404, detail="evaluation not configured")

    if include_imported:
        eval_agent = ResearchAssistant(corpus_path=CORPUS_PATH, include_imported=True)
    else:
        eval_agent = get_app().agent

    return run_evaluation(eval_agent, eval_path=eval_path, top_k=top_k, use_ragas=use_ragas)


@app.post("/rag-lab/evaluate")
async def rag_lab_evaluate(request: Request):
    payload = await read_json_payload(request)
    raw_eval_path = payload.get("eval_path") or (EVAL_PATH if EVAL_PATH else None)
    eval_path: Path | None = None
    if raw_eval_path:
        try:
            eval_path = _resolve_eval_path(str(raw_eval_path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    include_imported_value = payload.get("include_imported", True)
    include_imported = (
        include_imported_value
        if isinstance(include_imported_value, bool)
        else str(include_imported_value).strip().lower() not in ("false", "0", "no", "off")
    )
    eval_agent = get_app().agent if include_imported else ResearchAssistant(corpus_path=CORPUS_PATH, include_imported=False)
    return run_rag_lab_evaluation(
        eval_agent,
        eval_path=eval_path,
        cases=payload.get("cases"),
        configs=payload.get("configs"),
        default_top_k=_int_field(payload, "top_k", 5),
        default_candidate_k=payload.get("candidate_k"),
    )



@app.post("/export/markdown")
async def export_markdown(request: Request):
    payload = await read_json_payload(request)
    export_format = str(payload.get("format") or "markdown").strip().lower()
    data = payload.get("data")
    if data is None and payload.get("session_id"):
        try:
            session = get_app().get_session(str(payload["session_id"]))
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        messages = session.messages
        if len(messages) < 2:
            raise HTTPException(status_code=400, detail="会话中没有可导出的回答。")
        question = messages[-2].content
        answer = messages[-1].content
        data = {"question": question, "answer": answer, "evidence": [], "trace": []}
    if not isinstance(data, dict) or not data.get("answer"):
        raise HTTPException(status_code=400, detail="需要包含 answer 的 data 或有效 session_id。")

    if export_format == "obsidian":
        markdown = format_obsidian_markdown(data)
        suffix = "md"
    elif export_format == "bibtex":
        agent = get_app().agent
        papers: dict[str, dict] = {}
        for item in data.get("evidence") or []:
            pid = str(item.get("paper_id") or "").strip()
            if not pid or pid in papers:
                continue
            try:
                paper = agent.corpus.get_paper(pid)
                papers[pid] = {
                    "title": paper.title,
                    "authors": paper.authors,
                    "year": paper.year,
                    "venue": paper.venue,
                    "source_url": paper.source_url,
                }
            except Exception:
                papers[pid] = {"title": item.get("title") or pid}
        markdown = format_bibtex(data, papers)
        suffix = "bib"
    else:
        markdown = format_answer_markdown(data)
        suffix = "md"

    title = (data.get("question") or "answer")[:40].strip() or "answer"
    safe_title = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in title)
    return {
        "markdown": markdown,
        "filename": f"{safe_title}.{suffix}",
        "format": export_format,
    }


@app.post("/deep-review")
async def deep_review(request: Request):
    payload = await read_json_payload(request)
    topic = _text_field(payload, "topic", required=True)
    if not topic:
        raise HTTPException(status_code=400, detail="topic is required")
    return get_app().agent.generate_deep_review(topic, top_k=_int_field(payload, "top_k", 5))


@app.post("/settings/model")
async def update_model_settings(request: Request):
    payload = await read_json_payload(request)
    try:
        return apply_model_settings(get_app().agent, payload, MODEL_PROFILES_PATH, ENV_PATH)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/settings/models/list")
async def list_available_models(request: Request):
    payload = await read_json_payload(request)
    api_key = payload.get("api_key", "").strip()
    base_url = (payload.get("base_url", "") or "").strip()
    if not api_key or not base_url:
        raise HTTPException(status_code=400, detail="api_key and base_url are required")
    try:
        import httpx as _httpx
        from .llm import normalize_openai_base_url
        url = f"{normalize_openai_base_url(base_url)}/models"
        resp = _httpx.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        models = [item.get("id") for item in (data.get("data") or []) if item.get("id")]
        return {"models": models}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"获取模型列表失败：{exc}") from exc


# Static files (must be last)
app.mount("/static", NoCacheStaticFiles(directory=str(FRONTEND_DIR)), name="static")
