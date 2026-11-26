"""Fine-tune a small transformer on the synthetic tickets; score on the hand-labelled sets.  GPU box: python ml/finetune.py

Same split as ml/train.py: train on ml/train_tickets.jsonl only, report held-out category accuracy on data/tickets.json
(core) and data/tickets_hard.json (hard). Writes ml/finetune_results.json. Needs: pip install transformers.
"""
import json
import random
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

MODEL = sys.argv[1] if len(sys.argv) > 1 else "distilbert-base-uncased"
EPOCHS, LR, BATCH, MAXLEN, SEED = 8, 5e-5, 16, 160, 0
random.seed(SEED)
torch.manual_seed(SEED)

rows = [json.loads(line) for line in Path("ml/train_tickets.jsonl").read_text().splitlines()]
labels = sorted({r["category"] for r in rows})
lid = {c: i for i, c in enumerate(labels)}
dev = "cuda" if torch.cuda.is_available() else "cpu"
tok = AutoTokenizer.from_pretrained(MODEL)
model = AutoModelForSequenceClassification.from_pretrained(MODEL, num_labels=len(labels)).to(dev)
opt = torch.optim.AdamW(model.parameters(), lr=LR)
steps = EPOCHS * ((len(rows) + BATCH - 1) // BATCH)
sched = torch.optim.lr_scheduler.LambdaLR(opt, lambda s: max(0.0, 1 - s / steps))


def enc(texts):
    return tok(texts, truncation=True, max_length=MAXLEN, padding=True, return_tensors="pt").to(dev)


start = time.time()
model.train()
for epoch in range(EPOCHS):
    random.shuffle(rows)
    total = 0.0
    for i in range(0, len(rows), BATCH):
        b = rows[i:i + BATCH]
        out = model(**enc([r["text"] for r in b]), labels=torch.tensor([lid[r["category"]] for r in b], device=dev))
        out.loss.backward()
        opt.step()
        sched.step()
        opt.zero_grad()
        total += out.loss.item() * len(b)
    print(f"epoch {epoch + 1}: loss {total / len(rows):.4f}")
train_s = time.time() - start

model.eval()
report = {"model": MODEL, "train_rows": len(rows), "train_seconds": round(train_s, 1), "device": dev}
for name, f in {"core": "data/tickets.json", "hard": "data/tickets_hard.json"}.items():
    tickets = json.loads(Path(f).read_text())
    with torch.no_grad():
        t0 = time.time()
        pred = model(**enc([f"{t['subject']}\n{t['body']}" for t in tickets])).logits.argmax(-1).tolist()
        ms = (time.time() - t0) * 1000 / len(tickets)
    want = [t["expected_category"] if isinstance(t["expected_category"], list) else [t["expected_category"]] for t in tickets]
    hits = [labels[p] in w for p, w in zip(pred, want)]
    report[name] = {"acc": round(sum(hits) / len(hits), 3), "ms_per_ticket": round(ms, 2),
                    "misses": [f"{t['id']}: expected {t['expected_category']}, got {labels[p]}"
                               for t, p, h in zip(tickets, pred, hits) if not h]}
    print(name, report[name])
Path("ml/finetune_results.json").write_text(json.dumps(report, indent=1))
