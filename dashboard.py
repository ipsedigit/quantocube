import os
import subprocess
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

import db

DB_PATH = db.DB_PATH


def get_bill_types(db_path: Path = DB_PATH) -> list[str]:
    with db.get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT tipo FROM bollette ORDER BY tipo"
        ).fetchall()
    return [r["tipo"] for r in rows]


def get_bills_for_type(tipo: str, db_path: Path = DB_PATH) -> list[dict]:
    with db.get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM bollette WHERE tipo = ? ORDER BY periodo_fine DESC",
            [tipo],
        ).fetchall()
    return [dict(r) for r in rows]


def build_spending_chart(rows: list[dict]):
    if not rows:
        return None
    df = pd.DataFrame(rows)[["periodo_fine", "importo_totale"]]
    df = df.sort_values("periodo_fine")
    return px.line(
        df, x="periodo_fine", y="importo_totale",
        labels={"periodo_fine": "Data", "importo_totale": "Importo (€)"},
        markers=True,
    )


def build_consumption_chart(rows: list[dict]):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    if df["consumo"].isna().all():
        return None
    df = df[df["consumo"].notna()].sort_values("periodo_fine")
    non_null_units = df["unita_consumo"].dropna()
    unit = non_null_units.iloc[0] if not non_null_units.empty else ""
    return px.line(
        df, x="periodo_fine", y="consumo",
        labels={"periodo_fine": "Data", "consumo": f"Consumo ({unit})"},
        markers=True,
    )


def build_yearly_chart(rows: list[dict]):
    if not rows:
        return None
    df = pd.DataFrame(rows)[["periodo_fine", "importo_totale"]]
    df["anno"] = pd.to_datetime(df["periodo_fine"], format="mixed", errors="coerce").dt.year.astype(str)
    yearly = df.groupby("anno", sort=True)["importo_totale"].sum().reset_index()
    return px.bar(
        yearly, x="anno", y="importo_totale",
        labels={"anno": "Anno", "importo_totale": "Spesa totale (€)"},
    )


def open_pdf(path: str) -> None:
    if not path or not Path(path).exists():
        return
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)


def render_dashboard(db_path: Path = DB_PATH) -> None:
    tipos = get_bill_types(db_path)

    if not tipos:
        st.info("Nessuna bolletta nel database. Carica dei PDF nella sezione Bollette.")
        return

    tabs = st.tabs([t.upper() for t in tipos])

    for tab, tipo in zip(tabs, tipos):
        with tab:
            bills = get_bills_for_type(tipo, db_path)

            col1, col2, col3 = st.columns(3)

            with col1:
                st.caption("Spesa nel tempo")
                fig = build_spending_chart(bills)
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Dati spesa non disponibili")

            with col2:
                st.caption("Consumo nel tempo")
                fig = build_consumption_chart(bills)
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Dati consumo non disponibili")

            with col3:
                st.caption("Confronto annuale")
                fig = build_yearly_chart(bills)
                if fig is not None:
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.info("Dati non disponibili")

            st.divider()
            st.caption(f"Bollette {tipo.upper()}")

            header = st.columns([2, 1, 1, 1, 1])
            header[0].markdown("**Fornitore**")
            header[1].markdown("**Inizio**")
            header[2].markdown("**Fine**")
            header[3].markdown("**Importo**")
            header[4].markdown("**PDF**")

            for bill in bills:
                row = st.columns([2, 1, 1, 1, 1])
                row[0].write(bill["fornitore"])
                row[1].write(bill["periodo_inizio"])
                row[2].write(bill["periodo_fine"])
                row[3].write(f"€ {bill['importo_totale']:.2f}")

                pdf_path = bill.get("file_pdf")
                pdf_available = bool(pdf_path and Path(pdf_path).exists())
                if row[4].button(
                    "Apri PDF",
                    key=f"pdf_{bill['id']}",
                    disabled=not pdf_available,
                ):
                    open_pdf(pdf_path)
