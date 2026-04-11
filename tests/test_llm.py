import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import db
import llm


def _mock_response(content=None, tool_calls=None):
    msg = MagicMock()
    msg.content = content or ""
    msg.tool_calls = tool_calls or []
    msg.model_dump.return_value = {
        "role": "assistant",
        "content": content or "",
        "tool_calls": [],
    }
    resp = MagicMock()
    resp.message = msg
    return resp


@pytest.fixture(autouse=True)
def mock_model():
    with patch("llm.get_model", return_value="qwen2.5:7b"):
        yield


@pytest.fixture
def pdb(tmp_path):
    db_path = tmp_path / "test.db"
    db.init_db(db_path)
    db.insert_bill(
        {
            "tipo": "luce", "fornitore": "Enel",
            "periodo_inizio": "2024-01-01", "periodo_fine": "2024-01-31",
            "importo_totale": 85.50, "consumo": 120.0, "unita_consumo": "kWh",
            "tariffa": "monoraria", "scadenza_pagamento": "2024-02-15",
            "file_pdf": None, "file_md": None,
        },
        db_path,
    )
    return db_path


def test_chat_plain_response():
    messages = [{"role": "user", "content": "Ciao"}]
    with patch("llm.ollama.chat", return_value=_mock_response("Ciao! Come posso aiutarti?")):
        result = llm.chat(messages)
    assert result["text"] == "Ciao! Come posso aiutarti?"
    assert result["chart_data"] is None


def test_chat_with_get_spending_tool(pdb):
    tool_call = MagicMock()
    tool_call.function.name = "get_spending"
    tool_call.function.arguments = {"tipo": "luce"}

    with patch("llm.ollama.chat", side_effect=[
        _mock_response(tool_calls=[tool_call]),
        _mock_response("Hai speso 85,50€ per la luce."),
    ]):
        result = llm.chat(
            [{"role": "user", "content": "Quanto ho speso per la luce?"}],
            db_path=pdb,
        )
    assert result["text"] == "Hai speso 85,50€ per la luce."
    assert result["chart_data"] is None


def test_chat_with_get_trend_sets_chart_data(pdb):
    tool_call = MagicMock()
    tool_call.function.name = "get_trend"
    tool_call.function.arguments = {"tipo": "luce"}

    with patch("llm.ollama.chat", side_effect=[
        _mock_response(tool_calls=[tool_call]),
        _mock_response("Ecco il trend della luce."),
    ]):
        result = llm.chat(
            [{"role": "user", "content": "Mostrami il trend della luce"}],
            db_path=pdb,
        )
    assert result["chart_data"] is not None
    assert len(result["chart_data"]) == 1
    assert result["chart_data"][0]["valore"] == pytest.approx(85.50)
    assert result["text"] == "Ecco il trend della luce."


def test_chat_unknown_get_trend_tool_no_chart_data():
    """chart_data must NOT be set when get_trend tool name is unknown/not in TOOL_FN."""
    tool_call = MagicMock()
    tool_call.function.name = "get_trend_nonexistent"  # not in TOOL_FN
    tool_call.function.arguments = {"tipo": "luce"}

    with patch("llm.ollama.chat", side_effect=[
        _mock_response(tool_calls=[tool_call]),
        _mock_response("Non ho trovato dati."),
    ]):
        result = llm.chat([{"role": "user", "content": "test"}])
    assert result["chart_data"] is None
