from __future__ import annotations

import io
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .core.agent import agent_status
from .core.analyst import analyze_question
from .core.document_agent import answer_document_question
from .core.profiler import prepare_dataframe, profile_dataframe
from .core.utils import json_safe, records_to_json

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
ROOT_DIR = BASE_DIR.parent
SAMPLES_DIR = ROOT_DIR / "samples"

app = FastAPI(
    title="InsightAgent SaaG",
    description="Agente conversacional de inteligencia de negocio para archivos CSV y Excel.",
    version="2.4.0",
)

def parse_cors_origins() -> tuple[list[str], bool]:
    """Read allowed frontend origins from CORS_ORIGINS.

    Use exact origins without trailing slash, for example:
    https://mi-app.vercel.app,http://localhost:3000

    If the variable is not set, the app keeps a permissive development/demo
    default. In production with a separate Vercel frontend, set CORS_ORIGINS
    explicitly in Render.
    """
    raw = os.getenv("CORS_ORIGINS", "").strip()
    if not raw:
        return ["*"], False
    origins = [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]
    return origins or ["*"], bool(origins)


CORS_ORIGINS, CORS_ALLOW_CREDENTIALS = parse_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=CORS_ALLOW_CREDENTIALS,
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

DATASETS: dict[str, dict[str, Any]] = {}
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


class ChatRequest(BaseModel):
    dataset_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1, max_length=1200)


class SheetSwitchRequest(BaseModel):
    sheet_name: str = Field(..., min_length=1, max_length=120)


class DatasetResponse(BaseModel):
    dataset_id: str
    filename: str
    profile: dict[str, Any]


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def health_payload() -> dict[str, Any]:
    env = os.getenv("APP_ENV") or os.getenv("ENV") or os.getenv("RENDER_ENV") or "development"
    return {
        "ok": True,
        "service": "insightagent-saag",
        "env": env,
        "time": datetime.now(timezone.utc).isoformat(),
        "agent": agent_status(),
    }


@app.get("/health", include_in_schema=False)
def health() -> dict[str, Any]:
    return health_payload()


@app.head("/health", include_in_schema=False)
def health_head() -> Response:
    return Response(status_code=200)


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    return health_payload()


@app.head("/api/health", include_in_schema=False)
def api_health_head() -> Response:
    return Response(status_code=200)


@app.post("/api/upload")
async def upload_dataset(file: UploadFile = File(...)) -> JSONResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="El archivo es demasiado grande. Para esta versión usa archivos menores a 25 MB.")
    dataset = read_uploaded_file(raw, file.filename or "archivo")
    return JSONResponse(load_any_dataset(dataset, file.filename or "archivo"))


@app.post("/api/demo")
def load_demo_dataset() -> JSONResponse:
    sample_path = SAMPLES_DIR / "saas_sales_sample.csv"
    if not sample_path.exists():
        raise HTTPException(status_code=404, detail="No encontré los datos de ejemplo.")
    df = prepare_dataframe(pd.read_csv(sample_path))
    return JSONResponse(load_dataset(df, "saas_sales_sample.csv"))


@app.get("/api/datasets/{dataset_id}")
def get_dataset(dataset_id: str) -> JSONResponse:
    dataset = DATASETS.get(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="No encontré el conjunto de datos. Sube el archivo nuevamente.")
    return JSONResponse({"dataset_id": dataset_id, "filename": dataset["filename"], "mode": dataset.get("mode"), "profile": dataset["profile"]})


@app.post("/api/datasets/{dataset_id}/sheet")
def switch_sheet(dataset_id: str, req: SheetSwitchRequest) -> JSONResponse:
    dataset = DATASETS.get(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="No encontré el conjunto de datos. Sube el archivo nuevamente.")
    sheets = dataset.get("sheets") or {}
    if not sheets:
        raise HTTPException(status_code=400, detail="Este archivo no tiene hojas seleccionables.")
    if req.sheet_name not in sheets:
        available = ", ".join(sheets.keys())
        raise HTTPException(status_code=404, detail=f"No encontré la hoja '{req.sheet_name}'. Hojas disponibles: {available}.")
    selected = sheets[req.sheet_name]
    dataset["df"] = selected["df"]
    dataset["profile"] = selected["profile"]
    dataset["active_sheet"] = req.sheet_name
    dataset["mode"] = "dataset"
    dataset["history"] = []
    return JSONResponse(json_safe({"dataset_id": dataset_id, "filename": dataset["filename"], "mode": "dataset", "profile": selected["profile"]}))


