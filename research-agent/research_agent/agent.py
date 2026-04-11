from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .corpus import PaperCorpus
from .file_import import build_imported_paper
from .hybrid import HybridRetriever
from .llm import DashScopeLangChainClient, build_context_block
from .models import AnswerResult, ComparisonResult, ComparisonRow, ConversationMessage, Evidence, ReviewResult, ToolTrace
from .rag import LangChainVectorRAG
from .retrieval import BM25Retriever, QueryExpander, TfidfRetriever


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


class ResearchAssistant:
    def __init__(self, corpus_path: str | Path | None = None) -> None:
        self.corpus = PaperCorpus.from_json(corpus_path)
        self.llm = DashScopeLangChainClient()
        self.managed_upload_dir = Path(__file__).resolve().parent.parent / "uploads"
        self._rebuild_retrievers()

    def _rebuild_retrievers(self) -> None:
        self.tfidf_retriever = TfidfRetriever(self.corpus)
        self.bm25_retriever = BM25Retriever(self.corpus)
        self.query_expander = QueryExpander(self.corpus)
        self.vector_rag = LangChainVectorRAG(self.corpus, self.llm)
        self.hybrid_retriever = HybridRetriever(
            self.tfidf_retriever,
            self.bm25_retriever,
            self.vector_rag,
            self.llm,
            self.query_expander,
        )

    def list_imported_documents(self) -> list[dict]:
        return [
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "year": paper.year,
                "source_url": paper.source_url,
                "file_name": Path(paper.source_url).name,
                "summary_preview": paper.summary[:240],
            }
            for paper in reversed(self.corpus.list_imported_papers())
        ]

    def import_document(self, path: str | Path, original_name: str | None = None) -> dict:
        paper = build_imported_paper(path, original_name=original_name)
        self.corpus.add_imported_paper(paper, persist=True)
        self._rebuild_retrievers()
        return {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "source_url": paper.source_url,
            "file_name": Path(paper.source_url).name,
            "summary_preview": paper.summary[:360],
            "imported_count": len(self.corpus.list_imported_papers()),
        }

    def delete_document(self, paper_id: str) -> dict:
        removed = next((paper for paper in self.corpus.list_imported_papers() if paper.paper_id == paper_id), None)
        if removed is None:
            raise ValueError("未找到要删除的文档。")

        source_path = Path(removed.source_url)
        if self._is_managed_upload(source_path) and source_path.exists() and source_path.is_file():
            source_path.unlink()

        self.corpus.delete_imported_paper(paper_id, persist=True)
        self._rebuild_retrievers()
        return {
            "paper_id": paper_id,
            "title": removed.title,
            "remaining_count": len(self.corpus.list_imported_papers()),
        }

    def _is_managed_upload(self, path: str | Path) -> bool:
        root = self.managed_upload_dir.resolve(strict=False)
        resolved = Path(path).resolve(strict=False)
        return resolved == root or root in resolved.parents

    def _is_system_question(self, question: str) -> bool:
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

    def _prefers_chinese(self, text: str) -> bool:
        return any("\u4e00" <= char <= "\u9fff" for char in text)

    def _compact_text(self, value: str, limit: int = 180) -> str:
        compact = " ".join(value.split())
        if len(compact) <= limit:
            return compact
        return compact[: limit - 3].rstrip() + "..."

    def _looks_like_follow_up(self, question: str) -> bool:
        normalized = " ".join(question.lower().split())
        if not normalized:
            return False
        if any(marker in normalized for marker in FOLLOW_UP_MARKERS):
            return True
        return len(normalized.split()) <= 8

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

    def _iter_text_chunks(self, text: str, chunk_size: int = 48) -> Iterator[str]:
        if not text:
            return
        normalized = text.strip()
        for start in range(0, len(normalized), chunk_size):
            yield normalized[start : start + chunk_size]

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

    def _retrieve_evidence(self, query: str, top_k: int, trace: list[ToolTrace]) -> list[Evidence]:
        result = self.hybrid_retriever.search(query, top_k=max(top_k, 5), candidate_k=max(top_k * 3, 12))
        trace.extend(ToolTrace(**item) for item in result.trace)
        return result.evidence

    def search_papers(self, query: str, top_k: int = 5) -> list[dict]:
        evidence = self._retrieve_evidence(query, top_k=top_k * 2, trace=[])
        grouped: dict[str, dict] = {}
        for item in evidence:
            existing = grouped.get(item.paper_id)
            if not existing:
                grouped[item.paper_id] = {
                    "paper_id": item.paper_id,
                    "title": item.title,
                    "score": item.score,
                    "highlights": [item.text],
                }
                continue
            existing["score"] = max(existing["score"], item.score)
            if len(existing["highlights"]) < 2 and item.text not in existing["highlights"]:
                existing["highlights"].append(item.text)
        ranked = sorted(grouped.values(), key=lambda row: row["score"], reverse=True)
        return ranked[:top_k]

    def _rank_evidence_for_answer(self, evidence: list[Evidence], top_k: int, max_papers: int = 2) -> list[Evidence]:
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

    def _rule_based_answer(self, question: str, evidence: list[Evidence], trace: list[ToolTrace]) -> AnswerResult:
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
            paper = self.corpus.get_paper(paper_id)
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
            paper = self.corpus.get_paper(evidence[0].paper_id)
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

    def answer_question(
        self,
        question: str,
        top_k: int = 5,
        strict_grounded: bool = True,
        history: list[ConversationMessage] | None = None,
    ) -> AnswerResult:
        if self._is_system_question(question):
            return self._system_answer(question)

        history = list(history or [])
        trace: list[ToolTrace] = []
        retrieval_query = self._build_contextual_query(question, history, trace)
        raw_evidence = self._retrieve_evidence(retrieval_query, top_k=max(top_k * 3, 6), trace=trace)
        evidence = self._rank_evidence_for_answer(raw_evidence, top_k=top_k)

        if not evidence:
            if strict_grounded:
                return self._insufficient_evidence_answer(question, trace)
            if self.llm.enabled:
                try:
                    return self._llm_general_answer(question, trace)
                except Exception as exc:
                    trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))
            return AnswerResult(
                question=question,
                answer="当前本地语料库里没有找到相关证据。" if self._prefers_chinese(question) else "No relevant evidence was found in the local corpus.",
                evidence=[],
                trace=trace,
                insufficient_evidence=True,
            )

        if self.llm.enabled:
            try:
                return self._llm_answer(question, evidence, trace, history=history)
            except Exception as exc:
                trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))

        return self._rule_based_answer(question, evidence, trace)

    def answer_question_stream(
        self,
        question: str,
        top_k: int = 5,
        strict_grounded: bool = True,
        history: list[ConversationMessage] | None = None,
    ) -> Iterator[dict]:
        if self._is_system_question(question):
            result = self._system_answer(question)
            for chunk in self._iter_text_chunks(result.answer):
                yield {"type": "chunk", "delta": chunk}
            yield {"type": "final", "data": result.model_dump()}
            return

        history = list(history or [])
        trace: list[ToolTrace] = []
        retrieval_query = self._build_contextual_query(question, history, trace)
        raw_evidence = self._retrieve_evidence(retrieval_query, top_k=max(top_k * 3, 6), trace=trace)
        evidence = self._rank_evidence_for_answer(raw_evidence, top_k=top_k)

        if not evidence:
            if strict_grounded:
                result = self._insufficient_evidence_answer(question, trace)
            elif self.llm.enabled:
                try:
                    result = self._llm_general_answer(question, trace)
                except Exception as exc:
                    trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))
                    result = AnswerResult(
                        question=question,
                        answer="当前本地语料库里没有找到相关证据。" if self._prefers_chinese(question) else "No relevant evidence was found in the local corpus.",
                        evidence=[],
                        trace=trace,
                        insufficient_evidence=True,
                    )
            else:
                result = AnswerResult(
                    question=question,
                    answer="当前本地语料库里没有找到相关证据。" if self._prefers_chinese(question) else "No relevant evidence was found in the local corpus.",
                    evidence=[],
                    trace=trace,
                    insufficient_evidence=True,
                )
            for chunk in self._iter_text_chunks(result.answer):
                yield {"type": "chunk", "delta": chunk}
            yield {"type": "final", "data": result.model_dump()}
            return

        if self.llm.enabled:
            chunks: list[str] = []
            for delta in self._llm_answer_stream(question, evidence, trace, history=history):
                if not delta:
                    continue
                chunks.append(delta)
                yield {"type": "chunk", "delta": delta}
            streamed_answer = "".join(chunks).strip()
            if streamed_answer:
                result = AnswerResult(question=question, answer=streamed_answer, evidence=evidence, trace=trace)
                yield {"type": "final", "data": result.model_dump()}
                return

        result = self._rule_based_answer(question, evidence, trace)
        for chunk in self._iter_text_chunks(result.answer):
            yield {"type": "chunk", "delta": chunk}
        yield {"type": "final", "data": result.model_dump()}

    def compare_papers(
        self,
        paper_ids: list[str] | None = None,
        query: str | None = None,
        focus: str = "methods, findings, and limitations",
    ) -> ComparisonResult:
        trace: list[ToolTrace] = []
        if paper_ids:
            papers = self.corpus.get_papers(paper_ids)
            trace.append(
                ToolTrace(
                    tool="load_by_id",
                    input=", ".join(paper_ids),
                    output=", ".join(paper.paper_id for paper in papers),
                )
            )
        elif query:
            ranked = self.search_papers(query, top_k=3)
            papers = self.corpus.get_papers([item["paper_id"] for item in ranked])
            trace.append(
                ToolTrace(
                    tool="search_papers",
                    input=query,
                    output=", ".join(item["paper_id"] for item in ranked),
                )
            )
        else:
            raise ValueError("paper_ids or query is required")

        rows = [
            ComparisonRow(
                paper_id=paper.paper_id,
                title=paper.title,
                year=paper.year,
                methods=paper.methods,
                findings=paper.findings,
                limitations=paper.limitations,
            )
            for paper in papers
        ]
        titles = ", ".join(paper.title for paper in papers)
        narrative = f"This comparison focuses on {focus}. Included papers: {titles}."
        if self.llm.enabled and papers:
            context = build_context_block(
                [
                    {
                        "paper_id": paper.paper_id,
                        "title": paper.title,
                        "section": "summary",
                        "score": 1.0,
                        "text": f"Summary: {paper.summary} Methods: {'; '.join(paper.methods)} Findings: {'; '.join(paper.findings)} Limitations: {'; '.join(paper.limitations)}",
                    }
                    for paper in papers
                ]
            )
            try:
                llm_response = self.llm.complete(
                    system_prompt="You are a research assistant. Compare the papers only using the provided context. Reply in the same language as the user's focus description.",
                    user_prompt=f"Focus: {focus}\n\nContext:\n{context}\n\nWrite a concise comparison.",
                )
                narrative = llm_response.text
                trace.append(ToolTrace(tool="langchain_chat_qwen", input=focus, output=f"provider={llm_response.provider}, model={llm_response.model}"))
            except Exception as exc:
                trace.append(ToolTrace(tool="langchain_chat_error", input=focus, output=str(exc)))
        return ComparisonResult(focus=focus, narrative=narrative, rows=rows, trace=trace)

    def generate_review(self, topic: str, top_k: int = 5) -> ReviewResult:
        ranked = self.search_papers(topic, top_k=top_k)
        papers = self.corpus.get_papers([item["paper_id"] for item in ranked])
        trace = [
            ToolTrace(
                tool="search_papers",
                input=topic,
                output=", ".join(item["paper_id"] for item in ranked),
            )
        ]
        if not papers:
            return ReviewResult(
                topic=topic,
                overview="No representative papers were found in the local corpus.",
                trends=[],
                representative_papers=[],
                reading_order=[],
                open_problems=[],
                trace=trace,
            )

        trends = []
        open_problems = []
        for paper in papers[:3]:
            if paper.methods:
                trends.append(f"{paper.title}: {paper.methods[0]}")
            if paper.limitations:
                open_problems.append(paper.limitations[0])

        overview = (
            f"The topic '{topic}' is represented by {len(papers)} local papers. "
            "The literature moves from retrieval or tool augmentation toward more explicit "
            "self-reflection, multi-agent coordination, and domain-specific execution."
        )
        representative = [paper.title for paper in papers]
        reading_order = [paper.title for paper in sorted(papers, key=lambda paper: paper.year)]

        if self.llm.enabled:
            context = build_context_block(
                [
                    {
                        "paper_id": paper.paper_id,
                        "title": paper.title,
                        "section": "summary",
                        "score": 1.0,
                        "text": f"Summary: {paper.summary} Methods: {'; '.join(paper.methods)} Findings: {'; '.join(paper.findings)} Limitations: {'; '.join(paper.limitations)}",
                    }
                    for paper in papers
                ]
            )
            try:
                llm_response = self.llm.complete(
                    system_prompt="You are a research assistant. Produce a concise topic review from the provided papers only. Reply in the same language as the user's topic.",
                    user_prompt=(
                        f"Topic: {topic}\n\nContext:\n{context}\n\n"
                        "Return a compact overview, key trends, and open problems in plain text."
                    ),
                )
                overview = llm_response.text
                trace.append(ToolTrace(tool="langchain_chat_qwen", input=topic, output=f"provider={llm_response.provider}, model={llm_response.model}"))
            except Exception as exc:
                trace.append(ToolTrace(tool="langchain_chat_error", input=topic, output=str(exc)))

        return ReviewResult(
            topic=topic,
            overview=overview,
            trends=trends,
            representative_papers=representative,
            reading_order=reading_order,
            open_problems=open_problems[:5],
            trace=trace,
        )
