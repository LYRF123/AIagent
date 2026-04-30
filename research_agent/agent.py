from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

from .answer_generator import AnswerGenerator
from .comparison import compare_papers as _compare_papers_func
from .corpus import PaperCorpus
from .file_import import build_imported_paper
from .hybrid import HybridRetriever
from .llm import DashScopeLangChainClient
from .models import AnswerResult, ComparisonResult, ConversationMessage, Evidence, ToolTrace
from .rag import LangChainVectorRAG
from .retrieval import BM25Retriever, QueryExpander, TfidfRetriever
from .review import generate_review as _generate_review_func


class ResearchAssistant:
    QUERY_CACHE_SIZE = 64

    def __init__(
        self,
        corpus_path: str | Path | None = None,
        imported_path: str | Path | None = None,
        include_imported: bool = True,
    ) -> None:
        self.corpus = PaperCorpus.from_json(
            corpus_path,
            imported_path=imported_path,
            include_imported=include_imported,
        )
        self.llm = DashScopeLangChainClient()
        self.managed_upload_dir = Path(__file__).resolve().parent.parent / "uploads"
        self._data_dir = Path(__file__).resolve().parent.parent / "data"
        self.answer_generator = AnswerGenerator(self.llm)
        self._rebuild_retrievers()
        self._query_cache: dict[tuple, AnswerResult] = {}

    def _rebuild_retrievers(self) -> None:
        self.tfidf_retriever = TfidfRetriever(self.corpus)
        self.bm25_retriever = BM25Retriever(self.corpus)
        self.query_expander = QueryExpander(self.corpus)
        self.vector_rag = LangChainVectorRAG(self.corpus, self.llm, persist_dir=self._data_dir)
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
                "source_label": paper.source_label,
                "file_name": Path(paper.source_url).name,
                "summary_preview": paper.summary[:240],
            }
            for paper in reversed(self.corpus.list_imported_papers())
        ]

    def import_document(self, path: str | Path, original_name: str | None = None) -> dict:
        self._query_cache.clear()
        paper = build_imported_paper(path, original_name=original_name)
        self.corpus.add_imported_paper(paper, persist=True)
        # Rebuild non-vector retrievers (they need full corpus rebuilds)
        self.tfidf_retriever = TfidfRetriever(self.corpus)
        self.bm25_retriever = BM25Retriever(self.corpus)
        self.query_expander = QueryExpander(self.corpus)
        # Add just the new document to the vector store incrementally
        new_docs = self.vector_rag.build_documents_for_paper(paper.paper_id)
        self.vector_rag.add_documents(new_docs)
        # Rebuild hybrid retriever to pick up updated retrievers
        self.hybrid_retriever = HybridRetriever(
            self.tfidf_retriever,
            self.bm25_retriever,
            self.vector_rag,
            self.llm,
            self.query_expander,
        )
        self.vector_rag.flush()
        return {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "source_url": paper.source_url,
            "source_label": paper.source_label,
            "file_name": Path(paper.source_url).name,
            "summary_preview": paper.summary[:360],
            "imported_count": len(self.corpus.list_imported_papers()),
        }

    def delete_document(self, paper_id: str) -> dict:
        self._query_cache.clear()
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

    def _retrieve_evidence(self, query: str, top_k: int, trace: list[ToolTrace]) -> list[Evidence]:
        result = self.hybrid_retriever.search(query, top_k=max(top_k, 5), candidate_k=max(top_k * 4, 20))
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

    # ------------------------------------------------------------------
    # thin wrapper kept so tests that monkeypatch this method still work
    # ------------------------------------------------------------------

    def _llm_general_answer(self, question: str, trace: list[ToolTrace]) -> AnswerResult:
        return self.answer_generator._llm_general_answer(question, trace)

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def answer_question(
        self,
        question: str,
        top_k: int = 5,
        strict_grounded: bool = True,
        history: list[ConversationMessage] | None = None,
        self_correct: bool = True,
    ) -> AnswerResult:
        cache_key = (question, top_k, strict_grounded, self_correct, tuple((msg.role, msg.content) for msg in (history or [])))
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        ag = self.answer_generator

        if ag._is_system_question(question):
            result = ag._system_answer(question)
        else:
            history = list(history or [])
            trace: list[ToolTrace] = []
            retrieval_query = ag._build_contextual_query(question, history, trace)

            # ---- self-correcting retrieval loop ----
            if self_correct and self.llm.enabled:
                from .self_correct import self_correct_retrieval  # fmt: skip

                def _retrieve_for_self_correct(q: str, k: int) -> list[Evidence]:
                    return self._retrieve_evidence(q, top_k=k, trace=trace)

                raw_evidence = self_correct_retrieval(
                    query=retrieval_query,
                    retrieval_fn=_retrieve_for_self_correct,
                    llm_client=self.llm,
                    top_k=max(top_k * 3, 6),
                    max_rounds=3,
                    threshold=0.4,
                    trace=trace,
                )
            else:
                raw_evidence = self._retrieve_evidence(retrieval_query, top_k=max(top_k * 3, 6), trace=trace)
            evidence = ag._rank_evidence_for_answer(raw_evidence, top_k=top_k)

            if not evidence:
                if strict_grounded:
                    result = ag._insufficient_evidence_answer(question, trace)
                elif self.llm.enabled:
                    try:
                        result = self._llm_general_answer(question, trace)
                    except Exception as exc:
                        trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))
                        result = AnswerResult(
                            question=question,
                            answer="当前本地语料库中没有找到相关证据。" if ag._prefers_chinese(question) else "No relevant evidence was found in the local corpus.",
                            evidence=[],
                            trace=trace,
                            insufficient_evidence=True,
                        )
                else:
                    result = AnswerResult(
                        question=question,
                        answer="当前本地语料库中没有找到相关证据。" if ag._prefers_chinese(question) else "No relevant evidence was found in the local corpus.",
                        evidence=[],
                        trace=trace,
                        insufficient_evidence=True,
                    )
            elif self.llm.enabled:
                try:
                    result = ag._llm_answer(question, evidence, trace, history=history)
                except Exception as exc:
                    trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))
                    result = ag._rule_based_answer(question, evidence, trace, self.corpus.get_paper)
            else:
                result = ag._rule_based_answer(question, evidence, trace, self.corpus.get_paper)

        self._query_cache[cache_key] = result
        if len(self._query_cache) > self.QUERY_CACHE_SIZE:
            oldest_key = next(iter(self._query_cache))
            del self._query_cache[oldest_key]
        return result

    def answer_question_stream(
        self,
        question: str,
        top_k: int = 5,
        strict_grounded: bool = True,
        history: list[ConversationMessage] | None = None,
        self_correct: bool = True,
    ) -> Iterator[dict]:
        ag = self.answer_generator

        if ag._is_system_question(question):
            result = ag._system_answer(question)
            for chunk in ag._iter_text_chunks(result.answer):
                yield {"type": "chunk", "delta": chunk}
            yield {"type": "final", "data": result.model_dump()}
            return

        history = list(history or [])
        trace: list[ToolTrace] = []
        retrieval_query = ag._build_contextual_query(question, history, trace)

        # ---- self-correcting retrieval loop ----
        if self_correct and self.llm.enabled:
            from .self_correct import self_correct_retrieval  # fmt: skip

            def _retrieve_for_self_correct(q: str, k: int) -> list[Evidence]:
                return self._retrieve_evidence(q, top_k=k, trace=trace)

            raw_evidence = self_correct_retrieval(
                query=retrieval_query,
                retrieval_fn=_retrieve_for_self_correct,
                llm_client=self.llm,
                top_k=max(top_k * 3, 6),
                max_rounds=3,
                threshold=0.4,
                trace=trace,
            )
        else:
            raw_evidence = self._retrieve_evidence(retrieval_query, top_k=max(top_k * 3, 6), trace=trace)
        evidence = ag._rank_evidence_for_answer(raw_evidence, top_k=top_k)

        if not evidence:
            if strict_grounded:
                result = ag._insufficient_evidence_answer(question, trace)
            elif self.llm.enabled:
                try:
                    result = self._llm_general_answer(question, trace)
                except Exception as exc:
                    trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))
                    result = AnswerResult(
                        question=question,
                        answer="当前本地语料库中没有找到相关证据。" if ag._prefers_chinese(question) else "No relevant evidence was found in the local corpus.",
                        evidence=[],
                        trace=trace,
                        insufficient_evidence=True,
                    )
            else:
                result = AnswerResult(
                    question=question,
                    answer="当前本地语料库中没有找到相关证据。" if ag._prefers_chinese(question) else "No relevant evidence was found in the local corpus.",
                    evidence=[],
                    trace=trace,
                    insufficient_evidence=True,
                )
            for chunk in ag._iter_text_chunks(result.answer):
                yield {"type": "chunk", "delta": chunk}
            yield {"type": "final", "data": result.model_dump()}
            return

        if self.llm.enabled:
            chunks: list[str] = []
            for delta in ag._llm_answer_stream(question, evidence, trace, history=history):
                if not delta:
                    continue
                chunks.append(delta)
                yield {"type": "chunk", "delta": delta}
            streamed_answer = "".join(chunks).strip()
            if streamed_answer:
                result = ag._with_claim_audit(AnswerResult(question=question, answer=streamed_answer, evidence=evidence, trace=trace))
                yield {"type": "final", "data": result.model_dump()}
                return

        result = ag._rule_based_answer(question, evidence, trace, self.corpus.get_paper)
        for chunk in ag._iter_text_chunks(result.answer):
            yield {"type": "chunk", "delta": chunk}
        yield {"type": "final", "data": result.model_dump()}

    def compare_papers(
        self,
        paper_ids: list[str] | None = None,
        query: str | None = None,
        focus: str = "methods, findings, and limitations",
    ) -> ComparisonResult:
        if paper_ids:
            return _compare_papers_func(self.corpus, paper_ids, focus=focus, llm_client=self.llm)
        elif query:
            ranked = self.search_papers(query, top_k=3)
            ids = [item["paper_id"] for item in ranked]
            trace: list[ToolTrace] = [
                ToolTrace(
                    tool="search_papers",
                    input=query,
                    output=", ".join(ids),
                )
            ]
            return _compare_papers_func(self.corpus, ids, focus=focus, llm_client=self.llm, trace=trace)
        else:
            raise ValueError("paper_ids or query is required")

    def generate_review(self, topic: str, top_k: int = 5) -> ReviewResult:
        from .models import ReviewResult as _ReviewResult  # re-import for local safety

        ranked = self.search_papers(topic, top_k=top_k)
        ids = [item["paper_id"] for item in ranked]
        trace: list[ToolTrace] = [
            ToolTrace(
                tool="search_papers",
                input=topic,
                output=", ".join(ids),
            )
        ]
        return _generate_review_func(self.corpus, ids, topic, top_k=top_k, llm_client=self.llm, trace=trace)
