from conftest import make_result
from fastapi.testclient import TestClient

import api

client = TestClient(api.app)
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
