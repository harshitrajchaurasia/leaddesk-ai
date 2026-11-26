from conftest import make_result, make_ticket

from leaddesk import ghl
from leaddesk.models import DisputeVerdict


class FakeHTTP:
    def __init__(self, reply=None, fail=False):
        self.calls, self.reply, self.fail = [], reply or {}, fail

    def __call__(self, method, url, **kw):
        self.calls.append((method, url.removeprefix(ghl.BASE), kw))
        if self.fail:
            raise ConnectionError("down")
        reply = self.reply

        class R:
            def raise_for_status(self): pass
            def json(self): return reply
        return R()


def test_headers_and_client_lookup(monkeypatch):
    monkeypatch.setenv("GHL_API_KEY", "tok")
    monkeypatch.setenv("GHL_CLIENT_FIELD_ID", "f1")
    http = FakeHTTP({"contact": {"id": "ct1", "customFields": [{"id": "f0", "value": "x"}, {"id": "f1", "value": "C-03"}]}})
    assert ghl.client_for_contact("ct1", http=http) == "C-03"
    method, path, kw = http.calls[0]
    assert (method, path) == ("GET", "/contacts/ct1")
    assert kw["headers"]["Version"] == "v3" and kw["headers"]["Authorization"] == "Bearer tok"


def test_write_back_tags_and_note():
    http = FakeHTTP()
    r = make_result(ticket=make_ticket(ghl_contact_id="ct1"),
                    verdict=DisputeVerdict(verdict="REPLACE", reasons=["exclusivity breach: delivered to 3 agents"]))
    ghl.write_back(r, http=http)
    (m1, p1, k1), (m2, p2, k2) = http.calls
    assert (m1, p1) == ("POST", "/contacts/ct1/tags") and "ld-replace" in k1["json"]["tags"]
    assert (m2, p2) == ("POST", "/contacts/ct1/notes") and "exclusivity breach" in k2["json"]["body"]


def test_send_reply_uses_ticket_channel():
    http = FakeHTTP({"messageId": "msg9", "conversationId": "cv1"})
    sms = make_result(ticket=make_ticket(ghl_contact_id="ct1", channel="webhook"))
    assert ghl.send_reply(sms, "hello", http=http) == "msg9"
    assert http.calls[0][2]["json"]["type"] == "SMS" and http.calls[0][2]["json"]["message"] == "hello"
    ghl.send_reply(make_result(ticket=make_ticket(ghl_contact_id="ct1", channel="email", subject="Bad lead")), "hi", http=http)
    assert http.calls[1][2]["json"]["type"] == "Email" and http.calls[1][2]["json"]["subject"] == "Re: Bad lead"
    ghl.send_reply(make_result(ticket=make_ticket(ghl_contact_id="ct1", channel="email")), "Hi <b>\n\nline2", http=http)
    assert http.calls[2][2]["json"]["html"] == "<p>Hi &lt;b&gt;</p><p>line2</p>"


def test_ghl_down_never_raises():
    assert ghl.send_reply(make_result(ticket=make_ticket(ghl_contact_id="ct1")), "x", http=FakeHTTP(fail=True)) is None


def test_contact_lookup_failure_raises():
    import pytest
    with pytest.raises(ghl.GhlError):
        ghl.client_for_contact("ct1", http=FakeHTTP(fail=True))
