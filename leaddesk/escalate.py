"""Escalate tickets still waiting for approval after their SLA: a Monday notification to the support lead, once
per ticket. Run by deploy/leaddesk-escalate.timer every 10 minutes: `python -m leaddesk.escalate`."""
import logging
import os
from datetime import datetime, timezone

from dotenv import load_dotenv

from . import db, monday
from .config import RULES

MAX_PER_RUN = 5  # a backlog becomes 5 pings plus one summary, never a flood


def overdue(conn, now: datetime):
    board = os.getenv("MONDAY_BOARD_ID")
    return [r for r in db.list_results(conn) if r.status == "pending_approval" and r.due_at and r.due_at < now
            and r.monday_item_id and r.monday_board_id == board]  # never ping items on another board


def run(conn, *, now: datetime | None = None, notify=monday.notify) -> list[str]:
    now, lead, done = now or datetime.now(timezone.utc).replace(tzinfo=None), RULES.queue_owners.get("human_review"), []
    if not monday.user_for(lead):
        logging.info("no allowlisted Monday user for %r: nothing escalated", lead)
        return done
    todo = [r for r in overdue(conn, now) if db.mark_escalated(conn, r.ticket.id)]
    for r in todo[:MAX_PER_RUN]:
        mins = int((now - r.due_at).total_seconds() // 60)
        if notify(lead, r.monday_item_id, f"Overdue {mins} min: {r.ticket.id} ({r.route.queue}, owner {r.route.assignee}) {r.triage.summary}"):
            done.append(r.ticket.id)
        else:
            db.unmark_escalated(conn, r.ticket.id)  # not sent: try again next run
    if rest := todo[MAX_PER_RUN:]:
        if notify(lead, rest[0].monday_item_id, f"{len(rest)} more tickets are overdue: see the LeadDesk Inbox"):
            done += [r.ticket.id for r in rest]
        else:
            for r in rest:
                db.unmark_escalated(conn, r.ticket.id)
    return done


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=logging.INFO)
    logging.info("escalated %s", run(db.connect()))
