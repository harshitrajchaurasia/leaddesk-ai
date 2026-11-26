import pytest
from conftest import make_result, make_triage
from fastapi.testclient import TestClient

import api
from leaddesk import db, ghl

client = TestClient(api.app)


@pytest.fixture(autouse=True)
def _tmp_db(conn, monkeypatch):
    monkeypatch.setattr(api, "conn", conn)  # never touch the real leaddesk.db
BODY = {"id": "T-1", "client_id": "C-01", "subject": "s", "body": "b", "received_at": "2026-11-20T15:00:00"}


def test_webhook_ok(monkeypatch):
    monkeypatch.setattr(api, "process_ticket", lambda t, conn: make_result())
    r = client.post("/webhook/ticket", json=BODY)
    assert r.status_code == 200
    assert r.json()["queue"] == "billing"


def test_unknown_client_404(monkeypatch):
    def boom(t, conn):
        raise KeyError("unknown client C-99")
    monkeypatch.setattr(api, "process_ticket", boom)
    assert client.post("/webhook/ticket", json={**BODY, "client_id": "C-99"}).status_code == 404


def test_bad_body_422():
    assert client.post("/webhook/ticket", json={"client_id": "C-01"}).status_code == 422
    assert client.post("/webhook/ticket", json={**BODY, "body": ""}).status_code == 422


def test_login_gate(monkeypatch):
    monkeypatch.setenv("DEMO_USER", "demo")
    monkeypatch.setenv("DEMO_PASS", "s3cret")
    c = TestClient(api.app, base_url="https://testserver")  # cookie is Secure
    assert c.get("/api/results").status_code == 401
    assert c.post("/api/login", json={"username": "demo", "password": "nope"}).status_code == 401
    assert c.post("/api/login", json={"username": "demo", "password": "s3cret"}).status_code == 200
    assert c.get("/api/results").status_code == 200  # cookie set by login
    monkeypatch.setenv("DEMO_PASS", "rotated")
    assert c.get("/api/results").status_code == 401  # rotating the password logs everyone out


def test_index_served():
    assert client.get("/").status_code == 200


def test_login_lockout_and_expiry(monkeypatch):
    monkeypatch.setenv("DEMO_USER", "demo")
    monkeypatch.setenv("DEMO_PASS", "s3cret")
    api._fails.clear()
    c = TestClient(api.app)
    for _ in range(api.FAILS_PER_IP):
        assert c.post("/api/login", json={"username": "demo", "password": "nope"}).status_code == 401
    # locked out even with the right password
    assert c.post("/api/login", json={"username": "demo", "password": "s3cret"}).status_code == 429
    api._fails.clear()
    assert not api._authed(api._token(1))  # expired cookie
    assert not api._authed("garbage")


