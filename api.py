"""LeadDesk AI web app + webhook.  Run: uvicorn api:app --reload"""
import hashlib
import hmac
import json
import logging
import os
import time
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from leaddesk import calls, db, ghl, llm
from leaddesk.config import RULES
from leaddesk.models import Ticket
from leaddesk.pii import mask
from leaddesk.pipeline import approve, process_ticket

load_dotenv()
app = FastAPI(title="LeadDesk AI")
conn = db.connect()
db.seed(conn)
WEB = Path(__file__).parent / "web"
CALL_SAMPLES = Path(__file__).parent / "data" / "calls.json"
COOKIE = "ld_session"
log = logging.getLogger("uvicorn.error")  # shows up in journalctl next to the access log


# --- auth: in-app login for the hosted demo (no DEMO_PASS = open, for local dev) ---------------------------------
SESSION_TTL = 7 * 86400


def _key() -> bytes:
    # Key derives from the logins, so changing DEMO_PASS or EXTRA_LOGINS signs everyone out.
    return hashlib.sha256(f"leaddesk:{os.getenv('DEMO_USER', '')}:{os.getenv('DEMO_PASS', '')}:{os.getenv('EXTRA_LOGINS', '')}".encode()).digest()


def _login_ok(username: str, password: str) -> bool:
    """DEMO_USER/DEMO_PASS, or any "user:pass" in EXTRA_LOGINS (comma separated), e.g. one login per reviewer."""
    return any(hmac.compare_digest(username.encode(), u.encode()) & hmac.compare_digest(password.encode(), p.encode())
               for u, p in _logins())


def _logins() -> list[tuple[str, str]]:
    pairs = [(os.getenv("DEMO_USER", ""), os.getenv("DEMO_PASS", ""))]
    pairs += [(u.strip(), p.strip()) for u, _, p in (x.partition(":") for x in os.getenv("EXTRA_LOGINS", "").split(","))]
    return [(u, p) for u, p in pairs if u and p]


def _token(expiry: int) -> str:
    return f"{expiry}." + hmac.new(_key(), str(expiry).encode(), hashlib.sha256).hexdigest()


def _authed(session: str | None) -> bool:
    if not _logins():  # no login configured: open, for local dev
        return True
    try:
        expiry = int((session or "").split(".", 1)[0])
    except ValueError:
        return False
    return expiry > time.time() and hmac.compare_digest(session.encode(), _token(expiry).encode())


# ponytail: in-memory limiter, fine for one worker process; move to Redis if it ever runs several.
FAILS_PER_IP, FAILS_GLOBAL, WINDOW = 5, 30, 15 * 60
_fails: dict[str, list[float]] = {}


def _recent(ip: str, now: float) -> list[float]:
    hits = [t for t in _fails.get(ip, []) if t > now - WINDOW]
    if hits:
        _fails[ip] = hits
    else:
        _fails.pop(ip, None)
    return hits


def _locked(ip: str, now: float) -> bool:
    total = sum(len(_recent(k, now)) for k in list(_fails))
    return len(_recent(ip, now)) >= FAILS_PER_IP or total >= FAILS_GLOBAL


def require_session(ld_session: str | None = Cookie(default=None)):
    if not _authed(ld_session):
        raise HTTPException(status_code=401, detail="sign in required")


class Login(BaseModel):
    username: str
    password: str


@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    # Caddy sets X-Forwarded-For to CF-Connecting-IP, and the origin only admits Cloudflare.
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or request.client.host
    now = time.time()
    if _locked(ip, now):
        log.warning("login locked out ip=%s", ip)
        raise HTTPException(status_code=429, detail="Too many attempts. Try again in 15 minutes.")
    if not _login_ok(body.username, body.password):
        _fails.setdefault(ip, []).append(now)
        log.warning("login failed ip=%s", ip)  # never log the typed username/password
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    _fails.pop(ip, None)
    log.info("login ok user=%s ip=%s", body.username, ip)  # who signed in, and when (the password is never logged)
    response.set_cookie(COOKIE, _token(int(now) + SESSION_TTL), httponly=True, secure=True, samesite="lax",
                        max_age=SESSION_TTL)
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
    tp, dp = llm.default_provider("triage"), llm.default_provider("draft")
    name = {"grok": "Grok", "claude": "Claude"}
    return {"provider": name[tp] if tp == dp else f"{name[tp]} triage · {name[dp]} drafts", "call_provider": name[llm.default_provider("call")],
            "has_claude": bool(os.getenv("ANTHROPIC_API_KEY")),
            "time_saved": RULES.time_saved.model_dump(), "sla_minutes": RULES.sla_minutes,
            "clients": [c.model_dump() for c in db.list_clients(conn)],
            "samples": [{k: t[k] for k in ("id", "client_id", "channel", "subject", "body", "received_at")} for t in samples]}


