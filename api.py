"""Webhook intake.  Run: uvicorn api:app --reload"""
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

from leaddesk import db
from leaddesk.models import Ticket
from leaddesk.pipeline import process_ticket

load_dotenv()
app = FastAPI(title="LeadDesk AI webhook")
conn = db.connect()
db.seed(conn)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/webhook/ticket")
def webhook_ticket(ticket: Ticket):
    try:
        r = process_ticket(ticket, conn)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ticket_id": r.ticket.id, "queue": r.route.queue, "verdict": r.verdict.verdict if r.verdict else None,
            "monday_item_id": r.monday_item_id}
