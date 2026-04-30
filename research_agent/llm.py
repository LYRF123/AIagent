from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib import error, request
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


def _is_enabled_setting(value: str | None) -> bool:
    return (value or "").strip().lower() not in _DISABLED_VALUES


def _validate_rerank_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host not in _ALLOWED_RERANK_HOSTS:
        raise ValueError(f"Rerank URL host '{host}' is not in the allowed list: {_ALLOWED_RERANK_HOSTS}")


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
        self.base_url = (resolve_setting("DASHSCOPE_BASE_URL", explicit=base_url, default=DEFAULT_DASHSCOPE_BASE_URL) or DEFAULT_DASHSCOPE_BASE_URL).rstrip("/")
        self.model = resolve_setting("DASHSCOPE_MODEL", explicit=model, default=DEFAULT_DASHSCOPE_MODEL) or DEFAULT_DASHSCOPE_MODEL
        self.embedding_model = resolve_setting("DASHSCOPE_EMBEDDING_MODEL", explicit=embedding_model, default=DEFAULT_DASHSCOPE_EMBEDDING_MODEL) or DEFAULT_DASHSCOPE_EMBEDDING_MODEL
        self.rerank_model = resolve_setting("DASHSCOPE_RERANK_MODEL", explicit=rerank_model, default=DEFAULT_DASHSCOPE_RERANK_MODEL) or DEFAULT_DASHSCOPE_RERANK_MODEL
        self.rerank_url = resolve_setting("DASHSCOPE_RERANK_URL", explicit=rerank_url, default=DEFAULT_DASHSCOPE_RERANK_URL) or DEFAULT_DASHSCOPE_RERANK_URL
        self.timeout = timeout
        self._chat_models: dict[float, ChatOpenAI] = {}
        self._embedding_model: DashScopeEmbeddings | None = None

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
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        req = request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 ResearchAgent/1.0",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"Chat completion HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Chat completion connection failed: {exc.reason}") from exc
        choices = data.get("choices") or []
        message = (choices[0] or {}).get("message") if choices else {}
        text = self._normalize_content((message or {}).get("content", "")).strip()
        return LLMResponse(text=text, model=self.model, provider="dashscope")

    def stream_complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> Iterator[str]:
        """True SSE streaming via DashScope OpenAI-compatible API."""
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
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
                    yield delta.content
                # Check for finish_reason stop sentinel
                if chunk.choices[0].finish_reason is not None:
                    break
        except Exception as exc:
            raise RuntimeError(f"Stream completion failed: {exc}") from exc

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[RerankItem]:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        if not self.rerank_enabled:
            raise RuntimeError("DashScope rerank is disabled")
        _validate_rerank_url(self.rerank_url)
        if not documents:
            return []
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
        req = request.Request(
            self.rerank_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"DashScope rerank HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"DashScope rerank connection failed: {exc.reason}") from exc

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
        return reranked


def build_context_block(evidence: list[dict[str, Any]]) -> str:
    lines = []
    for index, item in enumerate(evidence, start=1):
        lines.append(
            f"[{index}] paper_id={item['paper_id']} title={item['title']} section={item['section']} score={item['score']}\n{item['text']}"
        )
    return "\n\n".join(lines)

