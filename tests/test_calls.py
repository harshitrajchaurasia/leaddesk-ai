import pytest
from conftest import make_ticket  # noqa: F401  (conftest fixtures)

from leaddesk import calls, db
from leaddesk.models import ActionItem, CallInsight


def insight(**kw) -> CallInsight:
    base = dict(summary="s", sentiment="neutral", churn_risk=0.1, upsell_signals=[], objections=[],
                action_items=[ActionItem(owner="us", task="send quote", due="Friday")])
    return CallInsight(**{**base, **kw})


def test_alerts_from_rules(annuity_client):
    a = calls.alerts(insight(churn_risk=0.8, upsell_signals=["add AZ"],
                             action_items=[ActionItem(owner="us", task="pull consent records", due=None)]), annuity_client)
    assert any("Churn risk 80%" in x and "Priya Shah" in x for x in a)
    assert any(x.startswith("Upsell") for x in a) and any("due date" in x for x in a)
    assert calls.alerts(insight(), annuity_client) == []


def test_process_call_masks_saves_and_sends_to_monday(conn):
    seen, sent = {}, []
    def analyze(text, client):
        seen["text"] = text
        return insight()
    r = calls.process_call("CALL-1", "C-01", "Call me on 555-201-3344 or ellen@example.com about the invoice.", conn,
                           provider="grok", analyze_fn=analyze, monday_fn=lambda res, cl: sent.append(res) or "item-7")
    assert "555-201-3344" not in seen["text"] and "ellen@example.com" not in seen["text"]
    assert r.monday_item_id == "item-7" and db.list_calls(conn)[0].id == "CALL-1"


def test_model_failure_raises_and_saves_nothing(conn):
    def boom(text, client):
        raise ValueError("bad json")
    with pytest.raises(calls.ModelUnavailable):
        calls.process_call("CALL-2", "C-01", "some transcript text here", conn, provider="grok", analyze_fn=boom, monday_fn=lambda r, c: None)
    assert db.list_calls(conn) == []


def test_unknown_client(conn):
    with pytest.raises(KeyError):
        calls.process_call("CALL-3", "C-99", "x" * 30, conn, provider="grok", analyze_fn=lambda t, c: insight())


def test_monday_call_item_with_subitems(tmp_path, annuity_client):
    from leaddesk import monday
    from leaddesk.models import CallResult
    queries = []
    def post(url, **kw):
        queries.append(kw["json"])
        class R:
            def json(self):
                key = kw["json"]["query"].split("{", 2)[1].split("(")[0].strip()
                return {"data": {key: {"id": str(len(queries))}}}
        return R()
    res = CallResult(id="CALL-1", client_id="C-01", transcript="t", insight=insight(action_items=[
        ActionItem(owner="us", task="a", due=None), ActionItem(owner="client", task="b", due="Mon")]),
        alerts=["x"], provider="grok", latency_ms=1)
    assert monday.create_call_item(res, annuity_client, token="t", board_id="b", post=post) == "1"
    assert [q["query"].split("{")[1].split("(")[0].strip() for q in queries] == ["create_item", "create_subitem", "create_subitem", "create_update"]
    assert queries[2]["variables"]["name"] == "[client] b (due Mon)"


def test_monday_failure_goes_to_outbox(tmp_path, annuity_client):
    from leaddesk import monday
    from leaddesk.models import CallResult
    res = CallResult(id="CALL-1", client_id="C-01", transcript="t", insight=insight(), alerts=[], provider="grok", latency_ms=1)
    out = tmp_path / "o.jsonl"
    assert monday.create_call_item(res, annuity_client, token=None, board_id=None, outbox_path=str(out)) is None
    assert "CALL-1" in out.read_text()


def test_monday_partial_failure_keeps_item_and_skips_outbox(tmp_path, annuity_client):
    from leaddesk import monday
    from leaddesk.models import CallResult
    n = []
    def post(url, **kw):
        n.append(1)
        if len(n) > 1:
            raise ConnectionError("monday hiccup")
        class R:
            def json(self): return {"data": {"create_item": {"id": "55"}}}
        return R()
    res = CallResult(id="CALL-9", client_id="C-01", transcript="t", insight=insight(), alerts=["<script>"], provider="grok", latency_ms=1)
    out = tmp_path / "o.jsonl"
    assert monday.create_call_item(res, annuity_client, token="t", board_id="b", post=post, outbox_path=str(out)) == "55"
    assert not out.exists()
