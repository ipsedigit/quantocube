import json
from functools import lru_cache
from pathlib import Path
import ollama
import db
import tools as tools_module

MODEL = "qwen2.5:7b"
FALLBACK_MODEL = "llama3.2:3b"
DB_PATH = db.DB_PATH

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_spending",
            "description": "Spesa totale per tipo di bolletta e periodo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "description": "Tipo di bolletta (luce, gas, acqua…)"},
                    "da": {"type": "string", "description": "Data inizio filtro (YYYY-MM-DD)"},
                    "a": {"type": "string", "description": "Data fine filtro (YYYY-MM-DD)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_consumption",
            "description": "Consumo per tipo di bolletta e periodo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "description": "Tipo di bolletta"},
                    "da": {"type": "string", "description": "Data inizio filtro (YYYY-MM-DD)"},
                    "a": {"type": "string", "description": "Data fine filtro (YYYY-MM-DD)"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_periods",
            "description": "Confronta spesa e consumo tra due periodi.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "description": "Tipo di bolletta"},
                    "periodo1_inizio": {"type": "string", "description": "Inizio primo periodo (YYYY-MM-DD)"},
                    "periodo1_fine": {"type": "string", "description": "Fine primo periodo (YYYY-MM-DD)"},
                    "periodo2_inizio": {"type": "string", "description": "Inizio secondo periodo (YYYY-MM-DD)"},
                    "periodo2_fine": {"type": "string", "description": "Fine secondo periodo (YYYY-MM-DD)"},
                },
                "required": ["tipo", "periodo1_inizio", "periodo1_fine", "periodo2_inizio", "periodo2_fine"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_latest_bill",
            "description": "Recupera l'ultima bolletta per tipo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "description": "Tipo di bolletta"},
                },
                "required": ["tipo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_trend",
            "description": "Serie storica di spesa o consumo per tipo. Usalo quando l'utente chiede un grafico o un andamento.",
            "parameters": {
                "type": "object",
                "properties": {
                    "tipo": {"type": "string", "description": "Tipo di bolletta"},
                    "da": {"type": "string", "description": "Data inizio filtro (YYYY-MM-DD)"},
                    "a": {"type": "string", "description": "Data fine filtro (YYYY-MM-DD)"},
                    "metrica": {
                        "type": "string",
                        "enum": ["importo_totale", "consumo"],
                        "description": "Campo da tracciare nel grafico",
                    },
                },
                "required": ["tipo"],
            },
        },
    },
]

TOOL_FN = {
    "get_spending": tools_module.get_spending,
    "get_consumption": tools_module.get_consumption,
    "compare_periods": tools_module.compare_periods,
    "get_latest_bill": tools_module.get_latest_bill,
    "get_trend": tools_module.get_trend,
}


@lru_cache(maxsize=1)
def get_model() -> str:
    try:
        available = [m.model for m in ollama.list().models]
        if any(MODEL in m for m in available):
            return MODEL
        if any(FALLBACK_MODEL in m for m in available):
            return FALLBACK_MODEL
    except Exception:
        pass
    return MODEL


def chat(messages: list[dict], db_path: Path = DB_PATH) -> dict:
    """
    Send messages to Ollama with tool support.
    Returns {"text": str, "chart_data": list | None}.
    chart_data is populated when get_trend is called.
    """
    model = get_model()
    try:
        response = ollama.chat(model=model, messages=messages, tools=TOOLS)
    except Exception as e:
        return {"text": f"Errore di connessione a Ollama: {e}", "chart_data": None}

    msg = response.message

    if not msg.tool_calls:
        return {"text": msg.content, "chart_data": None}

    chart_data = None
    tool_messages = []

    for tc in msg.tool_calls:
        fn_name = tc.function.name
        fn_args = dict(tc.function.arguments)
        fn = TOOL_FN.get(fn_name)
        if fn is None:
            result = {"error": f"Unknown tool: {fn_name}"}
        else:
            fn_args["db_path"] = db_path
            result = fn(**fn_args)
        if fn_name == "get_trend" and fn is not None:
            chart_data = result
        tool_messages.append({
            "role": "tool",
            "content": json.dumps(result, ensure_ascii=False, default=str),
        })

    follow_up = messages + [{"role": "assistant", "content": msg.content or ""}] + tool_messages
    try:
        final = ollama.chat(model=model, messages=follow_up)
    except Exception as e:
        return {"text": f"Errore di connessione a Ollama: {e}", "chart_data": chart_data}
    return {"text": final.message.content, "chart_data": chart_data}
