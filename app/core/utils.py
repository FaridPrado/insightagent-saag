from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


NULL_WORDS = {"", "nan", "none", "null", "nat"}


def normalize_text(value: Any) -> str:
    """Convierte a minúsculas, elimina acentos y normaliza separadores."""
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(value: Any) -> str:
    return normalize_text(value).replace(" ", "_") or "field"


def is_id_like(column_name: str, series: pd.Series | None = None) -> bool:
    name = normalize_text(column_name)
    if name in {"id", "uid", "uuid", "record id", "row id", "user id", "customer id", "client id", "account id"}:
        return True
    if name.endswith(" id") or name.endswith("_id") or name.startswith("id "):
        return True
    # No marcamos métricas numéricas de alta cardinalidad como IDs solo porque sean únicas.
    # Ingresos, costos, márgenes, scores y riesgo pueden tener alta unicidad.
    # El nombre de la columna es la señal principal para detectar IDs.
    return False


def json_safe(value: Any) -> Any:
    """Convierte objetos pandas/numpy a valores seguros para JSON."""
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        if pd.isna(value):
            return None
        return value.isoformat()
    if isinstance(value, pd.Timedelta):
        return str(value)
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if pd.isna(value):
        return None
    return value


def records_to_json(df: pd.DataFrame, limit: int = 50) -> list[dict[str, Any]]:
    if df is None or df.empty:
        return []
    subset = df.head(limit).copy()
    for col in subset.columns:
        if pd.api.types.is_datetime64_any_dtype(subset[col]):
            subset[col] = subset[col].dt.strftime("%Y-%m-%d")
    return [json_safe(row) for row in subset.to_dict(orient="records")]


def format_number(value: Any, digits: int = 2) -> str:
    if value is None or pd.isna(value):
        return "sin dato"
    try:
        num = float(value)
    except Exception:
        return str(value)
    abs_num = abs(num)
    if abs_num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.{digits}f}B"
    if abs_num >= 1_000_000:
        return f"{num / 1_000_000:.{digits}f}M"
    if abs_num >= 1_000:
        return f"{num / 1_000:.{digits}f}K"
    if abs_num == int(abs_num):
        return f"{int(num):,}"
    return f"{num:,.{digits}f}"


def pct(part: float, total: float) -> float:
    if not total:
        return 0.0
    return round((float(part) / float(total)) * 100, 2)


def clean_dataframe_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Hace que las columnas sean únicas, legibles y elimina columnas vacías."""
    df = df.copy()
    df = df.dropna(axis=1, how="all")
    seen: dict[str, int] = {}
    columns: list[str] = []
    for idx, raw in enumerate(df.columns):
        name = str(raw).strip() or f"Columna {idx + 1}"
        if name.lower().startswith("unnamed:"):
            name = f"Columna {idx + 1}"
        base = name
        if base in seen:
            seen[base] += 1
            name = f"{base} {seen[base]}"
        else:
            seen[base] = 1
        columns.append(name)
    df.columns = columns
    return df


def try_parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Interpreta columnas de texto como fechas cuando la mayoría de valores parecen fechas."""
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        if not (pd.api.types.is_object_dtype(df[col]) or pd.api.types.is_string_dtype(df[col])):
            continue
        series = df[col].dropna().astype(str).str.strip()
        if series.empty:
            continue
        name = normalize_text(col)
        sample = series.head(200)
        date_hint = any(token in name for token in ["date", "fecha", "created", "updated", "day", "month", "period", "periodo", "dia", "día", "mes"])
        if not date_hint and sample.str.contains(r"\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", regex=True).mean() < 0.55:
            continue
        
        try:
            parsed = pd.to_datetime(df[col], errors="coerce", format="mixed")
        except TypeError:
            parsed = pd.to_datetime(df[col], errors="coerce")
        success_rate = parsed.notna().sum() / max(df[col].notna().sum(), 1)
        if success_rate >= 0.70:
            df[col] = parsed
    return df


def clip_string(value: Any, max_len: int = 160) -> str:
    text = str(value) if value is not None else ""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "..."
