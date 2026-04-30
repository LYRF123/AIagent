from __future__ import annotations

import json
from .models import Evidence, ToolTrace

HIGH_SCORE_THRESHOLD = 0.7


def _heuristic_score(question: str, evidence: list[Evidence]) -> float:
    """Fast keyword-overlap score, returns 0.0-1.0."""
    from .retrieval import tokenize_text
    if not evidence:
        return 0.0
    q_tokens = set(tokenize_text(question))
    if not q_tokens:
        return 0.0
    chunk_scores = []
    for item in evidence:
        e_tokens = set(tokenize_text(item.text))
        if not e_tokens:
            chunk_scores.append(0.0)
        else:
            overlap = len(q_tokens & e_tokens)
            chunk_scores.append(overlap / max(len(q_tokens), 1))
    return sum(chunk_scores) / len(chunk_scores) if chunk_scores else 0.0


class EvidenceEvaluator:
    """Evaluate relevance of evidence chunks using LLM."""

    def __init__(self, llm_client):
        self.llm = llm_client
        self._eval_cache: dict[int, dict] = {}

    def evaluate(
        self, question: str, evidence: list[Evidence], trace: list[ToolTrace]
    ) -> dict:
        """
        Rate each evidence chunk 0-1 for relevance using LLM.
        Returns: {"scores": [0.8, 0.3, ...], "average": 0.55, "raw_response": "..."}

        If LLM is not enabled, returns perfect scores (skip evaluation).
        """
        if not self.llm.enabled:
            trace.append(
                ToolTrace(
                    tool="evidence_evaluator",
                    input=f"evaluate {len(evidence)} chunks for: {question}",
                    output="LLM disabled, skipping evaluation",
                )
            )
            return {
                "scores": [1.0] * len(evidence),
                "average": 1.0,
                "raw_response": "LLM disabled",
            }

        # Heuristic pre-check: if retrieval scores are already high, skip LLM
        avg_retrieval_score = sum(e.score for e in evidence) / len(evidence) if evidence else 0.0
        if avg_retrieval_score >= HIGH_SCORE_THRESHOLD:
            scores = [e.score for e in evidence]
            trace.append(
                ToolTrace(
                    tool="evidence_evaluator",
                    input=f"evaluate {len(evidence)} chunks for: {question}",
                    output=f"heuristic pre-check passed (avg_score={avg_retrieval_score:.3f} >= {HIGH_SCORE_THRESHOLD}), using retrieval scores",
                )
            )
            return {
                "scores": scores,
                "average": avg_retrieval_score,
                "raw_response": "heuristic pre-check",
            }

        # Cache check before heavy LLM work
        cache_key = hash((question, tuple(e.text for e in evidence)))
        if cache_key in self._eval_cache:
            trace.append(
                ToolTrace(
                    tool="evidence_evaluator",
                    input=f"evaluate {len(evidence)} chunks for: {question}",
                    output="cache hit",
                )
            )
            return self._eval_cache[cache_key]

        # Build prompt with numbered evidence chunks
        chunks_text = "\n".join(
            f"[{i + 1}] {item.text}"
            for i, item in enumerate(evidence)
        )
        user_prompt = (
            f"Question: {question}\n\n"
            f"Evidence chunks:\n{chunks_text}\n\n"
            "Return ONLY a JSON array of scores like [0.8, 0.3, 0.9]. No explanation."
        )
        system_prompt = (
            "You are an evidence evaluator. "
            "Rate each evidence chunk's relevance to the question on a scale of 0-1."
        )

        try:
            response = self.llm.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            raw = response.text.strip()
            # Extract JSON array from response
            scores = _parse_score_array(raw, len(evidence))
            average = sum(scores) / len(scores) if scores else 0.0
        except Exception:
            scores = [0.5] * len(evidence)
            average = 0.5
            raw = ""

        trace.append(
            ToolTrace(
                tool="evidence_evaluator",
                input=f"evaluate {len(evidence)} chunks for: {question}",
                output=f"scores={scores}, average={average:.3f}",
            )
        )

        result = {
            "scores": scores,
            "average": average,
            "raw_response": raw,
        }
        self._eval_cache[cache_key] = result
        return result


