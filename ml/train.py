"""Train the local classifier and score it on the hand-labelled eval sets.  Run: python -m ml.train

Also prints: the closest training row to each eval set (word and char TF-IDF cosine), so leakage is visible, and a
leave-one-style-out CV on the rows that record their style (how well it handles a writing style it never saw).
"""
import json
from pathlib import Path

import joblib
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import GroupKFold, cross_val_score

from leaddesk import ml
from leaddesk.pii import mask

SETS = {"core": "data/tickets.json", "hard": "data/tickets_hard.json", "blind": "data/tickets_blind.json"}


def _closest(train: list[str], evals: list[str]) -> str:
    out = []
    for kind in ("word", "char_wb"):
        vec = TfidfVectorizer(analyzer=kind, ngram_range=(1, 1) if kind == "word" else (3, 5)).fit(train + evals)
        out.append(f"{kind} {cosine_similarity(vec.transform(evals), vec.transform(train)).max():.2f}")
    return ", ".join(out)


def main():
    rows = [json.loads(line) for line in Path("ml/train_tickets.jsonl").read_text().splitlines()]
    X, y = [r["text"] for r in rows], [r["category"] for r in rows]
    cv = cross_val_score(ml.build(), X, y, cv=5)
    styled = [r for r in rows if "style" in r]
    loso = cross_val_score(ml.build(), [r["text"] for r in styled], [r["category"] for r in styled],
                           groups=[r["style"] for r in styled], cv=GroupKFold(len({r["style"] for r in styled})))
    model = ml.build().fit(X, y)
    ml.MODEL_PATH.parent.mkdir(exist_ok=True)
    joblib.dump(model, ml.MODEL_PATH)
    print(f"trained on {len(rows)} synthetic tickets; 5-fold CV {cv.mean():.1%}, leave-one-style-out {loso.mean():.1%} "
          f"(min {loso.min():.1%}) (synthetic, optimistic)")
    for name, f in SETS.items():
        if not Path(f).exists():
            continue
        tickets = json.loads(Path(f).read_text())
        texts = [mask(f"{t['subject']}\n{t['body']}") for t in tickets]  # same input the app gives the model
        pred = model.predict(texts)
        want = [t["expected_category"] if isinstance(t["expected_category"], list) else [t["expected_category"]] for t in tickets]
        hits = [p in w for p, w in zip(pred, want)]
        print(f"{name}: {sum(hits)}/{len(hits)} = {sum(hits) / len(hits):.1%} held-out category accuracy "
              f"(closest training row: {_closest(X, texts)})")
        for t, p, h in zip(tickets, pred, hits):
            if not h:
                print(f"   miss {t['id']}: expected {t['expected_category']}, got {p}")


if __name__ == "__main__":
    main()
