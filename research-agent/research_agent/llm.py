from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI
from openai import OpenAI


DEFAULT_DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_DASHSCOPE_RERANK_URL = "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
DEFAULT_DASHSCOPE_MODEL = "qwen-plus"
DEFAULT_DASHSCOPE_EMBEDDING_MODEL = "text-embedding-v4"
DEFAULT_DASHSCOPE_RERANK_MODEL = "gte-rerank-v2"


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
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.base_url = (base_url or os.getenv("DASHSCOPE_BASE_URL") or DEFAULT_DASHSCOPE_BASE_URL).rstrip("/")
        self.model = model or os.getenv("DASHSCOPE_MODEL") or DEFAULT_DASHSCOPE_MODEL
        self.embedding_model = embedding_model or os.getenv("DASHSCOPE_EMBEDDING_MODEL") or DEFAULT_DASHSCOPE_EMBEDDING_MODEL
        self.rerank_model = rerank_model or os.getenv("DASHSCOPE_RERANK_MODEL") or DEFAULT_DASHSCOPE_RERANK_MODEL
        self.rerank_url = rerank_url or os.getenv("DASHSCOPE_RERANK_URL") or DEFAULT_DASHSCOPE_RERANK_URL
        self.timeout = timeout
        self._chat_model: ChatOpenAI | None = None
        self._embedding_model: DashScopeEmbeddings | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def chat_model(self, temperature: float = 0.2) -> ChatOpenAI:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        if self._chat_model is None:
            self._chat_model = ChatOpenAI(
                model_name=self.model,
                openai_api_key=self.api_key,
                openai_api_base=self.base_url,
                temperature=temperature,
                max_retries=2,
                request_timeout=self.timeout,
            )
        return self._chat_model

    def embedding_client(self) -> DashScopeEmbeddings:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
        if self._embedding_model is None:
            self._embedding_model = DashScopeEmbeddings(
                api_key=self.api_key,
                base_url=self.base_url,
                model=self.embedding_model,
            )
        return self._embedding_model

    def complete(self, system_prompt: str, user_prompt: str, temperature: float = 0.2) -> LLMResponse:
        model = self.chat_model(temperature=temperature)
        response = model.invoke(
            [
                ("system", system_prompt),
                ("human", user_prompt),
            ]
        )
        text = getattr(response, "content", "")
        if isinstance(text, list):
            text = "\n".join(str(item) for item in text)
        return LLMResponse(text=str(text).strip(), model=self.model, provider="dashscope")

    def rerank(self, query: str, documents: list[str], top_n: int | None = None) -> list[RerankItem]:
        if not self.api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")
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
