# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Quanto** is a local-only personal bill assistant (Python/Streamlit) that lets users query household bills (electricity, gas, water, etc.) in natural language. All processing is local—no data leaves the machine. The spec is in `superpowers/specs/2026-04-10-bills-assistant-design.md`.

## Running the App

```bash
streamlit run app.py
```

## Downloading Bills from Gmail (one-shot)

```bash
python download_bills.py
```

Requires a `.env` file in the project root:

```
GMAIL_USER=tuo@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

The App Password is generated from Google Account → Security → 2-Step Verification → App passwords.
Gmail IMAP must be enabled (Gmail Settings → Forwarding and POP/IMAP).

The script searches all Gmail for emails with subject containing "Notifica emissione bolletta",
downloads all PDF attachments to `bills/pdfs/`, and skips files already present.
After running, upload the PDFs manually via the Quanto UI.

Requires Ollama running locally with `qwen2.5:7b` pulled (`llama3.2:3b` as fallback).

## Tech Stack

| Layer | Technology |
|-------|-----------|
| UI | Streamlit |
| LLM | Ollama (`qwen2.5:7b`) |
| Database | SQLite (`data/bills.db`) |
| PDF ingestion | `pymupdf4llm` (PDF → Markdown) |
| Visualization | Plotly (via Streamlit) |

## Architecture

Five modules with strict layering—no circular dependencies:

```
app.py → llm.py → tools.py → db.py
app.py → ingester.py → db.py
```

| Module | Responsibility |
|--------|---------------|
| `app.py` | Streamlit UI: chat interface + bill upload/ingestion |
| `llm.py` | Ollama client, tool schema, tool-calling orchestration |
| `tools.py` | Pure Python functions callable by the LLM (no side effects beyond DB reads) |
| `db.py` | SQLite schema, CRUD, query execution — no imports from other modules |
| `ingester.py` | PDF → Markdown (`bills/md/`) → LLM JSON extraction → SQLite insert |

### Data Flows

**Ingestion:** PDF upload → `pymupdf4llm` → `.md` file saved to `bills/md/` → Ollama extracts structured JSON → validated and inserted into SQLite.

**Query:** Natural language → Ollama (orchestrator) → decides tool call → `tools.py` function → SQLite → results returned to Ollama → final answer + optional Plotly chart.

### SQLite Schema (`bollette` table)

| Column | Type | Notes |
|--------|------|-------|
| `tipo` | TEXT | Free text: "luce", "gas", "acqua", etc. — no enum constraint |
| `fornitore` | TEXT | Provider name |
| `periodo_inizio` / `periodo_fine` | DATE | Supply period |
| `importo_totale` | REAL | Euros |
| `consumo` | REAL | Nullable (kWh, m³…) |
| `unita_consumo` | TEXT | Nullable unit |
| `tariffa` | TEXT | Rate type |
| `scadenza_pagamento` | DATE | Payment deadline |
| `file_pdf` / `file_md` | TEXT | Absolute paths to originals |

### LLM Tools (in `tools.py`)

Five functions exposed to the LLM: `get_spending`, `get_consumption`, `compare_periods`, `get_latest_bill`, `get_trend`. All take type/period filters, return structured data. `get_trend` triggers a Plotly chart in the UI.

## Key Design Decisions

- **No vector store**: Bills are structured data; SQLite with typed queries is sufficient.
- **No enum on `tipo`**: New bill types (phone, condo, etc.) work without schema migrations.
- **Markdown files persisted**: `bills/md/` files kept for debugging and reprocessing.
- **Single model for both roles**: Same Ollama model used for PDF extraction and query orchestration.
- **Hardware target**: 32 GB RAM, Nvidia GTX 1650 (4 GB VRAM); Ollama auto-offloads layers.