@app.post("/api/process", dependencies=api)
def process(ticket: Ticket):
    try:
        return process_ticket(ticket, conn).model_dump(mode="json")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))


class CallIn(BaseModel):
    client_id: str
    transcript: str = Field(min_length=20, max_length=60000)


@app.get("/api/calls", dependencies=api)
def list_calls():
    samples = [{k: c[k] for k in ("id", "client_id", "title", "transcript")} for c in json.loads(CALL_SAMPLES.read_text())]
    return {"samples": samples, "results": [c.model_dump(mode="json") for c in db.list_calls(conn)]}


@app.post("/api/call", dependencies=api)
def analyse_call(body: CallIn):
    try:
        return calls.process_call(f"CALL-{int(time.time() * 1000)}", body.client_id, body.transcript, conn).model_dump(mode="json")
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except calls.ModelUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))


class Approval(BaseModel):
    ticket_id: str
    final_reply: str


@app.post("/api/approve", dependencies=api)
def approve_reply(body: Approval):
    try:
        return approve(conn, body.ticket_id, body.final_reply).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="ticket not found")


@app.get("/api/results", dependencies=api)
def results():
    return [r.model_dump(mode="json") for r in db.list_results(conn)]


@app.get("/api/eval", dependencies=api)
def eval_results():
    f = Path("evals/results.json")
    return json.loads(f.read_text()) if f.exists() else []


@app.get("/api/usage", dependencies=api)
def usage():
    """Model spend from data/usage.jsonl: live tickets ("app") per step, plus everything else (evals, data generation)."""
    f = Path(llm.USAGE_PATH)
    rows = [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []
    steps: dict[str, dict] = {}
    for r in (r for r in rows if r["tag"] == "app"):
        s = steps.setdefault(r["step"], {"calls": 0, "usd": 0.0, "ms": 0})
        s["calls"] += 1
        s["usd"] += r["usd"]
        s["ms"] += r["ms"]
    return {"app": {k: {"calls": v["calls"], "usd": round(v["usd"], 5), "avg_ms": v["ms"] // v["calls"]} for k, v in steps.items()},
            "other_usd": round(sum(r["usd"] for r in rows if r["tag"] != "app"), 4)}


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


def _summary(r, duplicate=False) -> dict:
    return {"ticket_id": r.ticket.id, "queue": r.route.queue, "verdict": r.verdict.verdict if r.verdict else None,
            "monday_item_id": r.monday_item_id, "duplicate": duplicate}


def _once(ticket: Ticket, after=None) -> dict:
    """Process a webhook ticket at most once. Senders retry, and a retry can arrive while the first call is still
    running, so the id is claimed before any model call; a failed run releases it so the next retry works."""
    if (done := db.get_result(conn, ticket.id)) is not None:
        return _summary(done, duplicate=True)
    if not db.claim(conn, ticket.id):
        return {"ticket_id": ticket.id, "duplicate": True, "processing": True}
    try:
        r = process_ticket(ticket, conn)
    except KeyError as e:
        db.release(conn, ticket.id)
        raise HTTPException(status_code=404, detail=str(e))
    except Exception:
        db.release(conn, ticket.id)
        raise
    if after:
        after(r)
    return _summary(r)


@app.post("/webhook/ticket")
def webhook_ticket(ticket: Ticket):
    return _once(ticket)


class GhlEvent(BaseModel):
    """The fields we use from GHL's InboundMessage event (marketplace.gohighlevel.com/docs/webhook/InboundMessage)."""
    type: str
    contactId: str
    conversationId: str
    messageId: str | None = None
    messageType: str | None = None
    direction: str = "inbound"
    body: str | None = None
    subject: str | None = None
    dateAdded: str | None = None


@app.post("/webhook/ghl")
def webhook_ghl(event: GhlEvent):
    """Go High Level InboundMessage -> same pipeline, then tags + a note on the contact."""
    if not ghl.enabled():
        raise HTTPException(status_code=503, detail="GHL not configured")
    if event.type != "InboundMessage" or event.direction != "inbound" or not (event.body or "").strip():
        return {"ignored": "not an inbound message with text"}
    if event.messageType not in ("SMS", "Email"):
        return {"ignored": f"{event.messageType} messages are not handled (replies go out only as SMS or email)"}
    try:
        client_id = ghl.client_for_contact(event.contactId)
    except ghl.GhlError as e:
        raise HTTPException(status_code=502, detail=str(e))  # non-2xx so GHL retries instead of dropping it
    if client_id is None:
        return {"ignored": "contact is not linked to a client (custom field GHL_CLIENT_FIELD_ID)"}
    ticket = ghl.ticket_from_event(event.model_dump(), client_id)
    return _once(ticket, after=ghl.write_back)
