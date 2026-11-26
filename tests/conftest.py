from datetime import datetime
from pathlib import Path

import pytest

from leaddesk import db, llm
from leaddesk.models import Client, Result, Route, Ticket, Triage

DATA_DIR = str(Path(__file__).parent.parent / "data")


@pytest.fixture(autouse=True)
def _usage_log(tmp_path, monkeypatch):
    monkeypatch.setattr(llm, "USAGE_PATH", str(tmp_path / "usage.jsonl"))
    for k in ("MONDAY_API_TOKEN", "MONDAY_BOARD_ID", "MONDAY_CALLS_BOARD_ID", "GHL_API_KEY", "GHL_LOCATION_ID"):
        monkeypatch.delenv(k, raising=False)  # api.py loads .env: tests must never reach real Monday/GHL


@pytest.fixture
def conn(tmp_path):
    c = db.connect(str(tmp_path / "test.db"))
    db.seed(c, DATA_DIR)
    return c


@pytest.fixture
def annuity_client():
    return Client(id="C-01", name="Harbor Retirement Advisors", vertical="annuity", states=["FL", "GA", "SC"],
                  plan="Growth", account_manager="Priya Shah")


def make_triage(**kw) -> Triage:
    base = dict(category="billing", urgency="normal", sentiment="neutral", churn_risk=0.1, lead_id=None,
                summary="test", confidence=0.9)
    return Triage(**{**base, **kw})


def make_ticket(**kw) -> Ticket:
    base = dict(id="T-900", client_id="C-01", channel="form", subject="s", body="b",
                received_at=datetime(2026, 11, 20, 15, 0))
    return Ticket(**{**base, **kw})


def make_result(**kw) -> Result:
    base = dict(ticket=make_ticket(), triage=make_triage(), route=Route(queue="billing", priority="normal"),
                draft_reply="hi", provider="fake", latency_ms=5)
    return Result(**{**base, **kw})
