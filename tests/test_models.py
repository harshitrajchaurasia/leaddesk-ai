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


def test_lead_ids_normalised_deduped_and_include_lead_id():
    from conftest import make_triage
    t = make_triage(lead_id="l 105", lead_ids=["L-105", "lead #106", "L 107"])
    assert t.lead_ids == ["L-105", "L-106", "L-107"] and t.lead_id == "L-105"
    assert make_triage(lead_id=None, lead_ids=["l9"]).lead_id == "L-9"
    assert len(make_triage(lead_ids=[f"L-{i}" for i in range(50)]).lead_ids) == 50  # no silent cap


def test_rows_saved_before_lead_ids_still_load():
    from conftest import make_result
    from leaddesk.models import Result, Triage
    old = make_result(triage=__import__("conftest").make_triage(category="lead_quality", lead_id="L-105")).model_dump(mode="json")
    del old["triage"]["lead_ids"]
    assert Result.model_validate(old).triage.lead_ids == ["L-105"]
    assert "lead_ids" in Triage.model_json_schema()["required"]  # still required for the LLM
