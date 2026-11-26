import json
from datetime import datetime, timedelta

from conftest import make_result
from test_monday import fake_post

from leaddesk import db, escalate, monday
from leaddesk.models import Route


def people(monkeypatch, mapping, allow):
    monkeypatch.setenv("MONDAY_PEOPLE", json.dumps(mapping))
    monkeypatch.setenv("MONDAY_NOTIFY_USER_IDS", allow)


def test_only_allowlisted_users_are_ever_notified(monkeypatch):
    people(monkeypatch, {"Lead Ops team": 111, "Priya Shah": 999}, "111")
    assert monday.user_for("Lead Ops team") == 111
    assert monday.user_for("Priya Shah") is None  # mapped but not allowlisted
    assert monday.user_for("Nobody") is None and monday.user_for(None) is None
    post, calls = fake_post({"data": {"create_notification": {"text": "x"}}})
    assert monday.notify("Priya Shah", "5", "hi", token="t", post=post) is False and calls == []
    assert monday.notify("Lead Ops team", "5", "hi", token="t", post=post) is True
    assert calls[0]["json"]["variables"]["user"] == 111


def test_nobody_notified_without_config():
    post, calls = fake_post({})
    assert monday.notify("Lead Ops team", "5", "hi", token="t", post=post) is False and calls == []


def test_urgent_item_assigns_and_notifies_owner(monkeypatch, tmp_path):
    people(monkeypatch, {"Priya Shah": 111}, "111")
    monkeypatch.setenv("MONDAY_COLUMNS", json.dumps({"owner": "people_1"}))
    post, calls = fake_post({"data": {"create_item": {"id": "9"}, "create_notification": {"text": "x"}}})
    r = make_result(route=Route(queue="account_manager", priority="urgent", assignee="Priya Shah"))
    assert monday.create_item(r, token="t", board_id="b", post=post, outbox_path=str(tmp_path / "o")) == "9"
    vals = json.loads(calls[0]["json"]["variables"]["vals"])
    assert vals["people_1"] == {"personsAndTeams": [{"id": 111, "kind": "person"}]}
    assert len(calls) == 2 and calls[1]["json"]["variables"]["item"] == "9"


def test_normal_item_does_not_notify(monkeypatch, tmp_path):
    people(monkeypatch, {"Billing team": 111}, "111")
    post, calls = fake_post({"data": {"create_item": {"id": "9"}}})
    r = make_result(route=Route(queue="billing", priority="normal", assignee="Billing team"))
    monday.create_item(r, token="t", board_id="b", post=post, outbox_path=str(tmp_path / "o"))
    assert len(calls) == 1


def overdue_rows(conn, n=1, board="B1", **kw):
    now = datetime(2026, 12, 1, 12)
    for i in range(n):
        r = make_result(route=Route(queue="billing", priority="urgent", assignee="Billing team", sla_minutes=60),
                        monday_item_id=str(100 + i), monday_board_id=board, created_at=now - timedelta(hours=2), **kw)
        r.ticket = r.ticket.model_copy(update={"id": f"T-{i}"})
        db.save_result(conn, r)
    return now


def setup(monkeypatch, board="B1"):
    people(monkeypatch, {"Support lead": 111}, "111")
    monkeypatch.setenv("MONDAY_BOARD_ID", board)


def test_overdue_ticket_escalated_once(conn, monkeypatch):
    setup(monkeypatch)
    now = overdue_rows(conn)
    on_time = make_result(route=Route(queue="billing", priority="low", sla_minutes=2880), monday_item_id="8",
                          monday_board_id="B1", created_at=now - timedelta(hours=2))
    on_time.ticket = on_time.ticket.model_copy(update={"id": "T-on-time"})
    done = make_result(route=Route(queue="billing", priority="urgent", sla_minutes=60), monday_item_id="9",
                       monday_board_id="B1", created_at=now - timedelta(hours=2), status="approved")
    done.ticket = done.ticket.model_copy(update={"id": "T-done"})
    for r in (on_time, done):
        db.save_result(conn, r)
    sent = []
    notify = lambda owner, item, text: sent.append((owner, item, text)) or True
    assert escalate.run(conn, now=now, notify=notify) == ["T-0"]
    assert sent[0][0] == "Support lead" and sent[0][1] == "100" and "Overdue 60 min" in sent[0][2]
    assert escalate.run(conn, now=now, notify=notify) == []  # never twice


