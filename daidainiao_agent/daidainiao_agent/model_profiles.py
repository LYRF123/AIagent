from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .llm import load_dotenv_map


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mask_api_key(api_key: str) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}…{api_key[-4:]}"


def _default_store() -> dict[str, Any]:
    return {"active_profile_id": "", "profiles": []}


def load_profile_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _default_store()
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return _default_store()
    if isinstance(raw, list):
        profiles = [item for item in raw if isinstance(item, dict)]
        return {"active_profile_id": "", "profiles": profiles}
    if isinstance(raw, dict):
        profiles = raw.get("profiles") if isinstance(raw.get("profiles"), list) else []
        return {
            "active_profile_id": str(raw.get("active_profile_id") or ""),
            "profiles": [item for item in profiles if isinstance(item, dict)],
        }
    return _default_store()


def save_profile_store(path: Path, store: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_profile_id": store.get("active_profile_id") or "",
        "profiles": store.get("profiles") or [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def public_profile(profile: dict[str, Any]) -> dict[str, Any]:
    api_key = str(profile.get("api_key") or "")
    return {
        "id": profile.get("id", ""),
        "name": profile.get("name", ""),
        "provider": profile.get("provider", ""),
        "base_url": profile.get("base_url", ""),
        "model": profile.get("model", ""),
        "api_key_masked": _mask_api_key(api_key),
        "updated_at": profile.get("updated_at", ""),
    }


def write_env_file(env_path: Path, api_key: str, base_url: str, model: str) -> None:
    lines: list[str] = []
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            key = raw_line.split("=", 1)[0].strip() if "=" in raw_line else ""
            if key in {"DASHSCOPE_API_KEY", "DASHSCOPE_BASE_URL", "DASHSCOPE_MODEL"}:
                continue
            lines.append(raw_line)
    lines.extend(
        [
            f"DASHSCOPE_API_KEY={api_key}",
            f"DASHSCOPE_BASE_URL={base_url}",
            f"DASHSCOPE_MODEL={model}",
        ]
    )
    env_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    from . import llm as _llm

    _llm._ENV_CACHE = None


def resolve_provider(base_url: str) -> str:
    return "dashscope" if "dashscope" in (base_url or "").lower() else "openai_compatible"


def find_profile(store: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    for item in store.get("profiles") or []:
        if item.get("id") == profile_id:
            return item
    return None


def resolve_active_profile_id(store: dict[str, Any], llm: Any | None = None) -> str:
    active_id = str(store.get("active_profile_id") or "")
    active = find_profile(store, active_id) if active_id else None
    if llm is not None and active:
        base_url = getattr(llm, "base_url", "") or ""
        model = getattr(llm, "model", "") or ""
        if active.get("model") == model and (active.get("base_url") or "") == base_url:
            return active_id
    base_url = getattr(llm, "base_url", "") or "" if llm is not None else ""
    model = getattr(llm, "model", "") or "" if llm is not None else ""
    for item in store.get("profiles") or []:
        if item.get("model") == model and (item.get("base_url") or "") == base_url:
            return str(item.get("id") or "")
    profiles = list(store.get("profiles") or [])
    if not profiles:
        return ""
    profiles.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return str(profiles[0].get("id") or "")


def upsert_profile(
    store: dict[str, Any],
    *,
    profile_id: str | None,
    name: str,
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
) -> dict[str, Any]:
    profiles: list[dict[str, Any]] = list(store.get("profiles") or [])
    existing = next((item for item in profiles if item.get("id") == profile_id), None) if profile_id else None
    if existing is None:
        existing = {
            "id": uuid4().hex[:12],
            "name": name or f"{model} · {provider}",
            "provider": provider,
            "api_key": api_key,
            "base_url": base_url,
            "model": model,
            "updated_at": _now_iso(),
        }
        profiles.insert(0, existing)
    else:
        if name:
            existing["name"] = name
        existing["provider"] = provider
        if api_key:
            existing["api_key"] = api_key
        existing["base_url"] = base_url
        existing["model"] = model
        existing["updated_at"] = _now_iso()
        profiles = [existing] + [item for item in profiles if item.get("id") != existing["id"]]
    store["profiles"] = profiles
    store["active_profile_id"] = existing["id"]
    return existing


def build_model_settings_payload(agent, store: dict[str, Any], profile: dict[str, Any] | None, llm_result: dict[str, Any]) -> dict[str, Any]:
    llm = agent.llm
    active_id = resolve_active_profile_id(store, llm)
    if active_id:
        store["active_profile_id"] = active_id
    active = profile or find_profile(store, active_id)
    provider = (active or {}).get("provider") or llm_result.get("provider") or resolve_provider(getattr(llm, "base_url", "") or "")
    base_url = (active or {}).get("base_url") or getattr(llm, "base_url", "") or ""
    model = (active or {}).get("model") or getattr(llm, "model", "") or ""
    api_key = getattr(llm, "api_key", "") or ""
    return {
        "message": "模型设置已更新。",
        "provider": provider,
        "base_url": base_url,
        "model": model,
        "api_key": ("*" * 8) if api_key else "",
        "embedding_model": getattr(llm, "embedding_model", ""),
        "rerank_model": getattr(llm, "rerank_model", ""),
        "chat_enabled": llm_result.get("chat_enabled", getattr(llm, "enabled", True)),
        "embedding_enabled": llm_result.get("embedding_enabled", getattr(llm, "embedding_enabled", False)),
        "rerank_enabled": llm_result.get("rerank_enabled", getattr(llm, "rerank_enabled", False)),
        "active_profile_id": active_id,
        "profiles": [public_profile(item) for item in store.get("profiles") or []],
        "profile": public_profile(active) if active else None,
    }


def apply_model_settings(agent, payload: dict[str, Any], profiles_path: Path, env_path: Path) -> dict[str, Any]:
    store = load_profile_store(profiles_path)
    profile_id = str(payload.get("profile_id") or "").strip()
    name = str(payload.get("name") or "").strip()
    provider = str(payload.get("provider") or "").strip()
    base_url = str(payload.get("base_url") or "").strip()
    model = str(payload.get("model") or "").strip()

    api_key = str(payload.get("api_key") or "").strip()
    current_key = agent.llm.api_key or load_dotenv_map().get("DASHSCOPE_API_KEY", "")
    if not api_key or all(char == "*" for char in api_key):
        api_key = current_key

    if profile_id and not (provider or base_url or model or name):
        profile = find_profile(store, profile_id)
        if profile is None:
            raise ValueError("未找到要切换的配置。")
        store["active_profile_id"] = profile_id
        api_key = profile.get("api_key") or api_key
        base_url = profile.get("base_url") or base_url
        model = profile.get("model") or model
        provider = profile.get("provider") or resolve_provider(base_url)
    elif profile_id:
        profile = find_profile(store, profile_id)
        if profile is None:
            raise ValueError("未找到要更新的配置。")
        provider = provider or profile.get("provider") or resolve_provider(base_url)
        api_key = api_key or profile.get("api_key") or ""
        base_url = base_url or profile.get("base_url") or ""
        model = model or profile.get("model") or ""
        profile = upsert_profile(
            store,
            profile_id=profile_id,
            name=name or profile.get("name") or f"{model} · {provider}",
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )
    else:
        if not api_key:
            raise ValueError("api_key is required")
        provider = provider or resolve_provider(base_url)
        profile = upsert_profile(
            store,
            profile_id=None,
            name=name or f"{model} · {provider}",
            provider=provider,
            api_key=api_key,
            base_url=base_url,
            model=model,
        )

    if not api_key:
        raise ValueError("api_key is required")

    write_env_file(env_path, api_key, base_url, model)
    llm_result = agent.reconfigure_llm(api_key=api_key, base_url=base_url, model=model)
    save_profile_store(profiles_path, store)
    return build_model_settings_payload(agent, store, profile, llm_result)
