import logging
import os

import anthropic
import openai

from .models import Client, DisputeVerdict, Triage
from .prompts import DRAFT_SYSTEM, TRIAGE_SYSTEM

log = logging.getLogger(__name__)
FALLBACK_TRIAGE = Triage(category="other", urgency="normal", sentiment="neutral", churn_risk=0.0, lead_id=None,
                         summary="model output invalid - needs human", confidence=0.0)
ATTEMPTS = 2  # one retry on bad output; SDKs already retry 429/5xx themselves


def _triage_prompt(ticket_text: str, client: Client) -> str:
    return f"Client: {client.name} (sells {client.vertical}, licensed in {', '.join(client.states)})\n\n<ticket>\n{ticket_text}\n</ticket>"


# Any model failure (bad JSON, schema violation, missing key, outage) must route the ticket to a human,
# never crash the desk. Errors are logged so they stay visible.

def claude_triage(ticket_text: str, client: Client, *, anthropic_client=None) -> Triage:
    for attempt in range(ATTEMPTS):
        try:
            c = anthropic_client or anthropic.Anthropic()
            resp = c.messages.parse(
                model=os.getenv("CLAUDE_TRIAGE_MODEL", "claude-haiku-5-5"),
                max_tokens=2000,
                system=TRIAGE_SYSTEM,
                messages=[{"role": "user", "content": _triage_prompt(ticket_text, client)}],
                output_format=Triage,
            )
            if resp.parsed_output is not None:
                return Triage.model_validate(resp.parsed_output.model_dump())  # re-check ge/le bounds
            log.warning("claude triage attempt %d: no parsed output", attempt + 1)
        except Exception as e:
            log.warning("claude triage attempt %d failed: %r", attempt + 1, e)
    return FALLBACK_TRIAGE


def grok_triage(ticket_text: str, client: Client, *, openai_client=None) -> Triage:
    schema = {"name": "triage", "schema": Triage.model_json_schema()}
    for attempt in range(ATTEMPTS):
        try:
            c = openai_client or openai.OpenAI(api_key=os.getenv("XAI_API_KEY"), base_url="https://api.x.ai/v1")
            resp = c.chat.completions.create(
                model=os.environ["XAI_MODEL"],
                messages=[{"role": "system", "content": TRIAGE_SYSTEM},
                          {"role": "user", "content": _triage_prompt(ticket_text, client)}],
                response_format={"type": "json_schema", "json_schema": schema},
            )
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
        c = anthropic_client or anthropic.Anthropic()
        resp = c.messages.create(
            model=os.getenv("CLAUDE_DRAFT_MODEL", "claude-sonnet-5-5"),
            max_tokens=4000,
            system=DRAFT_SYSTEM,
            messages=[{"role": "user", "content": _draft_prompt(ticket_text, triage, verdict, client)}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()
    except Exception as e:
        log.warning("draft failed: %r", e)
        return f"[draft unavailable: {type(e).__name__}] Please write this reply manually."
