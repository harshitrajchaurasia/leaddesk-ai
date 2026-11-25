from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Vertical = Literal["annuity", "iul", "life", "final_expense", "retirement_planning", "debt_relief"]
Category = Literal["lead_quality", "billing", "campaign_change", "appointments", "tech_access", "cancellation", "other"]
Urgency = Literal["low", "normal", "high", "urgent"]
Queue = Literal["lead_ops", "account_manager", "billing", "campaign_ops", "support", "human_review"]


class Client(BaseModel):
    id: str
    name: str
    vertical: Vertical
    states: list[str]
    plan: str
    account_manager: str


class Lead(BaseModel):
    id: str
    client_id: str
    full_name: str
    phone: str
    email: str
    vertical: Vertical
    state: str
    age: int
    investable_assets: int | None = None
    consent_ts: datetime | None = None
    delivered_to_count: int = 1
    created_at: datetime
    first_contact_at: datetime | None = None
    source: str = "Meta Lead Form"


class Ticket(BaseModel):
    id: str
    client_id: str
    channel: Literal["email", "form", "webhook"] = "form"
    subject: str
    body: str = Field(min_length=1)
    received_at: datetime


class LabeledTicket(Ticket):
    expected_category: Category
    expected_queue: Queue


class Triage(BaseModel):
    category: Category
    urgency: Urgency
    sentiment: Literal["positive", "neutral", "frustrated", "angry"]
    churn_risk: float = Field(ge=0, le=1, description="0-1 likelihood the client cancels")
    lead_id: str | None = Field(default=None, description="Lead id like L-1042 if the ticket names one")
    summary: str = Field(description="One line, max 25 words")
    confidence: float = Field(ge=0, le=1, description="0-1 confidence in the category")


class DisputeVerdict(BaseModel):
    verdict: Literal["REPLACE", "VALID_COACH", "NEEDS_REVIEW"]
    reasons: list[str]


class Route(BaseModel):
    queue: Queue
    priority: Urgency
    assignee: str | None = None
    reasons: list[str] = []


class Result(BaseModel):
    ticket: Ticket
    triage: Triage
    verdict: DisputeVerdict | None = None
    route: Route
    draft_reply: str
    provider: str
    latency_ms: int
    monday_item_id: str | None = None
    status: Literal["pending_approval", "approved", "edited"] = "pending_approval"
    final_reply: str | None = None
