"""Pluggable strategies for retrieval, generation, audit, and decomposition.

Each strategy receives a PipelineContext and returns results that get
written back into the context. Concrete implementations wrap existing
classes (HybridRetriever, AnswerGenerator, QueryDecomposer) so the
behaviour is unchanged — only the wiring is different.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Retrieval strategy
# ---------------------------------------------------------------------------


@dataclass
class RetrievalConfig:
    """Tunable parameters for a retrieval run."""

    top_k: int = 5
    candidate_k: int = 20
    use_rerank: bool = True
    rerank_top_n: int | None = None

    def effective_candidate_k(self) -> int:
        return max(self.candidate_k, self.top_k * 4, 20)

    def effective_top_k(self) -> int:
        return max(self.top_k, 5)


class RetrievalStrategy(ABC):
    """Contract: given a query and a retriever, return evidence + diagnostics."""

    @abstractmethod
    def search(self, query: str, retriever: Any, config: RetrievalConfig) -> tuple[list[Any], dict]:
        """Returns (evidence_list, diagnostics_dict)."""


class HybridRetrieval(RetrievalStrategy):
    """Default strategy: hybrid fusion with optional rerank."""

    def search(self, query: str, retriever: Any, config: RetrievalConfig) -> tuple[list[Any], dict]:
        result = retriever.search(
            query,
            top_k=config.effective_top_k(),
            candidate_k=config.effective_candidate_k(),
            use_rerank=config.use_rerank,
        )
        return result.evidence, result.diagnostics


class FusionOnlyRetrieval(RetrievalStrategy):
    """Fusion without rerank (used by RAG Lab comparison)."""

    def search(self, query: str, retriever: Any, config: RetrievalConfig) -> tuple[list[Any], dict]:
        result = retriever.search(
            query,
            top_k=config.effective_top_k(),
            candidate_k=config.effective_candidate_k(),
            use_rerank=False,
        )
        return result.evidence, result.diagnostics


# ---------------------------------------------------------------------------
# Generation strategy
# ---------------------------------------------------------------------------


@dataclass
class GenerationConfig:
    """Parameters for answer generation."""

    temperature: float = 0.2
    max_papers: int = 3
    stream: bool = False

    def model_dump(self) -> dict:
        return {"temperature": self.temperature, "max_papers": self.max_papers, "stream": self.stream}


class GenerationStrategy(ABC):
    """Contract: given question + evidence, produce an answer string."""

    @abstractmethod
    def generate(
        self,
        question: str,
        evidence: list[Any],
        context: Any,    # PipelineContext
        answer_gen: Any, # AnswerGenerator instance
    ) -> tuple[str, list[Any]]:
        """Returns (answer_text, trace_entries)."""

    @abstractmethod
    def generate_stream(
        self,
        question: str,
        evidence: list[Any],
        context: Any,
        answer_gen: Any,
    ) -> Any:  # Iterator[str] or generator
        """Returns an iterator that yields text chunks."""


class LLMGeneration(GenerationStrategy):
    """Generate via LLM (DashScope Qwen)."""

    def __init__(self, config: GenerationConfig | None = None) -> None:
        self.config = config or GenerationConfig()

    def generate(
        self,
        question: str,
        evidence: list[Any],
        context: Any,
        answer_gen: Any,
    ) -> tuple[str, list[Any]]:
        trace: list[Any] = []
        result = answer_gen._llm_answer(
            question,
            evidence,
            trace,
            history=context.history,
        )
        return result.answer, trace

    def generate_stream(
        self,
        question: str,
        evidence: list[Any],
        context: Any,
        answer_gen: Any,
    ) -> Any:
        return answer_gen._llm_answer_stream(
            question,
            evidence,
            context.trace,
            history=context.history,
        )


class RuleBasedGeneration(GenerationStrategy):
    """Generate via rule-based logic (no LLM)."""

    def generate(
        self,
        question: str,
        evidence: list[Any],
        context: Any,
        answer_gen: Any,
    ) -> tuple[str, list[Any]]:
        trace: list[Any] = []
        result = answer_gen._rule_based_answer(
            question,
            evidence,
            trace,
            context.corpus.get_paper,
        )
        return result.answer, trace

    def generate_stream(
        self,
        question: str,
        evidence: list[Any],
        context: Any,
        answer_gen: Any,
    ) -> Any:
        # Rule-based generation doesn't support true streaming; yield whole answer as one chunk.
        answer, _ = self.generate(question, evidence, context, answer_gen)
        return iter([answer])


# ---------------------------------------------------------------------------
# Audit strategy
# ---------------------------------------------------------------------------


@dataclass
class AuditConfig:
    """Parameters for claim audit."""

    lexical_threshold: float = 0.18
    semantic_threshold: float = 0.18
    max_supporting_quotes: int = 3
    max_matched_terms: int = 12


class AuditStrategy(ABC):
    """Contract: given answer + evidence, produce claim audits."""

    @abstractmethod
    def audit(self, answer: str, evidence: list[Any], embedding_client: Any, answer_gen: Any) -> list[Any]:
        """Returns list of ClaimAudit."""


class FullAudit(AuditStrategy):
    """Lexical + semantic audit using AnswerGenerator.audit_claims()."""

    def audit(self, answer: str, evidence: list[Any], embedding_client: Any, answer_gen: Any) -> list[Any]:
        return answer_gen.audit_claims(answer, evidence, embedding_client=embedding_client)


class NoAudit(AuditStrategy):
    """Skip claim auditing (e.g. for system/meta/greeting answers)."""

    def audit(self, answer: str, evidence: list[Any], embedding_client: Any, answer_gen: Any) -> list[Any]:
        return []


# ---------------------------------------------------------------------------
# Decomposition strategy
# ---------------------------------------------------------------------------


class DecompositionStrategy(ABC):
    """Contract: decide whether and how to split a question into sub-questions."""

    @abstractmethod
    def should_decompose(self, question: str) -> bool: ...

    @abstractmethod
    def decompose(self, question: str, llm_client: Any, trace: list[Any]) -> list[str]: ...

    @abstractmethod
    def synthesize(self, question: str, sub_results: list[dict], llm_client: Any, trace: list[Any]) -> str: ...


class MultiHopDecomposer(DecompositionStrategy):
    """Delegates to existing QueryDecomposer."""

    def should_decompose(self, question: str) -> bool:
        from .decompose import QueryDecomposer  # fmt: skip
        return QueryDecomposer.should_decompose(question)

    def decompose(self, question: str, llm_client: Any, trace: list[Any]) -> list[str]:
        from .decompose import QueryDecomposer  # fmt: skip
        return QueryDecomposer.decompose(question, llm_client, trace)

    def synthesize(self, question: str, sub_results: list[dict], llm_client: Any, trace: list[Any]) -> str:
        from .decompose import QueryDecomposer  # fmt: skip
        return QueryDecomposer.synthesize(question, sub_results, llm_client, trace)


class NoDecompose(DecompositionStrategy):
    """Never decompose. Used when LLM is unavailable."""

    def should_decompose(self, question: str) -> bool:
        return False

    def decompose(self, question: str, llm_client: Any, trace: list[Any]) -> list[str]:
        return [question]

    def synthesize(self, question: str, sub_results: list[dict], llm_client: Any, trace: list[Any]) -> str:
        return sub_results[0].get("answer", "") if sub_results else ""
