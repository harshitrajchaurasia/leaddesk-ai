"""Business rules from config/rules.json, validated at startup so a typo fails loudly instead of misrouting tickets."""
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from .models import Category, Queue, Urgency

PATH = Path(__file__).parent.parent / "config" / "rules.json"


class Dispute(BaseModel):
    replacement_window_days: int = Field(gt=0)
    annuity_min_assets: int = Field(ge=0)
    speed_to_lead_minutes: int = Field(gt=0)


class TimeSaved(BaseModel):
    manual_minutes_per_ticket: float = Field(gt=0)
    review_minutes_per_ticket: float = Field(ge=0)


class Rules(BaseModel):
    model_config = ConfigDict(extra="ignore")  # "_note" keys are comments for whoever edits the file
    confidence_min: float = Field(ge=0, le=1)
    churn_min: float = Field(ge=0, le=1)
    category_queue: dict[Category, Queue]
    queue_owners: dict[Queue, str]
    sla_minutes: dict[Urgency, int]
    dispute: Dispute
    time_saved: TimeSaved


def load(path: Path = PATH) -> Rules:
    rules = Rules.model_validate_json(path.read_text())
    missing = {"billing", "campaign_change", "appointments", "tech_access", "other"} - set(rules.category_queue)
    if missing:
        raise ValueError(f"config/rules.json: category_queue is missing {sorted(missing)}")
    if missing := {"urgent", "high", "normal", "low"} - set(rules.sla_minutes):
        raise ValueError(f"config/rules.json: sla_minutes is missing {sorted(missing)}")
    return rules


RULES = load()
