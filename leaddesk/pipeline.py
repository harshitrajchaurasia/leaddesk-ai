import time
from typing import Literal

from . import db, llm, monday
from .dispute import check_lead
from .models import Result, Ticket
from .pii import mask
from .routing import route


def process_ticket(ticket: Ticket, conn, *, provider: Literal["claude", "grok"] | None = None,
                   triage_fn=None, draft_fn=None, monday_fn=None) -> Result:
    client = db.get_client(conn, ticket.client_id)
    if client is None:
        raise KeyError(f"unknown client {ticket.client_id}")
    provider = provider or llm.default_provider()
    triage_fn = triage_fn or llm.TRIAGE[provider]
    draft_fn = draft_fn or llm.DRAFT[provider]
    monday_fn = monday_fn or monday.create_item

    start = time.perf_counter()
    text = mask(f"{ticket.subject}\n{ticket.body}")
    triage = triage_fn(text, client)
    verdict = None
    if triage.category == "lead_quality":
        lead = db.get_lead(conn, triage.lead_id) if triage.lead_id else None
        if lead is not None and lead.client_id != client.id:
            lead = None  # a client can only dispute its own leads
        verdict = check_lead(lead, client, ticket.received_at)
    r = route(triage, verdict, client)
    draft = draft_fn(text, triage, verdict, client)
    result = Result(ticket=ticket, triage=triage, verdict=verdict, route=r, draft_reply=draft, provider=provider,
                    latency_ms=int((time.perf_counter() - start) * 1000))
    result.monday_item_id = monday_fn(result)
    db.save_result(conn, result)
    return result


def approve(conn, ticket_id: str, final_reply: str) -> Result:
    result = next(r for r in db.list_results(conn) if r.ticket.id == ticket_id)
    result.final_reply = final_reply
    result.status = "approved" if final_reply.strip() == result.draft_reply.strip() else "edited"
    db.save_result(conn, result)
    return result
