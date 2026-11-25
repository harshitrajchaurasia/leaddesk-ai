"""LeadDesk AI web app + webhook.  Run: uvicorn api:app --reload"""
import hashlib
import hmac
import json
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from leaddesk import db, llm
from leaddesk.models import Ticket
from leaddesk.pii import mask
from leaddesk.pipeline import approve, process_ticket

load_dotenv()
app = FastAPI(title="LeadDesk AI")
conn = db.connect()
db.seed(conn)
WEB = Path(__file__).parent / "web"
COOKIE = "ld_session"


# --- auth: in-app login for the hosted demo (no DEMO_PASS = open, for local dev) ---------------------------------
def _token(user: str) -> str:
    # ponytail: stateless signed cookie, no expiry; rotating DEMO_PASS logs everyone out
    return hmac.new(os.getenv("DEMO_PASS", "").encode(), user.encode(), hashlib.sha256).hexdigest()


def _authed(session: str | None) -> bool:
    if not os.getenv("DEMO_PASS"):
        return True
    return bool(session) and hmac.compare_digest(session, _token(os.getenv("DEMO_USER", "")))


def require_session(ld_session: str | None = Cookie(default=None)):
    if not _authed(ld_session):
        raise HTTPException(status_code=401, detail="sign in required")


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: Login, response: Response):
    user, password = os.getenv("DEMO_USER", ""), os.getenv("DEMO_PASS", "")
    if not (hmac.compare_digest(body.username, user) and hmac.compare_digest(body.password, password)):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    response.set_cookie(COOKIE, _token(user), httponly=True, secure=True, samesite="lax", max_age=7 * 86400)
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE)
    return {"ok": True}


# --- pages: React app built from frontend/ into web/ (it shows its own sign-in screen on 401) ----------------------
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB / "index.html")


if (WEB / "assets").exists():
    app.mount("/assets", StaticFiles(directory=WEB / "assets"), name="assets")


# --- app API (cookie protected) ----------------------------------------------------------------------------------
api = [Depends(require_session)]


@app.get("/api/bootstrap", dependencies=api)
def bootstrap():
    samples = json.loads(Path("data/tickets.json").read_text())
    return {"provider": llm.default_provider(), "has_claude": bool(os.getenv("ANTHROPIC_API_KEY")),
            "clients": [c.model_dump() for c in db.list_clients(conn)],
            "samples": [{k: t[k] for k in ("id", "client_id", "channel", "subject", "body", "received_at")} for t in samples]}


@app.post("/api/process", dependencies=api)
def process(ticket: Ticket):
    try:
        return process_ticket(ticket, conn).model_dump(mode="json")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


class Approval(BaseModel):
    ticket_id: str
    final_reply: str


@app.post("/api/approve", dependencies=api)
def approve_reply(body: Approval):
    try:
        return approve(conn, body.ticket_id, body.final_reply).model_dump(mode="json")
    except StopIteration:
        raise HTTPException(status_code=404, detail="ticket not found")


@app.get("/api/results", dependencies=api)
def results():
    return [r.model_dump(mode="json") for r in db.list_results(conn)]


@app.get("/api/eval", dependencies=api)
def eval_results():
    f = Path("evals/results.json")
    return json.loads(f.read_text()) if f.exists() else []


@app.post("/api/compare", dependencies=api)
def compare(ticket: Ticket):
    client = db.get_client(conn, ticket.client_id)
    if client is None:
        raise HTTPException(status_code=404, detail=f"unknown client {ticket.client_id}")
    text, out = mask(f"{ticket.subject}\n{ticket.body}"), {}
    for name in ("claude", "grok"):
        if name == "claude" and not os.getenv("ANTHROPIC_API_KEY"):
            out[name] = None
            continue
        start = time.perf_counter()
        out[name] = {"triage": llm.TRIAGE[name](text, client).model_dump(), "ms": int((time.perf_counter() - start) * 1000)}
    return out


# --- webhook + health (Caddy adds basic auth on /webhook/* when hosted) ------------------------------------------
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
