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
log = logging.getLogger("uvicorn.error")  # shows up in journalctl next to the access log


# --- auth: in-app login for the hosted demo (no DEMO_PASS = open, for local dev) ---------------------------------
SESSION_TTL = 7 * 86400


def _key() -> bytes:
    # Key derives from the login, so rotating DEMO_PASS signs everyone out.
    return hashlib.sha256(f"leaddesk:{os.getenv('DEMO_USER', '')}:{os.getenv('DEMO_PASS', '')}".encode()).digest()


def _token(expiry: int) -> str:
    return f"{expiry}." + hmac.new(_key(), str(expiry).encode(), hashlib.sha256).hexdigest()


def _authed(session: str | None) -> bool:
    if not os.getenv("DEMO_PASS"):
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
    user, password = os.getenv("DEMO_USER", ""), os.getenv("DEMO_PASS", "")
    ok = hmac.compare_digest(body.username.encode(), user.encode()) & \
        hmac.compare_digest(body.password.encode(), password.encode())
    if not ok:
        _fails.setdefault(ip, []).append(now)
        log.warning("login failed ip=%s", ip)  # never log the typed username/password
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    _fails.pop(ip, None)
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
    return {"provider": name[tp] if tp == dp else f"{name[tp]} triage · {name[dp]} drafts", "has_claude": bool(os.getenv("ANTHROPIC_API_KEY")),
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


@app.post("/webhook/ticket")
def webhook_ticket(ticket: Ticket):
    try:
        r = process_ticket(ticket, conn)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ticket_id": r.ticket.id, "queue": r.route.queue, "verdict": r.verdict.verdict if r.verdict else None,
            "monday_item_id": r.monday_item_id}
