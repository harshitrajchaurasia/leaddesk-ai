"""Frozen sentence embeddings + logistic regression; same split as ml/train.py.  GPU box: python ml/embed_eval.py [model ...]

Writes ml/embed_results.json. Needs: pip install sentence-transformers scikit-learn.
"""
import json
import sys
import time
from pathlib import Path

from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression

MODELS = sys.argv[1:] or ["BAAI/bge-small-en-v1.5", "BAAI/bge-base-en-v1.5", "intfloat/multilingual-e5-base"]
rows = [json.loads(line) for line in Path("ml/train_tickets.jsonl").read_text().splitlines()]
sets = {n: json.loads(Path(f).read_text()) for n, f in {"core": "data/tickets.json", "hard": "data/tickets_hard.json"}.items()}
report = {}
for name in MODELS:
    m = SentenceTransformer(name, device="cuda")
    pre = "query: " if "e5" in name else ""  # e5 models expect a prefix
    emb = lambda texts: m.encode([pre + t for t in texts], normalize_embeddings=True, batch_size=64)
    clf = LogisticRegression(C=10, max_iter=3000, class_weight="balanced").fit(emb([r["text"] for r in rows]), [r["category"] for r in rows])
    report[name] = {}
    for s, tickets in sets.items():
        t0 = time.time()
        pred = clf.predict(emb([f"{t['subject']}\n{t['body']}" for t in tickets]))
        ms = (time.time() - t0) * 1000 / len(tickets)
        want = [t["expected_category"] if isinstance(t["expected_category"], list) else [t["expected_category"]] for t in tickets]
        hits = [p in w for p, w in zip(pred, want)]
        report[name][s] = {"acc": round(sum(hits) / len(hits), 3), "ms_per_ticket": round(ms, 2),
                           "misses": [f"{t['id']}: expected {t['expected_category']}, got {p}" for t, p, h in zip(tickets, pred, hits) if not h]}
    print(name, {s: r["acc"] for s, r in report[name].items()}, report[name]["hard"]["misses"])
Path("ml/embed_results.json").write_text(json.dumps(report, indent=1))
