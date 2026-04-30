import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
import fitz
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
  "tariffa": "Prezzo fisso",
  "scadenza_pagamento": "2024-04-15"
}}

Regole:
- tipo: "luce", "gas", "acqua" o "telefono" (minuscolo)
- periodo_inizio e periodo_fine: metti "0000-00-00" come segnaposto, saranno
  calcolate automaticamente dal sistema — non devi calcolarle tu.
- importo_totale: il "Totale da pagare" in euro, numero decimale (es. 194.00)
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

_MESI_IT_ABBR = {
    "gen": "01", "feb": "02", "mar": "03", "apr": "04",
    "mag": "05", "giu": "06", "lug": "07", "ago": "08",
    "set": "09", "ott": "10", "nov": "11", "dic": "12",
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
    if any(k in head for k in ("telefon", "tim ", "telecom", "xdsl", "fibra", "internet")):
        return "telefono"
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

    # Method 3: TIM abbreviated-month format "dd mmm yy - dd mmm yy"
    _abbr = "|".join(_MESI_IT_ABBR.keys())
    m = re.search(
        rf"(\d{{2}})\s+({_abbr})\s+(\d{{2}})\s*[-–]\s*(\d{{2}})\s+({_abbr})\s+(\d{{2}})",
        markdown,
        re.IGNORECASE,
    )
    if m:
        inizio = f"20{m.group(3)}-{_MESI_IT_ABBR[m.group(2).lower()]}-{m.group(1)}"
        fine = f"20{m.group(6)}-{_MESI_IT_ABBR[m.group(5).lower()]}-{m.group(4)}"
        return {"periodo_inizio": inizio, "periodo_fine": fine}

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


def _extract_importo_da_pdf(pdf_path: Path) -> float | None:
    """Extract importo_totale from PDF page 1 using coordinate-based text extraction.

    A2A bills render 'QUANTO DEVO PAGARE' and the amount in a graphical box that
    pymupdf4llm skips entirely.  PyMuPDF's get_text('dict') can still read it.
    """
    try:
        doc = fitz.open(str(pdf_path))
        spans = []
        for block in doc[0].get_text("dict")["blocks"]:
            if block["type"] == 0:
                for line in block["lines"]:
                    for span in line["spans"]:
                        text = span["text"].strip()
                        if text:
                            spans.append((span["bbox"][1], text))

        header_y = next(
            (y for y, t in spans if "QUANTO DEVO PAGARE" in t.upper()), None
        )
        if header_y is None:
            return None

        for y, text in sorted(spans):
            if header_y < y < header_y + 200:
                if re.fullmatch(r"\d{1,3}(?:\.\d{3})*,\d{2}", text):
                    return float(text.replace(".", "").replace(",", "."))
    except Exception:
        pass
    return None


def _extract_importo_telefono(markdown: str) -> float | None:
    """Extract importo_totale from TIM bills via 'Totale da pagare' text line.

    Handles plain text ("Totale da pagare € 43,89") and pymupdf4llm table-cell
    format ("Totale da pagare<br>**€ 43,89**").
    """
    m = re.search(
        r"Totale da pagare\s*(?:<br>)?\s*\*{0,2}\s*€?\s*(\d{1,3}(?:\.\d{3})*,\d{2})",
        markdown,
        re.IGNORECASE,
    )
    if not m:
        return None
    return float(m.group(1).replace(".", "").replace(",", "."))


def _extract_voci_telefono(markdown: str) -> list[dict]:
    """Parse the 'Dettaglio dei costi' table and return one dict per service row.

    pymupdf4llm renders TIM bills with all services in one <br>-delimited cell:
    nome<br>dd mmm yy - dd mmm yy<br>N%<br>amount<br>[next service...]
    """
    section = re.search(
        r"(?:Dettaglio dei costi|Offerte e servizi)(.+?)Totale da pagare",
        markdown,
        re.DOTALL | re.IGNORECASE,
    )
    if not section:
        return []

    _abbr = "|".join(_MESI_IT_ABBR.keys())
    pattern = re.compile(
        rf"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 ]+?)"
        rf"<br>"
        rf"(\d{{2}})\s+({_abbr})\s+(\d{{2}})\s*-\s*(\d{{2}})\s+({_abbr})\s+(\d{{2}})"
        rf"<br>"
        rf"\d+%"
        rf"<br>"
        rf"([\d]+,[\d]{{2}})",
        re.IGNORECASE,
    )

    result = []
    for m in pattern.finditer(section.group(1)):
        nome = m.group(1).strip()
        inizio = f"20{m.group(4)}-{_MESI_IT_ABBR[m.group(3).lower()]}-{m.group(2)}"
        fine = f"20{m.group(7)}-{_MESI_IT_ABBR[m.group(6).lower()]}-{m.group(5)}"
        importo = float(m.group(8).replace(",", "."))
        result.append({"nome": nome, "importo": importo, "periodo_inizio": inizio, "periodo_fine": fine})

    return result


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
    # New format: "CONSUMO ANNUO ... al DD Mese YYYY"
    text = re.sub(
        r"CONSUMO ANNUO[\s\S]{0,400}?\bal \d{1,2} \w+ \d{4}",
        "[CONSUMO ANNUO: omesso]",
        text,
    )
    # Old format: "**Consumo annuo** ... DD.MM.YYYY"
    text = re.sub(
        r"\*\*[Cc]onsumo\s+[Aa]nnuo\*\*[\s\S]{0,600}?\d{2}\.\d{2}\.\d{4}",
        "[CONSUMO ANNUO: omesso]",
        text,
    )
    return text


def _extract_consumption(markdown: str, tipo: str) -> tuple[float | None, str | None]:
    """Deterministic regex fallback for consumption extraction.

    Used when the LLM returns null for consumo.  Returns (value, unit) or (None, None).
    """
    if tipo == "luce":
        return _extract_consumption_luce(markdown)
    if tipo == "gas":
        return _extract_consumption_gas(markdown)
    return None, None


def _extract_consumption_luce(markdown: str) -> tuple[float | None, str | None]:
    """Extract kWh from luce bills.

    Two formats:
    - New A2A: bold line item "**360 kWh** **0,189944 €/kWh** ..."
    - Old A2A: meter table rows "|...|61 kWh|Effettivo|"
    """
    # Method 1 – new format: first bold kWh after stripping annual consumption block.
    stripped = _strip_consumo_annuo(markdown[:4500])
    m = re.search(r"\*\*(\d[\d.]*)\s*kWh\*\*", stripped)
    if m:
        # Italian uses "." as thousands separator (e.g. "2.039") — remove it.
        return float(m.group(1).replace(".", "")), "kWh"

    # Method 2 – old format: sum all per-fascia rows from the meter table.
    vals = [int(v) for v in re.findall(r"\|(\d+)\s*kWh\|Effettivo\|", markdown)]
    if vals:
        return float(sum(vals)), "kWh"

    return None, None


def _extract_consumption_gas(markdown: str) -> tuple[float | None, str | None]:
    """Extract Smc from gas bills by summing meter-table rows.

    Row format: |DD.MM.YYYY|DD.MM.YYYY|meter_start|type|meter_end|type|consumption|Effettivo|...|
    """
    vals = [
        int(v)
        for v in re.findall(
            r"\|\d{2}\.\d{2}\.\d{4}\|\d{2}\.\d{2}\.\d{4}\|[\d.]+\|[^|]+\|[\d.]+\|[^|]+\|(\d+)\|Effettivo\|",
            markdown,
        )
    ]
    if vals:
        return float(sum(vals)), "Smc"
    return None, None


def _relevant_text(markdown: str, head: int = 3500, window: int = 1000) -> str:
    """Return a focused excerpt of the markdown for LLM extraction.

    The dates are no longer extracted by the LLM (handled by _extract_period_dates),
    so this function only needs to capture tipo, fornitore, importo_totale, consumo,
    and scadenza_pagamento — all of which appear in the first ~3500 chars.
    """
    header = _strip_consumo_annuo(markdown[:head])
    return header + markdown[head: head + window]


def repair_importo(db_path: Path = db.DB_PATH) -> list[dict]:
    """Re-extract importo_totale for all bills using coordinate-based PDF extraction.

    Updates the DB when a reliable value is found and it differs from what is stored.
    Returns a list of repair results.
    """
    with db.get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, importo_totale, file_pdf FROM bollette WHERE file_pdf IS NOT NULL"
        ).fetchall()

    results = []
    for row in rows:
        bill_id, stored = row["id"], row["importo_totale"]
        pdf_path = Path(row["file_pdf"])
        if not pdf_path.exists():
            results.append({"id": bill_id, "status": "pdf_missing"})
            continue

        importo = _extract_importo_da_pdf(pdf_path)
        if importo is None:
            results.append({"id": bill_id, "status": "not_found"})
            continue

        if importo == stored:
            results.append({"id": bill_id, "status": "ok", "importo": importo})
            continue

        with db.get_connection(db_path) as conn:
            conn.execute(
                "UPDATE bollette SET importo_totale = ? WHERE id = ?",
                [importo, bill_id],
            )
        results.append({"id": bill_id, "status": "updated", "old": stored, "new": importo})

    return results