class QueryRewriter:
    """Rewrite/decompose questions when evidence is insufficient."""

    def __init__(self, llm_client):
        self.llm = llm_client

    def rewrite(
        self,
        original_question: str,
        evidence: list[Evidence],
        attempt: int,
        trace: list[ToolTrace],
    ) -> str:
        """
        Rewrite the question to find missing information.
        On attempt 1: heuristic synonym expansion (uses QUERY_SYNONYMS)
        On attempt 2: decompose into sub-questions (LLM)
        On attempt 3: broaden the query (LLM)

        Uses heuristic on attempt 1, LLM on attempt >= 2.
        """
        if not self.llm.enabled:
            return original_question

        if attempt == 1:
            # Heuristic rewrite: synonym expansion
            from .retrieval import QUERY_SYNONYMS, tokenize_text
            tokens = tokenize_text(original_question)
            expanded_terms = []
            for token in tokens:
                syn = QUERY_SYNONYMS.get(token)
                if syn:
                    expanded_terms.append(syn)
            rewritten = f"{original_question} {' '.join(expanded_terms)}".strip() if expanded_terms else original_question
            trace.append(
                ToolTrace(
                    tool="query_rewriter",
                    input=f"attempt={attempt}, original={original_question}",
                    output=f"heuristic: {rewritten}",
                )
            )
            return rewritten

        system_prompts = {
            2: "You are a query decomposer. Break the question into specific sub-questions.",
            3: "You are a query simplifier. Extract the core concepts from the question.",
        }
        system_prompt = system_prompts.get(
            attempt,
            "You are a query rewriter. Rewrite the query to find missing information.",
        )

        # Build a brief evidence summary
        evidence_summary = "; ".join(
            f"[{item.paper_id}] {item.text[:200]}"
            for item in evidence[:3]
        )
        if len(evidence) > 3:
            evidence_summary += f" (and {len(evidence) - 3} more chunks)"

        user_prompt = (
            f"Original question: {original_question}\n\n"
            f"Retrieved evidence was insufficient. This is rewrite attempt {attempt}/3.\n\n"
            f"Retrieved evidence summary: {evidence_summary}\n\n"
            "Return ONLY the rewritten query text, no explanation."
        )

        try:
            response = self.llm.complete(
                system_prompt=system_prompt, user_prompt=user_prompt
            )
            rewritten = response.text.strip()
        except Exception:
            rewritten = original_question

        trace.append(
            ToolTrace(
                tool="query_rewriter",
                input=f"attempt={attempt}, original={original_question}",
                output=rewritten,
            )
        )

        return rewritten


def _parse_score_array(text: str, expected_length: int) -> list[float]:
    """Parse a JSON array of scores from LLM response text."""
    # Try to find and parse a JSON array in the text
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        try:
            scores = json.loads(text)
            if isinstance(scores, list) and all(isinstance(s, (int, float)) for s in scores):
                return [min(max(float(s), 0.0), 1.0) for s in scores]
        except (json.JSONDecodeError, ValueError):
            pass

    # Fallback: try to find an array somewhere in the text
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end > start:
        try:
            scores = json.loads(text[start : end + 1])
            if isinstance(scores, list) and len(scores) == expected_length:
                return [min(max(float(s), 0.0), 1.0) for s in scores]
        except (json.JSONDecodeError, ValueError):
            pass

    return [0.5] * expected_length


def self_correct_retrieval(
    query: str,
    retrieval_fn,  # callable(query, top_k) -> list[Evidence]
    llm_client,  # DashScopeLangChainClient instance
    top_k: int = 5,
    max_rounds: int = 3,
    threshold: float = 0.4,
    trace: list[ToolTrace] | None = None,
) -> list[Evidence]:
    """
    Main self-correcting retrieval loop.

    1. Retrieve evidence
    2. Evaluate relevance scores
    3. If avg_score < threshold AND rounds remaining:
       - Rewrite query
       - Go to step 1
    4. Return best evidence found
    """
    trace = trace or []
    current_query = query
    best_evidence: list[Evidence] = []
    best_score = 0.0

    evaluator = EvidenceEvaluator(llm_client)
    rewriter = QueryRewriter(llm_client)

    for round_idx in range(max_rounds):
        evidence = retrieval_fn(current_query, top_k)

        if not evidence:
            continue

        # In the round loop, after retrieving evidence, check heuristic shortcut
        if round_idx == 0:
            avg_retrieval = sum(e.score for e in evidence) / len(evidence) if evidence else 0.0
            if avg_retrieval >= threshold:
                # Use heuristic score for early skip of LLM
                heuristic = _heuristic_score(query, evidence)
                if heuristic >= threshold:
                    trace.append(
                        ToolTrace(
                            tool="self_correct_exit",
                            input=current_query,
                            output=f"heuristic={heuristic:.3f} >= threshold={threshold}, early exit round=1",
                        )
                    )
                    return evidence

        eval_result = evaluator.evaluate(query, evidence, trace)
        avg = eval_result["average"]

        if avg > best_score:
            best_score = avg
            best_evidence = evidence

        if avg >= threshold:
            trace.append(
                ToolTrace(
                    tool="self_correct_exit",
                    input=current_query,
                    output=f"score={avg:.3f} >= threshold={threshold}, round={round_idx + 1}",
                )
            )
            break

        if round_idx < max_rounds - 1:
            current_query = rewriter.rewrite(query, evidence, round_idx + 1, trace)
            trace.append(
                ToolTrace(
                    tool="self_correct_retry",
                    input=current_query,
                    output=f"round={round_idx + 2}, prev_score={avg:.3f}",
                )
            )

    return best_evidence
