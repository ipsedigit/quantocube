import re
import sqlite3
from pathlib import Path

_LEGAL_RE = re.compile(
    r"\s*\b(s\.?p\.?a\.?|s\.?r\.?l\.?|s\.?n\.?c\.?|s\.?a\.?s\.?|s\.?c\.?a\.?r\.?l\.?)\b\s*",
    re.IGNORECASE,
)


def _normalize_fornitore(name: str) -> str:
    """Lowercase, strip legal suffixes (s.p.a., s.r.l., …), collapse whitespace."""
    name = _LEGAL_RE.sub(" ", name)
    name = " ".join(name.lower().split())
    return name.strip(" .")

DB_PATH = Path(__file__).parent / "data" / "bills.db"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
        conn.execute("""
            CREATE TABLE IF NOT EXISTS bollette_voci (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                bolletta_id    INTEGER NOT NULL REFERENCES bollette(id) ON DELETE CASCADE,
                nome           TEXT NOT NULL,
                importo        REAL NOT NULL,
                periodo_inizio DATE,
                periodo_fine   DATE
            )
        """)


def insert_bill(data: dict, db_path: Path = DB_PATH) -> int:
    data = dict(data)
    data["fornitore"] = _normalize_fornitore(data["fornitore"])

    with get_connection(db_path) as conn:
        existing = conn.execute(
            """
            SELECT id FROM bollette
            WHERE tipo = ? AND fornitore = ?
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


def update_consumption(
    bill_id: int,
    consumo: float,
    unita_consumo: str,
    db_path: Path = DB_PATH,
) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE bollette SET consumo = ?, unita_consumo = ? WHERE id = ?",
            [consumo, unita_consumo, bill_id],
        )


def delete_bill(bill_id: int, db_path: Path = DB_PATH) -> None:
    with get_connection(db_path) as conn:
        conn.execute("DELETE FROM bollette WHERE id = ?", [bill_id])


def cleanup_duplicates(db_path: Path = DB_PATH) -> int:
    """Normalize all fornitore values and delete duplicate bills.

    Two bills are duplicates when tipo + fornitore (normalized) + periodo coincide.
    Among duplicates, the row with consumo NOT NULL is kept; otherwise the lowest id.
    Returns the number of deleted rows.
    """
    with get_connection(db_path) as conn:
        # Normalize existing fornitori.
        rows = conn.execute("SELECT id, fornitore FROM bollette").fetchall()
        for row in rows:
            normalized = _normalize_fornitore(row["fornitore"])
            if normalized != row["fornitore"]:
                conn.execute(
                    "UPDATE bollette SET fornitore = ? WHERE id = ?",
                    [normalized, row["id"]],
                )

        # Find groups with more than one row after normalization.
        groups = conn.execute("""
            SELECT tipo, fornitore, periodo_inizio, periodo_fine
            FROM bollette
            GROUP BY tipo, fornitore, periodo_inizio, periodo_fine
            HAVING COUNT(*) > 1
        """).fetchall()

        deleted = 0
        for g in groups:
            members = conn.execute("""
                SELECT id FROM bollette
                WHERE tipo = ? AND fornitore = ?
                  AND periodo_inizio = ? AND periodo_fine = ?
                ORDER BY (consumo IS NOT NULL) DESC, id ASC
            """, [g["tipo"], g["fornitore"], g["periodo_inizio"], g["periodo_fine"]]).fetchall()

            for row in members[1:]:
                conn.execute("DELETE FROM bollette WHERE id = ?", [row["id"]])
                deleted += 1

        # Second pass: deduplicate by file_pdf — same PDF can never be two distinct bills.
        pdf_groups = conn.execute("""
            SELECT file_pdf, COUNT(*) as cnt
            FROM bollette
            WHERE file_pdf IS NOT NULL
            GROUP BY file_pdf
            HAVING cnt > 1
        """).fetchall()

        for g in pdf_groups:
            members = conn.execute("""
                SELECT id FROM bollette
                WHERE file_pdf = ?
                ORDER BY (consumo IS NOT NULL) DESC, id ASC
            """, [g["file_pdf"]]).fetchall()

            for row in members[1:]:
                conn.execute("DELETE FROM bollette WHERE id = ?", [row["id"]])
                deleted += 1

    return deleted
