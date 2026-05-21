from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app_service import ResearchApp

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
MAX_JSON_BODY_BYTES = 1 * 1024 * 1024

RATE_LIMIT_EXEMPT_PREFIXES = ("/static/",)
RATE_LIMIT_EXEMPT_PATHS = {"/"}


def default_cors_origins() -> list[str]:
    raw = os.getenv("DAIDAINIAO_CORS_ORIGINS", "").strip()
    if raw:
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    ]


def cors_allow_credentials() -> bool:
    return os.getenv("DAIDAINIAO_CORS_CREDENTIALS", "").strip().lower() in ("1", "true", "yes")


def rate_limit_exempt(path: str) -> bool:
    if path in RATE_LIMIT_EXEMPT_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in RATE_LIMIT_EXEMPT_PREFIXES)


def resolve_data_path(path_value: str | Path, *, must_exist: bool = False) -> Path:
    """Resolve eval/corpus paths under PROJECT_ROOT or data/."""
    raw = Path(path_value)
    candidate = raw if raw.is_absolute() else (PROJECT_ROOT / raw)
    resolved = candidate.resolve(strict=False)
    data_root = DATA_DIR.resolve(strict=False)
    project_root = PROJECT_ROOT.resolve(strict=False)
    if not (resolved == data_root or data_root in resolved.parents or resolved == project_root or project_root in resolved.parents):
        raise ValueError("路径必须在项目 data 目录或项目根目录下。")
    if must_exist and not resolved.exists():
        raise ValueError("文件不存在。")
    return resolved


def import_saved_document(saved_path: Path, original_name: str, app: "ResearchApp") -> dict:
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
