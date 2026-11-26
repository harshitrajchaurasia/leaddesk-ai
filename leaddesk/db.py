import json
import sqlite3
from pathlib import Path

from .models import CallResult, Client, Lead, Result

# ponytail: JSON blobs keyed by id; normalise columns if we ever query by field
SCHEMA = """
create table if not exists clients (id text primary key, data text not null);
create table if not exists leads (id text primary key, data text not null);
create table if not exists results (ticket_id text primary key, created_at text default current_timestamp, data text not null);
create table if not exists webhook_claims (id text primary key, at text default current_timestamp);
create table if not exists escalations (ticket_id text primary key, at text default current_timestamp);
create table if not exists calls (id text primary key, created_at text default current_timestamp, data text not null);
"""


def connect(path: str = "leaddesk.db") -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.executescript(SCHEMA)
    return conn


def seed(conn: sqlite3.Connection, data_dir: str = "data") -> None:
    d = Path(data_dir)
    for table, file in (("clients", "clients.json"), ("leads", "leads.json")):
        rows = [(r["id"], json.dumps(r)) for r in json.loads((d / file).read_text())]
        conn.executemany(f"insert or replace into {table} (id, data) values (?, ?)", rows)
    conn.commit()


def _get(conn, table: str, id_: str) -> str | None:
    row = conn.execute(f"select data from {table} where id = ?", (id_,)).fetchone()
    return row[0] if row else None


def get_client(conn, client_id: str) -> Client | None:
    data = _get(conn, "clients", client_id)
    return Client.model_validate_json(data) if data else None


def list_clients(conn) -> list[Client]:
    return [Client.model_validate_json(r[0]) for r in conn.execute("select data from clients order by id")]


def get_lead(conn, lead_id: str) -> Lead | None:
    data = _get(conn, "leads", lead_id)
    return Lead.model_validate_json(data) if data else None


def save_result(conn, result: Result) -> None:
    conn.execute(
        "insert into results (ticket_id, data) values (?, ?) "
        "on conflict(ticket_id) do update set data = excluded.data",
        (result.ticket.id, result.model_dump_json()),
    )
    conn.commit()


def get_result(conn, ticket_id: str) -> Result | None:
    row = conn.execute("select data from results where ticket_id = ?", (ticket_id,)).fetchone()
    return Result.model_validate_json(row[0]) if row else None


def list_results(conn) -> list[Result]:
    rows = conn.execute("select data from results order by created_at desc, rowid desc")
    return [Result.model_validate_json(r[0]) for r in rows]


def save_call(conn, result: CallResult) -> None:
    conn.execute("insert into calls (id, data) values (?, ?) on conflict(id) do update set data = excluded.data",
                 (result.id, result.model_dump_json()))
    conn.commit()


def list_calls(conn) -> list[CallResult]:
    rows = conn.execute("select data from calls order by created_at desc, rowid desc")
    return [CallResult.model_validate_json(r[0]) for r in rows]


def claim(conn, ticket_id: str) -> bool:
    """True for the first caller only (webhook idempotency across concurrent retries)."""
    cur = conn.execute("insert or ignore into webhook_claims (id) values (?)", (ticket_id,))
    conn.commit()
    return cur.rowcount == 1


def unmark_escalated(conn, ticket_id: str) -> None:
    conn.execute("delete from escalations where ticket_id = ?", (ticket_id,))
    conn.commit()


def release(conn, ticket_id: str) -> None:
    conn.execute("delete from webhook_claims where id = ?", (ticket_id,))
    conn.commit()


def mark_escalated(conn, ticket_id: str) -> bool:
    """True the first time only, so an overdue ticket is escalated once."""
    cur = conn.execute("insert or ignore into escalations (ticket_id) values (?)", (ticket_id,))
    conn.commit()
    return cur.rowcount == 1
