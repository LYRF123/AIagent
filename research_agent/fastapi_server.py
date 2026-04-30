from __future__ import annotations

import json
import os
import threading
import time
from http import HTTPStatus
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from .app_service import ResearchApp
from .agent import ResearchAssistant
from .evaluation import default_eval_path, run_evaluation
from .rag_lab import run_rag_lab_evaluation
from .server import import_saved_document

CORPUS_PATH = os.getenv("RESEARCH_AGENT_CORPUS")
EVAL_PATH = os.getenv("RESEARCH_AGENT_EVAL_PATH")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend"
INDEX_FILE = FRONTEND_DIR / "index.html"
UPLOAD_DIR = PROJECT_ROOT / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

_app_instance = None


def get_app() -> ResearchApp:
    global _app_instance
    if _app_instance is None:
        _app_instance = ResearchApp(agent=ResearchAssistant(corpus_path=CORPUS_PATH))
    return _app_instance


app = FastAPI(title="Research Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting middleware
_rate_limits: dict[str, list[float]] = {}
_rate_lock = threading.Lock()


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    now = time.time()
    ip = request.client.host if request.client else "unknown"
    with _rate_lock:
        timestamps = _rate_limits.get(ip, [])
        timestamps[:] = [t for t in timestamps if now - t <= 60.0]
        if len(timestamps) >= 30:
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limit_exceeded", "message": "Too many requests. Please slow down."},
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
    except KeyError:
        raise HTTPException(status_code=404, detail="not found")


@app.get("/documents")
def list_documents():
    return {"items": get_app().agent.list_imported_documents()}


@app.get("/")
def serve_index():
    return FileResponse(INDEX_FILE)


# ----- POST endpoints -----

@app.post("/ask")
async def ask(request: Request):
    payload = await request.json()
    result = get_app().ask(
        payload["question"],
        top_k=int(payload.get("top_k", 5)),
        session_id=payload.get("session_id"),
        strict_grounded=bool(payload.get("strict_grounded", True)),
    ).model_dump()
    return result


@app.post("/ask-stream")
async def ask_stream(request: Request):
    payload = await request.json()

    async def event_generator():
        app_instance = get_app()
        try:
            for event in app_instance.ask_stream(
                payload["question"],
                top_k=int(payload.get("top_k", 5)),
                session_id=payload.get("session_id"),
                strict_grounded=bool(payload.get("strict_grounded", True)),
            ):
                event_type = str(event.get("type", "message"))
                event_data = event.get("data") if "data" in event else {"delta": event.get("delta", "")}
                if not isinstance(event_data, dict):
                    event_data = {"value": event_data}
                yield f"event: {event_type}\ndata: {json.dumps(event_data, ensure_ascii=False)}\n\n"
        except Exception:
            yield f"event: error\ndata: {json.dumps({'error': 'internal server error'})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/sessions")
async def create_session(request: Request):
    payload = await request.json()
    session = get_app().create_session(title=payload.get("title") or "New Session")
    return {
        "session": session.model_dump(),
        "sessions": [item.model_dump() for item in get_app().list_sessions()],
    }


@app.post("/delete-session")
async def delete_session(request: Request):
    payload = await request.json()
    deleted = get_app().delete_session(payload["session_id"])
    return {
        "message": "会话已删除。",
        "session": deleted.model_dump(),
        "sessions": [item.model_dump() for item in get_app().list_sessions()],
    }


@app.post("/import-document")
async def import_document(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file")
    safe_name = Path(file.filename).name
    saved_path = UPLOAD_DIR / f"{uuid4().hex[:10]}-{safe_name}"
    saved_path.write_bytes(file_bytes)
    result = import_saved_document(saved_path, file.filename)
    return result


@app.post("/delete-document")
async def delete_document(request: Request):
    payload = await request.json()
    deleted = get_app().agent.delete_document(payload["paper_id"])
    return {
        "message": "文档已删除，知识库已刷新。",
        "document": deleted,
        "documents": get_app().agent.list_imported_documents(),
    }


@app.post("/search")
async def search(request: Request):
    payload = await request.json()
    return get_app().agent.search_papers(payload["query"], top_k=int(payload.get("top_k", 5)))


@app.post("/compare")
async def compare(request: Request):
    payload = await request.json()
    return get_app().agent.compare_papers(
        paper_ids=payload.get("paper_ids"),
        query=payload.get("query"),
        focus=payload.get("focus", "methods, findings, and limitations"),
    ).model_dump()


@app.post("/review")
async def review(request: Request):
    payload = await request.json()
    return get_app().agent.generate_review(payload["topic"], top_k=int(payload.get("top_k", 5))).model_dump()


@app.post("/evaluate")
@app.get("/evaluate")
async def evaluate(request: Request):
    params = dict(request.query_params)
    if request.method == "POST":
        body = await request.json()
        params.update(body)
    top_k = int(params.get("top_k", 5))
    use_ragas = str(params.get("ragas", "false")).lower() in ("true", "1", "yes")
    include_imported = str(params.get("include_imported", "false")).lower() in ("true", "1", "yes")

    eval_path = EVAL_PATH if EVAL_PATH else None
    if eval_path is not None:
        if not Path(eval_path).exists():
            raise HTTPException(status_code=404, detail="evaluation not configured")
    else:
        if not default_eval_path().exists():
            raise HTTPException(status_code=404, detail="evaluation not configured")

    if include_imported:
        eval_agent = ResearchAssistant(corpus_path=CORPUS_PATH, include_imported=True)
    else:
        eval_agent = get_app().agent

    return run_evaluation(eval_agent, eval_path=eval_path, top_k=top_k, use_ragas=use_ragas)


@app.post("/rag-lab/evaluate")
async def rag_lab_evaluate(request: Request):
    payload = await request.json()
    eval_path = payload.get("eval_path") or (EVAL_PATH if EVAL_PATH else None)
    if eval_path is not None and not Path(eval_path).exists():
        raise HTTPException(status_code=404, detail="evaluation not configured")

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
        default_top_k=int(payload.get("top_k", 5)),
        default_candidate_k=payload.get("candidate_k"),
    )


# Static files (must be last)
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")
