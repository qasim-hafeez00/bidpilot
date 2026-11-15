"""Typed request/response models (the TypeScript client in apps/web/src/lib/api is generated from these via OpenAPI)."""
from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

EmailStr = Annotated[str, Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)]


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class SavedSearch(BaseModel):
    query: str = Field(min_length=2, max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=10)
    limit: int = Field(20, ge=1, le=50)


class Settings(BaseModel):
    hourly_floor: float = Field(ge=0, le=1000)
    min_fixed: float = Field(ge=0, le=100000)
    weekly_connects_budget: int = Field(ge=0, le=2000)
    autonomy: Literal["suggest", "auto_skip_low_fit"] = "suggest"
    saved_searches: list[SavedSearch] = Field(default_factory=list, max_length=20)
    marketplace_mode: Literal["gigsim", "upwork_live"] = "gigsim"


class OnboardingIn(Settings):
    persona: Literal["ai_ml", "fullstack", "data_analyst", "own"]
    gigsim_token: str | None = Field(None, max_length=200)


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str | None
    persona: str
    role: str
    onboarding_done: bool
    settings: Settings | None = None


class AuthOut(BaseModel):
    token: str
    user: UserOut


class JobRow(BaseModel):
    job_id: str
    title: str | None
    status: str
    fit: float | None
    risk: float | None
    decision: str | None
    price: dict[str, Any] | None
    connects_cost: int | None
    risk_flags: list[str] | None
    category: str | None
    dup_of: str | None
    updated_at: str | None


class JobDetail(BaseModel):
    job_id: str
    status: str
    job: dict[str, Any]
    job_spec: dict[str, Any] | None
    risk_report: dict[str, Any] | None
    fit_report: dict[str, Any] | None
    evidence: list[dict[str, Any]]
    decision: dict[str, Any] | None
    price_quote: dict[str, Any] | None
    attention_reason: str | None
    trace_id: str | None
    trace_url: str | None
    runs: list[dict[str, Any]]


class ApprovalIn(BaseModel):
    action: Literal["approve", "edit", "reject"]
    edited_text: str | None = Field(None, max_length=6000)
    edited_answers: list[str] | None = None
    reason: str | None = Field(None, max_length=500)


class ProposalOut(BaseModel):
    job_id: str
    status: str
    pending: dict[str, Any] | None
    drafts: list[dict[str, Any]]
    critiques: list[dict[str, Any]]
    verification: dict[str, Any] | None
    compliance: dict[str, Any] | None
    submission: dict[str, Any] | None
    attention_reason: str | None


class RegenerateIn(BaseModel):
    paragraph: str = Field(min_length=10, max_length=3000)
    instruction: str | None = Field(None, max_length=300)


class RunRef(BaseModel):
    run_id: str
    status: str = "queued"


class ConversationRow(BaseModel):
    thread_id: str
    title: str | None
    status: str | None
    intent: str | None
    proposal_id: str | None
    last_message_at: str | None


class ThreadOut(BaseModel):
    thread_id: str
    messages: list[dict[str, Any]]
    pending: dict[str, Any] | None
    status: str | None


class MemoryItem(BaseModel):
    namespace: str
    key: str
    rule: str | None = None
    insight: str | None = None
    support: str | None = None
    promoted_at: float | None = None


class Health(BaseModel):
    api: str
    marketplace: Literal["up", "down", "unknown"]
    details: dict[str, Any]
    queued_degraded: int
