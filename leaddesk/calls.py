"""Customer-success call intelligence: transcript -> structured insight -> alerts (in code) -> Monday item + subitems.

Same pattern as tickets: mask PII, one structured LLM call (validated, one retry), business rules in code, Monday.
"""
import os
import time

from . import db, llm, monday
from .models import CallInsight, CallResult, Client
from .pii import mask
from .prompts import CALL_SYSTEM
from .routing import CHURN_MIN


class ModelUnavailable(RuntimeError):
    pass


def _prompt(transcript: str, client: Client) -> str:
    return (f"Client: {client.name} ({client.vertical}), licensed in {', '.join(client.states)}, plan {client.plan}\n\n"
            f"<transcript>\n{transcript}\n</transcript>")


def _claude(text: str, client: Client) -> CallInsight:
    model, started = os.getenv("CLAUDE_CALL_MODEL", "claude-sonnet-5-5"), time.perf_counter()
    resp = llm._anthropic().messages.parse(model=model, max_tokens=4000, system=CALL_SYSTEM, output_format=CallInsight,
                                           messages=[{"role": "user", "content": _prompt(text, client)}])
    llm._record("call", "claude", model, getattr(resp, "usage", None), started)
    return CallInsight.model_validate(resp.parsed_output.model_dump())


def _grok(text: str, client: Client) -> CallInsight:
    model, started = llm.grok_model(), time.perf_counter()
    resp = llm._xai().chat.completions.create(
        model=model, messages=[{"role": "system", "content": CALL_SYSTEM}, {"role": "user", "content": _prompt(text, client)}],
        response_format={"type": "json_schema", "json_schema": {"name": "call", "schema": CallInsight.model_json_schema()}})
    llm._record("call", "grok", model, getattr(resp, "usage", None), started)
    return CallInsight.model_validate_json(resp.choices[0].message.content)


ANALYZE = {"claude": _claude, "grok": _grok}


def alerts(insight: CallInsight, client: Client) -> list[str]:
    """Who needs to know, decided by rules (same churn threshold as ticket routing)."""
    out = []
    if insight.churn_risk >= CHURN_MIN:
        out.append(f"Churn risk {insight.churn_risk:.0%}: account manager {client.account_manager} to call back today")
    if insight.upsell_signals:
        out.append(f"Upsell: {len(insight.upsell_signals)} signal(s), {client.account_manager} to follow up with an offer")
    if any(a.owner == "us" and not a.due for a in insight.action_items):
        out.append("Our follow-ups without a due date: set one in Monday")
    return out


def process_call(call_id: str, client_id: str, transcript: str, conn, *, provider: str | None = None,
                 analyze_fn=None, monday_fn=None) -> CallResult:
    client = db.get_client(conn, client_id)
    if client is None:
        raise KeyError(f"unknown client {client_id}")
    provider = provider or llm.default_provider("call")
    analyze_fn = analyze_fn or ANALYZE[provider]
    text, start = mask(transcript), time.perf_counter()
    for attempt in range(llm.ATTEMPTS):
        try:
            insight = analyze_fn(text, client)
            break
        except Exception as e:
            llm.log.warning("call analysis attempt %d failed: %r", attempt + 1, e)
    else:
        raise ModelUnavailable("call analysis failed twice; nothing was saved, try again")
    result = CallResult(id=call_id, client_id=client_id, transcript=text, insight=insight, alerts=alerts(insight, client),
                        provider=provider, latency_ms=int((time.perf_counter() - start) * 1000))
    result.monday_item_id = (monday_fn or monday.create_call_item)(result, client)
    db.save_call(conn, result)
    return result
