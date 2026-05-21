from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from .answer_generator import AnswerGenerator
from .comparison import compare_papers as _compare_papers_func
from .corpus import PaperCorpus
from .file_import import build_imported_paper
from .hybrid import HybridRetriever
from .llm import DashScopeLangChainClient, format_embedding_error
from .models import AnswerResult, ComparisonResult, ConversationMessage, Evidence, ToolTrace
from .pipeline import Pipeline, PipelineContext
from .rag import LangChainVectorRAG
from .retrieval import BM25Retriever, QueryExpander, TfidfRetriever
from .review import generate_review as _generate_review_func
from .steps import AuditStep, DecomposeStep, GenerateStep, RetrieveStep
from .strategies import (
    FullAudit,
    GenerationConfig,
    HybridRetrieval,
    LLMGeneration,
    MultiHopDecomposer,
    NoDecompose,
    RetrievalConfig,
    RuleBasedGeneration,
)


@dataclass
class _ResearchPrep:
    retrieval_query: str
    evidence: list[Evidence]
    trace: list[ToolTrace]
    retrieval_diagnostics: dict
    crag_decision: Any = None
    retrieval_confidence: float = 0.0
    early_result: AnswerResult | None = None


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
        self._last_retrieval_diagnostics: dict = {}

    def reconfigure_llm(self, api_key: str, base_url: str = "", model: str = "") -> dict:
        """Reconfigure the LLM client at runtime with new credentials."""
        import os as _os
        from .llm import load_dotenv_map

        _os.environ["DASHSCOPE_API_KEY"] = api_key
        if base_url:
            _os.environ["DASHSCOPE_BASE_URL"] = base_url
        if model:
            _os.environ["DASHSCOPE_MODEL"] = model

        is_dashscope = "dashscope" in (base_url or "")
        if not is_dashscope:
            # 自定义 API：关掉 DashScope 专有 rerank；embedding 默认关闭（多数中转站不支持）
            _os.environ["DASHSCOPE_RERANK_MODEL"] = "disabled"
            _os.environ["DASHSCOPE_EMBEDDING_MODEL"] = "disabled"

        # Clear the dotenv cache so resolve_setting picks up new os.environ values
        from . import llm as _llm
        _llm._ENV_CACHE = None

        # Recreate LLM client with explicit params
        self.llm = DashScopeLangChainClient(
            api_key=api_key,
            base_url=base_url or None,
            model=model or None,
        )
        self.answer_generator = AnswerGenerator(self.llm)
        self._rebuild_retrievers()
        self._query_cache.clear()

        return {
            "provider": "dashscope" if is_dashscope else "openai_compatible",
            "chat_enabled": self.llm.enabled,
            "model": self.llm.model,
            "embedding_enabled": self.llm.embedding_enabled,
            "rerank_enabled": self.llm.rerank_enabled,
        }

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

    def _document_summary(self, paper, imported_ids: set[str]) -> dict:
        passages = [item for item in self.corpus.passages if item.paper_id == paper.paper_id]
        section_counts = Counter(item.section for item in passages)
        source_pages = sorted(
            {
                segment.page
                for segment in paper.source_passages
                if segment.page is not None
            }
        )
        return {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "venue": paper.venue,
            "authors": paper.authors,
            "topics": paper.topics,
            "source_url": paper.source_url,
            "source_label": paper.source_label,
            "file_name": Path(paper.source_url).name if paper.source_url else "",
            "summary_preview": AnswerGenerator._compact_text(paper.summary, limit=360),
            "imported": paper.paper_id in imported_ids,
            "chunk_count": len(passages),
            "section_counts": dict(section_counts),
            "page_count": len(source_pages) if source_pages else None,
            "has_source_pages": bool(source_pages),
        }

    def list_knowledge_documents(self, include_base: bool = True) -> list[dict]:
        imported_ids = {paper.paper_id for paper in self.corpus.list_imported_papers()}
        papers = self.corpus.papers if include_base else self.corpus.list_imported_papers()
        return [
            self._document_summary(paper, imported_ids)
            for paper in sorted(
                papers,
                key=lambda item: (item.paper_id in imported_ids, item.year, item.title.lower()),
                reverse=True,
            )
        ]

    def get_document_detail(self, paper_id: str, passage_limit: int = 12) -> dict:
        paper = self.corpus.get_paper(paper_id)
        imported_ids = {item.paper_id for item in self.corpus.list_imported_papers()}
        passages = [item for item in self.corpus.passages if item.paper_id == paper_id]
        detail = self._document_summary(paper, imported_ids)
        detail.update(
            {
                "summary": paper.summary,
                "methods": paper.methods,
                "findings": paper.findings,
                "limitations": paper.limitations,
                "passages": [
                    {
                        "passage_id": item.passage_id,
                        "section": item.section,
                        "text": item.text,
                        "source_url": item.source_url,
                        "source_label": item.source_label,
                        "page": item.page,
                        "locator": item.locator,
                    }
                    for item in passages[: max(passage_limit, 1)]
                ],
                "passage_total": len(passages),
            }
        )
        return detail

    def build_reading_brief(self, paper_id: str) -> dict:
        paper = self.corpus.get_paper(paper_id)
        passages = [item for item in self.corpus.passages if item.paper_id == paper_id]
        terms = self._extract_terms(paper)
        suggested_questions = [
            f"{paper.title} 的核心问题是什么？",
            f"{paper.title} 使用了哪些方法？",
            f"{paper.title} 的主要发现和局限是什么？",
            f"{paper.title} 和同主题其他论文有什么差异？",
            f"基于 {paper.title}，后续还可以研究什么？",
        ]
        key_passages = [
            {
                "section": item.section,
                "text": AnswerGenerator._compact_text(item.text, limit=320),
                "source_label": item.source_label,
                "page": item.page,
                "locator": item.locator,
            }
            for item in passages[:5]
        ]
        return {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "venue": paper.venue,
            "authors": paper.authors,
            "source_label": paper.source_label,
            "summary": AnswerGenerator._compact_text(paper.summary, limit=900),
            "methods": paper.methods[:5],
            "findings": paper.findings[:5],
            "limitations": paper.limitations[:5],
            "terms": terms,
            "suggested_questions": suggested_questions,
            "key_passages": key_passages,
        }

    def _extract_terms(self, paper, limit: int = 12) -> list[str]:
        terms: list[str] = []
        for topic in paper.topics:
            if topic and topic not in terms:
                terms.append(topic)
        text = f"{paper.title} {paper.summary}"
        candidates = re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}(?:\s+[A-Za-z][A-Za-z0-9-]{2,})?", text)
        for candidate in candidates:
            normalized = " ".join(candidate.split())
            if normalized.lower() in {"this paper", "the paper", "and the", "with the"}:
                continue
            if normalized not in terms:
                terms.append(normalized)
            if len(terms) >= limit:
                break
        return terms[:limit]

    def generate_deep_review(self, topic: str, top_k: int = 5) -> dict:
        ranked = self.search_papers(topic, top_k=top_k)
        paper_ids = [item["paper_id"] for item in ranked]
        review = self.generate_review(topic, top_k=top_k)
        papers = [self.corpus.get_paper(paper_id) for paper_id in paper_ids if paper_id in self.corpus.paper_by_id]
        timeline = [
            {
                "paper_id": paper.paper_id,
                "title": paper.title,
                "year": paper.year,
                "venue": paper.venue,
            }
            for paper in sorted(papers, key=lambda item: item.year)
        ]
        evidence = self._retrieve_evidence(topic, top_k=max(top_k, 5), trace=[])
        return {
            "topic": topic,
            "overview": review.overview,
            "outline": [
                {"title": "研究背景", "body": AnswerGenerator._compact_text(review.overview, limit=520)},
                {"title": "代表工作", "items": review.representative_papers},
                {"title": "方法脉络", "items": review.trends},
                {"title": "开放问题", "items": review.open_problems},
            ],
            "representative_papers": review.representative_papers,
            "reading_order": review.reading_order,
            "open_problems": review.open_problems,
            "timeline": timeline,
            "evidence": [item.model_dump() for item in evidence[:top_k]],
            "trace": [item.model_dump() for item in review.trace],
        }

    def get_system_status(self) -> dict:
        from .hybrid import BM25_WEIGHT, FUSION_METHOD, TFIDF_WEIGHT, VECTOR_WEIGHT

        imported_count = len(self.corpus.list_imported_papers())
        return {
            "model": {
                "provider": "dashscope" if self.llm.enabled else "local",
                "chat_enabled": self.llm.enabled,
                "model": self.llm.model if self.llm.enabled else "rule-based",
                "embedding_enabled": self.llm.embedding_enabled,
                "embedding_model": self.llm.embedding_model,
                "rerank_enabled": self.llm.rerank_enabled,
                "rerank_model": self.llm.rerank_model,
            },
            "corpus": {
                "documents": len(self.corpus.papers),
                "base_documents": len(self.corpus.base_papers),
                "imported_documents": imported_count,
                "passages": len(self.corpus.passages),
            },
            "retrieval": {
                "fusion_method": FUSION_METHOD,
                "weights": {
                    "tfidf": TFIDF_WEIGHT,
                    "bm25": BM25_WEIGHT,
                    "vector": VECTOR_WEIGHT,
                },
                "vector_enabled": self.vector_rag.enabled,
                "query_cache_size": len(self._query_cache),
            },
            "usage": self.llm.usage_tracker.summary(),
        }

    def _sync_vector_index_for_paper(self, paper_id: str) -> str | None:
        if not self.llm.embedding_enabled:
            return None
        try:
            new_docs = self.vector_rag.build_documents_for_paper(paper_id)
            self.vector_rag.add_documents(new_docs)
            self.vector_rag.flush()
        except Exception as exc:
            return format_embedding_error(exc)
        return None

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

    def import_document(self, path: str | Path, original_name: str | None = None) -> dict:
        self._query_cache.clear()
        paper = build_imported_paper(path, original_name=original_name)
        self.corpus.add_imported_paper(paper, persist=True)
        new_passages = [p for p in self.corpus.passages if p.paper_id == paper.paper_id]
        self.tfidf_retriever.add_passages(new_passages)
        self.bm25_retriever.add_passages(new_passages)
        self.query_expander = QueryExpander(self.corpus)
        vector_warning = self._sync_vector_index_for_paper(paper.paper_id)
        self.hybrid_retriever = HybridRetriever(
            self.tfidf_retriever,
            self.bm25_retriever,
            self.vector_rag,
            self.llm,
            self.query_expander,
        )
        result = {
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "source_url": paper.source_url,
            "source_label": paper.source_label,
            "file_name": Path(paper.source_url).name,
            "summary_preview": paper.summary[:360],
            "imported_count": len(self.corpus.list_imported_papers()),
        }
        if vector_warning:
            result["vector_warning"] = vector_warning
        return result

    def _is_managed_upload(self, path: str | Path) -> bool:
        root = self.managed_upload_dir.resolve(strict=False)
        resolved = Path(path).resolve(strict=False)
        return resolved == root or root in resolved.parents

    def _retrieve_evidence(self, query: str, top_k: int, trace: list[ToolTrace], use_rerank: bool = True) -> list[Evidence]:
        result = self.hybrid_retriever.search(query, top_k=max(top_k, 5), candidate_k=max(top_k * 4, 20), use_rerank=use_rerank)
        trace.extend(ToolTrace(**item) for item in result.trace)
        self._last_retrieval_diagnostics = result.diagnostics
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
    # pipeline helpers
    # ------------------------------------------------------------------

    def _build_pipeline_context(
        self,
        question: str,
        retrieval_query: str = "",
        top_k: int = 5,
        strict_grounded: bool = True,
        history: list[ConversationMessage] | None = None,
        trace: list[ToolTrace] | None = None,
        use_rerank: bool = True,
    ) -> PipelineContext:
        """Wire all dependencies into a PipelineContext."""
        ag = self.answer_generator
        embedding = self.llm.embedding_client() if getattr(self.llm, "embedding_enabled", False) else None

        # Choose strategies based on LLM availability
        if self.llm.enabled:
            gen_strategy = LLMGeneration(GenerationConfig())
            decomposition_strategy: DecompositionStrategy = MultiHopDecomposer()
        else:
            gen_strategy = RuleBasedGeneration()
            decomposition_strategy = NoDecompose()

        retrieval_config = RetrievalConfig(top_k=top_k, use_rerank=use_rerank)

        ctx = PipelineContext(
            question=question,
            retrieval_query=retrieval_query or question,
            top_k=top_k,
            strict_grounded=strict_grounded,
            use_rerank=use_rerank,
            history=[{"role": msg.role, "content": msg.content} for msg in (history or [])],
            trace=list(trace or []),
            retriever=self.hybrid_retriever,
            llm_client=self.llm,
            embedding_client=embedding,
            corpus=self.corpus,
            generation_strategy=gen_strategy,
            audit_strategy=FullAudit(),
            decomposition_strategy=decomposition_strategy,
            extra={
                "answer_generator": ag,
                "retrieval_strategy": HybridRetrieval(),
                "retrieval_config": retrieval_config,
            },
        )
        return ctx

    def _run_multi_hop(
        self,
        question: str,
        retrieval_query: str,
        top_k: int,
        trace: list[ToolTrace],
        history: list[ConversationMessage] | None,
        use_rerank: bool = True,
    ) -> AnswerResult | None:
        """Run multi-hop decomposition. Returns AnswerResult if decomposition triggered successfully, None otherwise."""
        ctx = self._build_pipeline_context(
            question=question,
            retrieval_query=retrieval_query,
            top_k=top_k,
            history=history,
            trace=trace,
            use_rerank=use_rerank,
        )

        pipeline = Pipeline([DecomposeStep(), AuditStep()])
        result = pipeline.run(ctx)

        if ctx.sub_results:
            # DecomposeStep produced a synthesized answer
            return AnswerResult(
                question=question,
                answer=ctx.answer,
                evidence=ctx.evidence,
                trace=ctx.trace,
                claim_audit=ctx.claim_audit,
                sub_questions=ctx.sub_results,
                diagnostics=ctx.diagnostics,
                question_type="research",
            )
        return None

    def _prepare_research_answer(
        self,
        question: str,
        history: list[ConversationMessage],
        top_k: int,
        *,
        use_rerank: bool,
        self_correct: bool,
    ) -> _ResearchPrep:
        """Shared retrieval path for sync and streaming research answers."""
        ag = self.answer_generator
        trace: list[ToolTrace] = []
        self._last_retrieval_diagnostics = {}
        retrieval_query = ag._build_contextual_query(question, history, trace)

        multi_hop_result = self._run_multi_hop(
            question, retrieval_query, top_k, trace, history, use_rerank=use_rerank
        )
        if multi_hop_result is not None:
            return _ResearchPrep(
                retrieval_query=retrieval_query,
                evidence=[],
                trace=trace,
                retrieval_diagnostics={},
                early_result=multi_hop_result,
            )

        if self_correct and self.llm.enabled:
            from .self_correct import self_correct_retrieval  # fmt: skip

            def _retrieve_for_self_correct(q: str, k: int) -> list[Evidence]:
                return self._retrieve_evidence(q, top_k=k, trace=trace, use_rerank=use_rerank)

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
            raw_evidence = self._retrieve_evidence(
                retrieval_query, top_k=max(top_k * 3, 6), trace=trace, use_rerank=use_rerank
            )

        retrieval_diagnostics = dict(getattr(self, "_last_retrieval_diagnostics", {}) or {})
        evidence = ag._rank_evidence_for_answer(raw_evidence, top_k=top_k, question=question)

        crag_decision = None
        retrieval_confidence = 0.0
        if evidence and self_correct and self.llm.enabled:
            from .self_correct import crag_evaluate, CRAGDecision  # fmt: skip

            crag_decision, retrieval_confidence = crag_evaluate(
                query=retrieval_query,
                evidence=evidence,
                llm_client=self.llm,
                trace=trace,
            )
            if crag_decision == CRAGDecision.DECLINE:
                result = ag._insufficient_evidence_answer(question, trace)
                result.retrieval_confidence = retrieval_confidence
                result.question_type = "research"
                result.diagnostics = retrieval_diagnostics
                return _ResearchPrep(
                    retrieval_query=retrieval_query,
                    evidence=evidence,
                    trace=trace,
                    retrieval_diagnostics=retrieval_diagnostics,
                    crag_decision=crag_decision,
                    retrieval_confidence=retrieval_confidence,
                    early_result=result,
                )

        return _ResearchPrep(
            retrieval_query=retrieval_query,
            evidence=evidence,
            trace=trace,
            retrieval_diagnostics=retrieval_diagnostics,
            crag_decision=crag_decision,
            retrieval_confidence=retrieval_confidence,
        )

    def _finalize_research_answer(
        self,
        question: str,
        prep: _ResearchPrep,
        *,
        top_k: int,
        strict_grounded: bool,
        history: list[ConversationMessage],
        use_rerank: bool,
    ) -> AnswerResult:
        ag = self.answer_generator
        if prep.early_result is not None:
            return prep.early_result

        ctx = self._build_pipeline_context(
            question=question,
            retrieval_query=prep.retrieval_query,
            top_k=top_k,
            strict_grounded=strict_grounded,
            history=history,
            trace=prep.trace,
            use_rerank=use_rerank,
        )
        ctx.diagnostics = prep.retrieval_diagnostics
        ctx.evidence = prep.evidence

        if not prep.evidence:
            if strict_grounded:
                result = ag._insufficient_evidence_answer(question, prep.trace)
            elif self.llm.enabled:
                try:
                    result = self._llm_general_answer(question, prep.trace)
                except Exception as exc:
                    prep.trace.append(ToolTrace(tool="langchain_chat_error", input=question, output=str(exc)))
                    result = AnswerResult(
                        question=question,
                        answer=(
                            "当前本地语料库中没有找到相关证据。"
                            if ag._prefers_chinese(question)
                            else "No relevant evidence was found in the local corpus."
                        ),
                        evidence=[],
                        trace=prep.trace,
                        insufficient_evidence=True,
                    )
            else:
                result = AnswerResult(
                    question=question,
                    answer=(
                        "当前本地语料库中没有找到相关证据。"
                        if ag._prefers_chinese(question)
                        else "No relevant evidence was found in the local corpus."
                    ),
                    evidence=[],
                    trace=prep.trace,
                    insufficient_evidence=True,
                )
            result.diagnostics = ctx.diagnostics
        else:
            Pipeline([GenerateStep(), AuditStep()]).run(ctx)
            if self.llm.enabled and ctx.answer:
                result = AnswerResult(
                    question=question,
                    answer=ctx.answer,
                    evidence=ctx.evidence,
                    trace=ctx.trace,
                    claim_audit=ctx.claim_audit,
                    contradictions=ctx.contradictions,
                )
            else:
                result = ag._rule_based_answer(question, prep.evidence, prep.trace, self.corpus.get_paper)
            result.diagnostics = ctx.diagnostics
            if prep.crag_decision is not None:
                result.retrieval_confidence = prep.retrieval_confidence

        result.question_type = "research"
        return result

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
        use_rerank: bool = True,
    ) -> AnswerResult:
        cache_key = (question, top_k, strict_grounded, self_correct, use_rerank, tuple((msg.role, msg.content) for msg in (history or [])))
        if cache_key in self._query_cache:
            return self._query_cache[cache_key]

        ag = self.answer_generator

        question_type = ag.classify_question(question)
        if question_type == "system":
            result = ag._system_answer(question)
            result.question_type = question_type
        elif question_type == "meta":
            result = ag._meta_answer(question)
        elif question_type == "greeting":
            result = ag._greeting_answer(question)
        else:
            history = list(history or [])
            prep = self._prepare_research_answer(
                question,
                history,
                top_k,
                use_rerank=use_rerank,
                self_correct=self_correct,
            )
            result = self._finalize_research_answer(
                question,
                prep,
                top_k=top_k,
                strict_grounded=strict_grounded,
                history=history,
                use_rerank=use_rerank,
            )

        result.question_type = question_type
        self._query_cache[cache_key] = result
        self._trim_cache()
        return result

    def answer_question_stream(
        self,
        question: str,
        top_k: int = 5,
        strict_grounded: bool = True,
        history: list[ConversationMessage] | None = None,
        self_correct: bool = True,
        use_rerank: bool = True,
    ) -> Iterator[dict]:
        ag = self.answer_generator

        question_type = ag.classify_question(question)
        if question_type != "research":
            if question_type == "system":
                result = ag._system_answer(question)
                result.question_type = question_type
            elif question_type == "meta":
                result = ag._meta_answer(question)
            else:
                result = ag._greeting_answer(question)
            for chunk in ag._iter_text_chunks(result.answer):
                yield {"type": "chunk", "delta": chunk}
            yield {"type": "final", "data": result.model_dump()}
            return

        history = list(history or [])
        yield {"type": "step", "step": "retrieve"}
        prep = self._prepare_research_answer(
            question,
            history,
            top_k,
            use_rerank=use_rerank,
            self_correct=self_correct,
        )
        yield {"type": "step", "step": "decompose"}

        if prep.early_result is not None:
            yield {"type": "step", "step": "generate"}
            for chunk in ag._iter_text_chunks(prep.early_result.answer):
                yield {"type": "chunk", "delta": chunk}
            yield {"type": "final", "data": prep.early_result.model_dump()}
            return

        evidence = prep.evidence
        trace = prep.trace
        ctx = self._build_pipeline_context(
            question=question,
            retrieval_query=prep.retrieval_query,
            top_k=top_k,
            strict_grounded=strict_grounded,
            history=history,
            trace=trace,
            use_rerank=use_rerank,
        )
        ctx.diagnostics = prep.retrieval_diagnostics
        ctx.evidence = evidence

        if not evidence:
            result = self._finalize_research_answer(
                question,
                prep,
                top_k=top_k,
                strict_grounded=strict_grounded,
                history=history,
                use_rerank=use_rerank,
            )
            for chunk in ag._iter_text_chunks(result.answer):
                yield {"type": "chunk", "delta": chunk}
            yield {"type": "final", "data": result.model_dump()}
            return

        yield {"type": "step", "step": "generate"}
        if self.llm.enabled:
            chunks: list[str] = []
            for delta in ag._llm_answer_stream(question, evidence, trace, history=history):
                if not delta:
                    continue
                chunks.append(delta)
                yield {"type": "chunk", "delta": delta}
            streamed_answer = "".join(chunks).strip()
            if streamed_answer:
                embedding = self.llm.embedding_client() if getattr(self.llm, "embedding_enabled", False) else None
                result = ag._with_claim_audit(
                    AnswerResult(question=question, answer=streamed_answer, evidence=evidence, trace=trace),
                    embedding_client=embedding,
                )
                result.diagnostics = ctx.diagnostics
                if prep.crag_decision is not None:
                    result.retrieval_confidence = prep.retrieval_confidence
                yield {"type": "step", "step": "cite"}
                yield {"type": "final", "data": result.model_dump()}
                return

        result = ag._rule_based_answer(question, evidence, trace, self.corpus.get_paper)
        result.diagnostics = ctx.diagnostics
        if prep.crag_decision is not None:
            result.retrieval_confidence = prep.retrieval_confidence
        yield {"type": "step", "step": "cite"}
        for chunk in ag._iter_text_chunks(result.answer):
            yield {"type": "chunk", "delta": chunk}
        yield {"type": "final", "data": result.model_dump()}

    def _trim_cache(self) -> None:
        if len(self._query_cache) > self.QUERY_CACHE_SIZE:
            oldest_key = next(iter(self._query_cache))
            del self._query_cache[oldest_key]

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
