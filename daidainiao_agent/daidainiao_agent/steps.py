"""Concrete pipeline steps for the RAG workflow.

Each step wraps an existing code path from agent.py / answer_generator.py,
making it a self-contained, testable unit.
"""

from __future__ import annotations

from typing import Any

from .models import AnswerResult, ClaimAudit, ConversationMessage, Evidence, ToolTrace
from .pipeline import PipelineContext, PipelineStep, StepResult


# ---------------------------------------------------------------------------
# Step 1: Retrieve evidence
# ---------------------------------------------------------------------------


class RetrieveStep(PipelineStep):
    """Execute retrieval and write evidence + diagnostics to context."""

    name = "retrieve"

    def execute(self, ctx: PipelineContext) -> StepResult:
        retriever = ctx.retriever
        if retriever is None:
            return StepResult(step=self.name, ok=False, error="no retriever available")

        retrieval_strategy = ctx.extra.get("retrieval_strategy")
        config = ctx.extra.get("retrieval_config")
        search_result = None

        if retrieval_strategy is None or config is None:
            search_result = retriever.search(
                ctx.retrieval_query or ctx.question,
                top_k=max(ctx.top_k, 5),
                candidate_k=max(ctx.top_k * 4, 20),
                use_rerank=ctx.use_rerank,
            )
            evidence = search_result.evidence
            diagnostics = search_result.diagnostics
        else:
            evidence, diagnostics = retrieval_strategy.search(
                ctx.retrieval_query or ctx.question, retriever, config
            )

        if search_result is not None and getattr(search_result, "trace", None):
            for item in search_result.trace:
                if isinstance(item, dict):
                    ctx.trace.append(
                        ToolTrace(
                            tool=item.get("tool", "retrieval"),
                            input=item.get("input", ctx.retrieval_query or ctx.question),
                            output=item.get("output", ""),
                        )
                    )
        ctx.trace.extend(
            ToolTrace(tool="retrieval", input=ctx.retrieval_query or ctx.question,
                       output=f"returned {len(evidence)} evidence items")
        )
        ctx.evidence = evidence
        ctx.diagnostics = diagnostics
        return StepResult(
            step=self.name,
            ok=True,
            metrics={"evidence_count": len(evidence), "diagnostics_keys": list(diagnostics.keys())},
        )


# ---------------------------------------------------------------------------
# Step 2: Decompose (multi-hop)
# ---------------------------------------------------------------------------


class DecomposeStep(PipelineStep):
    """Check if the question should be split into sub-questions, and if so,
    retrieve and answer each sub-question independently, then synthesize."""

    name = "decompose"

    def execute(self, ctx: PipelineContext) -> StepResult:
        llm = ctx.llm_client
        if llm is None or not getattr(llm, "enabled", False):
            return StepResult(step=self.name, ok=True, metrics={"decomposed": False, "reason": "llm_disabled"})

        strategy = ctx.decomposition_strategy
        question = ctx.retrieval_query or ctx.question

        if not strategy.should_decompose(question):
            return StepResult(step=self.name, ok=True, metrics={"decomposed": False})

        sub_questions = strategy.decompose(question, llm, ctx.trace)
        if len(sub_questions) <= 1:
            return StepResult(step=self.name, ok=True, metrics={"decomposed": False, "sub_count": len(sub_questions)})

        retriever = ctx.retriever
        answer_gen = ctx.extra.get("answer_generator")
        sub_results: list[dict] = []
        all_evidence: list[Evidence] = []

        for sq in sub_questions:
            sq_evidence = self._retrieve_for_sub(sq, ctx, retriever)
            sq_ranked = answer_gen._rank_evidence_for_answer(sq_evidence, top_k=ctx.top_k, question=sq) if answer_gen else sq_evidence[:ctx.top_k]

            sq_answer = ""
            if sq_ranked:
                if llm.enabled:
                    try:
                        sq_result = answer_gen._llm_answer(sq, sq_ranked, list(ctx.trace), history=ctx.history)
                        sq_answer = sq_result.answer
                    except Exception:
                        sq_answer = sq_ranked[0].text if sq_ranked else ""
                else:
                    sq_answer = sq_ranked[0].text if sq_ranked else ""

            sub_results.append({
                "question": sq,
                "answer": sq_answer,
                "evidence_count": len(sq_ranked),
            })
            all_evidence.extend(sq_ranked)

        # Deduplicate
        seen: set[tuple] = set()
        unique: list[Evidence] = []
        for e in all_evidence:
            key = (e.paper_id, e.section, e.text)
            if key not in seen:
                seen.add(key)
                unique.append(e)

        synthesized = strategy.synthesize(question, sub_results, llm, ctx.trace)

        # Write results to context (pipeline will use these instead of the original answer)
        ctx.answer = synthesized
        ctx.evidence = unique[:ctx.top_k * 2]
        ctx.sub_results = sub_results
        ctx.question_type = "research"

        return StepResult(step=self.name, ok=True, metrics={
            "decomposed": True,
            "sub_count": len(sub_questions),
            "evidence_count": len(unique),
        })

    def _retrieve_for_sub(self, query: str, ctx: PipelineContext, retriever: Any) -> list[Evidence]:
        retrieval_strategy = ctx.extra.get("retrieval_strategy")
        config = ctx.extra.get("retrieval_config")
        if retrieval_strategy and config:
            evidence, _ = retrieval_strategy.search(query, retriever, config)
            return evidence
        result = retriever.search(query, top_k=max(ctx.top_k * 2, 4), candidate_k=max(ctx.top_k * 4, 20), use_rerank=ctx.use_rerank)
        ctx.trace.extend(ToolTrace(**item) for item in result.trace)
        return result.evidence


