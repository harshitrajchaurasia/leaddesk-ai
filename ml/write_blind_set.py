"""Write a blind eval set: python -m ml.write_blind_set  ->  data/tickets_blind.json (then review every label by hand).

The hard set's sub-scenarios fed into the generator brief (ml/generate_data.py), so it no longer tells us how the
model handles tickets nobody planned for. This set is written by a different model family (Claude Sonnet, not Grok),
from a brief that describes the business only: no scenario list, no style list. Cost: about $0.05.
"""
import json
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

from leaddesk import db, llm
from leaddesk.models import Category
from leaddesk.prompts import TRIAGE_SYSTEM

OUT = Path("data/tickets_blind.json")
QUEUE = {"lead_quality": "lead_ops", "billing": "billing", "campaign_change": "campaign_ops", "appointments": "account_manager",
         "tech_access": "support", "cancellation": "account_manager", "other": "human_review"}  # routing.py defaults


class Msg(BaseModel):
    client_id: str
    channel: str
    subject: str
    body: str
    category: Category
    also_acceptable: list[Category]


class Inbox(BaseModel):
    messages: list[Msg]


def main():
    load_dotenv()
    llm.USAGE_TAG = "datagen"
    conn = db.connect(":memory:")
    db.seed(conn)
    clients = "\n".join(f"- {c.id}: {c.name} ({c.vertical}, states {', '.join(c.states)})" for c in db.list_clients(conn))
    cats = TRIAGE_SYSTEM.split("Categories (pick exactly one):")[1].split("Fields:")[0]
    resp = llm._anthropic().messages.parse(
        model="claude-sonnet-5-5", max_tokens=16000,
        messages=[{"role": "user", "content": f"""Acme Leads sells exclusive leads (from Meta ads) to US insurance and
financial agents, and books appointments for some of them. Write 36 support messages exactly as they would land in the
Acme support inbox over a normal month, from these clients:
{clients}

Write them the way real agents write: whatever they actually need, in their own words. Use channel "email", "form" or
"webhook". Fake data only (names, ids like L-123 if the agent names a lead). Cover every category below at least 3 times,
the rest in realistic proportions. Then label each message with the one category a careful support lead would pick, and
list any other category that would also be defensible in also_acceptable (usually empty).

Categories:{cats}"""}],
        output_format=Inbox,
    )
    llm._record("datagen", "claude", "claude-sonnet-5-5", resp.usage, 0)
    rows = [{"id": f"B-{i:02d}", "client_id": m.client_id, "channel": m.channel, "received_at": "2026-11-24T10:00:00",
             "subject": m.subject, "body": m.body,
             "expected_category": [m.category, *m.also_acceptable] if m.also_acceptable else m.category,
             "expected_queue": QUEUE[m.category]} for i, m in enumerate(resp.parsed_output.messages, 1)]
    OUT.write_text("[\n" + ",\n".join("  " + json.dumps(r) for r in rows) + "\n]\n")
    print(f"{len(rows)} tickets -> {OUT}. Review every label and queue before using it.")


if __name__ == "__main__":
    main()
