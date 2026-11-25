import json
import os
from pathlib import Path

import requests

from .models import Result

API_URL = "https://api.monday.com/v2"
# ponytail: hardcoded column ids; copy real ids from your board (column menu > "Column id")
COLUMNS = {"status": "status", "priority": "priority", "category": "text", "client": "text0", "summary": "long_text"}
MUTATION = """mutation ($board: ID!, $name: String!, $vals: JSON!) {
  create_item (board_id: $board, item_name: $name, column_values: $vals) { id }
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
