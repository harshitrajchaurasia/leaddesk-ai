"""Call-intelligence eval on hand-labelled transcripts (data/calls.json).  Run: python -m evals.run_call_eval --provider both

Checks per call: churn band (high >= 0.7, medium 0.3-0.7, low <= 0.3), upsell found or not, sentiment in the
labelled set, and at least the labelled number of action items. Per-call scores are kept in the results file. Results merge into evals/call_results.json."""
import argparse
import json
import time
from pathlib import Path

from dotenv import load_dotenv

from leaddesk import calls, db, llm
from leaddesk.pii import mask


def run(provider: str, conn, samples: list[dict]) -> dict:
    checks, latencies, misses, per_call = [], [], [], []
    for c in samples:
        client, start = db.get_client(conn, c["client_id"]), time.perf_counter()
        i = calls.ANALYZE[provider](mask(c["transcript"]), client)
        latencies.append((time.perf_counter() - start) * 1000)
        e = c["expect"]
        band = {"high": i.churn_risk >= 0.7, "medium": 0.3 < i.churn_risk < 0.7, "low": i.churn_risk <= 0.3}
        per_call.append({"id": c["id"], "churn": i.churn_risk, "sentiment": i.sentiment, "upsell": len(i.upsell_signals),
                         "actions": len(i.action_items)})
        got = {"churn": band[e["churn"]], "sentiment": i.sentiment in e["sentiment"],
               "upsell": bool(i.upsell_signals) == e["upsell"], "action_items": len(i.action_items) >= e["min_action_items"]}
        checks += got.values()
        misses += [f"{c['id']} {k}: churn {i.churn_risk:.2f}, {i.sentiment}, upsell {i.upsell_signals}, {len(i.action_items)} actions"
                   for k, ok in got.items() if not ok]
        print(f"  {provider} {c['id']} churn {i.churn_risk:.2f} upsell {len(i.upsell_signals)} actions {len(i.action_items)}")
    rows = [json.loads(r) for r in Path(llm.USAGE_PATH).read_text().splitlines()] if Path(llm.USAGE_PATH).exists() else []
    return {"provider": provider, "calls": len(samples), "checks_passed": f"{sum(checks)}/{len(checks)}",
            "avg_latency_ms": int(sum(latencies) / len(latencies)), "misses": misses, "per_call": per_call,
            "usd_total": round(sum(r["usd"] for r in rows if r["tag"] == "eval-call" and r["provider"] == provider), 4)}


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--provider", choices=["claude", "grok", "both"], default="both")
    args = p.parse_args()
    llm.USAGE_TAG = "eval-call"
    conn = db.connect(":memory:")
    db.seed(conn)
    samples = json.loads(Path("data/calls.json").read_text())
    results = [run(pr, conn, samples) for pr in (["claude", "grok"] if args.provider == "both" else [args.provider])]
    out = Path("evals/call_results.json")
    old = [r for r in (json.loads(out.read_text()) if out.exists() else []) if r["provider"] not in {x["provider"] for x in results}]
    out.write_text(json.dumps(old + results, indent=1))
    for r in results:
        print(r["provider"], r["checks_passed"], f"{r['avg_latency_ms']} ms", f"${r['usd_total']}", r["misses"])


if __name__ == "__main__":
    main()
