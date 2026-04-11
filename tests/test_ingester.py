import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import db
import ingester

EXTRACTED = {
    "tipo": "luce",
    "fornitore": "Enel",
    "periodo_inizio": "2024-01-01",
    "periodo_fine": "2024-01-31",
    "importo_totale": 85.50,
    "consumo": 120.0,
    "unita_consumo": "kWh",
    "tariffa": "monoraria",
    "scadenza_pagamento": "2024-02-15",
}


@pytest.fixture
def setup(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    md_dir = tmp_path / "md"
    pdf_path = tmp_path / "enel.pdf"
    pdf_path.write_bytes(b"%PDF fake")
    return db_path, md_dir, pdf_path


def test_ingest_pdf_returns_bill_data(setup):
    db_path, md_dir, pdf_path = setup
    mock_resp = MagicMock()
    mock_resp.message.content = json.dumps(EXTRACTED)

    with patch("ingester.pymupdf4llm.to_markdown", return_value="# Bolletta\nImporto: 85.50"):
        with patch("ingester.ollama.chat", return_value=mock_resp):
            result = ingester.ingest_pdf(pdf_path, db_path=db_path, md_dir=md_dir)

    assert result["tipo"] == "luce"
    assert result["importo_totale"] == pytest.approx(85.50)


def test_ingest_pdf_saves_markdown(setup):
    db_path, md_dir, pdf_path = setup
    mock_resp = MagicMock()
    mock_resp.message.content = json.dumps(EXTRACTED)

    with patch("ingester.pymupdf4llm.to_markdown", return_value="# Bolletta"):
        with patch("ingester.ollama.chat", return_value=mock_resp):
            ingester.ingest_pdf(pdf_path, db_path=db_path, md_dir=md_dir)

    md_files = list(md_dir.glob("*.md"))
    assert len(md_files) == 1


def test_ingest_pdf_inserts_into_db(setup):
    db_path, md_dir, pdf_path = setup
    mock_resp = MagicMock()
    mock_resp.message.content = json.dumps(EXTRACTED)

    with patch("ingester.pymupdf4llm.to_markdown", return_value="# Bolletta"):
        with patch("ingester.ollama.chat", return_value=mock_resp):
            ingester.ingest_pdf(pdf_path, db_path=db_path, md_dir=md_dir)

    with db.get_connection(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM bollette").fetchone()[0]
    assert count == 1


def test_ingest_pdf_strips_json_code_fence(setup):
    """LLM sometimes wraps the JSON in a markdown code block."""
    db_path, md_dir, pdf_path = setup
    mock_resp = MagicMock()
    mock_resp.message.content = f"```json\n{json.dumps(EXTRACTED)}\n```"

    with patch("ingester.pymupdf4llm.to_markdown", return_value="# Bolletta"):
        with patch("ingester.ollama.chat", return_value=mock_resp):
            result = ingester.ingest_pdf(pdf_path, db_path=db_path, md_dir=md_dir)

    assert result["tipo"] == "luce"


def test_parse_json_raises_on_invalid_json():
    """Malformed LLM output raises ValueError, not JSONDecodeError."""
    with pytest.raises(ValueError, match="LLM returned invalid JSON"):
        ingester._parse_json("not-valid-json")


def test_parse_json_raises_on_fenced_invalid_json():
    """Malformed JSON inside a code fence also raises ValueError."""
    with pytest.raises(ValueError, match="LLM returned invalid JSON"):
        ingester._parse_json("```json\nnot-valid\n```")


def test_extract_bill_data_raises_on_missing_fields(setup):
    """If LLM omits required fields, raises ValueError."""
    db_path, md_dir, pdf_path = setup
    incomplete = {"tipo": "luce"}  # missing fornitore, periodo_inizio, etc.
    mock_resp = MagicMock()
    mock_resp.message.content = json.dumps(incomplete)

    with pytest.raises(ValueError, match="Campi mancanti"):
        with patch("ingester.ollama.chat", return_value=mock_resp):
            ingester.extract_bill_data("# Bolletta")
