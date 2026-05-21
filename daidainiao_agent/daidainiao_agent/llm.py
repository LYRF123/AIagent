from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
import httpx
import re
from urllib.parse import urlparse

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from openai import OpenAI


DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
DEFAULT_DASHSCOPE_MODEL = "qwen-plus"
DEFAULT_DASHSCOPE_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_DASHSCOPE_RERANK_MODEL = "gte-rerank-v2"
_ENV_CACHE: dict[str, str] | None = None


def load_dotenv_map() -> dict[str, str]:
    global _ENV_CACHE
    if _ENV_CACHE is not None:
        return _ENV_CACHE

    project_root = Path(__file__).resolve().parent.parent
    env_path = project_root / ".env"
    values: dict[str, str] = {}
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                values[key] = value
    _ENV_CACHE = values
    return values


def resolve_setting(name: str, explicit: str | None = None, default: str | None = None) -> str | None:
    if explicit:
        return explicit
    if os.getenv(name):
        return os.getenv(name)
    env_file_values = load_dotenv_map()
    if env_file_values.get(name):
        return env_file_values[name]
    return default


@dataclass
class LLMResponse:
    text: str
    model: str
    provider: str


@dataclass
class RerankItem:
    index: int
    relevance_score: float
    document: str


_ALLOWED_RERANK_HOSTS = {"dashscope.aliyuncs.com"}
_DISABLED_VALUES = {"", "0", "false", "none", "off", "disabled"}


def format_embedding_error(exc: BaseException) -> str:
    """Human-readable hint when remote embedding fails during import/indexing."""
    name = type(exc).__name__
    text = str(exc).strip()
    if "PermissionDenied" in name or "blocked" in text.lower():
        return (
            "Embedding 接口被拒绝（中转站可能未开放 /v1/embeddings）。"
            "文档已写入知识库，但向量索引未更新；可在 .env 设置 DASHSCOPE_EMBEDDING_MODEL=disabled 后重启。"
        )
    if text:
        return f"向量索引更新失败：{text}"
    return "向量索引更新失败，请检查 Embedding 模型与 API 配置。"


def _is_enabled_setting(value: str | None) -> bool:
    return (value or "").strip().lower() not in _DISABLED_VALUES


def _validate_rerank_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in _ALLOWED_RERANK_HOSTS:
        raise ValueError(f"Rerank URL host '{host}' is not in the allowed list: {_ALLOWED_RERANK_HOSTS}")


def normalize_openai_base_url(base_url: str) -> str:
    """Strip trailing slashes and collapse accidental repeated ``/v1`` suffixes."""
    cleaned = (base_url or "").strip().rstrip("/")
    if not cleaned:
        return cleaned
    return re.sub(r"(?:/v1)+$", "/v1", cleaned)


