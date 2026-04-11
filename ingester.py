import json
import re
from functools import lru_cache
from pathlib import Path
import ollama
import pymupdf4llm
import db

_MODEL = "qwen2.5:7b"
_FALLBACK_MODEL = "llama3.2:3b"


@lru_cache(maxsize=1)
def _get_model() -> str:
    try:
        available = [m.model for m in ollama.list().models]
        if any(_MODEL in m for m in available):
            return _MODEL
        if any(_FALLBACK_MODEL in m for m in available):
            return _FALLBACK_MODEL
    except Exception:
        pass
    return _MODEL


MD_DIR = Path(__file__).parent / "bills" / "md"

EXTRACTION_PROMPT = """\
Sei un estrattore di dati da bollette italiane. Analizza il testo della bolletta \
e restituisci un JSON con ESATTAMENTE questi nomi di campo:

{{
  "tipo": "gas",
  "fornitore": "ENI",
  "periodo_inizio": "2024-01-01",
  "periodo_fine": "2024-03-31",
  "importo_totale": 123.45,
  "consumo": 55.0,
  "unita_consumo": "Smc",
  "tariffa": "Prezzo fisso",
  "scadenza_pagamento": "2024-04-15"
}}

Regole:
- tipo: "luce", "gas", "acqua" o "telefono" (minuscolo)
- periodo_inizio e periodo_fine: OBBLIGATORIO, formato YYYY-MM-DD.
  Sono le date di INIZIO e FINE del periodo di fatturazione effettivo di questa bolletta.
  Cerca la tabella delle letture contatore (es. "31.12.2025 28.02.2026") o la sezione
  "Periodo dal ... al ..." riferita ai consumi fatturati.
  ATTENZIONE: ignora le frasi come "determinato dal X al Y" o "consumo annuo dal X al Y"
  che indicano il periodo di riferimento annuo dell'offerta, NON il periodo della bolletta.
  Converti le date italiane: "01 Gennaio 2026" → "2026-01-01",
  "28 Febbraio 2026" → "2026-02-28", "31 Marzo 2026" → "2026-03-31".
  Converti le date numeriche: "31.12.2025" → "2025-12-31", "28.02.2026" → "2026-02-28".
  Mesi: Gennaio=01, Febbraio=02, Marzo=03, Aprile=04, Maggio=05, Giugno=06,
  Luglio=07, Agosto=08, Settembre=09, Ottobre=10, Novembre=11, Dicembre=12.
- importo_totale: il "Totale da pagare" in euro, numero decimale (es. 194.00)
- consumo: consumo numerico fatturato, oppure null se non presente
- unita_consumo: unità di misura (es. "kWh", "Smc", "m³"), oppure null
- tariffa: tipo tariffa oppure null
- scadenza_pagamento: formato YYYY-MM-DD oppure null

Testo bolletta:
{markdown}
"""


def _parse_json(text: str) -> dict:
    """Strip optional markdown fences then parse JSON."""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        text = match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON: {text!r}") from exc


def pdf_to_markdown(pdf_path: Path) -> str:
    return pymupdf4llm.to_markdown(str(pdf_path))


def extract_bill_data(markdown: str) -> dict:
    prompt = EXTRACTION_PROMPT.format(markdown=markdown)
    response = ollama.chat(
        model=_get_model(),
        messages=[{"role": "user", "content": prompt}],
        format="json",
    )
    data = _parse_json(response.message.content)
    required = {"tipo", "fornitore", "periodo_inizio", "periodo_fine", "importo_totale"}
    missing = required - data.keys()
    if missing:
        raise ValueError(f"Campi mancanti nell'estrazione LLM: {missing}")
    null_required = {k for k in required if data.get(k) is None}
    if null_required:
        raise ValueError(
            f"Campi obbligatori nulli nell'estrazione LLM: {null_required}. "
            f"Dati estratti: {data}"
        )
    return data


def _relevant_text(markdown: str, head: int = 3500, window: int = 1000) -> str:
    """Return the first `head` chars plus the window around the readings table.

    3500 chars captures tipo, fornitore, and importo_totale for typical Italian
    bills (these appear within the first 2-3 pages / ~3000 chars).
    The readings table (meter dates = real billing period) typically sits beyond
    that, so we locate it with a regex and append a focused window around it.
    """
    header = markdown[:head]
    # Look for a line with two dates close together (dd.mm.yyyy dd.mm.yyyy)
    # which is the signature of the meter readings table in Italian bills.
    match = re.search(r"\d{2}\.\d{2}\.\d{4}\s+\d{2}\.\d{2}\.\d{4}", markdown[head:])
    if match:
        start = head + max(0, match.start() - 100)
        snippet = markdown[start: start + window]
        return header + "\n\n[...]\n\n" + snippet
    # Fallback: extend the head without readings table
    return markdown[:head + window]


def ingest_pdf(
    pdf_path: Path,
    db_path: Path = db.DB_PATH,
    md_dir: Path = MD_DIR,
) -> dict:
    md_dir.mkdir(parents=True, exist_ok=True)
    markdown = pdf_to_markdown(pdf_path)

    md_path = md_dir / (pdf_path.stem + ".md")
    md_path.write_text(markdown, encoding="utf-8")

    data = extract_bill_data(_relevant_text(markdown))
    data["file_pdf"] = str(pdf_path.resolve())
    data["file_md"] = str(md_path.resolve())

    db.insert_bill(data, db_path)
    return data
