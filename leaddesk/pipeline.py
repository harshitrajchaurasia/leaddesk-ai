import os
import re
import time
from datetime import datetime, timezone
from typing import Literal

from . import db, ghl, llm, ml, monday
from .dispute import check_leads
from .models import MAX_LEADS_PER_TICKET, DisputeVerdict, MLOpinion, Result, Ticket
from .pii import mask
from .routing import CONFIDENCE_MIN, route


def dispute(triage, client, conn, received_at, text: str = ""):
    """Lead Dispute Check for every lead the ticket names (None unless it is a lead-quality ticket).

    Ids the model expanded from a range ("L-7201 to L-7205") don't appear in the text: their reasons say so."""
    if triage.category != "lead_quality":
        return None
    if len(triage.lead_ids) > MAX_LEADS_PER_TICKET:
        return DisputeVerdict(verdict="NEEDS_REVIEW", reasons=[f"{len(triage.lead_ids)} leads named (more than {MAX_LEADS_PER_TICKET}): check by hand"])
    def label(lid):
        return lid if not text or re.search(rf"\b{lid.split('-')[-1]}\b", text) else f"{lid} (inside a range)"
    leads = {label(lid): db.get_lead(conn, lid) for lid in triage.lead_ids}
    leads = {k: (l if l is not None and l.client_id == client.id else None)  # a client can only dispute its own leads
             for k, l in leads.items()}
    return check_leads(leads, client, received_at)


def process_ticket(ticket: Ticket, conn, *, provider: Literal["claude", "grok"] | None = None,
                   triage_fn=None, draft_fn=None, monday_fn=None) -> Result:
    client = db.get_client(conn, ticket.client_id)
    if client is None:
        raise KeyError(f"unknown client {ticket.client_id}")
    tp, dp = provider or llm.default_provider("triage"), provider or llm.default_provider("draft")
    provider = tp if tp == dp else f"{tp} triage, {dp} draft"
    triage_fn = triage_fn or llm.TRIAGE[tp]
    draft_fn = draft_fn or llm.DRAFT[dp]
    monday_fn = monday_fn or monday.create_item

    start = time.perf_counter()
    text = mask(f"{ticket.subject}\n{ticket.body}")
    triage = triage_fn(text, client)
    local = ml.triage(text)
    if triage == llm.FALLBACK_TRIAGE and local is not None:
        # model API down or bad output: keep the local category as a hint, but always send it to a human
        triage = local.model_copy(update={"confidence": min(local.confidence, CONFIDENCE_MIN - 0.01)})
    verdict = dispute(triage, client, conn, ticket.received_at, text)
    r = route(triage, verdict, client)
    draft = draft_fn(text, triage, verdict, client)
    result = Result(created_at=datetime.now(timezone.utc).replace(tzinfo=None), ticket=ticket, triage=triage, ml=local and MLOpinion(category=local.category, confidence=local.confidence),
                    verdict=verdict, route=r, draft_reply=draft, provider=provider,
                    latency_ms=int((time.perf_counter() - start) * 1000))
    result.monday_item_id = monday_fn(result)
    result.monday_board_id = result.monday_item_id and os.getenv("MONDAY_BOARD_ID")
    db.save_result(conn, result)
    return result


def approve(conn, ticket_id: str, final_reply: str) -> Result:
    result = db.get_result(conn, ticket_id)
    if result is None:
        raise KeyError(f"unknown ticket {ticket_id}")
    result.final_reply = final_reply
    result.status = "approved" if final_reply.strip() == result.draft_reply.strip() else "edited"
    result.approved_at = result.approved_at or datetime.now(timezone.utc).replace(tzinfo=None)
    if result.ticket.ghl_contact_id and ghl.enabled() and not result.ghl_message_id:  # never text a contact twice
        result.ghl_message_id = ghl.send_reply(result, final_reply)
        result.send_error = None if result.ghl_message_id else "GHL send failed: approve again to retry, or reply in GHL"
    db.save_result(conn, result)
    return result
