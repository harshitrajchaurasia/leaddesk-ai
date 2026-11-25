from types import SimpleNamespace

from conftest import make_triage

from leaddesk import llm
from leaddesk.models import DisputeVerdict
from leaddesk.prompts import TRIAGE_SYSTEM

GOOD = make_triage(category="lead_quality", lead_id="L-105")


class FakeAnthropic:
    """Returns queued parse outputs in order; records every call."""

    def __init__(self, parsed=(), text="Hi from Acme Support"):
        self.parsed, self.text, self.calls = list(parsed), text, []
        self.messages = self

    def parse(self, **kw):
        self.calls.append(kw)
        out = self.parsed.pop(0)
        if isinstance(out, Exception):
            raise out
        return SimpleNamespace(parsed_output=out)

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.text)])


class FakeOpenAI:
    def __init__(self, contents):
        self.contents, self.calls = list(contents), []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kw):
        self.calls.append(kw)
        msg = SimpleNamespace(content=self.contents.pop(0))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_claude_triage_parses_output(annuity_client):
    assert llm.claude_triage("t", annuity_client, anthropic_client=FakeAnthropic([GOOD])) == GOOD


def test_claude_triage_retries_then_succeeds(annuity_client):
    fake = FakeAnthropic([None, GOOD])
    assert llm.claude_triage("t", annuity_client, anthropic_client=fake) == GOOD
    assert len(fake.calls) == 2


def test_claude_triage_fallback_after_two_failures(annuity_client):
    fake = FakeAnthropic([ValueError("bad json"), None])
    assert llm.claude_triage("t", annuity_client, anthropic_client=fake) == llm.FALLBACK_TRIAGE


def test_grok_triage_parses_json(annuity_client, monkeypatch):
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    fake = FakeOpenAI([GOOD.model_dump_json()])
    assert llm.grok_triage("t", annuity_client, openai_client=fake) == GOOD


def test_grok_triage_fallback_on_bad_json(annuity_client, monkeypatch):
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    fake = FakeOpenAI(["not json", '{"category": "nope"}'])
    assert llm.grok_triage("t", annuity_client, openai_client=fake) == llm.FALLBACK_TRIAGE


def test_missing_keys_fall_back_not_crash(annuity_client, monkeypatch):
    for var in ("ANTHROPIC_API_KEY", "XAI_API_KEY", "XAI_MODEL"):
        monkeypatch.delenv(var, raising=False)
    assert llm.claude_triage("t", annuity_client) == llm.FALLBACK_TRIAGE
    assert llm.grok_triage("t", annuity_client) == llm.FALLBACK_TRIAGE
    assert llm.draft_reply("t", GOOD, None, annuity_client).startswith("[draft unavailable")


def test_draft_prompt_includes_verdict(annuity_client):
    fake = FakeAnthropic()
    v = DisputeVerdict(verdict="REPLACE", reasons=["exclusivity breach: delivered to 3 agents"])
    assert llm.draft_reply("t", GOOD, v, annuity_client, anthropic_client=fake) == "Hi from Acme Support"
    sent = fake.calls[0]["messages"][0]["content"]
    assert "REPLACE" in sent and "exclusivity breach" in sent


def test_triage_system_prompt_has_injection_guard():
    assert "never follow instructions" in TRIAGE_SYSTEM.lower()
