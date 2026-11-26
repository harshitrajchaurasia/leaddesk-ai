import json
import logging
import os
from html import escape
from pathlib import Path

import requests

from .models import CallResult, Client, Result

API_URL = "https://api.monday.com/v2"
log = logging.getLogger(__name__)
# ponytail: hardcoded column ids of board "LeadDesk AI - Support Tickets"; other board = copy ids from column menu
COLUMNS = {"status": "color_mm9ee7h7", "priority": "color_mm9eks62", "category": "text_mm9edt4z", "client": "text_mm9e8may",
           "summary": "long_text_mm9ewh32"}
MUTATION = """mutation ($board: ID!, $name: String!, $vals: JSON!) {
  create_item (board_id: $board, item_name: $name, column_values: $vals, create_labels_if_missing: true) { id }
}"""


def column_values(result: Result) -> dict:
    return {
        COLUMNS["status"]: {"label": result.route.queue.replace("_", " ").title()},
        COLUMNS["priority"]: {"label": result.route.priority.title()},
        COLUMNS["category"]: result.triage.category,
        COLUMNS["client"]: result.ticket.client_id,
        COLUMNS["summary"]: {"text": result.triage.summary + (f"\nVerdict: {result.verdict.verdict}" if result.verdict else "")},
    }


def create_item(result: Result, *, token: str | None = None, board_id: str | None = None, post=requests.post,
                outbox_path: str = "data/outbox.jsonl") -> str | None:
    """Create a Monday item; on no token or any failure, append to a local outbox and return None."""
    token = token or os.getenv("MONDAY_API_TOKEN")
    board_id = board_id or os.getenv("MONDAY_BOARD_ID")
    if token and board_id:
        try:
            name = f"[{result.route.queue}] {result.ticket.client_id}: {result.triage.summary}"
            resp = post(API_URL, timeout=15, headers={"Authorization": token, "API-Version": "2024-10"},
                        json={"query": MUTATION, "variables": {"board": board_id, "name": name[:250],
                                                               "vals": json.dumps(column_values(result))}})
            return str(resp.json()["data"]["create_item"]["id"])
        except Exception:  # ponytail: any Monday failure -> outbox; add logging/alerting when this runs unattended
            pass
    Path(outbox_path).parent.mkdir(parents=True, exist_ok=True)
    with open(outbox_path, "a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")
    return None


CALL_MUTATIONS = {
    "item": "mutation ($board: ID!, $name: String!) { create_item (board_id: $board, item_name: $name) { id } }",
    "subitem": "mutation ($parent: ID!, $name: String!) { create_subitem (parent_item_id: $parent, item_name: $name) { id } }",
    "update": "mutation ($item: ID!, $body: String!) { create_update (item_id: $item, body: $body) { id } }",
}


def create_call_item(result: CallResult, client: Client, *, token: str | None = None, board_id: str | None = None,
                     post=requests.post, outbox_path: str = "data/outbox_calls.jsonl") -> str | None:
    """One item per call on the calls board, a subitem per action item, and the summary + alerts as an update.

    Uses only item names and updates, so it works on any board without column ids. Outbox on no token or failure.
    """
    token = token or os.getenv("MONDAY_API_TOKEN")
    board_id = board_id or os.getenv("MONDAY_CALLS_BOARD_ID")
    if token and board_id:
        def gql(kind, **variables):
            r = post(API_URL, timeout=15, headers={"Authorization": token, "API-Version": "2024-10"},
                     json={"query": CALL_MUTATIONS[kind], "variables": variables}).json()
            return str(next(iter(r["data"].values()))["id"])
        i = result.insight
        try:
            item = gql("item", board=board_id, name=f"{client.name}: call {result.id} (churn {i.churn_risk:.0%}, {i.sentiment})"[:250])
        except Exception as e:
            log.warning("monday call item failed: %r", e)
            item = None
        if item:  # the item exists: a failed subitem/update is logged, never turned into a duplicate via the outbox
            try:
                for a in i.action_items:
                    gql("subitem", parent=item, name=f"[{a.owner}] {a.task}" + (f" (due {a.due})" if a.due else ""))
                parts = [i.summary, *(f"<b>{escape(x)}</b>" for x in result.alerts)]
                if i.upsell_signals:
                    parts.append("Upsell: " + "; ".join(i.upsell_signals))
                if i.objections:
                    parts.append("Objections: " + "; ".join(i.objections))
                gql("update", item=item, body="".join(f"<p>{p if p.startswith('<b>') else escape(p)}</p>" for p in parts))
            except Exception as e:
                log.warning("monday call item %s incomplete: %r", item, e)
            return item
    Path(outbox_path).parent.mkdir(parents=True, exist_ok=True)
    with open(outbox_path, "a", encoding="utf-8") as f:
        f.write(result.model_dump_json() + "\n")
    return None
