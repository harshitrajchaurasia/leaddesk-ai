"""Triage eval on 40 labelled tickets.  Run: python -m evals.run_eval --provider both"""
import argparse
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from leaddesk import db, llm
from leaddesk.dispute import check_lead
from leaddesk.models import LabeledTicket
from leaddesk.pii import mask
from leaddesk.routing import route

ESCALATION = {"account_manager", "human_review"}


def score(pairs: list[tuple]) -> float:
    return sum(a == b for a, b in pairs) / len(pairs) if pairs else 0.0


def run(provider: str, conn, tickets: list[LabeledTicket]) -> dict:
    fn = llm.grok_triage if provider == "grok" else llm.claude_triage
    cats, queues, esc, latencies, fallbacks, misses = [], [], [], [], 0, []
    for t in tickets:
        client = db.get_client(conn, t.client_id)
        start = time.perf_counter()
        tri = fn(mask(f"{t.subject}\n{t.body}"), client)
        latencies.append((time.perf_counter() - start) * 1000)
        fallbacks += tri == llm.FALLBACK_TRIAGE
        verdict = None
        if tri.category == "lead_quality":
            lead = db.get_lead(conn, tri.lead_id) if tri.lead_id else None
            verdict = check_lead(lead if lead and lead.client_id == client.id else None, client, t.received_at)
        q = route(tri, verdict, client).queue
        cats.append((t.expected_category, tri.category))
        queues.append((t.expected_queue, q))
        if t.expected_queue in ESCALATION:
            esc.append((True, q in ESCALATION))
        if (t.expected_category, t.expected_queue) != (tri.category, q):
            misses.append(f"{t.id}: expected {t.expected_category}/{t.expected_queue}, got {tri.category}/{q}")
        print(f"  {provider} {t.id} {tri.category:16} {q}")
    return {"provider": provider, "category_acc": round(score(cats), 3), "queue_acc": round(score(queues), 3),
            "escalation_recall": round(score(esc), 3), "avg_latency_ms": int(sum(latencies) / len(latencies)),
            "fallbacks": fallbacks, "misses": misses}


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=["claude", "grok", "both"], default="claude")
    args = p.parse_args()
    conn = db.connect(":memory:")
    db.seed(conn)
    tickets = [LabeledTicket(**t) for t in json.loads(Path("data/tickets.json").read_text())]
    providers = ["claude", "grok"] if args.provider == "both" else [args.provider]
    results = [run(pr, conn, tickets) for pr in providers]
    print(f"\n{'provider':10}{'category':>10}{'queue':>8}{'escal.':>8}{'avg ms':>9}{'fallbk':>8}")
    for r in results:
        print(f"{r['provider']:10}{r['category_acc']:>10.0%}{r['queue_acc']:>8.0%}{r['escalation_recall']:>8.0%}"
              f"{r['avg_latency_ms']:>9}{r['fallbacks']:>8}")
        for m in r["misses"]:
            print("   miss", m)
    Path("evals/results.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