# ---------------------------------------------------------------------------
# Step 3: Generate answer
# ---------------------------------------------------------------------------


class GenerateStep(PipelineStep):
    """Produce an answer from evidence using the configured generation strategy."""

    name = "generate"

    def execute(self, ctx: PipelineContext) -> StepResult:
        # If DecomposeStep already produced an answer, skip
        if ctx.answer and ctx.sub_results:
            return StepResult(step=self.name, ok=True, metrics={"skipped": True, "reason": "decompose_produced_answer"})

        answer_gen = ctx.extra.get("answer_generator")
        if answer_gen is None:
            return StepResult(step=self.name, ok=False, error="no answer_generator available")

        gen_strategy = ctx.generation_strategy
        evidence = ctx.evidence
        question = ctx.question

        # Rank evidence for answer
        if answer_gen and evidence:
            evidence = answer_gen._rank_evidence_for_answer(evidence, top_k=ctx.top_k, question=question)
        ctx.evidence = evidence

        # Detect contradictions
        if len({e.paper_id for e in evidence}) >= 2 and getattr(ctx.llm_client, "enabled", False):
            try:
                from .contradiction import detect_contradictions  # fmt: skip
                ctx.contradictions = detect_contradictions(evidence, ctx.llm_client, ctx.trace)
            except Exception:
                ctx.contradictions = []

        if gen_strategy is None:
            # Fallback to rule-based
            answer, _ = answer_gen._rule_based_answer(
                question, evidence, list(ctx.trace), ctx.corpus.get_paper
            )
        else:
            answer, trace_entries = gen_strategy.generate(question, evidence, ctx, answer_gen)
            # trace_entries may already be in ctx.trace via gen_strategy; avoid double-add
            for t in trace_entries:
                if t not in ctx.trace:
                    ctx.trace.append(t)

        ctx.answer = answer
        return StepResult(
            step=self.name,
            ok=True,
            metrics={"answer_length": len(answer), "evidence_count": len(ctx.evidence)},
        )


# ---------------------------------------------------------------------------
# Step 4: Claim audit
# ---------------------------------------------------------------------------


class AuditStep(PipelineStep):
    """Audit the generated answer against evidence."""

    name = "audit"

    def execute(self, ctx: PipelineContext) -> StepResult:
        if not ctx.answer or ctx.insufficient_evidence:
            ctx.claim_audit = []
            return StepResult(step=self.name, ok=True, metrics={"claims": 0, "skipped": True})

        audit_strategy = ctx.audit_strategy
        embedding_client = ctx.embedding_client
        answer_gen = ctx.extra.get("answer_generator")

        if audit_strategy is None:
            ctx.claim_audit = []
            return StepResult(step=self.name, ok=True, metrics={"claims": 0, "skipped": True})

        try:
            audits = audit_strategy.audit(ctx.answer, ctx.evidence, embedding_client, answer_gen)
        except Exception:
            audits = []

        ctx.claim_audit = audits
        return StepResult(
            step=self.name,
            ok=True,
            metrics={"claims": len(audits)},
        )
