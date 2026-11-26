"""Escalate tickets still waiting for approval after their SLA: a Monday notification to the support lead, once
per ticket. Run by deploy/leaddesk-escalate.timer every 10 minutes: `python -m leaddesk.escalate`."""
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv

from . import db, monday
from .config import RULES


def overdue(conn, now: datetime | None = None):
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    return [r for r in db.list_results(conn) if r.status == "pending_approval" and r.due_at and r.due_at < now]


def run(conn, *, now: datetime | None = None, notify=monday.notify) -> list[str]:
    lead, done = RULES.queue_owners.get("human_review"), []
    for r in overdue(conn, now):
        # claim first: a failed notification is not retried (no repeated pings); the Inbox still shows Overdue
        if r.monday_item_id and db.mark_escalated(conn, r.ticket.id):
            mins = int(((now or datetime.now(timezone.utc).replace(tzinfo=None)) - r.due_at).total_seconds() // 60)
            notify(lead, r.monday_item_id, f"Overdue {mins} min: {r.ticket.id} ({r.route.queue}, owner {r.route.assignee}) {r.triage.summary}")
            done.append(r.ticket.id)
    return done


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    logging.info("escalated %s", run(db.connect()))
