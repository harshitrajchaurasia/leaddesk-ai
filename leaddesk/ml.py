"""Local ticket classifier: TF-IDF (word + char n-grams) + logistic regression.

Trained on synthetic tickets (ml/train_tickets.jsonl), never on the eval set. Runs in about 1 ms on CPU, costs nothing,
and works when every model API is down. Used as a second opinion next to the LLM and as the triage fallback.
"""
import re
from functools import lru_cache
from pathlib import Path

import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion, make_pipeline
from sklearn.feature_extraction.text import TfidfVectorizer

from .models import Triage

MODEL_PATH = Path(__file__).parent.parent / "models" / "triage_clf.joblib"


def build():
    features = FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)),  # typos, "cancelling"/"canceling"
    ])
    return make_pipeline(features, LogisticRegression(C=10, max_iter=2000, class_weight="balanced"))


@lru_cache(maxsize=1)
def _model():
    return joblib.load(MODEL_PATH) if MODEL_PATH.exists() else None


def predict(text: str) -> tuple[str, float] | None:
    """(category, probability) or None when no trained model is present."""
    m = _model()
    if m is None:
        return None
    probs = m.predict_proba([text])[0]
    i = probs.argmax()
    return str(m.classes_[i]), float(probs[i])


LEAD_ID = re.compile(r"\b(?:lead\s*#?|L)\s*-?\s*#?\s*\d+\b", re.I)


def triage(text: str, client=None) -> Triage | None:
    """A Triage from the local model alone: category + its probability as confidence, lead id by regex.

    Urgency/sentiment/churn stay neutral (the model doesn't predict them), so the routing rules still apply and a
    low-probability guess goes to human review. Used when the LLM triage fails, and as the "ml" eval provider.
    """
    p = predict(text)
    if p is None:
        return None
    m = LEAD_ID.search(text)
    return Triage(category=p[0], urgency="normal", sentiment="neutral", churn_risk=0.0, lead_id=m.group() if m else None,
                  summary="LLM unavailable: local model's category, needs a human check", confidence=round(p[1], 3))
