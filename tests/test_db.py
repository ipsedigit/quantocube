import pytest
from pathlib import Path
import db

@pytest.fixture
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    return db_path

SAMPLE_BILL = {
    "tipo": "luce",
    "fornitore": "Enel",
    "periodo_inizio": "2024-01-01",
    "periodo_fine": "2024-01-31",
    "importo_totale": 85.50,
    "consumo": 120.0,
    "unita_consumo": "kWh",
    "tariffa": "monoraria",
    "scadenza_pagamento": "2024-02-15",
    "file_pdf": "/bills/pdf/enel.pdf",
    "file_md": "/bills/md/enel.md",
}


def test_init_db_creates_table(tmp_db):
    with db.get_connection(tmp_db) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bollette'"
        )
        assert cursor.fetchone() is not None


def test_init_db_idempotent(tmp_db):
    db.init_db(tmp_db)  # second call must not raise
    with db.get_connection(tmp_db) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM bollette")
        assert cursor.fetchone()[0] == 0


def test_insert_bill_returns_id(tmp_db):
    row_id = db.insert_bill(SAMPLE_BILL, tmp_db)
    assert row_id == 1


def test_insert_bill_nullable_fields(tmp_db):
    data = {
        "tipo": "acqua",
        "fornitore": "ACEA",
        "periodo_inizio": "2024-01-01",
        "periodo_fine": "2024-03-31",
        "importo_totale": 45.00,
        "consumo": None,
        "unita_consumo": None,
        "tariffa": None,
        "scadenza_pagamento": None,
        "file_pdf": None,
        "file_md": None,
    }
    row_id = db.insert_bill(data, tmp_db)
    assert row_id == 1


def test_insert_multiple_bills(tmp_db):
    db.insert_bill(SAMPLE_BILL, tmp_db)
    db.insert_bill(
        {**SAMPLE_BILL, "periodo_inizio": "2024-02-01", "periodo_fine": "2024-02-29"},
        tmp_db,
    )
    with db.get_connection(tmp_db) as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM bollette")
        assert cursor.fetchone()[0] == 2


def test_insert_bill_round_trip(tmp_db):
    db.insert_bill(SAMPLE_BILL, tmp_db)
    with db.get_connection(tmp_db) as conn:
        row = conn.execute("SELECT * FROM bollette WHERE id = 1").fetchone()
    assert row["tipo"] == "luce"
    assert row["fornitore"] == "enel"
    assert row["importo_totale"] == pytest.approx(85.50)
    assert row["consumo"] == pytest.approx(120.0)
    assert row["file_pdf"] == "/bills/pdf/enel.pdf"


def test_init_db_creates_bollette_voci_table(tmp_db):
    with db.get_connection(tmp_db) as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='bollette_voci'"
        )
        assert cursor.fetchone() is not None


def test_init_db_bollette_voci_idempotent(tmp_db):
    db.init_db(tmp_db)  # second call must not raise
    with db.get_connection(tmp_db) as conn:
        count = conn.execute("SELECT COUNT(*) FROM bollette_voci").fetchone()[0]
    assert count == 0
