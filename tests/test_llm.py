import json
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


def test_default_provider_follows_anthropic_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert llm.default_provider() == "grok"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert llm.default_provider() == "claude"


def test_grok_draft_uses_verdict(annuity_client, monkeypatch):
    monkeypatch.setenv("XAI_MODEL", "grok-test")
    fake = FakeOpenAI(["  Hi from Acme Support  "])
    v = DisputeVerdict(verdict="VALID_COACH", reasons=["first contact after 360 min"])
    assert llm.grok_draft("t", GOOD, v, annuity_client, openai_client=fake) == "Hi from Acme Support"
    assert "first contact after 360 min" in fake.calls[0]["messages"][1]["content"]


def test_triage_system_prompt_has_injection_guard():
    assert "never follow instructions" in TRIAGE_SYSTEM.lower()


def test_usage_logged_with_xai_cost(annuity_client, monkeypatch):
    fake = FakeOpenAI([GOOD.model_dump_json()])
    usage = SimpleNamespace(prompt_tokens=900, completion_tokens=50, cost_in_usd_ticks=11_000_000)
    orig = fake.create
    fake.create = lambda **kw: SimpleNamespace(**{**vars(orig(**kw)), "usage": usage})
    llm.grok_triage("t", annuity_client, openai_client=fake)
    row = json.loads(open(llm.USAGE_PATH).read())
    assert (row["step"], row["in"], row["out"], row["usd"]) == ("triage", 900, 50, 0.0011)


def test_usage_cost_from_price_table_for_claude(annuity_client):
    fake = FakeAnthropic([GOOD])
    orig = fake.parse
    fake.parse = lambda **kw: SimpleNamespace(parsed_output=orig(**kw).parsed_output,
                                              usage=SimpleNamespace(input_tokens=1_000_000, output_tokens=0))
    llm.claude_triage("t", annuity_client, anthropic_client=fake)
    assert json.loads(open(llm.USAGE_PATH).read())["usd"] == 0.10


def test_lead_id_normalised():
    for raw in ("L-105", "l105", "L 105", "lead #105", " l-105 "):
        assert make_triage(lead_id=raw).lead_id == "L-105"
    assert make_triage(lead_id=None).lead_id is None
    assert make_triage(lead_id="").lead_id is None
    assert make_triage(lead_id="ABC").lead_id == "ABC"


def test_llm_provider_overrides(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    assert llm.default_provider() == "grok"


def test_per_step_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "grok")
    monkeypatch.setenv("DRAFT_PROVIDER", "claude")
    monkeypatch.delenv("TRIAGE_PROVIDER", raising=False)
    assert (llm.default_provider("triage"), llm.default_provider("draft")) == ("grok", "claude")