def _summarize_http_error_body(detail: str) -> str:
    text = (detail or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if "<html" in lowered or "<!doctype" in lowered:
        if "bad gateway" in lowered or "error code 502" in lowered:
            return "Cloudflare 返回 502 Bad Gateway：源站（你的 VPS/中转后端）无响应或崩溃。"
        if "cloudflare" in lowered and "error code 503" in lowered:
            return "Cloudflare 返回 503：源站暂时不可用或过载。"
        if "cloudflare" in lowered:
            return "Cloudflare 拦截/代理错误页（非 JSON API 响应），请检查源站与反代。"
        return "上游返回 HTML 错误页（非 API JSON），请检查中转服务是否在线。"
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            err = payload.get("error")
            if isinstance(err, dict) and err.get("message"):
                return str(err["message"])
            if isinstance(err, str):
                return err
    except json.JSONDecodeError:
        pass
    if len(text) > 280:
        return text[:280] + "..."
    return text


def format_chat_http_error(status_code: int, detail: str, base_url: str) -> str:
    endpoint = f"{normalize_openai_base_url(base_url)}/chat/completions"
    detail_short = _summarize_http_error_body(detail)
    hints = {
        401: "API Key 无效或未授权，请检查设置中的 Key。",
        403: "当前 Key 无权访问该接口。",
        404: (
            f"接口不存在（{endpoint}）。请确认 Base URL 以 /v1 结尾，"
            "且未重复拼接 /v1 或 /chat/completions。"
        ),
        429: "请求过于频繁，请稍后重试。",
        502: (
            "网关无法连接源站（502）。Cloudflare 显示 Host 错误时，"
            "说明 vps.0515dddywz.top 后面的 One API / 反代进程未启动、崩溃或端口不通；"
            "请登录 VPS 检查服务状态后重试。"
        ),
        503: (
            "上游 Chat 服务暂时不可用（503）。Base URL 与 Key 通常正确，"
            "但 /chat/completions 当前无法处理请求；请在服务商面板检查配额/负载，"
            "或稍后重试、更换模型。"
        ),
    }
    message = f"Chat completion HTTP {status_code}"
    if hint := hints.get(status_code):
        message = f"{message}: {hint}"
    if detail_short:
        message = f"{message} 详情: {detail_short}"
    return message


class DashScopeEmbeddings(Embeddings):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        batch_size: int = 10,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.batch_size = batch_size
        self.client = OpenAI(api_key=api_key, base_url=base_url)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        clean_texts = [text if isinstance(text, str) and text else " " for text in texts]
        vectors: list[list[float]] = []
        for start in range(0, len(clean_texts), self.batch_size):
            batch = clean_texts[start : start + self.batch_size]
            response = self.client.embeddings.create(model=self.model, input=batch)
            vectors.extend([item.embedding for item in response.data])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        response = self.client.embeddings.create(model=self.model, input=[text or " "])
        return response.data[0].embedding


class DashScopeLangChainClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        rerank_model: str | None = None,
        rerank_url: str | None = None,
        timeout: int = 60,
    ) -> None:
        self.api_key = resolve_setting("DASHSCOPE_API_KEY", explicit=api_key)
        resolved_base = resolve_setting("DASHSCOPE_BASE_URL", explicit=base_url, default=DEFAULT_DASHSCOPE_BASE_URL) or DEFAULT_DASHSCOPE_BASE_URL
        self.base_url = normalize_openai_base_url(resolved_base)
        self.model = resolve_setting("DASHSCOPE_MODEL", explicit=model, default=DEFAULT_DASHSCOPE_MODEL) or DEFAULT_DASHSCOPE_MODEL
        self.embedding_model = resolve_setting("DASHSCOPE_EMBEDDING_MODEL", explicit=embedding_model, default=DEFAULT_DASHSCOPE_EMBEDDING_MODEL) or DEFAULT_DASHSCOPE_EMBEDDING_MODEL
        self.rerank_model = resolve_setting("DASHSCOPE_RERANK_MODEL", explicit=rerank_model, default=DEFAULT_DASHSCOPE_RERANK_MODEL) or DEFAULT_DASHSCOPE_RERANK_MODEL
        self.rerank_url = resolve_setting("DASHSCOPE_RERANK_URL", explicit=rerank_url, default=DEFAULT_DASHSCOPE_RERANK_URL) or DEFAULT_DASHSCOPE_RERANK_URL
        self.timeout = timeout
        self._chat_models: dict[float, ChatOpenAI] = {}
        self._embedding_model: DashScopeEmbeddings | None = None
        self.usage_tracker = UsageTracker()

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @property
    def embedding_enabled(self) -> bool:
        return bool(self.api_key) and _is_enabled_setting(self.embedding_model)

    @property
    def rerank_enabled(self) -> bool:
        return bool(self.api_key) and _is_enabled_setting(self.rerank_model)

    @property
    def _openai_client(self) -> OpenAI:
        """Lazy OpenAI-compatible client for streaming."""
        if not hasattr(self, '_openai_client_cache'):
            self._openai_client_cache = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._openai_client_cache

    @property
    def _http_client(self) -> httpx.Client:
        """Lazy httpx client for raw API calls."""
        if not hasattr(self, '_http_client_cache'):
            self._http_client_cache = httpx.Client(timeout=self.timeout)
        return self._http_client_cache

    def chat_model(self, temperature: float = 0.2) -> ChatOpenAI:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        if temperature not in self._chat_models:
            self._chat_models[temperature] = ChatOpenAI(
                model_name=self.model,
                openai_api_key=self.api_key,
                openai_api_base=self.base_url,
                temperature=temperature,
                max_retries=2,
                request_timeout=self.timeout,
            )
        return self._chat_models[temperature]

    def embedding_client(self) -> DashScopeEmbeddings:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        if not self.embedding_enabled:
            raise RuntimeError("DashScope embeddings are disabled")
        if self._embedding_model is None:
            self._embedding_model = DashScopeEmbeddings(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.embedding_model,
            )
        return self._embedding_model

    def _normalize_content(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(self._normalize_content(item) for item in value)
        if isinstance(value, dict):
            text = value.get("text")
            return str(text) if text else ""
        return str(value or "")

    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> LLMResponse:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        import time as _time
        _start = _time.perf_counter()
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        try:
            response = self._http_client.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 ResearchAgent/1.0",
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            self.usage_tracker.record("complete", self.model, (_time.perf_counter() - _start) * 1000, error=str(exc))
            detail = exc.response.text
            raise RuntimeError(
                format_chat_http_error(exc.response.status_code, detail, self.base_url)
            ) from exc
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            self.usage_tracker.record("complete", self.model, (_time.perf_counter() - _start) * 1000, error=str(exc))
            raise RuntimeError(f"Chat completion connection failed: {exc}") from exc
        choices = data.get("choices") or []
        message = (choices[0] or {}).get("message") if choices else {}
        text = self._normalize_content((message or {}).get("content", "")).strip()
        _elapsed = (_time.perf_counter() - _start) * 1000
        _est_tokens = len(user_prompt.split()) + len(text.split())
        self.usage_tracker.record("complete", self.model, _elapsed, _est_tokens)
        return LLMResponse(text=text, model=self.model, provider="dashscope")

    def stream_complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> Iterator[str]:
        """True SSE streaming via DashScope OpenAI-compatible API."""
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        import time as _time
        _start = _time.perf_counter()
        _chunks: list[str] = []
        try:
            response = self._openai_client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=temperature,
                stream=True,
            )
            for chunk in response:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    _chunks.append(delta.content)
                    yield delta.content
                # Check for finish_reason stop sentinel
                if chunk.choices[0].finish_reason is not None:
                    break
            _elapsed = (_time.perf_counter() - _start) * 1000
            _full_text = "".join(_chunks)
            _est_tokens = len(user_prompt.split()) + len(_full_text.split())
            self.usage_tracker.record("stream_complete", self.model, _elapsed, _est_tokens)
        except RuntimeError:
            raise
        except Exception as exc:
            self.usage_tracker.record("stream_complete", self.model, (_time.perf_counter() - _start) * 1000, error=str(exc))
            raise RuntimeError(f"Stream completion failed: {exc}") from exc

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[RerankItem]:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        if not self.rerank_enabled:
            raise RuntimeError("DashScope rerank is disabled")
        _validate_rerank_url(self.rerank_url)
        if not documents:
            return []
        import time as _time
        _start = _time.perf_counter()
        payload = {
            "model": self.rerank_model,
            "input": {
                "query": query,
                "documents": documents,
            },
            "parameters": {
                "return_documents": True,
                "top_n": top_n or len(documents),
            },
        }
        try:
            response = self._http_client.post(
                self.rerank_url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            self.usage_tracker.record("rerank", self.rerank_model, (_time.perf_counter() - _start) * 1000, error=str(exc))
            detail = exc.response.text
            raise RuntimeError(f"DashScope rerank HTTP {exc.response.status_code}: {detail}") from exc
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            self.usage_tracker.record("rerank", self.rerank_model, (_time.perf_counter() - _start) * 1000, error=str(exc))
            raise RuntimeError(f"DashScope rerank connection failed: {exc}") from exc

        results = (data.get("output") or {}).get("results") or []
        reranked: list[RerankItem] = []
        for item in results:
            document = item.get("document") or {}
            reranked.append(
                RerankItem(
                    index=int(item.get("index", 0)),
                    relevance_score=float(item.get("relevance_score", 0.0)),
                    document=str(document.get("text", "")),
                )
            )
        self.usage_tracker.record("rerank", self.rerank_model, (_time.perf_counter() - _start) * 1000, len(documents))
        return reranked


import threading
from collections import deque


class UsageRecord:
    __slots__ = ("timestamp", "method", "model", "latency_ms", "estimated_tokens", "error")

    def __init__(self, timestamp: float, method: str, model: str, latency_ms: float, estimated_tokens: int = 0, error: str = "") -> None:
        self.timestamp = timestamp
        self.method = method
        self.model = model
        self.latency_ms = latency_ms
        self.estimated_tokens = estimated_tokens
        self.error = error

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "method": self.method,
            "model": self.model,
            "latency_ms": round(self.latency_ms, 1),
            "estimated_tokens": self.estimated_tokens,
            "error": self.error,
        }


