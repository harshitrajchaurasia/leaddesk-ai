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


def test_overdue_ticket_escalated_once(conn):
    now = datetime(2026, 12, 1, 12)
    late = make_result(route=Route(queue="billing", priority="urgent", sla_minutes=60), monday_item_id="7",
                       created_at=now - timedelta(hours=2))
    on_time = make_result(route=Route(queue="billing", priority="low", sla_minutes=2880), monday_item_id="8",
                          created_at=now - timedelta(hours=2))
    on_time.ticket = on_time.ticket.model_copy(update={"id": "T-2"})
    done = make_result(route=late.route, monday_item_id="9", created_at=late.created_at, status="approved")
    done.ticket = done.ticket.model_copy(update={"id": "T-3"})
    for r in (late, on_time, done):
        db.save_result(conn, r)
    sent = []
    notify = lambda owner, item, text: sent.append((owner, item, text))
    assert escalate.run(conn, now=now, notify=notify) == [late.ticket.id]
    assert sent[0][0] == "Support lead" and sent[0][1] == "7" and "Overdue 60 min" in sent[0][2]
    assert escalate.run(conn, now=now, notify=notify) == []  # never twice
