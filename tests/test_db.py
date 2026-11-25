from conftest import DATA_DIR, make_result

from leaddesk import db


def test_seed_idempotent(conn):
    db.seed(conn, DATA_DIR)
    assert len(db.list_clients(conn)) == 8


def test_get_lead_roundtrip(conn):
    lead = db.get_lead(conn, "L-105")
    assert lead.client_id == "C-01"
    assert lead.delivered_to_count == 3


def test_get_lead_missing_returns_none(conn):
    assert db.get_lead(conn, "L-999") is None
    assert db.get_client(conn, "C-99") is None


def test_save_result_upserts(conn):
    db.save_result(conn, make_result())
    db.save_result(conn, make_result(status="approved"))
    results = db.list_results(conn)
    assert len(results) == 1
    assert results[0].status == "approved"
