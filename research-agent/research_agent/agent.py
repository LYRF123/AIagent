from __future__ import annotations

from pathlib import Path

from .corpus import PaperCorpus
from .file_import import build_imported_paper
from .hybrid import HybridRetriever
from .llm import DashScopeLangChainClient, build_context_block
from .models import AnswerResult, ComparisonResult, ComparisonRow, Evidence, ReviewResult, ToolTrace
from .rag import LangChainVectorRAG
from .retrieval import TfidfRetriever


SECTION_PRIORITY = {
    "summary": 0,
    "methods": 1,
    "findings": 2,
    "limitations": 3,
    "topics": 4,
}


class ResearchAssistant:
    def __init__(self, corpus_path: str | Path | None = None) -> None:
        self.corpus = PaperCorpus.from_json(corpus_path)
        self.llm = DashScopeLangChainClient()
        self._rebuild_retrievers()

    def _rebuild_retrievers(self) -> None:
        self.tfidf_retriever = TfidfRetriever(self.corpus)
        self.vector_rag = LangChainVectorRAG(self.corpus, self.llm)
        self.hybrid_retriever = HybridRetriever(self.tfidf_retriever, self.vector_rag, self.llm)

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
        removed = self.corpus.delete_imported_paper(paper_id, persist=True)
        if removed is None:
            raise ValueError("未找到要删除的文档。")

        source_path = Path(removed.source_url)
        if source_path.exists() and source_path.is_file():
            source_path.unlink()

        self._rebuild_retrievers()
        return {
            "paper_id": paper_id,
            "title": removed.title,
            "remaining_count": len(self.corpus.list_imported_papers()),
        }

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

    def _system_answer(self, question: str) -> AnswerResult:
        if self.llm.enabled:
            answer = (
                f"我当前通过阿里 DashScope 的 OpenAI 兼容接口调用 {self.llm.model} 模型回答，"
                f"检索层使用 Hybrid Retrieval（TF-IDF + LangChain FAISS）+ {self.llm.rerank_model} 重排 + {self.llm.embedding_model} 向量表示。"
            )
            trace = [
                ToolTrace(
                    tool="system_info",
                    input=question,
                    output=(
                        f"provider=dashscope, model={self.llm.model}, "
                        f"embedding={self.llm.embedding_model}, rerank={self.llm.rerank_model}"
                    ),
                )
            ]
        else:
            answer = "我当前运行的是本地规则版，没有启用 DashScope、混合检索、重排或外部大模型。"
            trace = [
                ToolTrace(
                    tool="system_info",
                    input=question,
                    output="provider=local, model=rule-based, retriever=tfidf",
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
        snippets_by_paper: dict[str, list[Evidence]] = {}
        for item in evidence:
            snippets_by_paper.setdefault(item.paper_id, []).append(item)

        lines = []
        for paper_id, snippets in snippets_by_paper.items():
            ordered = sorted(snippets, key=lambda item: (SECTION_PRIORITY.get(item.section, 99), -item.score))
            non_topic = [item for item in ordered if item.section != "topics"]
            if not non_topic:
                continue
            paper = self.corpus.get_paper(paper_id)
            primary = non_topic[0].text
            support = non_topic[1].text if len(non_topic) > 1 else None
            if support:
                sentence = f"{paper.title} ({paper.year}) indicates that {primary} Supporting detail: {support}"
            else:
                sentence = f"{paper.title} ({paper.year}) indicates that {primary}"
            lines.append(sentence)

        if not lines and evidence:
            paper = self.corpus.get_paper(evidence[0].paper_id)
            lines.append(f"{paper.title} ({paper.year}) is the closest match in the local corpus, but only topic-level evidence was found.")

        answer = " ".join(lines) if lines else "No relevant evidence was found in the local corpus."
        return AnswerResult(question=question, answer=answer, evidence=evidence, trace=trace)

    def _llm_answer(self, question: str, evidence: list[Evidence], trace: list[ToolTrace]) -> AnswerResult:
        context = build_context_block([item.model_dump() for item in evidence])
        system_prompt = (
            "You are a research assistant. Answer only from the provided evidence. "
            "Be concise and accurate. Reply in the same language as the user's question. "
            "If the evidence is weak, say so explicitly."
        )
        user_prompt = (
            f"Question:\n{question}\n\n"
            f"Evidence:\n{context}\n\n"
            "Write a short answer grounded in the evidence above."
        )
        llm_response = self.llm.complete(system_prompt=system_prompt, user_prompt=user_prompt)
        trace.append(
            ToolTrace(
                tool="langchain_chat_qwen",
                input=question,
                output=f"provider={llm_response.provider}, model={llm_response.model}",
            )
        )
        return AnswerResult(question=question, answer=llm_response.text, evidence=evidence, trace=trace)

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

    def answer_question(self, question: str, top_k: int = 5) -> AnswerResult:
        if self._is_system_question(question):
            return self._system_answer(question)

        trace: list[ToolTrace] = []
        raw_evidence = self._retrieve_evidence(question, top_k=max(top_k * 3, 6), trace=trace)
        evidence = self._rank_evidence_for_answer(raw_evidence, top_k=top_k)

        if not evidence:
            if self.llm.enabled:
                try:
                    return self._llm_general_answer(question, trace)
                except Exception as exc:
                    trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))
            return AnswerResult(
                question=question,
                answer="No relevant evidence was found in the local corpus.",
                evidence=[],
                trace=trace,
            )

        if self.llm.enabled:
            try:
                return self._llm_answer(question, evidence, trace)
            except Exception as exc:
                trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))

        return self._rule_based_answer(question, evidence, trace)

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
