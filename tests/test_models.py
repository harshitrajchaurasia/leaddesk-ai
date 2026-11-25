import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from leaddesk.models import Client, LabeledTicket, Lead, Triage

DATA = Path(__file__).parent.parent / "data"


def load(name):
    return json.loads((DATA / name).read_text())


def test_seed_files_validate():
    assert len([Client(**c) for c in load("clients.json")]) == 8
    assert len([Lead(**x) for x in load("leads.json")]) >= 60
    assert len([LabeledTicket(**t) for t in load("tickets.json")]) == 40


def test_referential_integrity():
    client_ids = {c["id"] for c in load("clients.json")}
    assert all(x["client_id"] in client_ids for x in load("leads.json"))
    assert all(t["client_id"] in client_ids for t in load("tickets.json"))


def test_triage_rejects_out_of_range():
    with pytest.raises(ValidationError):
        Triage(category="billing", urgency="low", sentiment="neutral", churn_risk=0.1, summary="x", confidence=1.5)
