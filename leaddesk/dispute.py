"""Lead Dispute Check: decides replacements in code, never in the LLM."""
import re
from datetime import datetime, timedelta

from .config import RULES
from .models import Client, DisputeVerdict, Lead

REPLACEMENT_WINDOW_DAYS = RULES.dispute.replacement_window_days  # values live in config/rules.json
ANNUITY_MIN_ASSETS = RULES.dispute.annuity_min_assets
SPEED_TO_LEAD_MINUTES = RULES.dispute.speed_to_lead_minutes


def _valid_us_phone(phone: str) -> bool:
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return len(digits) == 10


def check_leads(leads: dict[str, Lead | None], client: Client, complaint_at: datetime) -> DisputeVerdict:
    """Several leads in one ticket: check each, then one verdict. REPLACE only if every lead fails a rule,
    VALID_COACH only if every lead is valid; anything mixed goes to a person. Reasons name the lead."""
    if len(leads) <= 1:
        return check_lead(next(iter(leads.values()), None), client, complaint_at)
    each = {lid: check_lead(lead, client, complaint_at) for lid, lead in leads.items()}
    kinds = {v.verdict for v in each.values()}
    verdict = kinds.pop() if len(kinds) == 1 else "NEEDS_REVIEW"
    return DisputeVerdict(verdict=verdict, reasons=[f"{lid}: {'; '.join(v.reasons)}" for lid, v in each.items()])


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
    # Record is clean and the agent called fast, so coaching would be wrong: the complaint is about something the record
    # can't show (fax line, fake answer, wrong person). A human checks it, e.g. against the call recording.
    return DisputeVerdict(verdict="NEEDS_REVIEW", reasons=[f"lead passes all record checks and first contact was after {minutes} min: verify the complaint"])