@app.post("/api/chat")
def chat(req: ChatRequest) -> JSONResponse:
    dataset = DATASETS.get(req.dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="No encontré el conjunto de datos. Sube el archivo nuevamente.")
    if dataset.get("mode") == "document":
        answer = answer_document_question(dataset.get("content", ""), req.question, dataset.get("profile"))
    elif dataset.get("sheets") and wants_workbook_overview(req.question):
        answer = answer_workbook_overview(dataset, req.question)
    else:
        df: pd.DataFrame = dataset["df"]
        answer = analyze_question(df, req.question, dataset.get("profile"))
    dataset.setdefault("history", []).append({"question": req.question, "answer": answer})
    return JSONResponse(answer)


@app.get("/api/datasets/{dataset_id}/history")
def history(dataset_id: str) -> JSONResponse:
    dataset = DATASETS.get(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="No encontré el conjunto de datos.")
    return JSONResponse({"history": json_safe(dataset.get("history", []))})


@app.get("/api/datasets/{dataset_id}/preview")
def preview(dataset_id: str, limit: int = 50) -> JSONResponse:
    dataset = DATASETS.get(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="No encontré el conjunto de datos.")
    limit = max(1, min(limit, 200))
    if dataset.get("mode") == "document":
        return JSONResponse({"rows": dataset.get("preview_rows", [])[:limit]})
    return JSONResponse({"rows": records_to_json(dataset["df"], limit=limit)})


def read_uploaded_file(raw: bytes, filename: str) -> dict[str, Any]:
    suffix = Path(filename).suffix.lower()
    allowed = {".csv", ".xlsx", ".xls", ".txt", ".md", ".json"}
    if suffix not in allowed:
        raise HTTPException(
            status_code=400,
            detail="Formato no soportado. Usa CSV, Excel, TXT, MD o JSON. Los archivos tabulares activan el análisis avanzado; los documentos usan solo el chat.",
        )
    if suffix in {".txt", ".md", ".json"}:
        text = extract_text_file(raw, filename)
        return {"mode": "document", "content": text, "profile": document_profile(filename, text, "Archivo textual válido para chat documental.")}
    if suffix in {".xlsx", ".xls"}:
        try:
            return read_excel_workbook_dataset(raw, filename)
        except HTTPException as exc:
            text = extract_spreadsheet_text(raw, filename)
            if text.strip():
                return {"mode": "document", "content": text, "profile": document_profile(filename, text, f"No se pudo leer como tabla: {exc.detail}")}
            raise
    try:
        df = read_dataframe(raw, filename)
    except HTTPException as exc:
        text = extract_spreadsheet_text(raw, filename) if suffix in {".xlsx", ".xls"} else extract_text_file(raw, filename)
        if text.strip():
            return {"mode": "document", "content": text, "profile": document_profile(filename, text, f"No se pudo leer como tabla: {exc.detail}")}
        raise
    profile = profile_dataframe(df)
    mode, reason = classify_file_mode(df, profile)
    if mode == "document":
        text = dataframe_to_document_text(df, filename)
        doc_profile = profile | document_profile(filename, text, reason)
        doc_profile["warnings"] = (doc_profile.get("warnings") or []) + ["El archivo se cargó en modo documento porque no parece un dataset tabular de negocio."]
        return {"mode": "document", "content": text, "profile": doc_profile, "df": df}
    profile["mode"] = "dataset"
    return {"mode": "dataset", "df": df, "profile": profile}


def classify_file_mode(df: pd.DataFrame, profile: dict[str, Any]) -> tuple[str, str]:
    rows = int(profile.get("rows") or 0)
    cols = int(profile.get("columns_count") or 0)
    numeric = len(profile.get("numeric_columns", []))
    dates = len(profile.get("date_columns", []))
    categorical = len(profile.get("categorical_columns", []))
    usable_columns = numeric + dates + categorical + len(profile.get("text_columns", []))
    if rows < 2 or cols < 2:
        return "document", "El archivo no tiene suficientes filas o columnas para análisis tabular."
    if usable_columns < 2:
        return "document", "No se detectaron columnas analizables suficientes."
    if numeric == 0 and dates == 0 and categorical <= 1:
        return "document", "No se detectaron métricas, fechas o dimensiones suficientes para análisis de negocio."
    return "dataset", "Dataset tabular válido para análisis avanzado."


