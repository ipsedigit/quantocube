from contextlib import closing
from pathlib import Path
from typing import Optional
import db

DB_PATH = db.DB_PATH


def get_spending(
    tipo: Optional[str] = None,
    da: Optional[str] = None,
    a: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    query = (
        "SELECT tipo, fornitore, periodo_inizio, periodo_fine, importo_totale "
        "FROM bollette WHERE 1=1"
    )
    params: list = []
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if da:
        query += " AND periodo_fine >= ?"
        params.append(da)
    if a:
        query += " AND periodo_inizio <= ?"
        params.append(a)
    query += " ORDER BY periodo_fine"
    with closing(db.get_connection(db_path)) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_consumption(
    tipo: Optional[str] = None,
    da: Optional[str] = None,
    a: Optional[str] = None,
    db_path: Path = DB_PATH,
) -> list[dict]:
    query = (
        "SELECT tipo, fornitore, periodo_inizio, periodo_fine, consumo, unita_consumo "
        "FROM bollette WHERE consumo IS NOT NULL"
    )
    params: list = []
    if tipo:
        query += " AND tipo = ?"
        params.append(tipo)
    if da:
        query += " AND periodo_fine >= ?"
        params.append(da)
    if a:
        query += " AND periodo_inizio <= ?"
        params.append(a)
    query += " ORDER BY periodo_fine"
    with closing(db.get_connection(db_path)) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_latest_bill(tipo: str, db_path: Path = DB_PATH) -> Optional[dict]:
    query = """
        SELECT tipo, fornitore, periodo_inizio, periodo_fine,
               importo_totale, consumo, unita_consumo, tariffa, scadenza_pagamento
        FROM bollette WHERE tipo = ?
        ORDER BY periodo_fine DESC LIMIT 1
    """
    with closing(db.get_connection(db_path)) as conn:
        row = conn.execute(query, [tipo]).fetchone()
    return dict(row) if row else None


def get_trend(
    tipo: str,
    da: Optional[str] = None,
    a: Optional[str] = None,
    metrica: str = "importo_totale",
    db_path: Path = DB_PATH,
) -> list[dict]:
    if metrica not in {"importo_totale", "consumo"}:
        raise ValueError(f"metrica non valida: {metrica!r}. Valori accettati: importo_totale, consumo")
    query = (
        f"SELECT periodo_fine AS data, {metrica} AS valore, tipo "
        "FROM bollette WHERE tipo = ?"
    )
    params: list = [tipo]
    if da:
        query += " AND periodo_fine >= ?"
        params.append(da)
    if a:
        query += " AND periodo_inizio <= ?"
        params.append(a)
    query += " ORDER BY periodo_fine"
    with closing(db.get_connection(db_path)) as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def compare_periods(
    tipo: str,
    periodo1_inizio: str,
    periodo1_fine: str,
    periodo2_inizio: str,
    periodo2_fine: str,
    db_path: Path = DB_PATH,
) -> dict:
    def _fetch(inizio: str, fine: str) -> dict:
        query = """
            SELECT COALESCE(SUM(importo_totale), 0) AS importo_totale,
                   COALESCE(SUM(consumo), 0)        AS consumo
            FROM bollette
            WHERE tipo = ? AND periodo_inizio <= ? AND periodo_fine >= ?
        """
        with closing(db.get_connection(db_path)) as conn:
            row = conn.execute(query, [tipo, fine, inizio]).fetchone()
        return {"importo_totale": row["importo_totale"], "consumo": row["consumo"]}

    p1 = _fetch(periodo1_inizio, periodo1_fine)
    p2 = _fetch(periodo2_inizio, periodo2_fine)
    return {
        "periodo1": p1,
        "periodo2": p2,
        "variazione_importo": round(p2["importo_totale"] - p1["importo_totale"], 2),
        "variazione_consumo": round(p2["consumo"] - p1["consumo"], 2),
    }
