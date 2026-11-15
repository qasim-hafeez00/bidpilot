"""Structured hand-offs between agents (C3). Anything a later step decides on is one of these objects."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class JobSpec(BaseModel):
    job_id: str
    title: str
    deliverables: list[str] = Field(default_factory=list)
    required_skills: list[str] = Field(default_factory=list)
    core_skills: list[str] = Field(default_factory=list)
    budget_type: Literal["hourly", "fixed"] = "fixed"
    budget_min: float | None = None
    budget_max: float | None = None
    timeline: str | None = None
    experience_level: str | None = None
    screening_questions: list[str] = Field(default_factory=list)
    hidden_needs: list[str] = Field(default_factory=list)
    domain: str = "other"
    extraction: Literal["rules", "rules+llm"] = "rules"


class RiskReport(BaseModel):
    score: float = Field(ge=0, le=1)
    scam_likelihood: float = Field(ge=0, le=1, default=0.0)
    client_quality: float = Field(ge=0, le=1, default=0.5)
    flags: list[str] = Field(default_factory=list)
    injection_detected: bool = False
    injection_spans: list[str] = Field(default_factory=list)
    explanation: str = ""


class RequirementEvidence(BaseModel):
    requirement: str
    skill: str | None = None
    core: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    project_ids: list[str] = Field(default_factory=list)
    strength: Literal["strong", "partial", "none"] = "none"


class FitReport(BaseModel):
    score: float = Field(ge=0, le=1)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    matrix: list[RequirementEvidence] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class BidDecision(BaseModel):
    action: Literal["bid", "watch", "skip"]
    reasons: list[str] = Field(default_factory=list)
    auto: bool = False


class PriceQuote(BaseModel):
    amount: float = Field(gt=0)
    bid_type: Literal["hourly", "fixed"]
    band: tuple[float, float]
    rationale: str
    connects_cost: int = 0
    connects_usd: float = 0.0
    expected_value_usd: float = 0.0
    connects_worth_it: bool = True


class ProposalDraft(BaseModel):
    job_id: str
    cover_letter: str
    screening_answers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    version: int = 1
    status: str = "pending_review"


class Critique(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    instructions: str = ""
    scores: dict[str, float] = Field(default_factory=dict)


class ComplianceVerdict(BaseModel):
    status: Literal["pass", "fixed", "block"]
    violations: list[dict] = Field(default_factory=list)
    fixed_text: str | None = None
    reason: str = ""


class Approval(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_text: str | None = None
    edited_answers: list[str] | None = None
    reason: str | None = None
    approver: str | None = None


class MessageIntent(BaseModel):
    intent: Literal["question", "negotiation", "interview_request", "scam_signal", "other"]
    confidence: float = Field(ge=0, le=1, default=0.5)
    reason: str = ""


class ReplyDraft(BaseModel):
    thread_id: str
    text: str
    slots: list[dict] = Field(default_factory=list)
    intent: str = "other"
