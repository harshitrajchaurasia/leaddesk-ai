import pytest
from conftest import make_triage

from leaddesk.models import DisputeVerdict
from leaddesk.pii import mask
from leaddesk.routing import route


def test_low_confidence_wins_over_everything(annuity_client):
    r = route(make_triage(category="cancellation", confidence=0.5), None, annuity_client)
    assert r.queue == "human_review"
    assert r.reasons == ["low confidence 0.50"]


def test_cancellation_urgent_to_am(annuity_client):
    r = route(make_triage(category="cancellation", urgency="normal"), None, annuity_client)
    assert (r.queue, r.priority, r.assignee) == ("account_manager", "urgent", "Priya Shah")


def test_high_churn_bumps_priority(annuity_client):
    r = route(make_triage(category="billing", churn_risk=0.8), None, annuity_client)
    assert (r.queue, r.priority) == ("account_manager", "urgent")


def test_lead_quality_replace_to_lead_ops(annuity_client):
    v = DisputeVerdict(verdict="REPLACE", reasons=["invalid phone"])
    assert route(make_triage(category="lead_quality"), v, annuity_client).queue == "lead_ops"


def test_lead_quality_valid_coach_to_am(annuity_client):
    v = DisputeVerdict(verdict="VALID_COACH", reasons=["never contacted"])
    r = route(make_triage(category="lead_quality"), v, annuity_client)
    assert (r.queue, r.assignee) == ("account_manager", "Priya Shah")


@pytest.mark.parametrize("category,queue", [
    ("billing", "billing"), ("campaign_change", "campaign_ops"), ("appointments", "account_manager"),
    ("tech_access", "support"), ("other", "human_review"),
])
def test_category_map(annuity_client, category, queue):
    assert route(make_triage(category=category), None, annuity_client).queue == queue


def test_mask_email():
    assert mask("mail patricia.w@example.com now") == "mail [email] now"


@pytest.mark.parametrize("phone", ["555-201-3344", "(555) 201 3344", "+1 555 201 3344", "5552013344"])
def test_mask_phone_formats(phone):
    assert mask(f"call {phone} today") == "call [phone] today"


def test_mask_keeps_lead_ids_and_money():
    text = "Lead L-1042 charged $2,400 on 11/20"
    assert mask(text) == text


def test_churn_beats_low_confidence(annuity_client):
    r = route(make_triage(category="cancellation", confidence=0.6, churn_risk=0.7), None, annuity_client)
    assert (r.queue, r.priority) == ("account_manager", "urgent")
