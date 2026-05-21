from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class SourceSegment(BaseModel):
    text: str
    source_url: str = ""
    source_label: str = ""
    page: int | None = None
    locator: str = ""


class Paper(BaseModel):
    paper_id: str
    title: str
    year: int
    venue: str
    authors: list[str]
    source_url: str = ""
    source_label: str = ""
    page: int | None = None
    locator: str = ""
    source_passages: list[SourceSegment] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    summary: str
    methods: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class Passage(BaseModel):
    passage_id: str
    paper_id: str
    title: str
    section: Literal["summary", "methods", "findings", "limitations", "topics"]
    text: str
    source_url: str = ""
    source_label: str = ""
    page: int | None = None
    locator: str = ""


class Evidence(BaseModel):
    paper_id: str
    title: str
    section: str
    text: str
    score: float
    source_url: str = ""
    source_label: str = ""
    page: int | None = None
    locator: str = ""


class ClaimAudit(BaseModel):
    claim_id: str
    claim: str
    status: Literal["supported", "weak", "unsupported", "citation_mismatch"]
    evidence_numbers: list[int] = Field(default_factory=list)
    supporting_quotes: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)
    reason: str = ""
    semantic_score: float = 0.0


class ToolTrace(BaseModel):
    tool: str
    input: str
    output: str


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class SessionSummary(BaseModel):
    session_id: str
    title: str
    turn_count: int
    updated_at: str
    preview: str = ""


class SessionDetail(SessionSummary):
    messages: list[ConversationMessage] = Field(default_factory=list)


class AnswerResult(BaseModel):
    question: str
    answer: str
    evidence: list[Evidence]
    trace: list[ToolTrace]
    claim_audit: list[ClaimAudit] = Field(default_factory=list)
    insufficient_evidence: bool = False
    question_type: str = "research"
    retrieval_confidence: float = 0.0
    contradictions: list[dict] = Field(default_factory=list)
    diagnostics: dict = Field(default_factory=dict)
    sub_questions: list[dict] = Field(default_factory=list)
    session_id: str = ""
    session_title: str = ""
    history: list[ConversationMessage] = Field(default_factory=list)


class ComparisonRow(BaseModel):
    paper_id: str
    title: str
    year: int
    methods: list[str]
    findings: list[str]
    limitations: list[str]


class ComparisonResult(BaseModel):
    focus: str
    narrative: str
    rows: list[ComparisonRow]
    trace: list[ToolTrace]


class ReviewResult(BaseModel):
    topic: str
    overview: str
    trends: list[str]
    representative_papers: list[str]
    reading_order: list[str]
    open_problems: list[str]
    trace: list[ToolTrace]


class EvalCase(BaseModel):
    case_id: str
    question: str
    expected_paper_ids: list[str]
    expected_keywords: list[str] = Field(default_factory=list)
    reference: str = ""
    tags: list[str] = Field(default_factory=list)
    difficulty: str = ""