def extract_text_file(raw: bytes, filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    for encoding in ["utf-8", "utf-8-sig", "latin1"]:
        try:
            text = raw.decode(encoding)
            if suffix == ".json":
                try:
                    return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
                except Exception:
                    return text
            return text
        except UnicodeDecodeError:
            continue
    raise HTTPException(status_code=400, detail="No pude leer el texto del archivo.")


def extract_spreadsheet_text(raw: bytes, filename: str) -> str:
    try:
        book = pd.read_excel(io.BytesIO(raw), sheet_name=None, header=None, dtype=str)
    except Exception:
        return ""
    sections = []
    for sheet, frame in book.items():
        clean = frame.dropna(how="all").dropna(axis=1, how="all").fillna("")
        if clean.empty:
            continue
        lines = [f"Hoja: {sheet}"]
        for _, row in clean.head(250).iterrows():
            text = " | ".join(str(x).strip() for x in row.tolist() if str(x).strip())
            if text:
                lines.append(text)
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


def dataframe_to_document_text(df: pd.DataFrame, filename: str) -> str:
    rows = records_to_json(df, limit=300)
    lines = [f"Archivo: {filename}", f"Filas detectadas: {len(df)}", f"Columnas detectadas: {len(df.columns)}", "Contenido extraído:"]
    for i, row in enumerate(rows, start=1):
        pieces = [f"{k}: {v}" for k, v in row.items() if v not in [None, ""]]
        lines.append(f"Registro {i}: " + "; ".join(pieces))
    return "\n".join(lines)


def document_profile(filename: str, text: str, reason: str) -> dict[str, Any]:
    preview = []
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            preview.append({"fragmento": clean[:300]})
        if len(preview) >= 12:
            break
    return {
        "mode": "document",
        "filename": filename,
        "title": filename,
        "mode_reason": reason,
        "summary": "Archivo cargado para lectura y preguntas mediante el chat.",
        "rows": len([x for x in text.splitlines() if x.strip()]),
        "columns_count": 1,
        "numeric_columns": [],
        "date_columns": [],
        "categorical_columns": [],
        "text_columns": ["contenido"],
        "missing_pct": 0,
        "columns": [{"name": "contenido", "type": "texto", "unique": len(set(text.splitlines())), "missing_pct": 0}],
        "preview": preview,
        "warnings": [reason],
        "suggested_questions": [
            "Resume el contenido principal del archivo.",
            "¿Qué puntos importantes debo revisar?",
            "¿Qué riesgos o inconsistencias aparecen en el archivo?",
            "Extrae las decisiones, tareas o fechas importantes si existen.",
        ],
    }


def load_any_dataset(dataset: dict[str, Any], filename: str) -> dict[str, Any]:
    if dataset.get("mode") == "document":
        dataset_id = uuid.uuid4().hex[:12]
        profile = dataset.get("profile") or document_profile(filename, dataset.get("content", ""), "Archivo en modo documento.")
        DATASETS[dataset_id] = {
            "id": dataset_id,
            "filename": filename,
            "mode": "document",
            "content": dataset.get("content", ""),
            "df": dataset.get("df"),
            "profile": profile,
            "preview_rows": profile.get("preview", []),
            "history": [],
        }
        return json_safe({"dataset_id": dataset_id, "filename": filename, "mode": "document", "profile": profile})
    return load_dataset(
        dataset["df"],
        filename,
        profile=dataset.get("profile"),
        sheets=dataset.get("sheets"),
        active_sheet=dataset.get("active_sheet"),
    )



def read_excel_workbook_dataset(raw: bytes, filename: str) -> dict[str, Any]:
    workbook, accepted, sheet_summaries = analyze_excel_workbook(raw)
    if not accepted:
        raise HTTPException(status_code=400, detail="No encontré una hoja con estructura tabular confiable dentro del libro.")

    accepted.sort(key=lambda item: item["score"], reverse=True)
    active = accepted[0]
    sheet_names = list(workbook.keys())
    useful_count = len(accepted)
    sheets: dict[str, dict[str, Any]] = {}

    sheet_options = []
    for item in accepted:
        df = item["df"]
        sheet_name = item["sheet"]
        profile = profile_dataframe(df)
        profile["mode"] = "dataset"
        profile["source_meta"] = item["meta"]
        profile["workbook"] = build_workbook_payload(
            sheet_names=sheet_names,
            sheet_summaries=sheet_summaries,
            accepted=accepted,
            active_sheet=sheet_name,
            filename=filename,
        )
        profile["warnings"] = build_workbook_warnings(
            sheet_count=len(sheet_names),
            useful_count=useful_count,
            active_sheet=sheet_name,
            header_row=item["header_row"],
            total_sheets=len(sheet_names),
            generic_headers=item["meta"].get("generic_headers", 0),
        )
        sheets[sheet_name] = {"df": df, "profile": profile, "score": item["score"], "header_row": item["header_row"]}
        sheet_options.append(sheet_name)

    best_profile = sheets[active["sheet"]]["profile"]
    return {
        "mode": "dataset",
        "df": active["df"],
        "profile": best_profile,
        "sheets": sheets,
        "active_sheet": active["sheet"],
        "workbook_sheets": sheet_names,
    }


def analyze_excel_workbook(raw: bytes) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        workbook = pd.read_excel(io.BytesIO(raw), sheet_name=None, header=None)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No pude abrir el libro de Excel: {exc}") from exc

    accepted: list[dict[str, Any]] = []
    sheet_summaries: list[dict[str, Any]] = []
    for sheet_name, raw_df in workbook.items():
        if raw_df is None or raw_df.empty or raw_df.dropna(how="all").empty:
            sheet_summaries.append({"name": sheet_name, "mode": "vacía", "rows": 0, "columns_count": 0, "score": 0})
            continue

        best: dict[str, Any] | None = None
        max_header = min(12, max(len(raw_df) - 2, 0))
        for header_row in range(max_header + 1):
            candidate = excel_candidate_from_header(raw_df, header_row)
            if candidate.empty:
                continue
            prepared = prepare_dataframe(candidate)
            score, details = score_excel_candidate(prepared, raw_df, header_row)
            details.update({
                "sheet": sheet_name,
                "header_row": header_row + 1,
                "strategy": "excel_multi_sheet_smart_header_detection",
            })
            item = {"score": float(score), "sheet": sheet_name, "header_row": header_row + 1, "df": prepared, "meta": details}
            if best is None or item["score"] > best["score"]:
                best = item

        if best and best["score"] >= 18:
            prof = profile_dataframe(best["df"])
            rows = int(prof.get("rows") or 0)
            cols = int(prof.get("columns_count") or 0)
            numeric_count = len(prof.get("numeric_columns", []))
            date_count = len(prof.get("date_columns", []))
            categorical_count = len(prof.get("categorical_columns", []))
            # Evita activar hojas auxiliares pequeñas como diccionarios de campos.
            # Una hoja es analítica si tiene métricas, fechas o suficiente estructura categórica.
            analytical = rows >= 5 and cols >= 2 and (numeric_count > 0 or date_count > 0 or (categorical_count >= 2 and rows >= 20))
            if analytical:
                accepted.append(best)
                sheet_summaries.append({
                    "name": sheet_name,
                    "mode": "dataset",
                    "rows": rows,
                    "columns_count": cols,
                    "numeric_columns_count": numeric_count,
                    "date_columns_count": date_count,
                    "categorical_columns_count": categorical_count,
                    "header_row": best["header_row"],
                    "score": round(float(best["score"]), 2),
                })
            else:
                sheet_summaries.append({
                    "name": sheet_name,
                    "mode": "documental o auxiliar",
                    "rows": rows,
                    "columns_count": cols,
                    "numeric_columns_count": numeric_count,
                    "date_columns_count": date_count,
                    "categorical_columns_count": categorical_count,
                    "header_row": best["header_row"],
                    "score": round(float(best["score"]), 2),
                })
        else:
            clean = raw_df.dropna(how="all").dropna(axis=1, how="all")
            sheet_summaries.append({
                "name": sheet_name,
                "mode": "documental o irregular",
                "rows": int(clean.shape[0]),
                "columns_count": int(clean.shape[1]),
                "score": round(float(best["score"]), 2) if best else 0,
            })
    return workbook, accepted, sheet_summaries


def build_workbook_payload(
    sheet_names: list[str],
    sheet_summaries: list[dict[str, Any]],
    accepted: list[dict[str, Any]],
    active_sheet: str,
    filename: str,
) -> dict[str, Any]:
    accepted_names = {item["sheet"] for item in accepted}
    summaries_by_name = {item["name"]: item for item in sheet_summaries}
    sheets_payload = []
    for name in sheet_names:
        summary = dict(summaries_by_name.get(name, {"name": name, "mode": "desconocida"}))
        summary["selectable"] = name in accepted_names
        summary["active"] = name == active_sheet
        sheets_payload.append(summary)
    return {
        "is_workbook": True,
        "filename": filename,
        "sheet_count": len(sheet_names),
        "active_sheet": active_sheet,
        "selectable_count": len(accepted_names),
        "sheets": sheets_payload,
    }


def build_workbook_warnings(sheet_count: int, useful_count: int, active_sheet: str, header_row: int, total_sheets: int, generic_headers: int = 0) -> list[str]:
    warnings: list[str] = []
    if sheet_count > 1:
        warnings.append(
            f"Se detectaron {sheet_count} hojas en el archivo. Actualmente se está analizando la hoja '{active_sheet}'."
        )
        if useful_count > 1:
            warnings.append(
                f"{useful_count} hojas parecen tener estructura analítica. Puedes cambiar la hoja activa desde el selector sin volver a subir el archivo."
            )
        else:
            warnings.append(
                "Solo una hoja parece tener estructura tabular confiable para análisis avanzado; las demás parecen vacías, documentales o auxiliares."
            )
    if header_row > 1:
        warnings.append(f"Se detectó que los encabezados reales empiezan en la fila {header_row} de la hoja '{active_sheet}'.")
    if generic_headers:
        warnings.append("Algunos encabezados estaban vacíos o duplicados y fueron normalizados automáticamente.")
    return warnings


def wants_workbook_overview(question: str) -> bool:
    q = normalize_for_workbook(question)
    triggers = [
        "todas las hojas", "todas sus hojas", "todas", "multihoja", "multiples hojas", "múltiples hojas",
        "que hojas", "qué hojas", "hojas tiene", "hojas del archivo", "libro de excel", "workbook",
        "cambiar de hoja", "otra hoja", "analiza las hojas", "usar todas las hojas", "usa todas las hojas",
    ]
    return any(trigger in q for trigger in triggers)


def normalize_for_workbook(text: str) -> str:
    text = str(text or "").lower().strip()
    replacements = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n", "ü": "u"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return re.sub(r"\s+", " ", text)


def answer_workbook_overview(dataset: dict[str, Any], question: str) -> dict[str, Any]:
    profile = dataset.get("profile") or {}
    workbook = profile.get("workbook") or {}
    sheets = workbook.get("sheets") or []
    active = workbook.get("active_sheet") or dataset.get("active_sheet") or "no definida"
    selectable = [s for s in sheets if s.get("selectable")]
    table = []
    for sheet in sheets:
        table.append({
            "hoja": sheet.get("name"),
            "estado": "analizable" if sheet.get("selectable") else sheet.get("mode", "no analizable"),
            "filas": sheet.get("rows", 0),
            "columnas": sheet.get("columns_count", 0),
            "metricas": sheet.get("numeric_columns_count", 0),
            "fechas": sheet.get("date_columns_count", 0),
            "encabezado_fila": sheet.get("header_row", "n/a"),
        })
    if len(selectable) > 1:
        summary = f"El archivo tiene {len(sheets)} hojas y {len(selectable)} parecen analizables. La hoja activa es '{active}'. Para evitar mezclar tablas incompatibles, el análisis avanzado trabaja sobre una hoja activa a la vez."
        recommendations = [
            "Cambia la hoja activa desde el selector cuando quieras analizar otra tabla del mismo libro.",
            "Pide análisis entre hojas solo cuando exista una llave común clara, como cliente_id, producto_id, fecha o centro de costo.",
            "Para una comparación multihoja confiable, primero revisa qué contiene cada hoja y luego define qué quieres cruzar.",
        ]
    else:
        summary = f"El archivo tiene {len(sheets)} hojas, pero solo una parece tener estructura tabular confiable para análisis avanzado. La hoja activa es '{active}'."
        recommendations = [
            "Mantén la hoja activa actual para KPIs, tendencias, rankings y gráficos.",
            "Si otra hoja contiene datos relevantes, revisa si tiene encabezados claros y filas consistentes.",
        ]
    return json_safe({
        "intent": "workbook_overview",
        "title": "Estructura del libro de Excel",
        "question": question,
        "executive_summary": summary,
        "findings": [
            f"Hojas detectadas: {len(sheets)}.",
            f"Hojas analizables: {len(selectable)}.",
            f"Hoja activa actual: {active}.",
        ],
        "recommendations": recommendations,
        "table_title": "Hojas detectadas",
        "table": table,
        "chart": None,
        "kpis": [
            {"label": "Hojas", "value": len(sheets)},
            {"label": "Analizables", "value": len(selectable)},
            {"label": "Hoja activa", "value": active},
        ],
        "limitations": [
            "La versión actual no une hojas automáticamente porque muchas hojas de Excel representan entidades distintas y unirlas sin llaves puede producir conclusiones incorrectas."
        ],
        "calculation_note": "Resumen calculado a partir de la estructura detectada del libro de Excel y de los perfiles por hoja.",
        "agent": {"llm_used": False, "provider": "local", "model": "workbook-router"},
    })

def read_dataframe(raw: bytes, filename: str) -> pd.DataFrame:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".xlsx", ".xls"}:
            df = read_excel_smart(raw, filename)
        else:
            df = read_csv_with_fallback(raw)
            df = prepare_dataframe(df)
            df.attrs["source_meta"] = {"strategy": "csv_auto", "warnings": []}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No pude leer el archivo: {exc}") from exc
    if df.empty:
        raise HTTPException(status_code=400, detail="El conjunto de datos no tiene filas.")
    return df