class UsageTracker:
    """Track API usage across all LLM client methods."""

    def __init__(self, max_records: int = 500) -> None:
        self._lock = threading.Lock()
        self.records: deque[UsageRecord] = deque(maxlen=max_records)
        self._total_calls = 0
        self._total_errors = 0
        self._total_tokens = 0
        self._total_latency_ms = 0.0

    def record(self, method: str, model: str, latency_ms: float, estimated_tokens: int = 0, error: str = "") -> None:
        import time
        rec = UsageRecord(
            timestamp=time.time(),
            method=method,
            model=model,
            latency_ms=latency_ms,
            estimated_tokens=estimated_tokens,
            error=error,
        )
        with self._lock:
            self.records.append(rec)
            self._total_calls += 1
            self._total_latency_ms += latency_ms
            self._total_tokens += estimated_tokens
            if error:
                self._total_errors += 1

    def summary(self) -> dict:
        with self._lock:
            return {
                "total_calls": self._total_calls,
                "total_errors": self._total_errors,
                "total_estimated_tokens": self._total_tokens,
                "total_latency_ms": round(self._total_latency_ms, 1),
                "avg_latency_ms": round(self._total_latency_ms / max(self._total_calls, 1), 1),
                "recent_records": [r.to_dict() for r in self.records],
            }


def build_context_block(evidence: list[dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(evidence, start=1):
        lines.append(
            f"[{index}] paper_id={item['paper_id']} title={item['title']} section={item['section']} score={item['score']}\n{item['text']}"
        )
    return "\n\n".join(lines)

