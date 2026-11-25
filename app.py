"""LeadDesk AI demo UI.  Run: streamlit run app.py"""
import json
from datetime import datetime
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

from leaddesk import db, llm
from leaddesk.models import Ticket
from leaddesk.pii import mask
from leaddesk.pipeline import approve, process_ticket

load_dotenv()
st.set_page_config(page_title="LeadDesk AI", layout="wide")


@st.cache_resource
def get_conn():
    conn = db.connect()
    db.seed(conn)
    return conn


conn = get_conn()
clients = {c.id: c for c in db.list_clients(conn)}
samples = {f"{t['id']} - {t['subject']}": t for t in json.loads(Path("data/tickets.json").read_text())}
VERDICT_STYLE = {"REPLACE": ":green[REPLACE]", "VALID_COACH": ":blue[VALID - COACH AGENT]", "NEEDS_REVIEW": ":orange[NEEDS REVIEW]"}

st.title("LeadDesk AI")
st.caption(f"AI support desk for a lead-gen agency: triage, lead dispute check, routing, drafted replies, Monday.com. "
           f"Model: **{llm.default_provider().title()}**")
tab_new, tab_inbox, tab_compare, tab_metrics = st.tabs(["New ticket", "Inbox", "Claude vs Grok", "Metrics"])


def ticket_form(key: str) -> Ticket:
    pick = st.selectbox("Load sample ticket", ["(write your own)"] + list(samples), key=f"{key}_pick")
    s = samples.get(pick, {})
    ids = list(clients)
    cid = st.selectbox("Client", ids, index=ids.index(s.get("client_id", ids[0])),
                       format_func=lambda i: f"{i} - {clients[i].name} ({clients[i].vertical})", key=f"{key}_c_{pick}")
    subject = st.text_input("Subject", s.get("subject", ""), key=f"{key}_s_{pick}")
    body = st.text_area("Message", s.get("body", ""), height=120, key=f"{key}_b_{pick}")
    return Ticket(id=s.get("id", f"T-{datetime.now():%H%M%S}"), client_id=cid, channel=s.get("channel", "form"),
                  subject=subject, body=body or " ", received_at=s.get("received_at", datetime.now()))


with tab_new:
    left, right = st.columns([2, 3])
    with left:
        ticket = ticket_form("new")
        go = st.button("Process ticket", type="primary")
    with right:
        if go:
            with st.spinner("Triage -> dispute check -> routing -> draft -> Monday..."):
                st.session_state.result = process_ticket(ticket, conn)
        r = st.session_state.get("result")
        if r:
            a, b, c, d = st.columns(4)
            a.metric("Category", r.triage.category)
            b.metric("Queue", r.route.queue)
            c.metric("Priority", r.route.priority)
            d.metric("Latency", f"{r.latency_ms} ms")
            if r.verdict:
                st.markdown(f"**Lead dispute check:** {VERDICT_STYLE[r.verdict.verdict]}")
                for reason in r.verdict.reasons:
                    st.markdown(f"- {reason}")
            st.markdown(f"**Routing:** {', '.join(r.route.reasons)}" + (f" -> assigned to **{r.route.assignee}**" if r.route.assignee else ""))
            with st.expander("Triage JSON (Claude structured output)"):
                st.json(r.triage.model_dump())
            reply = st.text_area("Draft reply (edit, then approve - nothing is sent automatically)", r.draft_reply, height=200,
                                 key=f"reply_{r.ticket.id}")
            if st.button("Approve reply"):
                st.session_state.result = approve(conn, r.ticket.id, reply)
                st.success(f"Saved as **{st.session_state.result.status}**")
            st.caption(f"Monday item: {r.monday_item_id}" if r.monday_item_id else "Monday: no token set - saved to data/outbox.jsonl")

with tab_inbox:
    rows = [{"ticket": r.ticket.id, "client": clients[r.ticket.client_id].name, "category": r.triage.category,
             "verdict": r.verdict.verdict if r.verdict else "", "queue": r.route.queue, "priority": r.route.priority,
             "status": r.status, "summary": r.triage.summary} for r in db.list_results(conn)]
    st.dataframe(rows, use_container_width=True) if rows else st.info("No tickets processed yet.")

with tab_compare:
    ticket = ticket_form("cmp")
    if st.button("Run both models"):
        text, client = mask(f"{ticket.subject}\n{ticket.body}"), clients[ticket.client_id]
        cols = st.columns(2)
        for col, (name, fn) in zip(cols, [("Claude", llm.claude_triage), ("Grok", llm.grok_triage)]):
            if name == "Claude" and llm.default_provider() != "claude":
                col.info("Claude path is implemented and tested; no Anthropic key on this deployment.")
                st.session_state["cmp_Claude"] = None
                continue
            start = datetime.now()
            t = fn(text, client)
            col.subheader(f"{name} - {(datetime.now() - start).total_seconds():.1f}s")
            col.json(t.model_dump())
            st.session_state[f"cmp_{name}"] = t
        a, b = st.session_state["cmp_Claude"], st.session_state["cmp_Grok"]
        if a is not None:
            diffs = [k for k in ("category", "urgency", "sentiment", "lead_id") if getattr(a, k) != getattr(b, k)]
            st.warning(f"Disagree on: {', '.join(diffs)}") if diffs else st.success("Models agree on category, urgency, sentiment, lead id.")

with tab_metrics:
    results = db.list_results(conn)
    if results:
        n = len(results)
        a, b, c, d = st.columns(4)
        a.metric("Tickets processed", n)
        b.metric("Avg latency", f"{sum(r.latency_ms for r in results) // n} ms")
        c.metric("Sent to human review", f"{sum(r.route.queue == 'human_review' for r in results) / n:.0%}")
        reviewed = [r for r in results if r.status != "pending_approval"]
        d.metric("Drafts edited by human", f"{sum(r.status == 'edited' for r in reviewed) / len(reviewed):.0%}" if reviewed else "-")
    eval_file = Path("evals/results.json")
    if eval_file.exists():
        st.subheader("Triage eval (40 labelled tickets)")
        st.dataframe(json.loads(eval_file.read_text()), use_container_width=True)
