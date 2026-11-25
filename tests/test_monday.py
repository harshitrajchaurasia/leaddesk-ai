import json
from types import SimpleNamespace

from conftest import make_result

from leaddesk.monday import create_item


def fake_post(payload):
    calls = []

    def post(url, **kw):
        calls.append(kw)
        return SimpleNamespace(json=lambda: payload)
    return post, calls


def test_no_token_writes_outbox(tmp_path, monkeypatch):
    monkeypatch.delenv("MONDAY_API_TOKEN", raising=False)
    out = tmp_path / "outbox.jsonl"
    assert create_item(make_result(), outbox_path=str(out)) is None
    assert len(out.read_text().splitlines()) == 1


def test_posts_mutation_and_returns_id(tmp_path):
    post, calls = fake_post({"data": {"create_item": {"id": "123"}}})
    item = create_item(make_result(), token="tok", board_id="42", post=post, outbox_path=str(tmp_path / "o.jsonl"))
    assert item == "123"
    variables = calls[0]["json"]["variables"]
    assert variables["board"] == "42"
    assert json.loads(variables["vals"])["text"] == "billing"
    assert calls[0]["headers"]["Authorization"] == "tok"


def test_api_error_falls_back_to_outbox(tmp_path):
    post, _ = fake_post({"errors": [{"message": "bad column"}]})
    out = tmp_path / "o.jsonl"
    assert create_item(make_result(), token="tok", board_id="42", post=post, outbox_path=str(out)) is None
    assert out.exists()