def repair_null_consumption(db_path: Path = db.DB_PATH) -> list[dict]:
    """Re-extract consumption for all bills that have consumo = NULL.

    Reads the stored markdown file, applies deterministic regex extraction,
    and updates the DB if a value is found.  Returns a list of repair results.
    """
    with db.get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT id, tipo, file_md FROM bollette WHERE consumo IS NULL AND file_md IS NOT NULL"
        ).fetchall()

    results = []
    for row in rows:
        bill_id, tipo, file_md = row["id"], row["tipo"], row["file_md"]
        md_path = Path(file_md)
        if not md_path.exists():
            results.append({"id": bill_id, "tipo": tipo, "status": "md_missing"})
            continue

        markdown = md_path.read_text(encoding="utf-8")
        val, unit = _extract_consumption(markdown, tipo)
        if val is None:
            results.append({"id": bill_id, "tipo": tipo, "status": "not_found"})
            continue

        db.update_consumption(bill_id, val, unit, db_path)
        results.append({"id": bill_id, "tipo": tipo, "consumo": val, "unita_consumo": unit, "status": "updated"})

    return results


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

    # Override importo_totale with coordinate-based extraction (more reliable than LLM
    # for bills where the total lives in a graphical box not captured by pymupdf4llm).
    importo = _extract_importo_da_pdf(pdf_path)
    if importo is None and data.get("tipo") == "telefono":
        importo = _extract_importo_telefono(markdown)
    if importo is not None:
        data["importo_totale"] = importo

    # Consumption is never trusted to the LLM — regex only.
    val, unit = _extract_consumption(markdown, data.get("tipo", ""))
    data["consumo"] = val
    data["unita_consumo"] = unit

    required = {"tipo", "fornitore", "periodo_inizio", "periodo_fine", "importo_totale"}
    null_required = {k for k in required if not data.get(k) or data[k] == "0000-00-00"}
    if null_required:
        raise ValueError(
            f"Campi obbligatori mancanti dopo l'estrazione: {null_required}. "
            f"Dati: {data}"
        )

    data["file_pdf"] = str(pdf_path.resolve())
    data["file_md"] = str(md_path.resolve())

    bill_id = db.insert_bill(data, db_path)

    if data.get("tipo") == "telefono":
        voci = _extract_voci_telefono(markdown)
        if voci and not db.get_voci_by_bolletta(bill_id, db_path):
            db.insert_voci(bill_id, voci, db_path)

    return data
