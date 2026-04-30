import pytest
import db
import dashboard

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
        "periodo_inizio": "2025-01-01", "periodo_fine": "2025-01-31",
        "importo_totale": 95.00, "consumo": 140.0, "unita_consumo": "kWh",
        "tariffa": "monoraria", "scadenza_pagamento": "2025-02-15",
        "file_pdf": None, "file_md": None,
    },
    {
        "tipo": "gas", "fornitore": "ENI",
        "periodo_inizio": "2024-01-01", "periodo_fine": "2024-01-31",
        "importo_totale": 120.00, "consumo": None, "unita_consumo": None,
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


def test_get_bill_types(pdb):
    types = dashboard.get_bill_types(pdb)
    assert types == ["gas", "luce"]


def test_get_bill_types_empty_db(tmp_path):
    db_path = tmp_path / "empty.db"
    db.init_db(db_path)
    assert dashboard.get_bill_types(db_path) == []


def test_get_bills_for_type_returns_correct_rows(pdb):
    bills = dashboard.get_bills_for_type("luce", pdb)
    assert len(bills) == 2
    assert all(b["tipo"] == "luce" for b in bills)


def test_get_bills_for_type_ordered_desc(pdb):
    bills = dashboard.get_bills_for_type("luce", pdb)
    assert bills[0]["periodo_fine"] == "2025-01-31"
    assert bills[1]["periodo_fine"] == "2024-01-31"


def test_get_bills_for_type_unknown_tipo(pdb):
    bills = dashboard.get_bills_for_type("acqua", pdb)
    assert bills == []


def test_build_spending_chart_returns_figure(pdb):
    bills = dashboard.get_bills_for_type("luce", pdb)
    fig = dashboard.build_spending_chart(bills)
    assert fig is not None
    # verifica che l'asse X contenga i dati corretti
    assert len(fig.data) == 1
    assert len(fig.data[0].x) == 2


def test_build_consumption_chart_with_data(pdb):
    bills = dashboard.get_bills_for_type("luce", pdb)
    fig = dashboard.build_consumption_chart(bills)
    assert fig is not None
    assert len(fig.data[0].x) == 2


def test_build_consumption_chart_no_data(pdb):
    bills = dashboard.get_bills_for_type("gas", pdb)
    fig = dashboard.build_consumption_chart(bills)
    assert fig is None


def test_build_yearly_chart_groups_by_year(pdb):
    bills = dashboard.get_bills_for_type("luce", pdb)
    fig = dashboard.build_yearly_chart(bills)
    assert fig is not None
    # luce ha bollette in 2024 e 2025 → 2 barre
    assert len(fig.data[0].x) == 2


def test_build_yearly_chart_single_year(pdb):
    bills = dashboard.get_bills_for_type("gas", pdb)
    fig = dashboard.build_yearly_chart(bills)
    assert fig is not None
    assert len(fig.data[0].x) == 1


def test_build_spending_chart_empty_rows():
    assert dashboard.build_spending_chart([]) is None


def test_build_yearly_chart_empty_rows():
    assert dashboard.build_yearly_chart([]) is None


VOCI = [
    {"nome": "TIM CONNECT Premium XDSL", "importo": 33.90, "periodo_inizio": "2026-03-01", "periodo_fine": "2026-03-31"},
    {"nome": "Massima Velocità", "importo": 5.00, "periodo_inizio": "2026-03-01", "periodo_fine": "2026-03-31"},
    {"nome": "TIMVISION Light", "importo": 4.99, "periodo_inizio": "2026-03-01", "periodo_fine": "2026-03-31"},
]


def test_build_voci_chart_returns_figure():
    fig = dashboard.build_voci_chart(VOCI)
    assert fig is not None
    assert len(fig.data) == 1
    assert len(fig.data[0].x) == 3  # three importo values on x-axis


def test_build_voci_chart_empty_returns_none():
    assert dashboard.build_voci_chart([]) is None


def test_build_voci_chart_correct_values():
    fig = dashboard.build_voci_chart(VOCI)
    # Horizontal bar: x = importo values, y = service names
    assert pytest.approx(33.90) in fig.data[0].x
    assert "TIM CONNECT Premium XDSL" in fig.data[0].y
