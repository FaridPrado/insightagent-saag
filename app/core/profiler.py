from __future__ import annotations

from typing import Any

import pandas as pd

from .utils import clean_dataframe_columns, format_number, is_id_like, json_safe, pct, records_to_json, try_parse_dates


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    df = clean_dataframe_columns(df)
    df = try_parse_numbers(df)
    df = try_parse_dates(df)
    return df


def try_parse_numbers(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte columnas de texto con números reales a tipo numérico.

    Muchos Excel traen importes, horas, NPS o porcentajes como texto por filas de
    encabezado, símbolos de moneda o formatos regionales. Esta rutina intenta
    convertir solo cuando la mayoría de valores no vacíos se pueden interpretar
    como números, evitando tocar IDs como TCK-10001 o Cliente 001.
    """
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_numeric_dtype(df[col]) or pd.api.types.is_datetime64_any_dtype(df[col]):
            continue
        if is_id_like(str(col), df[col]):
            continue
        series = df[col].dropna().astype(str).str.strip()
        if series.empty:
            continue
        sample = series.head(500)
        # Evita convertir columnas con códigos alfanuméricos dominantes.
        alpha_ratio = sample.str.contains(r"[A-Za-zÁÉÍÓÚáéíóúÑñ]", regex=True).mean()
        digit_ratio = sample.str.contains(r"\d", regex=True).mean()
        if digit_ratio < 0.70 or alpha_ratio > 0.35:
            continue
        normalized = df[col].astype(str).str.strip()
        normalized = normalized.str.replace(r"[^0-9,.-]", "", regex=True)

        # Formato latino: 1.234,56 -> 1234.56
        latin = normalized.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
        # Formato anglo: 1,234.56 -> 1234.56
        anglo = normalized.str.replace(",", "", regex=False)

        parsed_latin = pd.to_numeric(latin, errors="coerce")
        parsed_anglo = pd.to_numeric(anglo, errors="coerce")
        valid_base = df[col].notna().sum() or 1
        latin_rate = parsed_latin.notna().sum() / valid_base
        anglo_rate = parsed_anglo.notna().sum() / valid_base
        # Si ambos formatos convierten la misma proporción, preferimos el anglo.
        # En Excel leído como objeto es común recibir floats como texto "1234.56";
        # interpretarlos como latino produciría 123456 y distorsionaría métricas.
        parsed = parsed_latin if latin_rate > anglo_rate else parsed_anglo
        success_rate = max(latin_rate, anglo_rate)
        if success_rate >= 0.72:
            df[col] = parsed
    return df


def infer_type(series: pd.Series, column_name: str) -> str:
    if pd.api.types.is_bool_dtype(series):
        return "boolean"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "fecha"
    if pd.api.types.is_numeric_dtype(series):
        return "id" if is_id_like(column_name, series) else "numerica"
    non_null = series.dropna()
    if non_null.empty:
        return "vacia"
    unique_count = non_null.nunique(dropna=True)
    unique_ratio = unique_count / max(len(non_null), 1)
    avg_len = non_null.astype(str).str.len().mean()
    if unique_count <= 2:
        return "boolean"
    if unique_ratio <= 0.25 or unique_count <= 30:
        return "categorica"
    if avg_len > 55:
        return "texto"
    return "categorica" if unique_count <= 100 else "texto"


def profile_column(df: pd.DataFrame, column: str) -> dict[str, Any]:
    series = df[column]
    col_type = infer_type(series, column)
    non_null = series.dropna()
    base: dict[str, Any] = {
        "name": column,
        "type": col_type,
        "missing": int(series.isna().sum()),
        "missing_pct": pct(series.isna().sum(), len(series)),
        "unique": int(non_null.nunique(dropna=True)) if not non_null.empty else 0,
    }
    if col_type == "numerica":
        numeric = pd.to_numeric(series, errors="coerce").dropna()
        if not numeric.empty:
            base.update({
                "min": json_safe(numeric.min()),
                "max": json_safe(numeric.max()),
                "mean": json_safe(numeric.mean()),
                "median": json_safe(numeric.median()),
                "sum": json_safe(numeric.sum()),
                "display_mean": format_number(numeric.mean()),
                "display_sum": format_number(numeric.sum()),
            })
    elif col_type == "fecha":
        if not non_null.empty:
            base.update({"min": json_safe(non_null.min()), "max": json_safe(non_null.max())})
    elif col_type in {"categorica", "boolean", "texto", "id"}:
        top = series.astype("object").where(series.notna(), None).dropna().astype(str).value_counts().head(8)
        base["top_values"] = [{"value": str(idx), "count": int(value), "share": pct(value, len(series))} for idx, value in top.items()]
    return base


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    columns = [profile_column(df, col) for col in df.columns]
    numeric_cols = [c["name"] for c in columns if c["type"] == "numerica"]
    date_cols = [c["name"] for c in columns if c["type"] == "fecha"]
    categorical_cols = [c["name"] for c in columns if c["type"] in {"categorica", "boolean"}]
    text_cols = [c["name"] for c in columns if c["type"] == "texto"]
    missing_cells = int(df.isna().sum().sum())
    total_cells = int(df.shape[0] * df.shape[1]) if df.shape[1] else 0

    warnings: list[str] = []
    source_meta = dict(df.attrs.get("source_meta") or {})
    for note in source_meta.get("warnings", []):
        if note and note not in warnings:
            warnings.append(str(note))
    if missing_cells:
        warnings.append(f"Detecté {format_number(missing_cells, 0)} celdas vacías ({pct(missing_cells, total_cells)}% del conjunto de datos).")
    if not numeric_cols:
        warnings.append("No detecté columnas numéricas de confianza. Puedes consultar el contenido, pero los KPIs, rankings y gráficos cuantitativos serán limitados.")
    if not date_cols:
        warnings.append("No detecté columnas de fecha, así que las tendencias y comparaciones entre periodos serán limitadas.")
    if df.shape[0] > 10000:
        warnings.append("Archivo grande cargado. Esta versión analiza en memoria; para producción conviene agregar almacenamiento persistente y tareas en cola.")

    suggestions = build_suggested_questions(numeric_cols, categorical_cols, date_cols, text_cols)
    return {
        "rows": int(df.shape[0]),
        "columns_count": int(df.shape[1]),
        "columns": columns,
        "numeric_columns": numeric_cols,
        "date_columns": date_cols,
        "categorical_columns": categorical_cols,
        "text_columns": text_cols,
        "missing_cells": missing_cells,
        "missing_pct": pct(missing_cells, total_cells),
        "preview": records_to_json(df, limit=25),
        "warnings": warnings,
        "suggested_questions": suggestions,
        "source_sheet": source_meta.get("sheet"),
        "header_row": source_meta.get("header_row"),
        "workbook_sheets": source_meta.get("workbook_sheets", []),
        "extraction_strategy": source_meta.get("strategy"),
        "extraction_score": source_meta.get("score"),
    }


def build_suggested_questions(numeric_cols: list[str], categorical_cols: list[str], date_cols: list[str], text_cols: list[str]) -> list[str]:
    metric = numeric_cols[0] if numeric_cols else "ingresos"
    dim = categorical_cols[0] if categorical_cols else "segmento"
    prompts = [
        "Dame un resumen ejecutivo de este conjunto de datos.",
        f"¿Cuáles son los 10 principales valores de {dim} por {metric}?",
        f"¿Qué valores de {dim} tienen peor rendimiento?",
        "Detecta anomalías y dime qué debería investigar.",
    ]
    if date_cols and numeric_cols:
        prompts.insert(2, f"Muéstrame la tendencia de {metric} en el tiempo.")
        prompts.append(f"¿Por qué cambió {metric} en el último periodo?")
    if categorical_cols and numeric_cols:
        prompts.append(f"Segmenta {metric} por {dim} y recomienda acciones.")
    if text_cols:
        prompts.append(f"Resume los temas principales en {text_cols[0]}.")
    return prompts[:8]
