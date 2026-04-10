from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Paper(BaseModel):
    paper_id: str
    title: str
    year: int
    venue: str
    authors: list[str]
    source_url: str
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


class Evidence(BaseModel):
    paper_id: str
    title: str
    section: str
    text: str
    score: float


class ToolTrace(BaseModel):
    tool: str
    input: str
    output: str


class AnswerResult(BaseModel):
    question: str
    answer: str
    evidence: list[Evidence]
    trace: list[ToolTrace]


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
