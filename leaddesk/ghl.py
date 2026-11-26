"""Go High Level adapter (LeadConnector API). Off unless GHL_API_KEY and GHL_LOCATION_ID are set.

Flow: GHL InboundMessage webhook -> ticket (client found via a contact custom field) -> pipeline -> tags + a note on
the contact -> after a human approves, the reply goes out as a GHL conversation message on the same channel.

Endpoints, the `Version: v3` header and the field names are taken from marketplace.gohighlevel.com/docs (checked
2026-11-26: contacts/get-contact, add-tags, create-note, conversations/send-a-new-message, webhook/InboundMessage).
Not yet run against a live GHL location: try it on a sandbox sub-account first.
Private Integration scopes needed: contacts.readonly, contacts.write, conversations/message.write.
"""
import logging
import os
from datetime import datetime, timezone

import requests

from .models import Result, Ticket

BASE = "https://services.leadconnectorhq.com"
log = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(os.getenv("GHL_API_KEY") and os.getenv("GHL_LOCATION_ID"))


class GhlError(RuntimeError):
    pass


def _call(method: str, path: str, *, http=requests.request, strict: bool = False, **kw) -> dict | None:
    """One API call. Failures are logged and return None (GHL being down must never break ticket handling),
    or raise GhlError when strict (callers that must tell "GHL failed" apart from "nothing there")."""
    try:
        r = http(method, BASE + path, timeout=15, **kw,
                 headers={"Authorization": f"Bearer {os.getenv('GHL_API_KEY', '')}", "Version": "v3", "Accept": "application/json"})
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log.warning("ghl %s %s failed: %r", method, path, e)
        if strict:
            raise GhlError(f"GHL {method} {path} failed: {type(e).__name__}") from e
        return None


def client_for_contact(contact_id: str, *, http=requests.request) -> str | None:
    """Our client id, read from the contact's custom field GHL_CLIENT_FIELD_ID (e.g. "C-01")."""
    data = _call("GET", f"/contacts/{contact_id}", http=http, strict=True) or {}
    field = os.getenv("GHL_CLIENT_FIELD_ID")
    return next((f.get("value") for f in data.get("contact", {}).get("customFields", []) if f.get("id") == field), None)


def ticket_from_event(event: dict, client_id: str) -> Ticket:
    email = event.get("messageType") == "Email"
    at = event.get("dateAdded") or datetime.now(timezone.utc)  # Ticket normalises to naive UTC
    return Ticket(id=f"GHL-{event.get('messageId') or event['conversationId'] + '-' + event.get('dateAdded', '')}",
                  client_id=client_id, channel="email" if email else "webhook", ghl_contact_id=event["contactId"],
                  subject=event.get("subject") or f"{event.get('messageType', 'Message')} from GHL",
                  body=event.get("body") or "", received_at=at)


def write_back(result: Result, *, http=requests.request) -> None:
    """Tag the contact (GHL lower-cases tags and creates missing ones) and leave a note with the triage outcome."""
    cid = result.ticket.ghl_contact_id
    tags = ["leaddesk", f"ld-{result.triage.category}", f"ld-queue-{result.route.queue}"]
    if result.verdict:
        tags.append(f"ld-{result.verdict.verdict.lower()}")
    _call("POST", f"/contacts/{cid}/tags", http=http, json={"tags": tags})
    lines = [f"LeadDesk: {result.triage.summary}", f"Queue: {result.route.queue} ({result.route.priority})"]
    if result.verdict:
        lines.append(f"Lead check: {result.verdict.verdict} - " + "; ".join(result.verdict.reasons))
    _call("POST", f"/contacts/{cid}/notes", http=http, json={"body": "\n".join(lines)})


def send_reply(result: Result, text: str, *, http=requests.request) -> str | None:
    """Send the approved reply on the channel the ticket came in on. Returns the GHL messageId."""
    body = {"type": "Email" if result.ticket.channel == "email" else "SMS", "contactId": result.ticket.ghl_contact_id,
            "message": text, "status": "pending"}
    # ponytail: the docs list `status` as required here; confirm on a sandbox that "pending" still sends (it may be
    # meant for custom-provider messages). Replies are the email-style draft: add a short SMS variant before go-live.
    if body["type"] == "Email":
        body["subject"] = f"Re: {result.ticket.subject}"
    return (_call("POST", "/conversations/messages", http=http, json=body) or {}).get("messageId")
