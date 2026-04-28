from __future__ import annotations

from collections.abc import Iterator

from .llm import build_context_block
from .models import AnswerResult, ConversationMessage, Evidence, ToolTrace


SECTION_PRIORITY = {
    "summary": 0,
    "methods": 1,
    "findings": 2,
    "limitations": 3,
    "topics": 4,
}
FOLLOW_UP_MARKERS = {
    "it",
    "its",
    "they",
    "their",
    "them",
    "this",
    "that",
    "these",
    "those",
    "he",
    "she",
    "then",
    "also",
    "instead",
    "compare",
    "相比",
    "它",
    "它们",
    "这个",
    "这个方法",
    "这篇",
    "那篇",
    "这些",
    "那些",
    "进一步",
    "继续",
    "然后",
    "同时",
    "另外",
}


class AnswerGenerator:
    def __init__(self, llm_client, strict_grounded: bool = True) -> None:
        self.llm = llm_client
        self.strict_grounded = strict_grounded

    # ------------------------------------------------------------------
    # static helpers (no self / no LLM dependency)
    # ------------------------------------------------------------------

    @staticmethod
    def _is_system_question(question: str) -> bool:
        normalized = question.strip().lower()
        keywords = [
            "你是什么模型",
            "你用的什么模型",
            "你是什么",
            "what model are you",
            "which model",
            "who are you",
            "what are you",
        ]
        return any(keyword in normalized for keyword in keywords)

    @staticmethod
    def _prefers_chinese(text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    @staticmethod
    def _compact_text(value: str, limit: int = 180) -> str:
        compact = " ".join(value.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    @staticmethod
    def _looks_like_follow_up(question: str) -> bool:
        normalized = " ".join(question.lower().split())
        if not normalized:
            return False
        return any(marker in normalized for marker in FOLLOW_UP_MARKERS)

    @staticmethod
    def _iter_text_chunks(text: str, chunk_size: int = 48) -> Iterator[str]:
        if not text:
            return
        normalized = text.strip()
        for start in range(0, len(normalized), chunk_size):
            yield normalized[start : start + chunk_size]

    @staticmethod
    def _rank_evidence_for_answer(evidence: list[Evidence], top_k: int, max_papers: int = 2) -> list[Evidence]:
        ranked = sorted(
            evidence,
            key=lambda item: (-(item.score - 0.02 * SECTION_PRIORITY.get(item.section, 5)), item.paper_id),
        )
        selected: list[Evidence] = []
        seen_pairs: set[tuple[str, str]] = set()
        paper_order: list[str] = []
        for item in ranked:
            if item.paper_id not in paper_order and len(paper_order) >= max_papers:
                continue
            key = (item.paper_id, item.section)
            if key in seen_pairs:
                continue
            selected.append(item)
            seen_pairs.add(key)
            if item.paper_id not in paper_order:
                paper_order.append(item.paper_id)
            if len(selected) >= top_k:
                break
        return selected

    # ------------------------------------------------------------------
    # helper: build prompts for LLM calls
    # ------------------------------------------------------------------

    def _build_history_block(self, history: list[ConversationMessage], limit: int = 4) -> str:
        if not history:
            return ""
        recent_history = history[-limit:]
        return "\n".join(
            f"{item.role.title()}: {self._compact_text(item.content, limit=220)}"
            for item in recent_history
        )

    def _build_answer_prompts(self, question: str, evidence: list[Evidence], history: list[ConversationMessage] | None = None) -> tuple[str, str]:
        context = build_context_block([item.model_dump() for item in evidence])
        history_block = self._build_history_block(history or [])
        system_prompt = (
            "You are a research assistant. Answer only from the provided evidence. "
            "Be concise and accurate. Reply in the same language as the user's question. "
            "If the evidence is weak, say so explicitly. Every factual claim must include bracket citations like [1] or [2]."
        )
        if history_block:
            user_prompt = (
                f"Conversation history:\n{history_block}\n\n"
                f"Question:\n{question}\n\n"
                f"Evidence:\n{context}\n\n"
                "Answer the latest question using the evidence above. Use the history only to resolve references in the latest question."
            )
        else:
            user_prompt = (
                f"Question:\n{question}\n\n"
                f"Evidence:\n{context}\n\n"
                "Write a short answer grounded in the evidence above."
            )
        return system_prompt, user_prompt

    # ------------------------------------------------------------------
    # contextual query building
    # ------------------------------------------------------------------

    def _build_contextual_query(self, question: str, history: list[ConversationMessage], trace: list[ToolTrace]) -> str:
        if not history:
            return question

        if not self._looks_like_follow_up(question):
            trace.append(
                ToolTrace(
                    tool="conversation_context",
                    input=question,
                    output="standalone_question_no_history_expansion",
                )
            )
            return question

        recent_user_questions = [item.content for item in history if item.role == "user"][-2:]
        recent_assistant_answers = [item.content for item in history if item.role == "assistant"][-1:]
        context_parts = [self._compact_text(item, limit=120) for item in recent_user_questions]
        context_parts.extend(self._compact_text(item, limit=160) for item in recent_assistant_answers)
        context_parts.append(question.strip())
        contextual_query = " ".join(part for part in context_parts if part)
        trace.append(
            ToolTrace(
                tool="conversation_context",
                input=question,
                output=contextual_query,
            )
        )
        return contextual_query

    # ------------------------------------------------------------------
    # answer generation: system info
    # ------------------------------------------------------------------

    def _system_answer(self, question: str) -> AnswerResult:
        if self.llm.enabled:
            answer = (
                f"我当前通过阿里 DashScope 的 OpenAI 兼容接口调用 {self.llm.model} 模型回答，"
                f"检索层使用 Hybrid Retrieval（TF-IDF + BM25 + LangChain FAISS）+ {self.llm.rerank_model} 重排 + {self.llm.embedding_model} 向量表示。"
            )
            trace = [
                ToolTrace(
                    tool="system_info",
                    input=question,
                    output=(
                        f"provider=dashscope, model={self.llm.model}, "
                        f"retrieval=tfidf+bm25+vector, embedding={self.llm.embedding_model}, rerank={self.llm.rerank_model}"
                    ),
                )
            ]
        else:
            answer = "我当前运行的是本地规则版，没有启用 DashScope、外部大模型、向量检索或重排；但本地仍然使用 TF-IDF + BM25 + 查询扩展做检索。"
            trace = [
                ToolTrace(
                    tool="system_info",
                    input=question,
                    output="provider=local, model=rule-based, retrieval=tfidf+bm25+query-expansion, vector=disabled, rerank=disabled",
                )
            ]
        return AnswerResult(question=question, answer=answer, evidence=[], trace=trace)

    # ------------------------------------------------------------------
    # answer generation: rule-based
    # ------------------------------------------------------------------

    def _rule_based_answer(self, question: str, evidence: list[Evidence], trace: list[ToolTrace], get_paper) -> AnswerResult:
        citation_map = {
            (item.paper_id, item.section, item.text): index
            for index, item in enumerate(evidence, start=1)
        }
        snippets_by_paper: dict[str, list[Evidence]] = {}
        for item in evidence:
            snippets_by_paper.setdefault(item.paper_id, []).append(item)

        prefers_chinese = self._prefers_chinese(question)
        lines = []
        for paper_id, snippets in snippets_by_paper.items():
            ordered = sorted(snippets, key=lambda item: (SECTION_PRIORITY.get(item.section, 99), -item.score))
            non_topic = [item for item in ordered if item.section != "topics"]
            if not non_topic:
                continue
            paper = get_paper(paper_id)
            primary = non_topic[0].text
            support = non_topic[1].text if len(non_topic) > 1 else None
            primary_citation = f"[{citation_map[(non_topic[0].paper_id, non_topic[0].section, non_topic[0].text)]}]"
            if prefers_chinese:
                if support:
                    support_citation = f"[{citation_map[(non_topic[1].paper_id, non_topic[1].section, non_topic[1].text)]}]"
                    sentence = f"{paper.title}（{paper.year}）表明：{primary} {primary_citation} 补充信息：{support} {support_citation}"
                else:
                    sentence = f"{paper.title}（{paper.year}）表明：{primary} {primary_citation}"
            else:
                if support:
                    support_citation = f"[{citation_map[(non_topic[1].paper_id, non_topic[1].section, non_topic[1].text)]}]"
                    sentence = f"{paper.title} ({paper.year}) indicates that {primary} {primary_citation} Supporting detail: {support} {support_citation}"
                else:
                    sentence = f"{paper.title} ({paper.year}) indicates that {primary} {primary_citation}"
            lines.append(sentence)

        if not lines and evidence:
            paper = get_paper(evidence[0].paper_id)
            if prefers_chinese:
                lines.append(f"{paper.title}（{paper.year}）是当前语料库中最接近的问题匹配，但目前只找到了主题级证据。")
            else:
                lines.append(f"{paper.title} ({paper.year}) is the closest match in the local corpus, but only topic-level evidence was found.")

        if lines:
            answer = " ".join(lines)
        elif prefers_chinese:
            answer = "当前本地语料库里没有找到相关证据。"
        else:
            answer = "No relevant evidence was found in the local corpus."
        return AnswerResult(question=question, answer=answer, evidence=evidence, trace=trace)

    # ------------------------------------------------------------------
    # answer generation: insufficient evidence
    # ------------------------------------------------------------------

    def _insufficient_evidence_answer(self, question: str, trace: list[ToolTrace]) -> AnswerResult:
        trace.append(
            ToolTrace(
                tool="grounded_answer_guard",
                input=question,
                output="blocked_unverified_answer_due_to_missing_evidence",
            )
        )
        return AnswerResult(
            question=question,
            answer="当前本地语料库里没有找到足够证据，因此我不能可靠地回答这个问题。" if self._prefers_chinese(question) else "No relevant evidence was found in the local corpus, so I can't answer this reliably.",
            evidence=[],
            trace=trace,
            insufficient_evidence=True,
        )

    # ------------------------------------------------------------------
    # answer generation: LLM
    # ------------------------------------------------------------------

    def _llm_answer(
        self,
        question: str,
        evidence: list[Evidence],
        trace: list[ToolTrace],
        history: list[ConversationMessage] | None = None,
    ) -> AnswerResult:
        system_prompt, user_prompt = self._build_answer_prompts(question, evidence, history)
        llm_response = self.llm.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        trace.append(
            ToolTrace(
                tool="langchain_chat_qwen",
                input=question,
                output=f"provider={llm_response.provider}, model={llm_response.model}",
            )
        )
        return AnswerResult(question=question, answer=llm_response.text, evidence=evidence, trace=trace)

    def _llm_answer_stream(
        self,
        question: str,
        evidence: list[Evidence],
        trace: list[ToolTrace],
        history: list[ConversationMessage] | None = None,
    ) -> Iterator[str]:
        system_prompt, user_prompt = self._build_answer_prompts(question, evidence, history)
        collected: list[str] = []
        try:
            for delta in self.llm.stream_complete(system_prompt=system_prompt, user_prompt=user_prompt):
                if not delta:
                    continue
                collected.append(delta)
                yield delta
            trace.append(
                ToolTrace(
                    tool="langchain_chat_qwen_stream",
                    input=question,
                    output=f"provider=dashscope, model={self.llm.model}",
                )
            )
            return
        except Exception as exc:
            trace.append(ToolTrace(tool="langchain_chat_stream_error", input=question, output=str(exc)))

        try:
            llm_response = self.llm.complete(system_prompt=system_prompt, user_prompt=user_prompt)
            streamed_text = "".join(collected)
            if llm_response.text.startswith(streamed_text):
                remainder = llm_response.text[len(streamed_text) :]
            else:
                remainder = llm_response.text if not streamed_text else ""
            if remainder:
                yield remainder
            trace.append(
                ToolTrace(
                    tool="langchain_chat_qwen",
                    input=question,
                    output=f"provider={llm_response.provider}, model={llm_response.model}",
                )
            )
        except Exception as exc:
            trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))

    def _llm_general_answer(self, question: str, trace: list[ToolTrace]) -> AnswerResult:
        system_prompt = (
            "You are a helpful assistant for a local research-agent application. "
            "Reply in the same language as the user's question. "
            "If the user asks about the model or system, answer directly and concisely."
        )
        llm_response = self.llm.complete(system_prompt=system_prompt, user_prompt=question)
        trace.append(
            ToolTrace(
                tool="langchain_chat_qwen",
                input=question,
                output=f"provider={llm_response.provider}, model={llm_response.model}",
            )
        )
        return AnswerResult(question=question, answer=llm_response.text, evidence=[], trace=trace)
