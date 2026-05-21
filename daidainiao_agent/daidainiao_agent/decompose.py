from __future__ import annotations

import re
from .models import Evidence, ToolTrace


# Heuristic patterns for detecting decomposable questions
_COMPARISON_PATTERNS = [
    re.compile(r"\b(?:vs\.?|versus|compared?\s+(?:to|with)|differ(?:ence|ent|s)?|区别|对比|比较|相比)\b", re.IGNORECASE),
]
_MULTI_ENTITY_PATTERN = re.compile(
    r"\b(?:和|与|及|以及|and|or|both)\b", re.IGNORECASE
)


class QueryDecomposer:
    """Decompose complex multi-hop questions into sub-questions."""

    @staticmethod
    def should_decompose(question: str) -> bool:
        """Heuristic check: does this question contain comparison or multi-entity patterns?"""
        normalized = question.strip()
        if not normalized or len(normalized) < 10:
            return False
        has_comparison = any(p.search(normalized) for p in _COMPARISON_PATTERNS)
        has_multi_entity = bool(_MULTI_ENTITY_PATTERN.search(normalized))
        return has_comparison and has_multi_entity

    @staticmethod
    def decompose(question: str, llm_client, trace: list[ToolTrace]) -> list[str]:
        """Use LLM to decompose a complex question into sub-questions.

        Returns a list of sub-question strings. Falls back to [question] on failure.
        """
        if not llm_client.enabled:
            return [question]

        system_prompt = (
            "You are a query decomposer for a research paper Q&A system. "
            "Break the user's complex question into 2-4 simpler, self-contained sub-questions. "
            "Each sub-question should be answerable independently from a paper corpus. "
            "Reply with one sub-question per line, no numbering, no explanation."
        )
        user_prompt = f"Decompose this question:\n{question}"

        try:
            response = llm_client.complete(system_prompt=system_prompt, user_prompt=user_prompt)
            lines = [line.strip() for line in response.text.strip().splitlines() if line.strip()]
            # Remove numbering like "1." or "- "
            cleaned = []
            for line in lines:
                line = re.sub(r"^\d+[\.\)]\s*", "", line)
                line = re.sub(r"^[-*]\s*", "", line)
                line = line.strip()
                if line:
                    cleaned.append(line)
            if not cleaned:
                return [question]
            trace.append(
                ToolTrace(
                    tool="query_decomposer",
                    input=question,
                    output=" | ".join(cleaned),
                )
            )
            return cleaned[:4]  # Cap at 4 sub-questions
        except Exception:
            return [question]

    @staticmethod
    def synthesize(question: str, sub_results: list[dict], llm_client, trace: list[ToolTrace]) -> str:
        """Synthesize sub-question answers into a unified answer.

        sub_results: list of {"question": str, "answer": str, "evidence_count": int}
        Returns synthesized answer string.
        """
        if not llm_client.enabled:
            # Rule-based fallback: concatenate answers
            parts = []
            for sr in sub_results:
                if sr.get("answer"):
                    parts.append(sr["answer"])
            return "\n\n".join(parts) if parts else ""

        context_parts = []
        for idx, sr in enumerate(sub_results, start=1):
            context_parts.append(
                f"Sub-question {idx}: {sr['question']}\n"
                f"Answer: {sr['answer']}"
            )
        context = "\n\n".join(context_parts)

        system_prompt = (
            "You are a research assistant. Synthesize the answers to sub-questions into "
            "a coherent, unified answer to the original question. "
            "Preserve all citation references like [1], [2] from the sub-answers. "
            "Reply in the same language as the original question."
        )
        user_prompt = (
            f"Original question: {question}\n\n"
            f"Sub-question answers:\n{context}\n\n"
            "Write a unified answer that addresses the original question."
        )

        try:
            response = llm_client.complete(system_prompt=system_prompt, user_prompt=user_prompt)
            trace.append(
                ToolTrace(
                    tool="query_synthesizer",
                    input=question,
                    output=f"synthesized from {len(sub_results)} sub-answers",
                )
            )
            return response.text.strip()
        except Exception:
            # Fallback: concatenate
            parts = [sr["answer"] for sr in sub_results if sr.get("answer")]
            return "\n\n".join(parts)
