from datetime import datetime, timedelta

from leaddesk.dispute import check_lead
from leaddesk.models import Lead

CREATED = datetime(2026, 11, 18, 14, 0)
COMPLAINT = datetime(2026, 11, 20, 15, 0)


def make_lead(**kw) -> Lead:
    base = dict(id="L-1", client_id="C-01", full_name="Test Person", phone="(555) 201-3344",
                email="t@example.com", vertical="annuity", state="FL", age=64, investable_assets=250_000,
                consent_ts=CREATED - timedelta(minutes=1), delivered_to_count=1, created_at=CREATED,
                first_contact_at=CREATED + timedelta(minutes=12))
    return Lead(**{**base, **kw})


def verdict(annuity_client, **kw):
    return check_lead(make_lead(**kw), annuity_client, COMPLAINT)


def test_missing_lead(annuity_client):
    v = check_lead(None, annuity_client, COMPLAINT)
    assert (v.verdict, v.reasons) == ("NEEDS_REVIEW", ["lead not found"])


def test_clean_lead_fast_contact(annuity_client):
    v = verdict(annuity_client)
    # clean record + fast call: nothing to coach, the complaint needs a human to verify
    assert v.verdict == "NEEDS_REVIEW" and "passes all record checks" in v.reasons[0]


def test_slow_contact(annuity_client):
    v = verdict(annuity_client, first_contact_at=CREATED + timedelta(minutes=360))
    assert (v.verdict, v.reasons) == ("VALID_COACH", ["first contact after 360 min"])


def test_never_contacted(annuity_client):
    v = verdict(annuity_client, first_contact_at=None)
    assert (v.verdict, v.reasons) == ("VALID_COACH", ["never contacted"])


def test_no_consent(annuity_client):
    v = verdict(annuity_client, consent_ts=None)
    assert (v.verdict, v.reasons) == ("REPLACE", ["missing consent record"])


def test_exclusivity_breach(annuity_client):
    v = verdict(annuity_client, delivered_to_count=3)
    assert (v.verdict, v.reasons) == ("REPLACE", ["exclusivity breach: delivered to 3 agents"])


def test_invalid_phone(annuity_client):
    assert verdict(annuity_client, phone="555-12").reasons == ["invalid phone"]


def test_phone_with_country_code_ok(annuity_client):
    assert "invalid phone" not in verdict(annuity_client, phone="+1 (555) 201-3344").reasons[0]


def test_wrong_vertical(annuity_client):
    assert verdict(annuity_client, vertical="debt_relief").reasons == ["wrong vertical"]


def test_outside_states(annuity_client):
    assert verdict(annuity_client, state="NY").reasons == ["outside licensed states"]


def test_annuity_assets_none_is_below_min(annuity_client):
    assert verdict(annuity_client, investable_assets=None).reasons == ["below annuity asset minimum"]


def test_multiple_reasons_all_listed(annuity_client):
    v = verdict(annuity_client, consent_ts=None, delivered_to_count=2, state="NY")
    assert v.verdict == "REPLACE"
    assert v.reasons == ["missing consent record", "exclusivity breach: delivered to 2 agents", "outside licensed states"]


def test_outside_window_needs_review(annuity_client):
    v = check_lead(make_lead(consent_ts=None), annuity_client, CREATED + timedelta(days=9))
    assert v.verdict == "NEEDS_REVIEW"
    assert v.reasons == ["missing consent record", "outside 7-day replacement window"]
