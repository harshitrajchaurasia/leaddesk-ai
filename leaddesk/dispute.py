"""Lead Dispute Check: decides replacements in code, never in the LLM."""
import re
from datetime import datetime, timedelta

from .models import Client, DisputeVerdict, Lead

REPLACEMENT_WINDOW_DAYS = 7
ANNUITY_MIN_ASSETS = 100_000
SPEED_TO_LEAD_MINUTES = 60


def _valid_us_phone(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return len(digits) == 10


def check_lead(lead: Lead | None, client: Client, complaint_at: datetime) -> DisputeVerdict:
    if lead is None:
        return DisputeVerdict(verdict="NEEDS_REVIEW", reasons=["lead not found"])

    reasons = []
    if lead.consent_ts is None:
        reasons.append("missing consent record")
    if lead.delivered_to_count > 1:
        reasons.append(f"exclusivity breach: delivered to {lead.delivered_to_count} agents")
    if not _valid_us_phone(lead.phone):
        reasons.append("invalid phone")
    if lead.vertical != client.vertical:
        reasons.append("wrong vertical")
    if lead.state not in client.states:
        reasons.append("outside licensed states")
    if lead.vertical == "annuity" and (lead.investable_assets or 0) < ANNUITY_MIN_ASSETS:
        reasons.append("below annuity asset minimum")

    if reasons:
        if complaint_at - lead.created_at > timedelta(days=REPLACEMENT_WINDOW_DAYS):
            return DisputeVerdict(verdict="NEEDS_REVIEW",
                                  reasons=reasons + [f"outside {REPLACEMENT_WINDOW_DAYS}-day replacement window"])
        return DisputeVerdict(verdict="REPLACE", reasons=reasons)

    if lead.first_contact_at is None:
        return DisputeVerdict(verdict="VALID_COACH", reasons=["never contacted"])
    minutes = int((lead.first_contact_at - lead.created_at).total_seconds() // 60)
    if minutes > SPEED_TO_LEAD_MINUTES:
        return DisputeVerdict(verdict="VALID_COACH", reasons=[f"first contact after {minutes} min"])
    return DisputeVerdict(verdict="VALID_COACH", reasons=["lead passes all checks"])
