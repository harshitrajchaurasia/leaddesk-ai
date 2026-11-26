import re
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, computed_field, field_validator, model_validator

Vertical = Literal["annuity", "iul", "life", "final_expense", "retirement_planning", "debt_relief"]
MAX_LEADS_PER_TICKET = 20  # more than this in one ticket -> NEEDS_REVIEW, never a bulk REPLACE


def normalise_lead_id(v: str | None) -> str | None:
    """'l105', 'L 105', 'lead #105' -> 'L-105' so the lookup matches; anything else passes through."""
    m = re.fullmatch(r"\s*(?:lead\s*#?|L)\s*-?\s*#?\s*(\d+)\s*", v or "", re.I)
    return f"L-{m.group(1)}" if m else (v or None)


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
    ghl_contact_id: str | None = None  # set when the ticket came from Go High Level; the reply goes back there

    @field_validator("received_at")
    @classmethod
    def _naive_utc(cls, v: datetime) -> datetime:
        """Lead records are naive UTC; an aware timestamp ("...Z") would break the dispute-window maths."""
        return v.astimezone(timezone.utc).replace(tzinfo=None) if v.tzinfo else v


class LabeledTicket(Ticket):
    expected_category: Category | list[Category]  # a list when more than one reading is defensible
    expected_queue: Queue
    expected_lead_id: str | None = None  # only read when present in the JSON; else taken from the body
    expected_lead_ids: list[str] | None = None  # multi-lead tickets: the full set, ranges expanded


class Triage(BaseModel):
    category: Category
    urgency: Urgency
    sentiment: Literal["positive", "neutral", "frustrated", "angry"]
    churn_risk: float = Field(ge=0, le=1, description="0-1 likelihood the client cancels")
    lead_id: str | None = Field(description="Lead id like L-1042 if the ticket names one, else null")  # required: models skip optional fields
    lead_ids: list[str] = Field(description="Every lead id the ticket names, ranges expanded (L-201 to L-203 -> L-201, L-202, L-203); [] if none")
    summary: str = Field(description="One line, max 25 words")
    confidence: float = Field(ge=0, le=1, description="0-1 confidence in the category")

    @field_validator("lead_id")
    @classmethod
    def _normalise_lead_id(cls, v: str | None) -> str | None:
        """'l105', 'L 105', 'lead #105' -> 'L-105' so the lookup matches; anything else passes through."""
        return normalise_lead_id(v)

    @model_validator(mode="before")
    @classmethod
    def _old_rows(cls, data):
        """Rows saved before lead_ids existed still load (the field stays required in the schema the LLM sees)."""
        if isinstance(data, dict) and "lead_ids" not in data:
            data = {**data, "lead_ids": []}
        return data

    @model_validator(mode="after")
    def _ids(self):
        """Normalise + dedupe lead_ids and keep lead_id in it. No silent cap: the dispute check sends long lists to a person."""
        ids = [normalise_lead_id(x) for x in ([self.lead_id] if self.lead_id else []) + self.lead_ids]
        self.lead_ids = list(dict.fromkeys(i for i in ids if i))
        self.lead_id = self.lead_ids[0] if self.lead_ids else None
        return self


class DisputeVerdict(BaseModel):
    verdict: Literal["REPLACE", "VALID_COACH", "NEEDS_REVIEW"]
    reasons: list[str]


class Route(BaseModel):
    queue: Queue
    priority: Urgency
    assignee: str | None = None
    reasons: list[str] = []
    sla_minutes: int | None = None  # from config/rules.json by priority


class MLOpinion(BaseModel):
    """The local classifier's category next to the LLM's (free, ~1 ms, no API)."""
    category: Category
    confidence: float


class Result(BaseModel):
    ticket: Ticket
    triage: Triage
    ml: MLOpinion | None = None
    verdict: DisputeVerdict | None = None
    route: Route
    draft_reply: str
    provider: str
    latency_ms: int
    monday_item_id: str | None = None
    status: Literal["pending_approval", "approved", "edited"] = "pending_approval"
    ghl_message_id: str | None = None  # set once the approved reply went out through GHL
    send_error: str | None = None
    created_at: datetime | None = None  # naive UTC; None on rows saved before this field existed
    approved_at: datetime | None = None

    @computed_field
    @property
    def due_at(self) -> datetime | None:
        """When a reply is due under the SLA; the UI flags pending tickets past it."""
        if self.created_at is None or self.route.sla_minutes is None:
            return None
        return self.created_at + timedelta(minutes=self.route.sla_minutes)
    final_reply: str | None = None


class ActionItem(BaseModel):
    owner: Literal["us", "client"] = Field(description="us = Acme Leads staff, client = the agent")
    task: str
    due: str | None = Field(description="Due date or timeframe if one was said, else null")


class CallInsight(BaseModel):
    summary: str = Field(description="2-3 neutral sentences; people by role, not name")
    sentiment: Literal["positive", "neutral", "frustrated", "angry"]
    churn_risk: float = Field(ge=0, le=1, description="0-1 likelihood the client cancels soon")
    upsell_signals: list[str] = Field(description="Concrete signs they would buy more (states, volume, products); empty if none")
    objections: list[str] = Field(description="Complaints or concerns they raised; empty if none")
    action_items: list[ActionItem]


class CallResult(BaseModel):
    id: str
    client_id: str
    transcript: str  # PII-masked
    insight: CallInsight
    alerts: list[str]  # decided in code from the insight
    provider: str
    latency_ms: int
    monday_item_id: str | None = None
