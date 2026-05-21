from __future__ import annotations

from collections.abc import Iterator
import re

from .models import AnswerResult, ClaimAudit, ConversationMessage, Evidence, ToolTrace


SECTION_PRIORITY = {
    "summary": 0,
    "methods": 1,
    "findings": 2,
    "limitations": 3,
    "topics": 4,
}
CLAIM_SENTENCE_PATTERN = re.compile(
    r"[^.!?;,，\u3002\uff01\uff1f\uff1b\uff0c\n]+"
    r"(?:[.!?;,，\u3002\uff01\uff1f\uff1b\uff0c]+(?:\s*\[\d+\])*)?"
)
CITATION_PATTERN = re.compile(r"\[(\d+)\]")
ONLY_CITATIONS_PATTERN = re.compile(r"^(?:\[\d+\]\s*)+$")
ENGLISH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
CJK_SEQUENCE_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
INSUFFICIENT_EVIDENCE_MARKERS = {
    "no relevant evidence",
    "insufficient evidence",
    "not enough evidence",
    "can't answer this reliably",
    "cannot answer this reliably",
    "\u6ca1\u6709\u627e\u5230",
    "\u8bc1\u636e\u4e0d\u8db3",
    "\u4e0d\u80fd\u53ef\u9760",
}
ENGLISH_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "based",
    "be",
    "been",
    "being",
    "by",
    "can",
    "claim",
    "claims",
    "detail",
    "does",
    "evidence",
    "for",
    "from",
    "has",
    "have",
    "how",
    "in",
    "indicate",
    "indicates",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "paper",
    "papers",
    "result",
    "results",
    "show",
    "shows",
    "study",
    "support",
    "supporting",
    "that",
    "the",
    "their",
    "these",
    "this",
    "those",
    "to",
    "use",
    "used",
    "uses",
    "using",
    "via",
    "was",
    "were",
    "what",
    "which",
    "with",
}
CJK_STOP_CHARS = set("\u7684\u4e86\u548c\u4e0e\u53ca\u5728\u662f\u5bf9\u4e2d\u8fd9\u90a3\u6709\u7528\u4e3a\u4ee5\u4e2a\u7b49\u4e5f\u5e76\u88ab\u5c06\u4ece\u6216\u800c\u5176")
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
        return AnswerGenerator.classify_question(question) == "system"

    @staticmethod
    def classify_question(question: str) -> str:
        normalized = question.strip().lower()
        system_keywords = [
            "你是什么模型",
            "你用的什么模型",
            "你是什么",
            "what model are you",
            "which model",
            "who are you",
            "what are you",
        ]
        if any(keyword in normalized for keyword in system_keywords):
            return "system"
        meta_keywords = [
            "what can you do",
            "help",
            "怎么用",
            "how to use",
            "功能",
            "capabilities",
            "使用方法",
            "how does this work",
            "what is this",
        ]
        if any(keyword in normalized for keyword in meta_keywords):
            return "meta"
        greeting_keywords = [
            "hello",
            "hi",
            "hey",
            "thanks",
            "thank you",
            "你好",
            "谢谢",
            "再见",
            "bye",
            "good morning",
            "good evening",
        ]
        if re.search(r"\bhi\b", normalized) or any(
            keyword in normalized for keyword in greeting_keywords if keyword != "hi"
        ):
            return "greeting"
        return "research"

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
    def _quote_preview(value: str, limit: int = 220) -> str:
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
    def _looks_like_definition_question(question: str) -> bool:
        normalized = question.strip().lower()
        return any(
            marker in normalized
            for marker in (
                "什么是",
                "是什么",
                "是啥",
                "干嘛",
                "做什么",
                "怎么理解",
                "介绍",
                "解释",
                "含义",
                "全称",
                "缩写",
                "what is",
                "what are",
                "what's",
                "define",
                "definition",
                "introduce",
                "explain",
                "tell me about",
                "stands for",
                "meaning",
            )
        )

    @staticmethod
    def _definition_bonus(question: str, item: Evidence) -> float:
        if not AnswerGenerator._looks_like_definition_question(question):
            return 0.0
        text = f"{item.title} {item.text}".lower()
        bonus = 0.0
        if item.page in (None, 1):
            bonus += 0.16
        if any(marker in text for marker in ("abstract", "we call", "referred to as", "specifically", "we refer to")):
            bonus += 0.22
        if "(" in item.text and ")" in item.text:
            bonus += 0.08
        query_tokens = set(re.findall(r"[a-z0-9]{2,}", question.lower()))
        if query_tokens and query_tokens & set(re.findall(r"[a-z0-9]{2,}", item.title.lower())):
            bonus += 0.08
        return bonus

    @staticmethod
    def _rank_evidence_for_answer(
        evidence: list[Evidence],
        top_k: int,
        max_papers: int = 3,
        question: str = "",
    ) -> list[Evidence]:
        ranked = sorted(
            evidence,
            key=lambda item: (
                -(item.score + AnswerGenerator._definition_bonus(question, item) - 0.02 * SECTION_PRIORITY.get(item.section, 5)),
                item.paper_id,
            ),
        )
        selected: list[Evidence] = []
        seen_pairs: set[tuple] = set()
        paper_order: list[str] = []
        for item in ranked:
            if item.paper_id not in paper_order and len(paper_order) >= max_papers:
                continue
            # 对于来自同一文档不同页的片段（section 相同但 locator 不同），
            # 用 (paper_id, section, locator) 作为去重 key，避免多页 PDF 只展示 1 条。
            locator_key = item.locator or item.text[:40]
            key: tuple = (item.paper_id, item.section, locator_key)
            if key in seen_pairs:
                continue
            selected.append(item)
            seen_pairs.add(key)
            if item.paper_id not in paper_order:
                paper_order.append(item.paper_id)
            if len(selected) >= top_k:
                break
        return selected

    @staticmethod
    def _claim_parts(answer: str) -> list[str]:
        parts: list[str] = []
        for match in CLAIM_SENTENCE_PATTERN.finditer(answer):
            claim = " ".join(match.group(0).split())
            if not claim or ONLY_CITATIONS_PATTERN.fullmatch(claim):
                continue
            parts.append(claim)
        return parts

    @staticmethod
    def _tokenize_for_audit(value: str) -> set[str]:
        normalized = value.lower()
        tokens = {
            token
            for token in ENGLISH_TOKEN_PATTERN.findall(normalized)
            if len(token) >= 3 and token not in ENGLISH_STOPWORDS and not token.isdigit()
        }
        for sequence in CJK_SEQUENCE_PATTERN.findall(normalized):
            cleaned = "".join(char for char in sequence if char not in CJK_STOP_CHARS)
            if len(cleaned) == 1:
                tokens.add(cleaned)
                continue
            for size in (2, 3):
                if len(cleaned) < size:
                    continue
                tokens.update(cleaned[index : index + size] for index in range(0, len(cleaned) - size + 1))
        return tokens

    @classmethod
    def _text_overlap(cls, claim: str, evidence: Evidence) -> tuple[list[str], float]:
        claim_terms = cls._tokenize_for_audit(CITATION_PATTERN.sub("", claim))
        if not claim_terms:
            return [], 0.0
        evidence_terms = cls._tokenize_for_audit(f"{evidence.title} {evidence.section} {evidence.text}")
        matched = sorted(claim_terms & evidence_terms)
        return matched, len(matched) / max(len(claim_terms), 1)

    @staticmethod
    def _semantic_overlap(claim_texts: list[str], evidence_texts: list[str], embedding_client) -> list[list[float]]:
        """Batch compute cosine similarity between claims and evidence texts.

        Returns a len(claims) x len(evidence) matrix of similarity scores.
        """
        import math

        if not claim_texts or not evidence_texts:
            return []

        all_texts = claim_texts + evidence_texts
        all_vectors = embedding_client.embed_documents(all_texts)

        claim_vectors = all_vectors[:len(claim_texts)]
        evidence_vectors = all_vectors[len(claim_texts):]

        def cosine_sim(a: list[float], b: list[float]) -> float:
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a))
            norm_b = math.sqrt(sum(x * x for x in b))
            if norm_a == 0 or norm_b == 0:
                return 0.0
            return dot / (norm_a * norm_b)

        matrix: list[list[float]] = []
        for cv in claim_vectors:
            row = [cosine_sim(cv, ev) for ev in evidence_vectors]
            matrix.append(row)
        return matrix

    @staticmethod
    def _is_insufficient_evidence_answer(answer: str) -> bool:
        normalized = answer.lower()
        return any(marker in normalized for marker in INSUFFICIENT_EVIDENCE_MARKERS)

    @classmethod
    def audit_claims(cls, answer: str, evidence: list[Evidence], embedding_client=None) -> list[ClaimAudit]:
        if not answer.strip() or cls._is_insufficient_evidence_answer(answer):
            return []

        # Pre-compute semantic similarity matrix if embeddings available
        claim_list = cls._claim_parts(answer)
        semantic_matrix: list[list[float]] = []
        if embedding_client and claim_list and evidence:
            try:
                claim_texts_clean = [CITATION_PATTERN.sub("", c).strip() for c in claim_list]
                evidence_texts = [f"{e.title} {e.section} {e.text}" for e in evidence]
                semantic_matrix = cls._semantic_overlap(claim_texts_clean, evidence_texts, embedding_client)
            except Exception:
                semantic_matrix = []

        audits: list[ClaimAudit] = []
        for index, claim in enumerate(claim_list, start=1):
            cited_numbers = [int(value) for value in CITATION_PATTERN.findall(claim)]
            if not cited_numbers:
                audits.append(
                    ClaimAudit(
                        claim_id=f"c{index}",
                        claim=claim,
                        status="unsupported",
                        reason="No citation was found for this factual claim.",
                    )
                )
                continue

            valid_numbers = [number for number in cited_numbers if 1 <= number <= len(evidence)]
            invalid_numbers = [number for number in cited_numbers if number not in valid_numbers]
            if invalid_numbers:
                audits.append(
                    ClaimAudit(
                        claim_id=f"c{index}",
                        claim=claim,
                        status="citation_mismatch",
                        evidence_numbers=cited_numbers,
                        reason=f"Citation(s) {invalid_numbers} do not point to returned evidence.",
                    )
                )
                continue

            matched_terms: set[str] = set()
            supporting_quotes: list[str] = []
            best_overlap = 0.0
            for number in valid_numbers:
                item = evidence[number - 1]
                item_matches, overlap = cls._text_overlap(claim, item)
                matched_terms.update(item_matches)
                best_overlap = max(best_overlap, overlap)
                if item_matches or item.text:
                    supporting_quotes.append(cls._quote_preview(item.text))

            # Semantic score from pre-computed matrix
            semantic_score = 0.0
            if semantic_matrix and (index - 1) < len(semantic_matrix):
                for number in valid_numbers:
                    if (number - 1) < len(semantic_matrix[index - 1]):
                        semantic_score = max(semantic_score, semantic_matrix[index - 1][number - 1])
            semantic_score = round(semantic_score, 4)

            # Use max of lexical and semantic for final decision
            effective_overlap = max(best_overlap, semantic_score)

            if effective_overlap >= 0.18 or len(matched_terms) >= 2:
                status = "supported"
                if semantic_score > best_overlap and semantic_score >= 0.18:
                    reason = "Citation supported by semantic similarity with cited evidence."
                else:
                    reason = "Citation points to evidence with overlapping claim terms."
            else:
                status = "weak"
                reason = "Citation exists, but lexical overlap with the cited evidence is weak."

            audits.append(
                ClaimAudit(
                    claim_id=f"c{index}",
                    claim=claim,
                    status=status,
                    evidence_numbers=valid_numbers,
                    supporting_quotes=supporting_quotes[:3],
                    matched_terms=sorted(matched_terms)[:12],
                    reason=reason,
                    semantic_score=semantic_score,
                )
            )
        return audits

    @classmethod
    def _with_claim_audit(cls, result: AnswerResult, embedding_client=None) -> AnswerResult:
        if not result.claim_audit:
            result.claim_audit = cls.audit_claims(result.answer, result.evidence, embedding_client=embedding_client)
        return result

    # ------------------------------------------------------------------
    # helper: build prompts for LLM calls
    # ------------------------------------------------------------------

    def _build_history_block(self, history: list[ConversationMessage] | list[dict], limit: int = 4) -> str:
        if not history:
            return ""
        recent_history = history[-limit:]
        lines: list[str] = []
        for item in recent_history:
            if isinstance(item, dict):
                role = str(item.get("role") or "user")
                content = str(item.get("content") or "")
            else:
                role = item.role
                content = item.content
            lines.append(f"{role.title()}: {self._compact_text(content, limit=220)}")
        return "\n".join(lines)

    @staticmethod
    def _format_source_info(item: Evidence) -> str:
        parts: list[str] = []
        if item.source_label:
            parts.append(f"source={item.source_label}")
        if item.page is not None:
            parts.append(f"page={item.page}")
        if item.locator and item.locator != f"page {item.page}":
            parts.append(f"locator={item.locator}")
        return " ".join(parts)

    def _build_evidence_context(self, evidence: list[Evidence]) -> str:
        lines = []
        for index, item in enumerate(evidence, start=1):
            source_info = self._format_source_info(item)
            source_suffix = f" {source_info}" if source_info else ""
            quote_preview = self._quote_preview(item.text)
            lines.append(
                f"[{index}] paper_id={item.paper_id} title={item.title} section={item.section} score={item.score}{source_suffix}\n"
                f"Quote preview: {quote_preview}\n"
                f"Full evidence: {item.text}"
            )
        return "\n\n".join(lines)

    def _build_answer_prompts(self, question: str, evidence: list[Evidence], history: list[ConversationMessage] | None = None) -> tuple[str, str]:
        context = self._build_evidence_context(evidence)
        history_block = self._build_history_block(history or [])
        system_prompt = (
            "You are a research assistant. Answer only from the provided evidence. "
            "Be concise and accurate. Reply in the same language as the user's question. "
            "Use the quote previews and full evidence as grounding. "
            "Every factual claim must include bracket citations like [1] or [2]. "
            "Do not cite evidence that does not directly support the claim. "
            "If the evidence is weak, say so explicitly with a citation."
        )
        if history_block:
            user_prompt = (
                f"Conversation history:\n{history_block}\n\n"
                f"Question:\n{question}\n\n"
                f"Evidence:\n{context}\n\n"
                "Answer the latest question using the evidence above. Lead with the evidence-backed answer, "
                "and keep each factual sentence citation-grounded. Use the history only to resolve references in the latest question."
            )
        else:
            user_prompt = (
                f"Question:\n{question}\n\n"
                f"Evidence:\n{context}\n\n"
                "Write a short answer grounded in the evidence above. Lead with cited evidence and cite every factual sentence."
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
            trace = [
                ToolTrace(
                    tool="system_info",
                    input=question,
                    output=(
                        f"provider=openai_compatible, model={self.llm.model}, base_url={self.llm.base_url}, "
                        f"retrieval=tfidf+bm25+vector, embedding={self.llm.embedding_model}, rerank={self.llm.rerank_model}"
                    ),
                )
            ]
            system_prompt = (
                "You are a model connectivity probe for a local research assistant. "
                "Reply in the same language as the user. Be brief. "
                "State that this response was produced by the configured chat API, "
                "and include the configured model name exactly as provided."
            )
            user_prompt = (
                f"User asked: {question}\n"
                f"Configured chat model: {self.llm.model}\n"
                f"Configured base URL: {self.llm.base_url}\n"
                "Confirm which configured model is answering right now."
            )
            try:
                llm_response = self.llm.complete(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.0)
                trace.append(
                    ToolTrace(
                        tool="chat_api_probe",
                        input=question,
                        output=f"provider={llm_response.provider}, model={llm_response.model}",
                    )
                )
                answer = llm_response.text or (
                    f"这次回复已通过当前配置的 chat API 生成，配置模型是 {self.llm.model}。"
                    if self._prefers_chinese(question)
                    else f"This reply was generated through the configured chat API. The configured model is {self.llm.model}."
                )
            except Exception as exc:
                trace.append(ToolTrace(tool="chat_api_probe_error", input=question, output=str(exc)))
                answer = (
                    f"我尝试调用当前配置的 chat API（模型：{self.llm.model}，Base URL：{self.llm.base_url}），但调用失败了：{exc}。"
                    if self._prefers_chinese(question)
                    else f"I tried to call the configured chat API (model: {self.llm.model}, base URL: {self.llm.base_url}), but the call failed: {exc}."
                )
            return AnswerResult(question=question, answer=answer, evidence=[], trace=trace, question_type="system")

        answer = (
            "当前没有配置 API Key，所以这条回复来自本地规则模式；检索仍使用 TF-IDF + BM25 + 查询扩展。"
            if self._prefers_chinese(question)
            else "No API key is configured, so this reply is from local rule-based mode; retrieval still uses TF-IDF + BM25 + query expansion."
        )
        trace = [
            ToolTrace(
                tool="system_info",
                input=question,
                output="provider=local, model=rule-based, retrieval=tfidf+bm25+query-expansion, vector=disabled, rerank=disabled",
            )
        ]
        return AnswerResult(question=question, answer=answer, evidence=[], trace=trace, question_type="system")

    def _meta_answer(self, question: str) -> AnswerResult:
        prefers_chinese = self._prefers_chinese(question)
        if prefers_chinese:
            answer = (
                "我是一个本地论文检索问答助手。你可以：\n"
                "• 提问关于已导入论文的问题（Ask 模式）\n"
                "• 上传 PDF/DOCX/TXT 文档扩充知识库\n"
                "• 对比多篇论文（Compare 模式）\n"
                "• 生成文献综述（Review 模式）\n"
                "• 用 RAG Lab 评测检索质量"
            )
        else:
            answer = (
                "I'm a local research paper Q&A assistant. You can:\n"
                "• Ask questions about imported papers (Ask mode)\n"
                "• Upload PDF/DOCX/TXT documents to expand the knowledge base\n"
                "• Compare multiple papers (Compare mode)\n"
                "• Generate literature reviews (Review mode)\n"
                "• Evaluate retrieval quality with RAG Lab"
            )
        trace = [ToolTrace(tool="meta_answer", input=question, output="capabilities_overview")]
        return AnswerResult(question=question, answer=answer, evidence=[], trace=trace, question_type="meta")

    def _greeting_answer(self, question: str) -> AnswerResult:
        prefers_chinese = self._prefers_chinese(question)
        if prefers_chinese:
            answer = "你好！有什么论文相关的问题我可以帮你解答吗？"
        else:
            answer = "Hello! What research questions can I help you with?"
        trace = [ToolTrace(tool="greeting_answer", input=question, output="greeting_response")]
        return AnswerResult(question=question, answer=answer, evidence=[], trace=trace, question_type="greeting")

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
                    sentence = f"{paper.title}（{paper.year}）表明：{primary} {primary_citation} 补充证据：{support} {support_citation}"
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
                lines.append(f"{paper.title}（{paper.year}）是当前语料库中与问题最接近的论文，但目前只找到了主题级证据。")
            else:
                lines.append(f"{paper.title} ({paper.year}) is the closest match in the local corpus, but only topic-level evidence was found.")

        if lines:
            answer = " ".join(lines)
        elif prefers_chinese:
            answer = "当前本地语料库中没有找到相关证据。"
        else:
            answer = "No relevant evidence was found in the local corpus."
        from .contradiction import detect_contradictions  # fmt: skip

        contradictions = detect_contradictions(evidence, self.llm, trace)
        embedding = self.llm.embedding_client() if getattr(self.llm, "embedding_enabled", False) else None
        return self._with_claim_audit(
            AnswerResult(
                question=question,
                answer=answer,
                evidence=evidence,
                trace=trace,
                contradictions=contradictions,
            ),
            embedding_client=embedding,
        )

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
            answer="当前本地语料库中没有找到足够证据，因此我还不能可靠地回答这个问题。" if self._prefers_chinese(question) else "No relevant evidence was found in the local corpus, so I can't answer this reliably.",
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
        from .contradiction import detect_contradictions  # fmt: skip

        contradictions = detect_contradictions(evidence, self.llm, trace)
        embedding = self.llm.embedding_client() if getattr(self.llm, "embedding_enabled", False) else None
        return self._with_claim_audit(
            AnswerResult(
                question=question,
                answer=llm_response.text,
                evidence=evidence,
                trace=trace,
                contradictions=contradictions,
            ),
            embedding_client=embedding,
        )

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
            "You are a helpful assistant for a local daidainiao-agent application. "
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
        return self._with_claim_audit(AnswerResult(question=question, answer=llm_response.text, evidence=[], trace=trace))
