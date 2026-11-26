"""Second-opinion label check.  Run: python -m ml.verify_labels

Reads ml/new_tickets.jsonl (from generate_data) and appends the agreed rows to ml/train_tickets.jsonl.
Each synthetic ticket keeps its label only if Claude (production triage prompt) agrees with the category Grok was asked
to write. Two different model families agreeing removes most label noise. Cost: about $0.0002 per ticket.
"""
import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv

from leaddesk import db, llm

SRC, TRAIN = Path("ml/new_tickets.jsonl"), Path("ml/train_tickets.jsonl")


def main():
    load_dotenv()
    llm.USAGE_TAG = "datagen"
    conn = db.connect(":memory:")
    db.seed(conn)
    client = db.get_client(conn, "C-01")
    rows = [json.loads(line) for line in SRC.read_text().splitlines()]
    with ThreadPoolExecutor(8) as pool:
        tri = list(pool.map(lambda r: llm.claude_triage(r["text"], client), rows))
    kept = [r for r, t in zip(rows, tri) if t.category == r["category"]]
    flips = Counter((r["category"], t.category) for r, t in zip(rows, tri) if t.category != r["category"])
    with TRAIN.open("a") as f:
        f.write("".join(json.dumps(r) + "\n" for r in kept))
    SRC.unlink()
    print(f"{len(kept)}/{len(rows)} kept -> {TRAIN}. Disagreements (asked -> claude):", dict(flips.most_common()))


if __name__ == "__main__":
    main()
