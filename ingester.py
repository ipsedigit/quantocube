import json
import re
from datetime import date, timedelta
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
- periodo_inizio e periodo_fine: metti "0000-00-00" come segnaposto, saranno
  calcolate automaticamente dal sistema — non devi calcolarle tu.
- importo_totale: il "Totale da pagare" in euro, numero decimale (es. 194.00)
- consumo: consumo numerico fatturato, oppure null se non presente
- unita_consumo: unità di misura (es. "kWh", "Smc", "m³"), oppure null
- tariffa: tipo tariffa oppure null
- scadenza_pagamento: formato YYYY-MM-DD oppure null

Testo bolletta:
{markdown}
"""

_MESI_IT = {
    "gennaio": "01", "febbraio": "02", "marzo": "03", "aprile": "04",
    "maggio": "05", "giugno": "06", "luglio": "07", "agosto": "08",
    "settembre": "09", "ottobre": "10", "novembre": "11", "dicembre": "12",
}


def _it_date(day: str, month: str, year: str) -> str | None:
    """Convert Italian word date components to YYYY-MM-DD, or None if unknown month."""
    m = _MESI_IT.get(month.strip().lower())
    return f"{year}-{m}-{day.zfill(2)}" if m else None


def _num_date(s: str) -> str:
    """Convert dd.mm.yyyy to YYYY-MM-DD."""
    d, m, y = s.split(".")
    return f"{y}-{m}-{d}"


def _extract_tipo(markdown: str) -> str | None:
    """Detect bill type from keywords in the markdown."""
    head = markdown[:3000].lower()
    if any(k in head for k in ("energia elettrica", "luce", "elettric", "kwh")):
        return "luce"
    if any(k in head for k in ("gas naturale", "gas", "smc", "metano")):
        return "gas"
    if any(k in head for k in ("acqua", "idric")):
        return "acqua"
    return None


def _extract_period_dates(markdown: str) -> dict | None:
    """Extract periodo_inizio / periodo_fine directly from markdown using regex.

    Two formats handled:
    1. Old A2A (picture-text): "bolletta per i consumi<br>dal DD Mese YYYY<br>al DD Mese YYYY"
       Dates are exact — no adjustment needed.
    2. New A2A (readings table): rows of "dd.mm.yyyy dd.mm.yyyy ..." after "Periodo dal".
       The first row's start date is the final meter reading of the PREVIOUS period,
       so we add 1 day to get the actual billing start.
    """
    # Method 1: old format — "QUANTO DEVO PAGARE" picture-text block
    m = re.search(
        r"bolletta per i consumi<br>\s*"
        r"dal\s+(\d{1,2})\s+(\w+)\s+(\d{4})<br>\s*"
        r"al\s+(\d{1,2})\s+(\w+)\s+(\d{4})",
        markdown,
        re.IGNORECASE,
    )
    if m:
        inizio = _it_date(m.group(1), m.group(2), m.group(3))
        fine = _it_date(m.group(4), m.group(5), m.group(6))
        if inizio and fine:
            return {"periodo_inizio": inizio, "periodo_fine": fine}

    # Method 2: new format — meter readings table.
    # Search within the readings table section if the header is present; otherwise
    # fall back to scanning the full document (some bill renderings omit the header).
    table = re.search(r"Periodo dal", markdown, re.IGNORECASE)
    area = markdown[table.start(): table.start() + 2000] if table else markdown
    rows = re.findall(r"(\d{2}\.\d{2}\.\d{4})(?:\s+|<br>|\|)(\d{2}\.\d{2}\.\d{4})", area)
    if rows:
        first_start = date.fromisoformat(_num_date(rows[0][0]))
        last_end = _num_date(rows[-1][1])
        inizio = (first_start + timedelta(days=1)).isoformat()
        return {"periodo_inizio": inizio, "periodo_fine": last_end}

    return None


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
    return data


def _strip_consumo_annuo(text: str) -> str:
    """Remove the CONSUMO ANNUO block so the LLM cannot mistake it for the billing period."""
    return re.sub(
        r"CONSUMO ANNUO[\s\S]{0,400}?\bal \d{1,2} \w+ \d{4}",
        "[CONSUMO ANNUO: omesso]",
        text,
    )


def _relevant_text(markdown: str, head: int = 3500, window: int = 1000) -> str:
    """Return a focused excerpt of the markdown for LLM extraction.

    The dates are no longer extracted by the LLM (handled by _extract_period_dates),
    so this function only needs to capture tipo, fornitore, importo_totale, consumo,
    and scadenza_pagamento — all of which appear in the first ~3500 chars.
    """
    header = _strip_consumo_annuo(markdown[:head])
    return header + markdown[head: head + window]


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

    # Override LLM date placeholders with regex-extracted dates (deterministic).
    period = _extract_period_dates(markdown)
    if period:
        data.update(period)
    elif data.get("periodo_inizio") == "0000-00-00":
        raise ValueError("Impossibile estrarre le date del periodo dalla bolletta.")

    # Override tipo if LLM returned null (keyword detection is more reliable).
    if not data.get("tipo"):
        data["tipo"] = _extract_tipo(markdown)

    required = {"tipo", "fornitore", "periodo_inizio", "periodo_fine", "importo_totale"}
    null_required = {k for k in required if not data.get(k) or data[k] == "0000-00-00"}
    if null_required:
        raise ValueError(
            f"Campi obbligatori mancanti dopo l'estrazione: {null_required}. "
            f"Dati: {data}"
        )

    data["file_pdf"] = str(pdf_path.resolve())
    data["file_md"] = str(md_path.resolve())

    db.insert_bill(data, db_path)
    return data
