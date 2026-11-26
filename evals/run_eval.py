"""Triage eval on labelled tickets.  Run: python -m evals.run_eval --provider grok --set all   (claude / both; core / hard)

core = 40 everyday tickets (data/tickets.json). hard = 18 adversarial ones (data/tickets_hard.json): typos, Spanish,
sarcasm, multi-intent, injections, a lead from another client's book, no lead id. blind = 36 tickets Claude Sonnet wrote
from a business-only brief (ml/write_blind_set.py), labels reviewed by hand: nothing was tuned on it."""
import argparse
import json
import re
import time
from pathlib import Path

from dotenv import load_dotenv

from leaddesk import db, llm, ml
from leaddesk.pipeline import dispute
from leaddesk.models import LabeledTicket
from leaddesk.pii import mask
from leaddesk.routing import route

ESCALATION = {"account_manager", "human_review"}


def score(pairs: list[tuple]) -> float:
    return sum(a == b for a, b in pairs) / len(pairs) if pairs else 0.0


SETS = {"core": "data/tickets.json", "hard": "data/tickets_hard.json", "blind": "data/tickets_blind.json",
        "mixed": "data/tickets_mixed.json"}


def run(provider: str, conn, tickets: list[LabeledTicket], name: str) -> dict:
    fn = {**llm.TRIAGE, "ml": ml.triage}[provider]
    cats, queues, esc, leads, latencies, fallbacks, misses, multi = [], [], [], [], [], 0, [], []
    usage_start = _usage_lines()
    for t in tickets:
        client = db.get_client(conn, t.client_id)
        start = time.perf_counter()
        text = mask(f"{t.subject}\n{t.body}")
        tri = fn(text, client)
        latencies.append((time.perf_counter() - start) * 1000)
        fallbacks += tri == llm.FALLBACK_TRIAGE
        verdict = dispute(tri, client, conn, t.received_at, text)  # same code path as the app
        q = route(tri, verdict, client).queue
        want_cat = t.expected_category if isinstance(t.expected_category, list) else [t.expected_category]
        cats.append((True, tri.category in want_cat))
        queues.append((t.expected_queue, q))
        if t.expected_category == "lead_quality":  # the dispute check only works if the lead id is extracted
            if "expected_lead_id" in t.model_fields_set:
                want = t.expected_lead_id
            else:
                m = re.search(r"\bL-\d+\b", t.body)
                want = m.group() if m else None
            leads.append((want, tri.lead_id))
        if t.expected_lead_ids:
            multi.append((set(t.expected_lead_ids), set(tri.lead_ids)))
            if set(t.expected_lead_ids) != set(tri.lead_ids):
                misses.append(f"{t.id}: lead ids expected {t.expected_lead_ids}, got {tri.lead_ids}")
        if t.expected_queue in ESCALATION:
            esc.append((True, q in ESCALATION))
        if tri.category not in want_cat or q != t.expected_queue:
            misses.append(f"{t.id}: expected {'|'.join(want_cat)}/{t.expected_queue}, got {tri.category}/{q} "
                          f"(conf {tri.confidence:.2f}, churn {tri.churn_risk:.2f})")
        print(f"  {provider} {t.id} {tri.category:16} {q}")
    new = [json.loads(r) for r in _usage_lines()[len(usage_start):]]
    usd = sum(r["usd"] for r in new if r["tag"] == "eval" and r["provider"] == provider)
    return {"set": name, "provider": provider, "model": _model(provider), "tickets": len(tickets),
            "category_acc": round(score(cats), 3), "queue_acc": round(score(queues), 3),
            "escalation_recall": round(score(esc), 3), "lead_id_acc": round(score(leads), 3),
            "multi_lead_ids": f"{sum(a == b for a, b in multi)}/{len(multi)}" if multi else None,
            "avg_latency_ms": int(sum(latencies) / len(latencies)), "fallbacks": fallbacks,
            "usd_per_ticket": round(usd / len(tickets), 5), "misses": misses}


def _usage_lines() -> list[str]:
    p = Path(llm.USAGE_PATH)
    return p.read_text().splitlines() if p.exists() else []


def _model(provider: str) -> str:
    import os
    if provider == "ml":
        return "tfidf+logreg (local)"
    return llm.grok_model() if provider == "grok" else os.getenv("CLAUDE_TRIAGE_MODEL", "claude-haiku-5-5")


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=["claude", "grok", "ml", "both"], default=None)
    p.add_argument("--set", choices=["core", "hard", "blind", "mixed", "all"], default="all")
    p.add_argument("--limit", type=int, default=None, help="only the first N tickets (cheap smoke run)")
    args = p.parse_args()
    llm.USAGE_TAG = "eval"
    conn = db.connect(":memory:")
    db.seed(conn)
    providers = ["claude", "grok"] if args.provider == "both" else [args.provider or llm.default_provider()]
    sets = list(SETS) if args.set == "all" else [args.set]
    results = []
    for name in sets:
        tickets = [LabeledTicket(**t) for t in json.loads(Path(SETS[name]).read_text())][:args.limit]
        results += [run(pr, conn, tickets, name) for pr in providers]
    print(f"\n{'set':6}{'provider':10}{'category':>10}{'queue':>8}{'escal.':>8}{'lead id':>9}{'avg ms':>9}{'fallbk':>8}{'$/ticket':>10}")
    for r in results:
        print(f"{r['set']:6}{r['provider']:10}{r['category_acc']:>10.0%}{r['queue_acc']:>8.0%}{r['escalation_recall']:>8.0%}"
              f"{r['lead_id_acc']:>9.0%}{r['avg_latency_ms']:>9}{r['fallbacks']:>8}{r['usd_per_ticket']:>10.5f}")
        for m in r["misses"]:
            print("   miss", m)
    # keep rows for sets/providers not run this time, replace the ones that were
    out = Path("evals/results.json")
    old = json.loads(out.read_text()) if out.exists() else []
    ran = {(r["set"], r["provider"]) for r in results}
    keep = [r for r in old if (r.get("set", "core"), r["provider"]) not in ran and args.limit is None]
    if args.limit is None:
        out.write_text(json.dumps(keep + results, indent=1))


if __name__ == "__main__":
    main()