def test_failed_notification_is_retried_next_run(conn, monkeypatch):
    setup(monkeypatch)
    now = overdue_rows(conn)
    assert escalate.run(conn, now=now, notify=lambda *a: False) == []
    assert escalate.run(conn, now=now, notify=lambda *a: True) == ["T-0"]


def test_nothing_happens_without_an_allowlisted_lead(conn, monkeypatch):
    monkeypatch.setenv("MONDAY_BOARD_ID", "B1")
    now = overdue_rows(conn)
    assert escalate.run(conn, now=now, notify=lambda *a: 1 / 0) == []
    setup(monkeypatch)
    assert escalate.run(conn, now=now, notify=lambda *a: True) == ["T-0"]  # not used up by the earlier run


def test_items_on_another_board_or_without_item_are_skipped(conn, monkeypatch):
    setup(monkeypatch, board="DEV")
    now = overdue_rows(conn, board="DEMO")
    r = make_result(route=Route(queue="billing", priority="urgent", sla_minutes=60), created_at=now - timedelta(hours=2))
    r.ticket = r.ticket.model_copy(update={"id": "T-no-item"})
    db.save_result(conn, r)
    assert escalate.run(conn, now=now, notify=lambda *a: 1 / 0) == []


def test_backlog_is_capped_with_one_summary(conn, monkeypatch):
    setup(monkeypatch)
    now = overdue_rows(conn, n=8)
    sent = []
    done = escalate.run(conn, now=now, notify=lambda o, i, t: sent.append(t) or True)
    assert len(sent) == escalate.MAX_PER_RUN + 1 and "3 more" in sent[-1] and len(done) == 8


def test_bad_config_never_raises(monkeypatch):
    people(monkeypatch, {"Support lead": "abc"}, "111")
    assert monday.user_for("Support lead") is None
    people(monkeypatch, {"Support lead": 111}, "111, x")
    assert monday.user_for("Support lead") is None
    monkeypatch.setenv("MONDAY_PEOPLE", "{not json")
    assert monday.user_for("Support lead") is None
    people(monkeypatch, {"Support lead": 111}, " 111 , ")
    assert monday.user_for("Support lead") == 111


def test_mapped_but_not_allowlisted_owner_is_not_assigned(monkeypatch, tmp_path):
    people(monkeypatch, {"Priya Shah": 999}, "111")
    monkeypatch.setenv("MONDAY_COLUMNS", json.dumps({"owner": "people_1"}))
    post, calls = fake_post({"data": {"create_item": {"id": "9"}}})
    r = make_result(route=Route(queue="account_manager", priority="urgent", assignee="Priya Shah"))
    monday.create_item(r, token="t", board_id="b", post=post, outbox_path=str(tmp_path / "o"))
    assert "people_1" not in json.loads(calls[0]["json"]["variables"]["vals"]) and len(calls) == 1


def test_call_churn_notifies_account_manager(monkeypatch, annuity_client):
    from leaddesk.models import CallInsight, CallResult
    people(monkeypatch, {"Priya Shah": 111}, "111")
    post, calls = fake_post({"data": {"create_item": {"id": "5"}, "create_update": {"id": "6"},
                                      "create_notification": {"text": "x"}}})
    insight = CallInsight(summary="s", sentiment="angry", churn_risk=0.9, upsell_signals=[], objections=[], action_items=[])
    res = CallResult(id="C1", client_id="C-01", transcript="t", insight=insight, alerts=["Churn risk 90%: call back"],
                     provider="grok", latency_ms=1)
    assert monday.create_call_item(res, annuity_client, token="t", board_id="b", post=post) == "5"
    assert calls[-1]["json"]["variables"]["user"] == 111
