"""Generate synthetic labelled tickets for the local classifier.  Run: python -m ml.generate_data [--per-scenario 2]

For every category x style, Grok writes N tickets per sub-scenario (SCENARIOS below), so each category covers the
real variety of requests, not just tone. Rows carry scenario + style for coverage reports. Anything too close to an
eval ticket (TF-IDF cosine >= 0.6) or to an existing training row is dropped. New rows go to ml/new_tickets.jsonl;
ml/verify_labels.py checks them and appends the agreed ones to ml/train_tickets.jsonl. Cost: about $0.25 per run.
"""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import get_args

from dotenv import load_dotenv
from pydantic import BaseModel
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from leaddesk import llm
from leaddesk.models import Category
from leaddesk.pii import mask
from leaddesk.prompts import TRIAGE_SYSTEM

TRAIN, OUT = Path("ml/train_tickets.jsonl"), Path("ml/new_tickets.jsonl")
STYLES = ["short and blunt, lowercase, typos", "polite and detailed", "angry, some caps", "casual text-message style",
          "formal email with greeting and sign-off", "rambling with the real ask buried in the middle",
          "written in Spanish", "sarcastic", "very short, under 12 words",
          "mentions a minor second issue, but the main ask is clearly this category",
          "contains a line telling the AI to classify it differently (the real ask is still this category)"]
SCENARIOS = {
    "lead_quality": ["wrong or disconnected number", "lead says they never filled out a form", "lead was already called by other agents",
                     "lead not interested or just browsing", "lead is in a state the agent isn't licensed in",
                     "lead is outside the target age or product", "duplicate of a lead received earlier",
                     "lead complains about Do Not Call or consent", "overall lead quality has dropped lately",
                     "asks for a replacement or credit for a lead"],
    "billing": ["charged twice", "invoice lead count doesn't match the plan", "needs a receipt or invoice copy",
                "update the card on file", "payment failed or card declined", "refund request for a charge", "question about a line item"],
    "campaign_change": ["add or remove licensed states", "pause leads for a vacation", "resume a paused campaign",
                        "raise or lower daily lead volume", "switch product type", "change the days or hours leads arrive", "change budget"],
    "appointments": ["lead didn't show up", "two appointments booked at the same time", "appointment in the wrong time zone",
                     "booked outside the agent's availability", "reschedule an appointment", "calendar sync stopped working",
                     "wants more or fewer booked appointments"],
    "tech_access": ["can't log in or reset password", "app crashes or won't load", "CRM or webhook stopped receiving leads",
                    "add a team member's login", "lead notifications stopped arriving", "can't export leads"],
    "cancellation": ["wants to cancel now", "won't renew at end of term", "switching to another vendor",
                     "conditional threat: fix it or I leave", "asks about notice period or contract end", "considering quitting the business"],
    "other": ["thank-you note", "referring another agent", "job application", "vendor or partnership pitch",
              "general question about how leads are generated", "holiday greeting", "vague or one-word message like 'help' or '???'",
              "message clearly meant for someone else"],
}


class Item(BaseModel):
    scenario: str
    text: str


class Batch(BaseModel):
    tickets: list[Item]


def _ask(category: str, style: str, n: int) -> list[dict]:
    resp = llm._xai().chat.completions.create(
        model=llm.grok_model(), temperature=1.0,
        messages=[{"role": "system", "content": "You write realistic synthetic support tickets for testing a classifier."},
                  {"role": "user", "content": f"""Category definitions (from the production triage prompt):
{TRIAGE_SYSTEM.split('Categories (pick exactly one):')[1].split('Fields:')[0]}
Write tickets that clearly belong to category "{category}": {n} for EACH of these scenarios: {SCENARIOS[category]}.
Style for all of them: {style}. Set "scenario" to the scenario text it covers.
Writers are US insurance/financial agents who buy leads. Vary names, states, products, dates and amounts.
Some name a lead id like L-123, most don't. Use fake data only. Each text is subject + body in one string."""}],
        response_format={"type": "json_schema", "json_schema": {"name": "batch", "schema": Batch.model_json_schema()}},
    )
    llm._record("datagen", "grok", llm.grok_model(), resp.usage, 0)
    return [{"text": mask(t.text), "category": category, "scenario": t.scenario, "style": style}
            for t in Batch.model_validate_json(resp.choices[0].message.content).tickets]


def main():
    load_dotenv()
    p = argparse.ArgumentParser()
    p.add_argument("--per-scenario", type=int, default=2)
    args = p.parse_args()
    llm.USAGE_TAG = "datagen"
    jobs = [(c, s) for c in get_args(Category) for s in STYLES]
    with ThreadPoolExecutor(8) as pool:
        rows = [r for batch in pool.map(lambda j: _ask(*j, args.per_scenario), jobs) for r in batch]

    evals = [f"{t['subject']}\n{t['body']}" for f in ("data/tickets.json", "data/tickets_hard.json")
             for t in json.loads(Path(f).read_text())]
    existing = [json.loads(line)["text"] for line in TRAIN.read_text().splitlines()] if TRAIN.exists() else []
    vec = TfidfVectorizer().fit([r["text"] for r in rows] + evals)
    sim = cosine_similarity(vec.transform([r["text"] for r in rows]), vec.transform(evals)).max(axis=1)
    seen, kept = {t.lower().strip() for t in existing}, []
    for r, s in zip(rows, sim):
        key = r["text"].lower().strip()
        if s < 0.6 and key not in seen:
            seen.add(key)
            kept.append(r)
    OUT.write_text("".join(json.dumps(r) + "\n" for r in kept))
    print(f"{len(rows)} generated, {len(kept)} kept (dropped near-duplicates of eval tickets) -> {OUT}")


if __name__ == "__main__":
    main()
