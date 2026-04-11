import pytest
from pathlib import Path
import db
import tools

BILLS = [
    {
        "tipo": "luce", "fornitore": "Enel",
        "periodo_inizio": "2024-01-01", "periodo_fine": "2024-01-31",
        "importo_totale": 85.50, "consumo": 120.0, "unita_consumo": "kWh",
        "tariffa": "monoraria", "scadenza_pagamento": "2024-02-15",
        "file_pdf": None, "file_md": None,
    },
    {
        "tipo": "luce", "fornitore": "Enel",
        "periodo_inizio": "2024-02-01", "periodo_fine": "2024-02-29",
        "importo_totale": 92.00, "consumo": 135.0, "unita_consumo": "kWh",
        "tariffa": "monoraria", "scadenza_pagamento": "2024-03-15",
        "file_pdf": None, "file_md": None,
    },
    {
        "tipo": "gas", "fornitore": "ENI",
        "periodo_inizio": "2024-01-01", "periodo_fine": "2024-01-31",
        "importo_totale": 120.00, "consumo": 55.0, "unita_consumo": "m³",
        "tariffa": "standard", "scadenza_pagamento": "2024-02-15",
        "file_pdf": None, "file_md": None,
    },
]


@pytest.fixture
def pdb(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    for bill in BILLS:
        db.insert_bill(bill, db_path)
    return db_path


def test_get_spending_all(pdb):
    rows = tools.get_spending(db_path=pdb)
    assert len(rows) == 3


def test_get_spending_by_tipo(pdb):
    rows = tools.get_spending(tipo="luce", db_path=pdb)
    assert len(rows) == 2
    total = sum(r["importo_totale"] for r in rows)
    assert total == pytest.approx(177.50)


def test_get_spending_by_period(pdb):
    rows = tools.get_spending(da="2024-02-01", a="2024-02-29", db_path=pdb)
    assert len(rows) == 1
    assert rows[0]["importo_totale"] == pytest.approx(92.00)


def test_get_consumption_by_tipo(pdb):
    rows = tools.get_consumption(tipo="gas", db_path=pdb)
    assert len(rows) == 1
    assert rows[0]["consumo"] == pytest.approx(55.0)
    assert rows[0]["unita_consumo"] == "m³"


def test_get_latest_bill(pdb):
    row = tools.get_latest_bill(tipo="luce", db_path=pdb)
    assert row is not None
    assert row["periodo_fine"] == "2024-02-29"


def test_get_latest_bill_not_found(pdb):
    row = tools.get_latest_bill(tipo="acqua", db_path=pdb)
    assert row is None


def test_get_trend_importo(pdb):
    rows = tools.get_trend(tipo="luce", db_path=pdb)
    assert len(rows) == 2
    assert rows[0]["data"] == "2024-01-31"
    assert rows[0]["valore"] == pytest.approx(85.50)
    assert rows[0]["tipo"] == "luce"


def test_get_trend_consumo(pdb):
    rows = tools.get_trend(tipo="luce", metrica="consumo", db_path=pdb)
    assert rows[0]["valore"] == pytest.approx(120.0)


def test_compare_periods(pdb):
    result = tools.compare_periods(
        tipo="luce",
        periodo1_inizio="2024-01-01", periodo1_fine="2024-01-31",
        periodo2_inizio="2024-02-01", periodo2_fine="2024-02-29",
        db_path=pdb,
    )
    assert result["periodo1"]["importo_totale"] == pytest.approx(85.50)
    assert result["periodo2"]["importo_totale"] == pytest.approx(92.00)
    assert result["variazione_importo"] == pytest.approx(6.50)


def test_get_trend_with_date_filter(pdb):
    rows = tools.get_trend(tipo="luce", da="2024-02-01", db_path=pdb)
    assert len(rows) == 1
    assert rows[0]["data"] == "2024-02-29"


def test_get_trend_invalid_metrica(pdb):
    with pytest.raises(ValueError):
        tools.get_trend(tipo="luce", metrica="invalid", db_path=pdb)


def test_compare_periods_variazione_consumo(pdb):
    result = tools.compare_periods(
        tipo="luce",
        periodo1_inizio="2024-01-01", periodo1_fine="2024-01-31",
        periodo2_inizio="2024-02-01", periodo2_fine="2024-02-29",
        db_path=pdb,
    )
    assert result["variazione_consumo"] == pytest.approx(15.0)  # 135 - 120
