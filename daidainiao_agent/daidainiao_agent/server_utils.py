from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .app_service import ResearchApp


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