def read_excel_smart(raw: bytes, filename: str) -> pd.DataFrame:
    """Lee la mejor hoja tabular de un libro de Excel.

    Esta función se mantiene para compatibilidad interna; la carga principal de
    Excel usa read_excel_workbook_dataset para conservar perfiles por hoja.
    """
    _workbook, accepted, _summaries = analyze_excel_workbook(raw)
    if not accepted:
        raise HTTPException(status_code=400, detail="No encontré una tabla legible dentro del libro de Excel.")
    accepted.sort(key=lambda item: item["score"], reverse=True)
    best = accepted[0]
    df = best["df"]
    df.attrs["source_meta"] = best["meta"] | {"warnings": build_workbook_warnings(
        sheet_count=len(_workbook),
        useful_count=len(accepted),
        active_sheet=best["sheet"],
        header_row=best["header_row"],
        total_sheets=len(_workbook),
        generic_headers=best["meta"].get("generic_headers", 0),
    ), "score": round(float(best["score"]), 2)}
    return df

def excel_candidate_from_header(raw_df: pd.DataFrame, header_idx: int) -> pd.DataFrame:
    if header_idx >= len(raw_df) - 1:
        return pd.DataFrame()
    header = raw_df.iloc[header_idx].tolist()
    data = raw_df.iloc[header_idx + 1 :].copy()

    # Elimina columnas completamente vacías considerando encabezado + datos.
    keep_positions = []
    for i, value in enumerate(header):
        col_values = data.iloc[:, i] if i < data.shape[1] else pd.Series(dtype=object)
        has_header = not is_blank_cell(value)
        has_values = col_values.notna().any() if not col_values.empty else False
        if has_header or has_values:
            keep_positions.append(i)
    if not keep_positions:
        return pd.DataFrame()

    data = data.iloc[:, keep_positions]
    header = [header[i] for i in keep_positions]
    columns = make_excel_columns(header)
    data.columns = columns
    data = data.dropna(how="all")
    data = data.dropna(axis=1, how="all")

    # Quita filas que repiten encabezados dentro del cuerpo.
    normalized_columns = [normalize_header_token(c) for c in data.columns]
    repeated_header_mask = []
    for _, row in data.iterrows():
        normalized_row = [normalize_header_token(v) for v in row.tolist()]
        overlap = len(set(normalized_columns) & set(x for x in normalized_row if x))
        repeated_header_mask.append(overlap >= max(2, min(4, len(normalized_columns) // 2)))
    if repeated_header_mask:
        data = data.loc[[not flag for flag in repeated_header_mask]]
    return data.reset_index(drop=True)


def make_excel_columns(values: list[Any]) -> list[str]:
    seen: dict[str, int] = {}
    output: list[str] = []
    for index, raw in enumerate(values, start=1):
        if is_blank_cell(raw):
            name = f"Columna {index}"
        else:
            name = str(raw).strip()
            name = re.sub(r"\s+", " ", name)
            if len(name) > 80:
                name = name[:80].strip()
        base = name
        if base in seen:
            seen[base] += 1
            name = f"{base} {seen[base]}"
        else:
            seen[base] = 1
        output.append(name)
    return output


def score_excel_candidate(df: pd.DataFrame, raw_df: pd.DataFrame, header_idx: int) -> tuple[float, dict[str, Any]]:
    rows, cols = df.shape
    if rows <= 0 or cols <= 0:
        return 0.0, {}
    profile = profile_dataframe(df)
    numeric = len(profile.get("numeric_columns", []))
    dates = len(profile.get("date_columns", []))
    categorical = len(profile.get("categorical_columns", []))
    text = len(profile.get("text_columns", []))
    non_empty_ratio = 1 - (float(profile.get("missing_pct") or 0) / 100)
    generic_headers = sum(1 for c in df.columns if str(c).lower().startswith("columna "))
    header_cells = raw_df.iloc[header_idx].dropna().astype(str).str.strip() if header_idx < len(raw_df) else pd.Series(dtype=str)
    header_quality = 0
    if not header_cells.empty:
        header_quality = min(1.0, header_cells.nunique() / max(cols, 1))
        if header_cells.str.contains(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", regex=True).mean() >= 0.55:
            header_quality += 0.35

    score = 0.0
    score += min(rows, 1000) * 0.035
    score += min(cols, 30) * 2.2
    score += numeric * 14
    score += dates * 10
    score += categorical * 5
    score += min(text, 6) * 1.5
    score += non_empty_ratio * 24
    score += header_quality * 18
    score -= generic_headers * 5
    if rows < 5:
        score -= 12
    if cols < 3:
        score -= 10
    return score, {
        "rows": rows,
        "columns": cols,
        "numeric_columns": numeric,
        "date_columns": dates,
        "categorical_columns": categorical,
        "generic_headers": generic_headers,
        "missing_pct": profile.get("missing_pct"),
    }


def is_blank_cell(value: Any) -> bool:
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except Exception:
        pass
    return str(value).strip() == ""


def normalize_header_token(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9áéíóúñü]+", "", text)
    return text


def read_csv_with_fallback(raw: bytes) -> pd.DataFrame:
    last_error: Exception | None = None
    for encoding in ["utf-8", "utf-8-sig", "latin1"]:
        try:
            return pd.read_csv(io.BytesIO(raw), encoding=encoding, sep=None, engine="python")
        except Exception as exc:
            last_error = exc
    raise last_error or ValueError("Codificación CSV no soportada")


def load_dataset(
    df: pd.DataFrame,
    filename: str,
    profile: dict[str, Any] | None = None,
    sheets: dict[str, dict[str, Any]] | None = None,
    active_sheet: str | None = None,
) -> dict[str, Any]:
    dataset_id = uuid.uuid4().hex[:12]
    profile = profile or profile_dataframe(df)
    profile["mode"] = "dataset"
    DATASETS[dataset_id] = {
        "id": dataset_id,
        "filename": filename,
        "mode": "dataset",
        "df": df,
        "profile": profile,
        "sheets": sheets or {},
        "active_sheet": active_sheet,
        "history": [],
    }
    return json_safe({"dataset_id": dataset_id, "filename": filename, "mode": "dataset", "profile": profile})