def test_usage_summary(monkeypatch):
    import json
    from leaddesk import llm
    rows = [{"tag": "app", "step": "triage", "usd": 0.001, "ms": 900}, {"tag": "app", "step": "triage", "usd": 0.002, "ms": 1100},
            {"tag": "app", "step": "draft", "usd": 0.003, "ms": 2000}, {"tag": "eval", "step": "triage", "usd": 0.5, "ms": 1}]
    with open(llm.USAGE_PATH, "w") as f:  # conftest points USAGE_PATH at a tmp file
        f.write("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.delenv("DEMO_PASS", raising=False)
    got = client.get("/api/usage").json()
    assert got["app"]["triage"] == {"calls": 2, "usd": 0.003, "avg_ms": 1000}
    assert got["app"]["draft"]["usd"] == 0.003 and got["other_usd"] == 0.5


def test_webhook_retry_is_idempotent(conn, monkeypatch):
    calls = []
    monkeypatch.setattr(api, "process_ticket", lambda t, c: calls.append(t) or (db.save_result(c, make_result(ticket=t)) or make_result(ticket=t)))
    first, second = client.post("/webhook/ticket", json=BODY).json(), client.post("/webhook/ticket", json=BODY).json()
    assert len(calls) == 1 and not first["duplicate"] and second["duplicate"]


GHL_EVENT = {"type": "InboundMessage", "locationId": "loc1", "contactId": "ct1", "conversationId": "cv1", "messageId": "m1",
             "messageType": "SMS", "direction": "inbound", "body": "L-105 was called by 3 other agents", "dateAdded": "2026-11-20T15:00:00.000Z"}


def test_ghl_webhook_runs_pipeline_and_writes_back(monkeypatch):
    monkeypatch.setenv("GHL_API_KEY", "k")
    monkeypatch.setenv("GHL_LOCATION_ID", "loc1")
    monkeypatch.setattr(ghl, "client_for_contact", lambda cid: "C-01")
    seen, wrote = {}, []
    monkeypatch.setattr(api, "process_ticket", lambda t, c: seen.setdefault("t", t) and make_result(ticket=t))
    monkeypatch.setattr(ghl, "write_back", wrote.append)
    r = client.post("/webhook/ghl", json=GHL_EVENT).json()
    t = seen["t"]
    assert r["ticket_id"] == "GHL-m1" and t.ghl_contact_id == "ct1" and t.client_id == "C-01"
    assert t.received_at.tzinfo is None and t.received_at.hour == 15  # naive UTC, comparable with lead records
    assert len(wrote) == 1


def test_ghl_webhook_ignores_unlinked_contacts_and_outbound(monkeypatch):
    monkeypatch.setenv("GHL_API_KEY", "k")
    monkeypatch.setenv("GHL_LOCATION_ID", "loc1")
    monkeypatch.setattr(ghl, "client_for_contact", lambda cid: None)
    assert "ignored" in client.post("/webhook/ghl", json=GHL_EVENT).json()
    assert "ignored" in client.post("/webhook/ghl", json={**GHL_EVENT, "direction": "outbound"}).json()


def test_ghl_webhook_off_without_config(monkeypatch):
    monkeypatch.delenv("GHL_API_KEY", raising=False)
    assert client.post("/webhook/ghl", json=GHL_EVENT).status_code == 503


def test_approve_unknown_ticket_404(monkeypatch):
    monkeypatch.delenv("DEMO_PASS", raising=False)
    assert client.post("/api/approve", json={"ticket_id": "NOPE", "final_reply": "x"}).status_code == 404


def test_aware_timestamp_is_normalised(monkeypatch):
    seen = {}
    monkeypatch.setattr(api, "process_ticket", lambda t, c: seen.setdefault("t", t) and make_result(ticket=t))
    client.post("/webhook/ticket", json={**BODY, "id": "T-Z", "received_at": "2026-11-20T20:00:00Z"})
    assert seen["t"].received_at.tzinfo is None and seen["t"].received_at.hour == 20


def test_retry_while_first_is_running_is_not_reprocessed(conn, monkeypatch):
    db.claim(conn, "T-1")  # first delivery still in flight
    monkeypatch.setattr(api, "process_ticket", lambda t, c: pytest.fail("must not run twice"))
    assert client.post("/webhook/ticket", json=BODY).json()["processing"] is True


def test_failed_run_releases_claim(conn, monkeypatch):
    def boom(t, c):
        raise RuntimeError("model down")
    monkeypatch.setattr(api, "process_ticket", boom)
    with pytest.raises(RuntimeError):
        client.post("/webhook/ticket", json=BODY)
    assert db.claim(conn, "T-1")  # free again for the sender's retry


def _ghl_on(monkeypatch):
    monkeypatch.setenv("GHL_API_KEY", "k")
    monkeypatch.setenv("GHL_LOCATION_ID", "loc1")


def test_ghl_lookup_failure_is_502_so_ghl_retries(monkeypatch):
    _ghl_on(monkeypatch)
    def down(cid):
        raise ghl.GhlError("GHL GET /contacts/ct1 failed")
    monkeypatch.setattr(ghl, "client_for_contact", down)
    assert client.post("/webhook/ghl", json=GHL_EVENT).status_code == 502


def test_ghl_other_channels_and_bad_payload(monkeypatch):
    _ghl_on(monkeypatch)
    assert "ignored" in client.post("/webhook/ghl", json={**GHL_EVENT, "messageType": "WhatsApp"}).json()
    assert client.post("/webhook/ghl", json={k: v for k, v in GHL_EVENT.items() if k != "contactId"}).status_code == 422


def test_bootstrap_names_call_provider(monkeypatch):
    monkeypatch.delenv("DEMO_PASS", raising=False)
    monkeypatch.setenv("TRIAGE_PROVIDER", "grok")
    monkeypatch.setenv("DRAFT_PROVIDER", "claude")
    monkeypatch.setenv("CALL_PROVIDER", "grok")
    b = client.get("/api/bootstrap").json()
    assert b["provider"] == "Grok triage · Claude drafts" and b["call_provider"] == "Grok"


def test_extra_logins(monkeypatch):
    monkeypatch.setenv("DEMO_USER", "demo"); monkeypatch.setenv("DEMO_PASS", "s3cret"); monkeypatch.setenv("EXTRA_LOGINS", "g:q,h:")
    assert api._login_ok("demo", "s3cret") and api._login_ok("g", "q")
    assert not api._login_ok("g", "s3cret") and not api._login_ok("h", "") and not api._login_ok("demo", "q")
