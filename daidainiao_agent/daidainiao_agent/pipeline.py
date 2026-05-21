"""Composable RAG pipeline: each step is an independent unit that reads/writes a shared PipelineContext.

Usage::

    pipeline = Pipeline([
        RetrieveStep(strategy=retrieval_strategy),
        DecomposeStep(strategy=decomp_strategy),
        GenerateStep(strategy=gen_strategy),
        AuditStep(strategy=audit_strategy),
    ])
    ctx = PipelineContext(question="...", top_k=5, history=[])
    result = pipeline.run(ctx)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Pipeline context — shared state passed between steps
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    """Mutable bag of state for the pipeline. Each step reads what it needs and writes its output."""

    question: str
    top_k: int = 5
    history: list[dict[str, str]] = field(default_factory=list)
    strict_grounded: bool = True
    self_correct: bool = False
    include_imported: bool = True
    use_rerank: bool = True
    session_id: str = ""
    session_title: str = ""

    # ---- state accumulated by steps ----
    retrieval_query: str = ""
    evidence: list[Any] = field(default_factory=list)
    trace: list[Any] = field(default_factory=list)
    answer: str = ""
    answer_chunks: list[str] = field(default_factory=list)
    claim_audit: list[Any] = field(default_factory=list)
    contradictions: list[dict] = field(default_factory=list)
    sub_results: list[dict] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)
    retrieval_confidence: float = 0.0
    insufficient_evidence: bool = False
    question_type: str = "research"

    # ---- external dependencies injected before pipeline runs ----
    retriever: Any = None          # HybridRetriever
    llm_client: Any = None         # DashScopeLangChainClient
    embedding_client: Any = None   # DashScopeEmbeddings or None
    corpus: Any = None             # PaperCorpus (for get_paper lookups)
    generation_strategy: Any = None
    audit_strategy: Any = None
    decomposition_strategy: Any = None

    # ---- extra data for strategy configs ----
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Step result
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    """Output metadata from one pipeline step."""

    step: str
    ok: bool = True
    error: str | None = None
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "ok": self.ok,
            "error": self.error,
            "metrics": self.metrics,
        }


# ---------------------------------------------------------------------------
# Pipeline step
# ---------------------------------------------------------------------------


class PipelineStep(ABC):
    """One unit of work in the RAG pipeline."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def execute(self, ctx: PipelineContext) -> StepResult:
        """Read from ctx, do work, write results to ctx, return StepResult."""


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------


class Pipeline:
    """Runs a sequence of PipelineSteps in order, carrying a shared PipelineContext."""

    def __init__(self, steps: list[PipelineStep]) -> None:
        self.steps = steps
        self._steps_by_name: dict[str, PipelineStep] = {step.name: step for step in steps}

    def run(self, ctx: PipelineContext) -> PipelineResult:
        """Execute all steps. Stops early if any step fails critically."""
        step_results: list[StepResult] = []
        for step in self.steps:
            result = step.execute(ctx)
            step_results.append(result)
            if not result.ok:
                break
        return PipelineResult(step_results=step_results, context=ctx)

    def get_step(self, name: str) -> PipelineStep | None:
        return self._steps_by_name.get(name)


@dataclass
class PipelineResult:
    """Complete result of a pipeline run."""

    step_results: list[StepResult]
    context: PipelineContext

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.step_results)

    @property
    def answer(self) -> str:
        return self.context.answer

    @property
    def evidence(self) -> list:
        return self.context.evidence

    @property
    def trace(self) -> list:
        return self.context.trace

    def to_dict(self) -> dict:
        return {
            "steps": [r.to_dict() for r in self.step_results],
            "ok": self.ok,
        }
