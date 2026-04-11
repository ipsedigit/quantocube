import streamlit as st
import plotly.express as px
import pandas as pd
from pathlib import Path

import db
import llm
import ingester
import dashboard

PDF_DIR = Path(__file__).parent / "bills" / "pdf"

SYSTEM_PROMPT = {
    "role": "system",
    "content": (
        "Sei Quanto, un assistente personale per l'analisi delle bollette domestiche. "
        "Rispondi sempre in italiano. Usa i tool a disposizione per rispondere "
        "alle domande su spese e consumi. Sii conciso e preciso."
    ),
}


def init() -> None:
    db.init_db()
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "ingested_files" not in st.session_state:
        st.session_state.ingested_files = set()


def _render_chart(chart_data: list) -> None:
    df = pd.DataFrame(chart_data)
    fig = px.line(
        df, x="data", y="valore", color="tipo",
        labels={"data": "Data", "valore": "Valore"},
    )
    st.plotly_chart(fig, use_container_width=True)


def render_chat() -> None:
    st.header("Chat")

    for msg in st.session_state.messages:
        if msg["role"] == "system":
            continue
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("chart_data"):
                _render_chart(msg["chart_data"])

    if prompt := st.chat_input("Fai una domanda sulle tue bollette…"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Sto elaborando…"):
                history = [SYSTEM_PROMPT] + [
                    {"role": m["role"], "content": m["content"]}
                    for m in st.session_state.messages
                    if m["role"] in ("user", "assistant")
                ]
                result = llm.chat(history)

            st.markdown(result["text"])
            if result.get("chart_data"):
                _render_chart(result["chart_data"])

        st.session_state.messages.append({
            "role": "assistant",
            "content": result["text"],
            "chart_data": result.get("chart_data"),
        })


def render_ingestion() -> None:
    st.header("Bollette")

    uploaded = st.file_uploader("Carica PDF", type="pdf", accept_multiple_files=True)

    if uploaded:
        for f in uploaded:
            if f.name in st.session_state.ingested_files:
                continue

            pdf_path = PDF_DIR / f.name
            PDF_DIR.mkdir(parents=True, exist_ok=True)
            pdf_path.write_bytes(f.read())

            with st.status(f"Elaborazione `{f.name}`…", expanded=True) as status:
                st.write("PDF salvato.")
                try:
                    data = ingester.ingest_pdf(pdf_path)
                    st.write("Markdown generato.")
                    st.write("Dati estratti.")
                    st.write("Salvato nel database.")
                    st.session_state.ingested_files.add(f.name)
                    status.update(label=f"`{f.name}` importata.", state="complete")
                    st.json(data)
                except Exception as e:
                    status.update(label=f"Errore su `{f.name}`.", state="error")
                    st.error(str(e))

    st.divider()
    st.subheader("Bollette nel database")

    with db.get_connection() as conn:
        rows = conn.execute(
            "SELECT id, tipo, fornitore, periodo_inizio, periodo_fine, "
            "importo_totale, file_pdf, file_md "
            "FROM bollette ORDER BY periodo_fine DESC"
        ).fetchall()

    if rows:
        records = [dict(r) for r in rows]
        display_df = pd.DataFrame([{
            "Elimina": False,
            "tipo": r["tipo"],
            "fornitore": r["fornitore"],
            "periodo_inizio": r["periodo_inizio"],
            "periodo_fine": r["periodo_fine"],
            "importo_totale": r["importo_totale"],
        } for r in records])

        edited_df = st.data_editor(
            display_df,
            column_config={
                "Elimina": st.column_config.CheckboxColumn("", width="small"),
                "tipo": st.column_config.TextColumn("Tipo"),
                "fornitore": st.column_config.TextColumn("Fornitore"),
                "periodo_inizio": st.column_config.TextColumn("Inizio"),
                "periodo_fine": st.column_config.TextColumn("Fine"),
                "importo_totale": st.column_config.NumberColumn("Importo (€)", format="%.2f"),
            },
            disabled=["tipo", "fornitore", "periodo_inizio", "periodo_fine", "importo_totale"],
            hide_index=True,
            use_container_width=True,
        )

        to_delete = edited_df.index[edited_df["Elimina"]].tolist()
        if to_delete:
            if st.button(f"Elimina {len(to_delete)} bolletta/e selezionata/e", type="primary"):
                for idx in to_delete:
                    record = records[idx]
                    db.delete_bill(record["id"])
                    for key in ("file_pdf", "file_md"):
                        p = record.get(key)
                        if p:
                            Path(p).unlink(missing_ok=True)
                st.rerun()
    else:
        st.info("Nessuna bolletta nel database. Carica dei PDF sopra.")


def main() -> None:
    st.set_page_config(page_title="Quanto", page_icon="💡", layout="wide")
    init()
    tab_dash, tab_chat, tab_ingest = st.tabs(["Dashboard", "Chat", "Bollette"])
    with tab_dash:
        dashboard.render_dashboard()
    with tab_chat:
        render_chat()
    with tab_ingest:
        render_ingestion()


if __name__ == "__main__":
    main()
