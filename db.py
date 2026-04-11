import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "bills.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path = DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bollette (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL,
                fornitore TEXT NOT NULL,
                periodo_inizio DATE NOT NULL,
                periodo_fine DATE NOT NULL,
                importo_totale REAL NOT NULL,
                consumo REAL,
                unita_consumo TEXT,
                tariffa TEXT,
                scadenza_pagamento DATE,
                file_pdf TEXT,
                file_md TEXT
            )
        """)


def insert_bill(data: dict, db_path: Path = DB_PATH) -> int:
    with get_connection(db_path) as conn:
        existing = conn.execute(
            """
            SELECT id FROM bollette
            WHERE tipo = ? AND LOWER(fornitore) = LOWER(?)
              AND periodo_inizio = ? AND periodo_fine = ?
            """,
            [data["tipo"], data["fornitore"], data["periodo_inizio"], data["periodo_fine"]],
        ).fetchone()
        if existing:
            return existing["id"]

        cursor = conn.execute(
            """
            INSERT INTO bollette (
                tipo, fornitore, periodo_inizio, periodo_fine,
                importo_totale, consumo, unita_consumo, tariffa,
                scadenza_pagamento, file_pdf, file_md
            ) VALUES (
                :tipo, :fornitore, :periodo_inizio, :periodo_fine,
                :importo_totale, :consumo, :unita_consumo, :tariffa,
                :scadenza_pagamento, :file_pdf, :file_md
            )
            """,
            data,
        )
        return cursor.lastrowid


def delete_bill(bill_id: int, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM bollette WHERE id = ?", [bill_id])
