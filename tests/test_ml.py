from leaddesk import ml


def test_local_triage_extracts_lead_id_and_neutral_fields():
    t = ml.triage("lead l 105 was already called by two other agents, replace it")
    assert t.category == "lead_quality" and t.lead_id == "L-105"
    assert t.churn_risk == 0.0 and 0 < t.confidence <= 1


def test_local_triage_none_without_model(monkeypatch):
    monkeypatch.setattr(ml, "_model", lambda: None)
    assert ml.triage("anything") is None
