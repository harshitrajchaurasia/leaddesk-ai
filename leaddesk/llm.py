import json
import logging
import os
import time
from pathlib import Path

import anthropic
import openai

from .models import Client, DisputeVerdict, Triage
from .prompts import DRAFT_SYSTEM, TRIAGE_SYSTEM

log = logging.getLogger(__name__)
FALLBACK_TRIAGE = Triage(category="other", urgency="normal", sentiment="neutral", churn_risk=0.0, lead_id=None, lead_ids=[],
                         summary="model output invalid - needs human", confidence=0.0)
ATTEMPTS = 2  # one retry on bad output; SDKs already retry 429/5xx themselves
GROK_MODEL = "grok-4.20-0309-non-reasoning"
USAGE_PATH = "data/usage.jsonl"
USAGE_TAG = "app"  # the eval runner sets "eval" so spend can be split
# USD per 1M tokens (input, output). xAI returns the exact cost per call, so this is only its fallback.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "grok-4.20-0309-non-reasoning": (1.25, 2.50)}


def _record(step: str, provider: str, model: str, usage, started: float) -> None:
    """Append one row per model call: tokens, cost, latency. Never raises."""
    try:
        tin = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", 0) or 0
        tout = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", 0) or 0
        ticks = getattr(usage, "cost_in_usd_ticks", None)  # xAI: 1 tick = 1e-10 USD
        pin, pout = PRICES.get(model, (0, 0))
        cost = ticks / 1e10 if ticks else (tin * pin + tout * pout) / 1e6
        row = {"ts": round(time.time()), "tag": USAGE_TAG, "step": step, "provider": provider, "model": model,
               "in": tin, "out": tout, "usd": round(cost, 6), "ms": int((time.perf_counter() - started) * 1000)}
        Path(USAGE_PATH).parent.mkdir(parents=True, exist_ok=True)
        with open(USAGE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
    except Exception as e:
        log.warning("usage log failed: %r", e)


def grok_model() -> str:
    return os.getenv("XAI_MODEL") or GROK_MODEL


def _triage_prompt(ticket_text: str, client: Client) -> str:
    return f"Client: {client.name} (sells {client.vertical}, licensed in {', '.join(client.states)})\n\n<ticket>\n{ticket_text}\n</ticket>"


# Any model failure (bad JSON, schema violation, missing key, outage) must route the ticket to a human,
# never crash the desk. Errors are logged so they stay visible.

def claude_triage(ticket_text: str, client: Client, *, anthropic_client=None) -> Triage:
    for attempt in range(ATTEMPTS):
        try:
            c = anthropic_client or _anthropic()
            model, started = os.getenv("CLAUDE_TRIAGE_MODEL", "claude-haiku-5-5"), time.perf_counter()
            resp = c.messages.parse(
                model=model,
                max_tokens=2000,
                system=TRIAGE_SYSTEM,
                messages=[{"role": "user", "content": _triage_prompt(ticket_text, client)}],
                output_format=Triage,
            )
            _record("triage", "claude", model, getattr(resp, "usage", None), started)
            if resp.parsed_output is not None:
                return Triage.model_validate(resp.parsed_output.model_dump())  # re-check ge/le bounds
            log.warning("claude triage attempt %d: no parsed output", attempt + 1)
        except Exception as e:
            log.warning("claude triage attempt %d failed: %r", attempt + 1, e)
    return FALLBACK_TRIAGE


def _anthropic() -> anthropic.Anthropic:
    # Keys not scoped to a workspace must name one per request.
    ws = os.getenv("ANTHROPIC_WORKSPACE_ID")
    return anthropic.Anthropic(default_headers={"anthropic-workspace-id": ws} if ws else None)


def default_provider(step: str | None = None) -> str:
    """Per step: TRIAGE_PROVIDER / DRAFT_PROVIDER, then LLM_PROVIDER, then Claude when an Anthropic key is set,
    otherwise Grok (any OpenAI-compatible endpoint via XAI_BASE_URL)."""
    return ((step and os.getenv(f"{step.upper()}_PROVIDER")) or os.getenv("LLM_PROVIDER")
            or ("claude" if os.getenv("ANTHROPIC_API_KEY") else "grok"))


def _xai():
    return openai.OpenAI(api_key=os.getenv("XAI_API_KEY"), base_url=os.getenv("XAI_BASE_URL") or "https://api.x.ai/v1")


def grok_triage(ticket_text: str, client: Client, *, openai_client=None) -> Triage:
    schema = {"name": "triage", "schema": Triage.model_json_schema()}
    for attempt in range(ATTEMPTS):
        try:
            c = openai_client or _xai()
            model, started = grok_model(), time.perf_counter()
            resp = c.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": TRIAGE_SYSTEM},
                          {"role": "user", "content": _triage_prompt(ticket_text, client)}],
                response_format={"type": "json_schema", "json_schema": schema},
            )
            _record("triage", "grok", model, getattr(resp, "usage", None), started)
            return Triage.model_validate_json(resp.choices[0].message.content)
        except Exception as e:
            log.warning("grok triage attempt %d failed: %r", attempt + 1, e)
    return FALLBACK_TRIAGE


def _draft_prompt(ticket_text: str, triage: Triage, verdict: DisputeVerdict | None, client: Client) -> str:
    v = f"{verdict.verdict} - reasons: {'; '.join(verdict.reasons)}" if verdict else "none (not a lead dispute)"
    return (f"Client: {client.name}, plan: {client.plan}, account manager: {client.account_manager}\n"
            f"Triage: category={triage.category}, urgency={triage.urgency}, churn_risk={triage.churn_risk:.2f}\n"
            f"Lead dispute verdict: {v}\n\n<ticket>\n{ticket_text}\n</ticket>")


def draft_reply(ticket_text: str, triage: Triage, verdict: DisputeVerdict | None, client: Client,
                *, anthropic_client=None) -> str:
    try:
        c = anthropic_client or _anthropic()
        model, started = os.getenv("CLAUDE_DRAFT_MODEL", "claude-sonnet-5-5"), time.perf_counter()
        resp = c.messages.create(
            model=model,
            max_tokens=4000,
            system=DRAFT_SYSTEM,
            messages=[{"role": "user", "content": _draft_prompt(ticket_text, triage, verdict, client)}],
        )
        _record("draft", "claude", model, getattr(resp, "usage", None), started)
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        log.warning("draft failed: %r", e)
        return f"[draft unavailable: {type(e).__name__}] Please write this reply manually."


def grok_draft(ticket_text: str, triage: Triage, verdict: DisputeVerdict | None, client: Client,
               *, openai_client=None) -> str:
    try:
        c = openai_client or _xai()
        model, started = grok_model(), time.perf_counter()
        resp = c.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": DRAFT_SYSTEM},
                      {"role": "user", "content": _draft_prompt(ticket_text, triage, verdict, client)}],
        )
        _record("draft", "grok", model, getattr(resp, "usage", None), started)
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.warning("grok draft failed: %r", e)
        return f"[draft unavailable: {type(e).__name__}] Please write this reply manually."


TRIAGE = {"claude": claude_triage, "grok": grok_triage}
DRAFT = {"claude": draft_reply, "grok": grok_draft}
