from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from typing import Any

import pandas as pd

from .agent import plan_analysis, polish_response
from .profiler import profile_dataframe
from .utils import clip_string, format_number, json_safe, normalize_text, pct, records_to_json


METRIC_HINTS = {
    "ingresos": ["revenue", "sales", "venta", "ventas", "ingreso", "ingresos", "mrr", "arr", "gmv", "amount", "importe", "valor", "total", "billing", "facturacion", "facturación"],
    "utilidad": ["profit", "ganancia", "utilidad", "margin", "margen"],
    "costos": ["cost", "costo", "coste", "expense", "gasto"],
    "cantidad": ["quantity", "qty", "cantidad", "units", "unidades", "orders", "ordenes", "órdenes", "pedidos"],
    "score": ["score", "nps", "csat", "satisfaction", "satisfaccion", "satisfacción", "rating", "calificacion", "calificación"],
    "riesgo": ["risk", "riesgo", "churn", "attrition", "retention", "retencion", "retención"],
}

DIMENSION_HINTS = [
    "customer", "cliente", "client", "account", "cuenta", "empresa", "company", "owner", "responsable",
    "seller", "sales rep", "vendedor", "asesor", "producto", "product", "plan", "category", "categoria",
    "categoría", "segment", "segmento", "region", "región", "pais", "país", "country", "city", "ciudad",
    "channel", "canal", "status", "estado",
]

DATE_HINTS = ["date", "fecha", "created", "updated", "period", "periodo", "month", "mes", "day", "dia", "día", "quarter", "trimestre"]
RISK_NEGATIVE_HINTS = ["ticket", "complaint", "queja", "incident", "incidente", "delay", "late", "overdue", "atraso", "riesgo", "risk", "churn"]
RISK_POSITIVE_HINTS = ["nps", "csat", "satisfaction", "satisfaccion", "satisfacción", "score", "rating", "health", "salud"]


VALID_INTENTS = {
    "smalltalk",
    "summary",
    "trend",
    "change",
    "ranking_desc",
    "ranking_asc",
    "anomalies",
    "risk",
    "correlation",
    "average",
    "total",
    "distribution",
    "themes",
    "chart",
    "profile",
    "file_assessment",
    "executive_recommendation",
    "groupby",
}

CONVERSATIONAL_PHRASES = [
    "hola",
    "buenas",
    "buenos dias",
    "buenas tardes",
    "buenas noches",
    "como estas",
    "como vas",
    "que tal",
    "hey",
    "hi",
    "hello",
    "gracias",
    "muchas gracias",
    "ok",
    "vale",
    "perfecto",
    "listo",
    "quien eres",
    "que eres",
    "que puedes hacer",
    "como funcionas",
    "como funciona",
    "ayuda",
    "help",
]

DATA_REQUEST_TERMS = set(
    " ".join([
        "resumen ejecutivo diagnostico analisis analizar insight hallazgo recomendacion",
        "ingresos ventas revenue sales margen utilidad costos gasto cantidad unidades pedidos ordenes",
        "cliente clientes producto productos segmento segmentos pais region canal vendedor responsable",
        "ranking top mejores peores mayor menor principales lider",
        "tendencia mensual semanal diario fecha periodo cambio aumento caida subio bajo bajaron",
        "anomalia anomalías anomalias outlier raro inusual extrano extraño atipico atípico riesgo churn retencion renovacion",
        "correlacion relacion distribucion histograma promedio media total suma cuanto",
        "tabla grafico grafica barras linea pastel torta dispersion scatter columnas campos metricas dimension dimensiones filas celdas vacias archivo documento mixto reunion gerencia ejecutivo",
    ]).split()
)


@dataclass
class Context:
    question: str
    question_norm: str
    profile: dict[str, Any]
    metric: str | None
    dimension: str | None
    date_col: str | None


def analyze_question(df: pd.DataFrame, question: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or profile_dataframe(df)
    ctx = build_context(df, question, profile)
    fallback_intent = detect_intent(ctx.question_norm)

    # Los mensajes conversacionales no deben pasar por el motor analítico.
    # Esto evita que saludos como "Hola" terminen generando siempre el mismo resumen del dataset.
    if fallback_intent == "smalltalk":
        return answer_conversational(ctx)

    plan = plan_analysis(
        question=ctx.question,
        profile=profile,
        fallback={"intent": fallback_intent, "metric": ctx.metric, "dimension": ctx.dimension, "date_col": ctx.date_col},
    )
    selected_intent = normalize_intent(plan.get("intent"), fallback_intent)
    ctx = apply_plan_to_context(df, ctx, plan)
    answer = execute_intent(df, ctx, selected_intent)
    answer.setdefault("analysis_plan", [])
    answer["analysis_plan"] = [
        f"Intención seleccionada: {spanish_intent(selected_intent)}",
        f"Métrica usada: {ctx.metric or 'no detectada'}",
        f"Dimensión usada: {ctx.dimension or 'no detectada'}",
        f"Fecha usada: {ctx.date_col or 'no detectada'}",
    ] + answer.get("analysis_plan", [])[:4]
    return polish_response(answer, profile, ctx.question, plan)


def execute_intent(df: pd.DataFrame, ctx: Context, intent: str) -> dict[str, Any]:
    if intent == "smalltalk":
        return answer_conversational(ctx)
    if intent == "summary":
        return answer_summary(df, ctx)
    if intent == "trend":
        return answer_trend(df, ctx)
    if intent == "change":
        return answer_change(df, ctx)
    if intent == "ranking_desc":
        return answer_ranking(df, ctx, ascending=False)
    if intent == "ranking_asc":
        return answer_ranking(df, ctx, ascending=True)
    if intent == "anomalies":
        return answer_anomalies(df, ctx)
    if intent == "risk":
        return answer_risk(df, ctx)
    if intent == "correlation":
        return answer_correlation(df, ctx)
    if intent == "average":
        return answer_kpi(df, ctx, mode="promedio")
    if intent == "total":
        return answer_kpi(df, ctx, mode="total")
    if intent == "distribution":
        return answer_distribution(df, ctx)
    if intent == "themes":
        return answer_themes(df, ctx)
    if intent == "chart":
        return answer_chart(df, ctx)
    if intent == "profile":
        return answer_profile(df, ctx)
    if intent == "file_assessment":
        return answer_file_assessment(df, ctx)
    if intent == "executive_recommendation":
        return answer_executive_recommendation(df, ctx)
    return answer_groupby(df, ctx)


def build_context(df: pd.DataFrame, question: str, profile: dict[str, Any]) -> Context:
    q = question.strip() or "Dame un resumen ejecutivo de este conjunto de datos."
    qn = normalize_text(q)
    metric = select_metric(df, profile, qn)
    dimension = select_dimension(df, profile, qn, metric)
    date_col = select_date_column(profile, qn)
    return Context(question=q, question_norm=qn, profile=profile, metric=metric, dimension=dimension, date_col=date_col)


def apply_plan_to_context(df: pd.DataFrame, ctx: Context, plan: dict[str, Any]) -> Context:
    columns = set(df.columns)
    metric = plan.get("metric") if plan.get("metric") in columns else ctx.metric
    dimension = plan.get("dimension") if plan.get("dimension") in columns else ctx.dimension
    date_col = plan.get("date_col") if plan.get("date_col") in columns else ctx.date_col
    return replace(ctx, metric=metric, dimension=dimension, date_col=date_col)


def normalize_intent(raw_intent: Any, fallback: str) -> str:
    intent = normalize_text(str(raw_intent or "")).strip()
    if intent in VALID_INTENTS:
        return intent
    return fallback if fallback in VALID_INTENTS else "groupby"


def detect_intent(qn: str) -> str:
    if is_conversational_message(qn):
        return "smalltalk"

    # Intenciones específicas antes del resumen general.
    if any(w in qn for w in ["grafica", "grafico", "gráfica", "gráfico", "chart", "barras", "barra", "linea", "línea", "pastel", "torta", "pie", "dispersion", "dispersión", "scatter", "histograma"]):
        return "chart"
    if any(w in qn for w in ["dataset de negocio", "archivo parece", "parece un dataset", "documento", "archivo mixto", "tipo de archivo", "estructura del archivo", "es tabular"]):
        return "file_assessment"
    if any(w in qn for w in ["recomendacion ejecutiva", "recomendación ejecutiva", "reunion de gerencia", "reunión de gerencia", "junta", "gerencia", "decision ejecutiva", "decisión ejecutiva", "para una reunion", "para una reunión"]):
        return "executive_recommendation"
    if any(w in qn for w in ["anomalia", "anomalía", "anomalias", "anomalías", "outlier", "raro", "inusual", "extraño", "extrano", "atipico", "atípico", "que ves raro", "qué ves raro"]):
        return "anomalies"
    if any(w in qn for w in ["riesgo", "churn", "retention", "retencion", "retención", "renovar", "renovacion", "renovación", "renewal"]):
        return "risk"
    if any(w in qn for w in ["correlacion", "correlación", "relacion entre", "relación entre"]):
        return "correlation"
    if any(w in qn for w in ["tema", "temas", "palabras", "comentarios", "feedback", "texto"]):
        return "themes"
    if any(w in qn for w in ["tendencia", "por mes", "por semana", "por dia", "por día", "mensual", "semanal", "evolucion", "evolución", "linea de tiempo", "línea de tiempo"]):
        return "trend"
    if any(w in qn for w in ["columnas detectaste", "que columnas", "qué columnas", "columnas hay", "campos", "metrica principal", "métrica principal", "dimensiones detectaste", "mapa del conjunto"]):
        return "profile"
    if any(w in qn for w in ["cambio", "bajo", "bajaron", "cayo", "cayó", "caida", "caída", "subio", "subió", "aumento", "aumentó", "por que", "por qué", "ultimo periodo", "último periodo"]):
        return "change"
    if any(w in qn for w in ["peor", "menor", "menores", "bottom", "bajo rendimiento", "menos"]):
        return "ranking_asc"
    if any(w in qn for w in ["top", "mejor", "mejores", "mayor", "mayores", "ranking", "lider", "líder", "principal"]):
        return "ranking_desc"
    if any(w in qn for w in ["promedio", "media"]):
        return "average"
    if any(w in qn for w in ["total", "suma", "cuanto", "cuánto"]):
        return "total"
    if any(w in qn for w in ["distribucion", "distribución", "histograma"]):
        return "distribution"
    if any(w in qn for w in ["resumen", "ejecutivo", "overview", "diagnostico", "diagnóstico", "que ves", "qué ves", "que esta pasando", "qué está pasando"]):
        return "summary"
    return "groupby"


def is_conversational_message(qn: str) -> bool:
    qn = (qn or "").strip()
    if not qn:
        return True

    tokens = re.findall(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ0-9]+", qn)
    token_count = len(tokens)
    has_data_terms = any(term in qn.split() for term in DATA_REQUEST_TERMS) or any(phrase in qn for phrase in [
        "por ingresos", "por ventas", "por cliente", "por producto", "por segmento",
        "datos", "dataset", "conjunto", "archivo", "excel", "csv", "analiza", "analizar",
    ])

    if any(phrase in qn for phrase in CONVERSATIONAL_PHRASES):
        if not has_data_terms:
            return True
        # Permite preguntas de ayuda cortas aunque haya una palabra genérica como "archivo".
        if token_count <= 10 and any(phrase in qn for phrase in ["que puedes hacer", "como funcionas", "como funciona", "ayuda", "help"]):
            return True

    # Mensajes cortos sin intención analítica clara se responden como conversación normal.
    if token_count <= 8 and not has_data_terms:
        return True

    return False


def spanish_intent(intent: str) -> str:
    return {
        "smalltalk": "conversación",
        "summary": "resumen ejecutivo",
        "trend": "tendencia temporal",
        "change": "cambio entre periodos",
        "ranking_desc": "ranking superior",
        "ranking_asc": "ranking inferior",
        "anomalies": "detección de anomalías",
        "risk": "riesgo",
        "correlation": "correlación",
        "average": "promedio",
        "total": "total",
        "distribution": "distribución",
        "themes": "temas de texto",
        "chart": "gráfico solicitado",
        "profile": "perfil de columnas",
        "file_assessment": "evaluación del archivo",
        "executive_recommendation": "recomendación ejecutiva",
        "groupby": "segmentación",
    }.get(str(intent), "segmentación")


def select_metric(df: pd.DataFrame, profile: dict[str, Any], qn: str) -> str | None:
    numeric_cols = profile.get("numeric_columns", [])
    if not numeric_cols:
        return None
    scored: list[tuple[int, str]] = []
    for col in numeric_cols:
        cn = normalize_text(col)
        score = 0
        if cn and cn in qn:
            score += 100
        for hints in METRIC_HINTS.values():
            for h in hints:
                hn = normalize_text(h)
                if hn in qn and hn in cn:
                    score += 60
                elif hn in cn:
                    score += 12
                elif hn in qn and any(part in cn for part in hn.split()):
                    score += 8
        if any(bad in cn for bad in ["id", "zip", "phone", "telefono", "teléfono", "year", "ano", "año"]):
            score -= 30
        non_null = pd.to_numeric(df[col], errors="coerce").notna().sum()
        score += min(10, int(non_null / max(len(df), 1) * 10))
        scored.append((score, col))
    scored.sort(reverse=True, key=lambda item: item[0])
    return scored[0][1] if scored else numeric_cols[0]


def select_dimension(df: pd.DataFrame, profile: dict[str, Any], qn: str, metric: str | None = None) -> str | None:
    candidates = list(profile.get("categorical_columns", [])) + [c for c in profile.get("text_columns", []) if df[c].nunique(dropna=True) <= 80]
    if not candidates:
        return None
    scored: list[tuple[int, str]] = []
    for col in candidates:
        if col == metric:
            continue
        cn = normalize_text(col)
        unique = df[col].nunique(dropna=True)
        score = 0
        if cn and cn in qn:
            score += 100
        for hint in DIMENSION_HINTS:
            hn = normalize_text(hint)
            if hn in qn and hn in cn:
                score += 70
            elif hn in cn:
                score += 16
        if 2 <= unique <= 20:
            score += 20
        elif 21 <= unique <= 80:
            score += 10
        elif unique > 150:
            score -= 20
        scored.append((score, col))
    scored.sort(reverse=True, key=lambda item: item[0])
    return scored[0][1] if scored else candidates[0]


def select_date_column(profile: dict[str, Any], qn: str) -> str | None:
    date_cols = profile.get("date_columns", [])
    if not date_cols:
        return None
    scored: list[tuple[int, str]] = []
    for col in date_cols:
        cn = normalize_text(col)
        score = 0
        if cn in qn:
            score += 100
        if any(h in cn for h in DATE_HINTS):
            score += 20
        scored.append((score, col))
    scored.sort(reverse=True, key=lambda item: item[0])
    return scored[0][1]


def base_response(ctx: Context, title: str, intent: str) -> dict[str, Any]:
    return {
        "intent": intent,
        "title": title,
        "question": ctx.question,
        "executive_summary": "",
        "findings": [],
        "recommendations": [],
        "table": [],
        "table_title": "",
        "chart": None,
        "kpis": [],
        "analysis_plan": [],
        "limitations": [],
        "calculation_note": f"Cálculo realizado sobre {format_number(ctx.profile.get('rows', 0), 0)} filas y {format_number(ctx.profile.get('columns_count', 0), 0)} columnas del conjunto activo.",
    }


def answer_conversational(ctx: Context) -> dict[str, Any]:
    res = base_response(ctx, "Listo para ayudarte", "smalltalk")
    rows = ctx.profile.get("rows", 0)
    columns = ctx.profile.get("columns_count", 0)
    mode = ctx.profile.get("mode", "dataset")
    qn = ctx.question_norm
    is_greeting = any(phrase in qn for phrase in ["hola", "buenas", "buenos dias", "buenas tardes", "buenas noches", "como estas", "que tal", "hey", "hi", "hello"])

    if mode == "document":
        res["executive_summary"] = (
            "Hola. El archivo está cargado y puedo ayudarte a consultar su contenido."
            if is_greeting else
            "No identifiqué una solicitud concreta sobre el archivo. Puedo ayudarte a resumirlo, extraer puntos clave o buscar información específica en su contenido."
        )
        res["recommendations"] = [
            "Pídeme un resumen del documento.",
            "Pregúntame por puntos clave, riesgos, acuerdos o próximos pasos.",
            "Solicita que compare secciones o extraiga información específica.",
        ]
        res["calculation_note"] = "No se ejecutó análisis tabular porque el mensaje no contenía una solicitud analítica."
    else:
        res["executive_summary"] = (
            "Hola. El conjunto de datos está cargado y puedo ayudarte a convertir preguntas de negocio en análisis claros."
            if is_greeting else
            "No identifiqué una solicitud analítica clara. El conjunto de datos está cargado; puedes pedir un resumen, ranking, tendencia, anomalía, gráfico o recomendación ejecutiva."
        )
        res["kpis"] = [
            {"label": "Filas cargadas", "value": format_number(rows, 0)},
            {"label": "Columnas", "value": format_number(columns, 0)},
        ]
        res["recommendations"] = [
            "Pide un resumen ejecutivo del conjunto de datos.",
            "Pregunta por rankings de clientes, productos, segmentos o responsables.",
            "Solicita tendencias, anomalías, cambios recientes o riesgos.",
        ]
        res["calculation_note"] = "No se ejecutaron cálculos sobre el conjunto de datos porque el mensaje no contenía una solicitud analítica."

    res["analysis_plan"] = [
        "El mensaje fue clasificado como conversacional.",
        "No se ejecutó ranking, tendencia, anomalía ni agregación.",
        "Se devolvió una respuesta de orientación para continuar el análisis.",
    ]
    res["agent"] = {"llm_used": False, "provider": "local", "model": "router-conversacional"}
    return finalize(res)


def answer_summary(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    res = base_response(ctx, "Resumen ejecutivo", "summary")
    rows = len(df)
    columns = len(df.columns)
    metric = ctx.metric
    dim = ctx.dimension
    date_col = ctx.date_col
    missing_pct = ctx.profile.get("missing_pct", 0)
    res["executive_summary"] = f"Analicé {format_number(rows, 0)} filas y {columns} columnas. El conjunto de datos está listo para preguntas de negocio y tiene {format_number(missing_pct)}% de celdas vacías."
    res["kpis"] = [
        {"label": "Filas", "value": format_number(rows, 0)},
        {"label": "Columnas", "value": format_number(columns, 0)},
        {"label": "Celdas vacías", "value": f"{format_number(missing_pct)}%"},
    ]
    if metric:
        series = pd.to_numeric(df[metric], errors="coerce").dropna()
        if not series.empty:
            total = float(series.sum())
            avg = float(series.mean())
            res["kpis"].extend([
                {"label": f"Total de {metric}", "value": format_number(total)},
                {"label": f"Promedio de {metric}", "value": format_number(avg)},
            ])
            res["findings"].append(f"La métrica numérica principal parece ser {metric}: total {format_number(total)} y promedio {format_number(avg)}.")
    if dim and metric:
        grouped = safe_group_sum(df, dim, metric).head(8)
        if not grouped.empty:
            top = grouped.iloc[0]
            total_metric = float(pd.to_numeric(df[metric], errors="coerce").sum())
            share = pct(top[metric], total_metric)
            res["findings"].append(f"{top[dim]} es el mayor valor de {dim} por {metric}, con {format_number(top[metric])} ({share}% del total).")
            display_table = add_ranking_position(grouped)
            res["table_title"] = f"Principales {dim} por {metric}"
            res["table"] = records_to_json(display_table, limit=8)
            res["chart"] = chart_payload("bar", grouped, dim, metric, f"Principales {dim} por {metric}")
    if date_col and metric:
        trend = monthly_trend(df, date_col, metric, granularity=requested_time_granularity(ctx.question_norm))
        if len(trend) >= 2:
            latest = trend.iloc[-1]
            previous = trend.iloc[-2]
            change = pct(latest[metric] - previous[metric], previous[metric]) if previous[metric] else 0.0
            res["findings"].append(f"El último periodo ({latest['periodo']}) cerró en {format_number(latest[metric])}, una variación de {format_number(change)}% frente a {previous['periodo']}.")
    res["recommendations"] = [
        "Pregunta por una tendencia para entender la dirección del negocio en el tiempo.",
        "Pregunta por los mejores y peores segmentos para detectar concentración o bajo rendimiento.",
        "Pide anomalías antes de tomar decisiones basadas en picos o caídas aisladas.",
    ]
    res["calculation_note"] = f"Perfilado automático sobre {format_number(rows, 0)} filas: se detectaron tipos de columnas, métricas disponibles, dimensiones y valores faltantes."
    res["analysis_plan"] = ["Se perfilaron columnas", "Se detectaron métricas y dimensiones", "Se calcularon KPIs base", "Se generaron preguntas recomendadas"]
    return finalize(res)


def answer_ranking(df: pd.DataFrame, ctx: Context, ascending: bool) -> dict[str, Any]:
    metric = ctx.metric
    dim = ctx.dimension
    direction = "menor" if ascending else "mayor"
    res = base_response(ctx, f"Ranking de {dim or 'segmentos'} por {metric or 'métrica'}", "ranking_asc" if ascending else "ranking_desc")
    if not metric or not dim:
        res["executive_summary"] = "Necesito al menos una métrica numérica y una dimensión categórica para construir un ranking."
        res["limitations"].append("No se detectó una métrica o dimensión adecuada.")
        return finalize(res)
    limit = requested_limit(ctx.question_norm, default=10, maximum=25)
    grouped = safe_group_sum(df, dim, metric, ascending=ascending).head(limit)
    if grouped.empty:
        res["executive_summary"] = "No pude crear un ranking con las columnas seleccionadas."
        return finalize(res)
    leader = grouped.iloc[0]
    total = float(pd.to_numeric(df[metric], errors="coerce").sum())
    share = pct(float(leader[metric]), total)
    res["executive_summary"] = f"El {direction} {dim} es {leader[dim]} con {format_number(leader[metric])} en {metric}, equivalente al {share}% del total."
    res["findings"] = [
        f"El ranking agrega {metric} por {dim}.",
        f"Los {min(3, len(grouped))} primeros valores del ranking suman {format_number(grouped.head(3)[metric].sum())}.",
        "La tabla de soporte muestra el valor individual y la participación de cada posición.",
    ]
    if len(grouped) >= 2:
        gap = float(grouped.iloc[0][metric]) - float(grouped.iloc[1][metric])
        res["findings"].append(f"La diferencia entre el puesto 1 y el puesto 2 es {format_number(abs(gap))}.")
    res["recommendations"] = [
        "Investiga qué está haciendo diferente el segmento líder y documenta el patrón.",
        "Revisa los segmentos inferiores para encontrar problemas de datos, proceso o bloqueo comercial.",
        "Pide una tendencia por periodo para saber si el ranking es estable o reciente.",
    ]
    display_table = add_ranking_position(grouped)
    res["table_title"] = f"Ranking de {dim} por {metric}"
    res["table"] = records_to_json(display_table, limit=len(display_table))
    res["chart"] = chart_payload("bar", grouped, dim, metric, f"Ranking de {dim} por {metric}")
    res["calculation_note"] = f"Cálculo realizado sobre {format_number(len(df), 0)} filas: se agrupó {metric} por {dim} y se ordenó de {direction} a {'mayor' if ascending else 'menor'}."
    res["analysis_plan"] = [f"Métrica seleccionada: {metric}", f"Dimensión seleccionada: {dim}", "Se agruparon valores", "Se ordenó el ranking"]
    return finalize(res)


def answer_groupby(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    metric = ctx.metric
    dim = ctx.dimension
    res = base_response(ctx, f"Segmentación por {dim or 'dimensión'}", "groupby")
    if not metric or not dim:
        return answer_summary(df, ctx)
    grouped = safe_group_sum(df, dim, metric).head(12)
    total = float(pd.to_numeric(df[metric], errors="coerce").sum())
    if not grouped.empty:
        top = grouped.iloc[0]
        res["executive_summary"] = f"{metric} se concentra principalmente en {top[dim]}, con {format_number(top[metric])} ({pct(top[metric], total)}% del total)."
        res["findings"] = [
            f"Agrupé {format_number(len(df), 0)} filas por {dim} y sumé {metric}.",
            f"Los 5 grupos principales representan {format_number(grouped.head(5)[metric].sum())} de {metric}.",
        ]
        res["recommendations"] = [
            "Compara los grupos principales contra conversión, margen o tickets si esas columnas existen.",
            "Usa esta segmentación para priorizar acciones en lugar de tratar todos los registros igual.",
        ]
        display_table = add_ranking_position(grouped)
        res["table_title"] = f"Segmentación de {metric} por {dim}"
        res["table"] = records_to_json(display_table, limit=12)
        res["chart"] = chart_payload("bar", grouped, dim, metric, f"{metric} por {dim}")
        res["calculation_note"] = f"Cálculo realizado sobre {format_number(len(df), 0)} filas: se agrupó {metric} por {dim}."
    return finalize(res)


def answer_kpi(df: pd.DataFrame, ctx: Context, mode: str) -> dict[str, Any]:
    metric = ctx.metric
    res = base_response(ctx, f"{mode.capitalize()} de {metric or 'métrica'}", "average" if mode == "promedio" else "total")
    if not metric:
        res["executive_summary"] = "No detecté una métrica numérica para este cálculo."
        return finalize(res)
    series = pd.to_numeric(df[metric], errors="coerce").dropna()
    if series.empty:
        res["executive_summary"] = f"{metric} no tiene suficientes valores numéricos."
        return finalize(res)
    value = series.mean() if mode == "promedio" else series.sum()
    res["executive_summary"] = f"El {mode} de {metric} es {format_number(value)} sobre {format_number(len(series), 0)} filas válidas."
    res["kpis"] = [{"label": f"{mode.capitalize()} de {metric}", "value": format_number(value)}]
    res["findings"] = [f"Mínimo: {format_number(series.min())}.", f"Máximo: {format_number(series.max())}.", f"Mediana: {format_number(series.median())}."]
    res["calculation_note"] = f"Cálculo realizado sobre {format_number(len(series), 0)} filas válidas de la métrica {metric}."
    res["recommendations"] = ["Pide este KPI por segmento o periodo para convertirlo en una decisión accionable."]
    return finalize(res)


def answer_trend(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    metric = ctx.metric
    date_col = ctx.date_col
    res = base_response(ctx, f"Tendencia de {metric or 'métrica'} en el tiempo", "trend")
    if not metric or not date_col:
        res["executive_summary"] = "Necesito una métrica numérica y una columna de fecha para calcular una tendencia."
        res["limitations"].append("No se detectó una métrica o columna de fecha adecuada.")
        return finalize(res)
    granularity = requested_time_granularity(ctx.question_norm)
    trend = monthly_trend(df, date_col, metric, granularity=granularity)
    if trend.empty:
        res["executive_summary"] = "No pude calcular la tendencia temporal con las columnas seleccionadas."
        return finalize(res)
    first = trend.iloc[0]
    latest = trend.iloc[-1]
    change = pct(float(latest[metric]) - float(first[metric]), float(first[metric])) if first[metric] else 0.0
    res["executive_summary"] = f"{metric} pasó de {format_number(first[metric])} en {first['periodo']} a {format_number(latest[metric])} en {latest['periodo']}, una variación de {format_number(change)}% en el periodo disponible."
    if len(trend) >= 2:
        prev = trend.iloc[-2]
        mom = pct(float(latest[metric]) - float(prev[metric]), float(prev[metric])) if prev[metric] else 0.0
        res["findings"].append(f"El último periodo cambió {format_number(mom)}% frente a {prev['periodo']}.")
    peak = trend.sort_values(metric, ascending=False).iloc[0]
    low = trend.sort_values(metric, ascending=True).iloc[0]
    res["findings"].extend([f"Periodo pico: {peak['periodo']} con {format_number(peak[metric])}.", f"Periodo más bajo: {low['periodo']} con {format_number(low[metric])}."])
    res["recommendations"] = ["Revisa los drivers del último periodo por segmento para entender qué cambió.", "Busca eventos comerciales u operativos alrededor de los periodos pico y bajo."]
    label = granularity_label(granularity)
    res["table_title"] = f"Tendencia {label} de {metric}"
    res["table"] = records_to_json(trend.tail(12), limit=12)
    res["chart"] = chart_payload("line", trend, "periodo", metric, f"Tendencia {label} de {metric}")
    res["calculation_note"] = f"Cálculo realizado sobre registros con {date_col} y {metric}: se agregaron valores con granularidad {label}."
    res["analysis_plan"] = [f"Se interpretó {date_col} como periodo", f"Se agregó {metric} con granularidad {label}", "Se calcularon variaciones temporales"]
    return finalize(res)


def answer_change(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    metric = ctx.metric
    date_col = ctx.date_col
    dim = ctx.dimension
    res = base_response(ctx, f"Cambio del último periodo en {metric or 'métrica'}", "change")
    if not metric or not date_col:
        return answer_trend(df, ctx)
    granularity = requested_time_granularity(ctx.question_norm)
    trend = monthly_trend(df, date_col, metric, granularity=granularity)
    if len(trend) < 2:
        res["executive_summary"] = "Se necesitan al menos dos periodos para explicar un cambio."
        return finalize(res)
    latest = trend.iloc[-1]
    previous = trend.iloc[-2]
    delta = float(latest[metric]) - float(previous[metric])
    change = pct(delta, float(previous[metric])) if previous[metric] else 0.0
    direction = "aumentó" if delta >= 0 else "disminuyó"
    res["executive_summary"] = f"{metric} {direction} en {format_number(abs(delta))} ({format_number(change)}%) de {previous['periodo']} a {latest['periodo']}."
    res["findings"] = [f"Periodo anterior: {previous['periodo']} = {format_number(previous[metric])}.", f"Último periodo: {latest['periodo']} = {format_number(latest[metric])}."]
    if dim:
        driver_table = period_driver_table(df, date_col, metric, dim, previous["periodo"], latest["periodo"], granularity=granularity)
        if not driver_table.empty:
            driver = driver_table.iloc[0]
            res["findings"].append(f"El principal driver absoluto por {dim} fue {driver[dim]}, con variación de {format_number(driver['variacion'])}.")
            res["table_title"] = f"Drivers del cambio de {metric} por {dim}"
            res["table"] = records_to_json(driver_table.head(10), limit=10)
            res["chart"] = chart_payload("bar", driver_table.head(10), dim, "variacion", f"Drivers del cambio de {metric} por {dim}")
    if not res["chart"]:
        res["table_title"] = f"Tendencia reciente de {metric}"
        res["table"] = records_to_json(trend.tail(12), limit=12)
        res["chart"] = chart_payload("line", trend, "periodo", metric, f"{metric} en el tiempo")
    res["calculation_note"] = f"Comparación entre {previous['periodo']} y {latest['periodo']} sobre {metric}; los drivers se calculan por {dim} cuando existe una dimensión válida. Granularidad: {granularity_label(granularity)}."
    res["recommendations"] = [
        "Valida si el driver es un movimiento real del negocio o un problema de actualización de datos.",
        "Compara la misma métrica por segmento, responsable, producto y canal antes de decidir acciones.",
        "Crea una alerta si el movimiento del último periodo es importante para la operación.",
    ]
    return finalize(res)


def answer_anomalies(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    metric = ctx.metric
    date_col = ctx.date_col
    res = base_response(ctx, "Detección de anomalías", "anomalies")
    if not metric:
        res["executive_summary"] = "No detecté una métrica numérica para analizar anomalías."
        return finalize(res)
    if date_col:
        data = monthly_trend(df, date_col, metric)
        label_col = "periodo"
    else:
        data = df[[metric]].copy().reset_index().rename(columns={"index": "fila"})
        label_col = "fila"
    if data.empty or data[metric].nunique() <= 1:
        res["executive_summary"] = "La métrica seleccionada no tiene suficiente variación para detectar anomalías."
        return finalize(res)
    values = pd.to_numeric(data[metric], errors="coerce")
    mean = values.mean()
    std = values.std(ddof=0)
    if not std or math.isnan(std):
        std = 1.0
    data = data.copy()
    data["z_score"] = ((values - mean) / std).round(2)
    data["severidad"] = data["z_score"].abs().map(lambda x: "Alta" if x >= 2 else "Media" if x >= 1.3 else "Baja")
    anomalies = data[data["z_score"].abs() >= 1.3].sort_values("z_score", key=lambda s: s.abs(), ascending=False).head(10)
    if anomalies.empty:
        res["executive_summary"] = f"No encontré anomalías fuertes en {metric}. Los valores se mantienen relativamente estables alrededor de {format_number(mean)}."
        anomalies = data.sort_values(metric, ascending=False).head(5)
    else:
        strongest = anomalies.iloc[0]
        res["executive_summary"] = f"Encontré {len(anomalies)} posibles anomalías en {metric}. La más fuerte aparece en {strongest[label_col]} con z-score {strongest['z_score']}."
    res["findings"] = [f"Promedio base de {metric}: {format_number(mean)}.", f"Desviación estándar base: {format_number(std)}."]
    res["recommendations"] = ["Trata las anomalías como pistas de investigación, no como conclusiones automáticas.", "Verifica si la anomalía se explica por estacionalidad, campañas, datos faltantes o incidentes operativos."]
    res["table_title"] = f"Posibles anomalías en {metric}"
    res["table"] = records_to_json(anomalies, limit=10)
    res["chart"] = chart_payload("bar", anomalies, label_col, metric, f"Posibles anomalías en {metric}")
    res["calculation_note"] = f"Cálculo realizado sobre {format_number(len(data), 0)} puntos usando z-score de {metric}."
    return finalize(res)


def answer_correlation(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    res = base_response(ctx, "Análisis de correlaciones", "correlation")
    numeric_cols = ctx.profile.get("numeric_columns", [])
    if len(numeric_cols) < 2:
        res["executive_summary"] = "Se necesitan al menos dos columnas numéricas para analizar correlaciones."
        return finalize(res)
    corr = df[numeric_cols].apply(pd.to_numeric, errors="coerce").corr(numeric_only=True)
    rows: list[dict[str, Any]] = []
    for i, a in enumerate(numeric_cols):
        for b in numeric_cols[i + 1 :]:
            value = corr.loc[a, b]
            if pd.isna(value):
                continue
            rows.append({"metrica_a": a, "metrica_b": b, "correlacion": round(float(value), 3), "fuerza": abs(float(value))})
    rows = sorted(rows, key=lambda item: item["fuerza"], reverse=True)[:10]
    if not rows:
        res["executive_summary"] = "No encontré correlaciones relevantes."
        return finalize(res)
    top = rows[0]
    res["executive_summary"] = f"La relación numérica más fuerte está entre {top['metrica_a']} y {top['metrica_b']}, con correlación {top['correlacion']}."
    res["findings"] = ["Correlación no implica causalidad. Úsalo como una pista para análisis más profundo."]
    res["recommendations"] = ["Valida las relaciones fuertes por segmento y periodo antes de usarlas para decisiones."]
    table = pd.DataFrame(rows).drop(columns=["fuerza"])
    res["table_title"] = "Correlaciones más fuertes"
    res["table"] = records_to_json(table, limit=10)
    res["chart"] = chart_payload("bar", pd.DataFrame(rows), "metrica_b", "fuerza", "Correlaciones más fuertes")
    res["calculation_note"] = f"Cálculo realizado sobre {format_number(len(numeric_cols), 0)} métricas numéricas con correlación de Pearson."
    return finalize(res)


def answer_distribution(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    metric = ctx.metric
    res = base_response(ctx, f"Distribución de {metric or 'métrica'}", "distribution")
    if not metric:
        res["executive_summary"] = "No detecté una métrica numérica para analizar distribución."
        return finalize(res)
    values = pd.to_numeric(df[metric], errors="coerce").dropna()
    if values.empty:
        res["executive_summary"] = f"{metric} no contiene valores numéricos."
        return finalize(res)
    bins = min(10, max(4, int(math.sqrt(len(values)))))
    counts = pd.cut(values, bins=bins).value_counts().sort_index()
    table = pd.DataFrame({"rango": [str(idx) for idx in counts.index], "conteo": counts.values})
    res["executive_summary"] = f"{metric} va de {format_number(values.min())} a {format_number(values.max())}, con mediana de {format_number(values.median())}."
    res["findings"] = [f"Promedio: {format_number(values.mean())}.", f"Desviación estándar: {format_number(values.std())}."]
    res["recommendations"] = ["Revisa los rangos extremos y compara la distribución por segmento."]
    res["table_title"] = f"Distribución de {metric}"
    res["table"] = records_to_json(table, limit=12)
    res["chart"] = chart_payload("bar", table, "rango", "conteo", f"Distribución de {metric}")
    res["calculation_note"] = f"Cálculo realizado sobre {format_number(len(values), 0)} valores válidos de {metric}."
    return finalize(res)


def answer_themes(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    res = base_response(ctx, "Temas en texto", "themes")
    text_cols = ctx.profile.get("text_columns", [])
    candidates = text_cols or [c for c in ctx.profile.get("categorical_columns", []) if df[c].nunique(dropna=True) > 8]
    if not candidates:
        res["executive_summary"] = "No detecté una columna de texto para extraer temas."
        return finalize(res)
    col = candidates[0]
    stopwords = set("the a an and or to of in for from with by on at is are was were be been que para por con los las una uno este esta de del el la en y o un al se es son como mas más pero sin sus tus mis mi tu su".split())
    words: dict[str, int] = {}
    for value in df[col].dropna().astype(str).head(5000):
        for word in re.findall(r"[a-zA-Z][a-zA-Z0-9_]{2,}", normalize_text(value)):
            if word not in stopwords:
                words[word] = words.get(word, 0) + 1
    top = sorted(words.items(), key=lambda item: item[1], reverse=True)[:15]
    table = pd.DataFrame(top, columns=["palabra_clave", "conteo"])
    res["executive_summary"] = f"La palabra clave más repetida en {col} es {top[0][0] if top else 'n/a'}."
    res["findings"] = [f"Analicé hasta 5.000 valores de texto de la columna {col}."]
    res["recommendations"] = ["Usa este resultado como escaneo rápido. Para producción, agrega embeddings y clustering de temas."]
    res["table_title"] = f"Palabras frecuentes en {col}"
    res["table"] = records_to_json(table, limit=15)
    res["chart"] = chart_payload("bar", table, "palabra_clave", "conteo", f"Palabras frecuentes en {col}")
    res["calculation_note"] = f"Cálculo realizado sobre hasta 5.000 valores de texto de la columna {col}."
    return finalize(res)


def answer_risk(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    res = base_response(ctx, "Análisis de riesgo", "risk")
    entity = select_entity_column(df, ctx)
    if not entity:
        res["executive_summary"] = "No pude detectar una columna de cliente, cuenta o entidad para analizar riesgo."
        return finalize(res)
    working = df.copy()
    feature_notes: list[str] = []
    score_parts: list[pd.Series] = []
    for col in ctx.profile.get("numeric_columns", []):
        cn = normalize_text(col)
        values = pd.to_numeric(working[col], errors="coerce")
        if values.dropna().empty:
            continue
        normed = normalize_series(values)
        if any(h in cn for h in RISK_NEGATIVE_HINTS):
            score_parts.append(normed.fillna(0) * 30)
            feature_notes.append(f"Valores altos en {col} aumentan el riesgo.")
        if any(h in cn for h in RISK_POSITIVE_HINTS):
            score_parts.append((1 - normed.fillna(0)) * 30)
            feature_notes.append(f"Valores bajos en {col} aumentan el riesgo.")
        if "churn" in cn or "riesgo" in cn or "risk" in cn:
            score_parts.append(normed.fillna(0) * 45)
            feature_notes.append(f"{col} fue tratado como señal directa de riesgo.")
    if ctx.date_col:
        dates = pd.to_datetime(working[ctx.date_col], errors="coerce")
        max_date = dates.max()
        if pd.notna(max_date):
            days_since = (max_date - dates).dt.days
            working["_dias_desde_ultimo_evento"] = days_since
            score_parts.append(normalize_series(days_since).fillna(0) * 25)
            feature_notes.append(f"Fechas más antiguas en {ctx.date_col} aumentan el riesgo.")
    if not score_parts:
        if ctx.metric:
            values = pd.to_numeric(working[ctx.metric], errors="coerce")
            score_parts.append((1 - normalize_series(values).fillna(0)) * 45)
            feature_notes.append(f"Valores bajos en {ctx.metric} se usaron como aproximación de riesgo.")
        else:
            res["executive_summary"] = "No detecté señales de riesgo. Agrega columnas como riesgo_churn, tickets, NPS, satisfacción, última actividad o ingresos."
            return finalize(res)
    working["_puntaje_riesgo"] = sum(score_parts).clip(lower=0, upper=100)
    agg_dict: dict[str, Any] = {"_puntaje_riesgo": "mean"}
    if ctx.metric:
        agg_dict[ctx.metric] = "sum"
    if ctx.date_col:
        agg_dict[ctx.date_col] = "max"
    risk_all = working.groupby(entity, dropna=False).agg(agg_dict).reset_index()
    risk_all["puntaje_riesgo"] = risk_all["_puntaje_riesgo"].round(1)
    risk_all["nivel_riesgo"] = risk_all["puntaje_riesgo"].map(lambda x: "Alto" if x >= 65 else "Medio" if x >= 35 else "Bajo")
    risk_all = risk_all.drop(columns=["_puntaje_riesgo"]).sort_values("puntaje_riesgo", ascending=False)
    limit = requested_limit(ctx.question_norm, default=10, maximum=25)
    risk = risk_all.head(limit)
    top = risk.iloc[0] if not risk.empty else None
    res["executive_summary"] = f"Evalué {format_number(len(risk_all), 0)} registros de {entity} y muestro los {format_number(len(risk), 0)} con mayor prioridad. El mayor riesgo es {top[entity]} con puntaje {top['puntaje_riesgo']}/100." if top is not None else "No pude crear una tabla de riesgo."
    res["findings"] = feature_notes[:4] or ["El puntaje de riesgo es heurístico y se basa en las columnas disponibles."]
    res["findings"].append(f"La tabla está limitada a {format_number(len(risk), 0)} registros según la solicitud o el valor por defecto.")
    res["calculation_note"] = f"Puntaje heurístico calculado por {entity} con las señales disponibles; escala de 0 a 100, donde valores altos indican mayor prioridad de revisión. Se evaluaron {format_number(len(risk_all), 0)} registros y se muestran {format_number(len(risk), 0)}."
    res["recommendations"] = [
        "Usa la lista de alto riesgo como cola de revisión gerencial, no como decisión automática final.",
        "Agrega etiquetas reales de churn o renovación para entrenar un modelo más sólido después.",
        "Pide el riesgo por responsable o segmento para asignar acciones concretas.",
    ]
    res["table_title"] = f"Mayor riesgo por {entity}"
    res["table"] = records_to_json(risk, limit=len(risk))
    res["chart"] = chart_payload("bar", risk, entity, "puntaje_riesgo", f"Mayor riesgo por {entity}")
    return finalize(res)




def answer_profile(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    res = base_response(ctx, "Mapa del conjunto de datos", "profile")
    numeric = ctx.profile.get("numeric_columns", [])
    dates = ctx.profile.get("date_columns", [])
    categorical = ctx.profile.get("categorical_columns", [])
    text_cols = ctx.profile.get("text_columns", [])
    metric = ctx.metric or (numeric[0] if numeric else None)
    dim = ctx.dimension or (categorical[0] if categorical else None)
    date_col = ctx.date_col or (dates[0] if dates else None)
    source = ctx.profile.get("source_sheet")
    source_txt = f" La hoja seleccionada para el análisis fue '{source}'." if source else ""
    res["executive_summary"] = (
        f"Detecté {format_number(ctx.profile.get('rows', 0), 0)} filas y {format_number(ctx.profile.get('columns_count', 0), 0)} columnas. "
        f"La métrica principal sugerida es {metric or 'no detectada'}; la dimensión principal sugerida es {dim or 'no detectada'}." + source_txt
    )
    res["kpis"] = [
        {"label": "Columnas", "value": format_number(ctx.profile.get("columns_count", 0), 0)},
        {"label": "Métricas", "value": format_number(len(numeric), 0)},
        {"label": "Fechas", "value": format_number(len(dates), 0)},
        {"label": "Dimensiones", "value": format_number(len(categorical), 0)},
    ]
    rows = []
    for col in ctx.profile.get("columns", []):
        rows.append({
            "columna": col.get("name"),
            "tipo": tipo_legible(col.get("type")),
            "unicos": col.get("unique"),
            "vacios_pct": col.get("missing_pct"),
            "suma": col.get("display_sum") or "",
            "promedio": col.get("display_mean") or "",
        })
    res["table_title"] = "Columnas detectadas"
    res["table"] = rows[:40]
    res["findings"] = [
        f"Métricas numéricas: {', '.join(numeric) if numeric else 'ninguna detectada' }.",
        f"{plural_count(len(dates), 'columna de fecha', 'columnas de fecha')}: {', '.join(dates) if dates else 'ninguna detectada' }.",
        f"Dimensiones categóricas: {', '.join(categorical[:8]) if categorical else 'ninguna detectada' }.",
    ]
    if text_cols:
        res["findings"].append(f"Columnas de texto disponibles: {', '.join(text_cols[:5])}.")
    res["recommendations"] = [
        "Usa la métrica principal para resúmenes, tendencias y rankings iniciales.",
        "Pide análisis por una dimensión concreta si quieres comparar segmentos, clientes, países o categorías.",
        "Si una columna fue clasificada de forma inesperada, renómbrala o limpia su formato en el archivo original.",
    ]
    res["calculation_note"] = "Se leyó el perfil de columnas generado al cargar el archivo; no se ejecutó una agregación adicional."
    return finalize(res)


def answer_file_assessment(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    res = base_response(ctx, "Evaluación del archivo", "file_assessment")
    numeric = len(ctx.profile.get("numeric_columns", []))
    dates = len(ctx.profile.get("date_columns", []))
    categorical = len(ctx.profile.get("categorical_columns", []))
    text_cols = len(ctx.profile.get("text_columns", []))
    sheet = ctx.profile.get("source_sheet")
    header_row = ctx.profile.get("header_row")
    workbook_sheets = ctx.profile.get("workbook_sheets", [])
    looks_dataset = ctx.profile.get("rows", 0) >= 5 and ctx.profile.get("columns_count", 0) >= 3 and (numeric + dates + categorical) >= 2
    classification = "dataset tabular de negocio" if looks_dataset else "archivo documental o mixto"
    res["executive_summary"] = f"Este archivo parece un {classification}. Detecté {numeric} métricas numéricas, {dates} columnas de fecha, {categorical} dimensiones y {text_cols} columnas de texto."
    if sheet:
        res["findings"].append(f"Para el análisis se seleccionó la hoja '{sheet}'" + (f" con encabezados en la fila {header_row}." if header_row else "."))
    if workbook_sheets:
        res["findings"].append(f"El libro contiene {len(workbook_sheets)} hoja(s): {', '.join(map(str, workbook_sheets[:8]))}.")
    res["findings"].extend([
        f"Tamaño analizado: {format_number(ctx.profile.get('rows', 0), 0)} filas y {format_number(ctx.profile.get('columns_count', 0), 0)} columnas.",
        f"Celdas vacías estimadas: {format_number(ctx.profile.get('missing_pct', 0))}%.",
    ])
    res["recommendations"] = [
        "Si quieres análisis avanzado, conserva una fila clara de encabezados y una tabla principal por hoja.",
        "Si el archivo mezcla reportes, notas y tablas, el sistema intentará seleccionar la tabla más útil automáticamente.",
        "Para auditoría, revisa la vista previa y confirma que la hoja/tabla seleccionada sea la esperada.",
    ]
    res["limitations"] = ctx.profile.get("warnings", [])[:5]
    res["calculation_note"] = "Evaluación basada en la estructura detectada al cargar el archivo: filas, columnas, tipos, hoja seleccionada y encabezados."
    return finalize(res)


def answer_executive_recommendation(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    res = base_response(ctx, "Recomendación ejecutiva", "executive_recommendation")
    metric = ctx.metric
    dim = ctx.dimension
    date_col = ctx.date_col
    parts: list[str] = []
    table = pd.DataFrame()
    if metric:
        values = pd.to_numeric(df[metric], errors="coerce").dropna()
        if not values.empty:
            parts.append(f"{metric} totaliza {format_number(values.sum())} con promedio de {format_number(values.mean())}.")
            res["kpis"].extend([
                {"label": f"Total de {metric}", "value": format_number(values.sum())},
                {"label": f"Promedio de {metric}", "value": format_number(values.mean())},
            ])
    if dim and metric:
        grouped = safe_group_sum(df, dim, metric).head(5)
        if not grouped.empty:
            table = add_ranking_position(grouped)
            leader = grouped.iloc[0]
            parts.append(f"La mayor concentración está en {leader[dim]} con {format_number(leader[metric])}.")
            res["chart"] = chart_payload("bar", grouped, dim, metric, f"Principales {dim} por {metric}")
    if date_col and metric:
        trend = monthly_trend(df, date_col, metric)
        if len(trend) >= 2:
            latest = trend.iloc[-1]
            prev = trend.iloc[-2]
            delta = pct(float(latest[metric]) - float(prev[metric]), float(prev[metric])) if prev[metric] else 0
            parts.append(f"El último periodo cambió {format_number(delta)}% frente a {prev['periodo']}.")
    res["executive_summary"] = " ".join(parts) if parts else "El archivo está listo para una revisión ejecutiva, pero necesito una métrica clara para priorizar decisiones."
    res["findings"] = parts or ["No hay suficiente evidencia cuantitativa para priorizar una decisión única."]
    res["recommendations"] = [
        "Prioriza la revisión de los segmentos con mayor impacto económico o mayor riesgo operativo.",
        "Valida los cambios recientes antes de asignar responsables o presupuesto.",
        "Convierte los hallazgos principales en 2 o 3 acciones con dueño, fecha y métrica de seguimiento.",
    ]
    if not table.empty:
        res["table_title"] = f"Evidencia principal por {dim}"
        res["table"] = records_to_json(table, limit=5)
    res["calculation_note"] = f"Recomendación generada con KPIs, concentración por dimensión y tendencia temporal cuando esas columnas existen. Base: {format_number(len(df), 0)} filas."
    return finalize(res)


def answer_chart(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    chart_type = requested_chart_type(ctx.question_norm)
    metric = ctx.metric
    dim = ctx.dimension
    date_col = ctx.date_col

    if chart_type == "line":
        return answer_trend(df, ctx)
    if chart_type == "histogram":
        res = answer_distribution(df, ctx)
        if res.get("chart"):
            res["chart"]["type"] = "histogram"
        return res
    if chart_type == "scatter":
        return answer_scatter_chart(df, ctx)
    if chart_type == "pie":
        return answer_pie_chart(df, ctx)

    # Barras por defecto: ranking/segmentación.
    if metric and dim:
        res = answer_ranking(df, ctx, ascending=False)
        if res.get("chart"):
            res["chart"]["type"] = "bar"
        res["intent"] = "chart"
        res["title"] = f"Gráfica de barras de {metric} por {dim}"
        return res
    res = answer_summary(df, ctx)
    res["intent"] = "chart"
    res["limitations"].append("No detecté una combinación clara de métrica y dimensión para graficar.")
    return res


def answer_pie_chart(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    metric = ctx.metric
    dim = ctx.dimension
    res = base_response(ctx, f"Gráfica de pastel de {metric or 'métrica'} por {dim or 'dimensión'}", "chart")
    if not metric or not dim:
        res["executive_summary"] = "Necesito una métrica numérica y una dimensión categórica para crear una gráfica de pastel."
        res["limitations"].append("No se detectó métrica o dimensión suficiente para participación porcentual.")
        return finalize(res)
    grouped = safe_group_sum(df, dim, metric).head(8)
    if grouped.empty:
        res["executive_summary"] = "No pude crear la gráfica de pastel con las columnas seleccionadas."
        return finalize(res)
    res["executive_summary"] = f"La gráfica de pastel muestra la participación de {metric} por {dim}. El grupo líder es {grouped.iloc[0][dim]} con {format_number(grouped.iloc[0][metric])}."
    res["table_title"] = f"Participación de {metric} por {dim}"
    res["table"] = records_to_json(add_ranking_position(grouped), limit=8)
    res["chart"] = chart_payload("pie", grouped, dim, metric, f"Participación de {metric} por {dim}")
    res["findings"] = [f"Los {len(grouped)} grupos principales representan {format_number(grouped[metric].sum())} de {metric}."]
    res["recommendations"] = ["Usa la participación para revisar concentración y dependencia de pocos segmentos.", "Complementa con una tendencia si necesitas saber si la concentración está creciendo o bajando."]
    res["calculation_note"] = f"Cálculo realizado sobre {format_number(len(df), 0)} filas: se agrupó {metric} por {dim} y se calculó participación."
    return finalize(res)


def answer_scatter_chart(df: pd.DataFrame, ctx: Context) -> dict[str, Any]:
    metrics = select_two_metrics(ctx)
    res = base_response(ctx, "Gráfica de dispersión", "chart")
    if len(metrics) < 2:
        res["executive_summary"] = "Necesito dos métricas numéricas para crear una gráfica de dispersión."
        res["limitations"].append("No se detectaron dos columnas numéricas en la pregunta o en el archivo.")
        return finalize(res)
    x_col, y_col = metrics[0], metrics[1]
    data = df[[x_col, y_col]].copy()
    data[x_col] = pd.to_numeric(data[x_col], errors="coerce")
    data[y_col] = pd.to_numeric(data[y_col], errors="coerce")
    data = data.dropna().head(300)
    if data.empty:
        res["executive_summary"] = f"No hay suficientes valores válidos para graficar {x_col} contra {y_col}."
        return finalize(res)
    corr = data[x_col].corr(data[y_col])
    res["executive_summary"] = f"La gráfica de dispersión compara {x_col} contra {y_col}. La correlación aproximada en los puntos válidos es {format_number(corr)}."
    res["kpis"] = [{"label": "Puntos graficados", "value": format_number(len(data), 0)}, {"label": "Correlación", "value": format_number(corr)}]
    res["findings"] = ["Cada punto representa un registro con valores válidos en ambas métricas.", "La correlación es una señal exploratoria; no implica causalidad."]
    res["recommendations"] = ["Revisa puntos extremos porque pueden explicar comportamientos atípicos.", "Segmenta la dispersión por cliente, país o producto si necesitas una causa accionable."]
    res["table_title"] = f"Muestra de puntos: {x_col} vs {y_col}"
    res["table"] = records_to_json(data.head(12), limit=12)
    res["chart"] = chart_payload("scatter", data, x_col, y_col, f"{y_col} vs {x_col}")
    res["calculation_note"] = f"Cálculo realizado sobre {format_number(len(data), 0)} registros válidos de {x_col} y {y_col}."
    return finalize(res)


def requested_chart_type(qn: str) -> str:
    if any(x in qn for x in ["pastel", "torta", "pie"]):
        return "pie"
    if any(x in qn for x in ["dispersion", "dispersión", "scatter"]):
        return "scatter"
    if "histograma" in qn:
        return "histogram"
    if any(x in qn for x in ["linea", "línea", "tendencia", "mensual", "tiempo"]):
        return "line"
    return "bar"


def select_two_metrics(ctx: Context) -> list[str]:
    numeric = ctx.profile.get("numeric_columns", [])
    matches = []
    for col in numeric:
        if normalize_text(col) in ctx.question_norm:
            matches.append(col)
    if ctx.metric and ctx.metric not in matches:
        matches.insert(0, ctx.metric)
    for col in numeric:
        if col not in matches:
            matches.append(col)
        if len(matches) >= 2:
            break
    return matches[:2]


def tipo_legible(kind: Any) -> str:
    return {
        "numerica": "numérica",
        "fecha": "fecha",
        "categorica": "categórica",
        "texto": "texto",
        "boolean": "booleano",
        "vacia": "vacía",
        "id": "id",
    }.get(str(kind), str(kind or "desconocido"))


def requested_limit(qn: str, default: int = 10, maximum: int = 50) -> int:
    match = re.search(r"\b(?:top|primeros|primeras|principales|mayores|menores)?\s*(\d{1,3})\b", qn or "")
    if not match:
        return default
    try:
        value = int(match.group(1))
    except Exception:
        return default
    return max(1, min(value, maximum))


def requested_time_granularity(qn: str | None) -> str | None:
    qn = qn or ""
    if any(word in qn for word in ["diario", "diaria", "por dia", "por día", "dia a dia", "día a día"]):
        return "D"
    if any(word in qn for word in ["semanal", "por semana", "semanas"]):
        return "W"
    if any(word in qn for word in ["mensual", "por mes", "mes a mes", "meses"]):
        return "M"
    if any(word in qn for word in ["trimestral", "trimestre", "quarter", "q1", "q2", "q3", "q4"]):
        return "Q"
    if any(word in qn for word in ["anual", "por ano", "por año", "year", "ano a ano", "año a año"]):
        return "Y"
    return None


def granularity_label(granularity: str | None) -> str:
    return {
        "D": "diaria",
        "W": "semanal",
        "M": "mensual",
        "Q": "trimestral",
        "Y": "anual",
        None: "automática",
    }.get(granularity, "automática")


def plural_count(count: int, singular: str, plural: str) -> str:
    return f"{format_number(count, 0)} {singular if count == 1 else plural}"

def add_ranking_position(grouped: pd.DataFrame) -> pd.DataFrame:
    display = grouped.copy().reset_index(drop=True)
    if "posicion" in display.columns:
        display = display.drop(columns=["posicion"])
    display.insert(0, "posicion", range(1, len(display) + 1))
    return display


def safe_group_sum(df: pd.DataFrame, dim: str, metric: str, ascending: bool = False) -> pd.DataFrame:
    data = df[[dim, metric]].copy()
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    data[dim] = data[dim].fillna("Sin dato").astype(str).map(lambda x: clip_string(x, 80))
    grouped = data.groupby(dim, dropna=False)[metric].sum(min_count=1).reset_index()
    grouped = grouped.dropna(subset=[metric]).sort_values(metric, ascending=ascending)
    grouped["participacion_pct"] = grouped[metric].map(lambda x: pct(x, grouped[metric].sum()))
    return grouped


def monthly_trend(df: pd.DataFrame, date_col: str, metric: str, granularity: str | None = None) -> pd.DataFrame:
    data = df[[date_col, metric]].copy()
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    data = data.dropna(subset=[date_col, metric])
    if data.empty:
        return pd.DataFrame(columns=["periodo", metric])
    span_days = (data[date_col].max() - data[date_col].min()).days
    period_code = granularity
    if period_code not in {"D", "W", "M", "Q", "Y"}:
        if span_days <= 45:
            period_code = "D"
        elif span_days <= 370:
            period_code = "M"
        else:
            period_code = "Q"
    period = data[date_col].dt.to_period(period_code)
    grouped = data.groupby(period)[metric].sum(min_count=1).reset_index()
    grouped[date_col] = grouped[date_col].astype(str)
    grouped = grouped.rename(columns={date_col: "periodo"})
    return grouped


def period_driver_table(df: pd.DataFrame, date_col: str, metric: str, dim: str, prev_period: str, latest_period: str, granularity: str | None = None) -> pd.DataFrame:
    data = df[[date_col, metric, dim]].copy()
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce")
    data[metric] = pd.to_numeric(data[metric], errors="coerce")
    span_days = (data[date_col].max() - data[date_col].min()).days if data[date_col].notna().any() else 0
    period_code = granularity
    if period_code not in {"D", "W", "M", "Q", "Y"}:
        if span_days <= 45:
            period_code = "D"
        elif span_days <= 370:
            period_code = "M"
        else:
            period_code = "Q"
    data["periodo"] = data[date_col].dt.to_period(period_code).astype(str)
    filtered = data[data["periodo"].isin([prev_period, latest_period])].copy()
    if filtered.empty:
        return pd.DataFrame()
    grouped = filtered.groupby([dim, "periodo"], dropna=False)[metric].sum(min_count=1).reset_index()
    pivot = grouped.pivot_table(index=dim, columns="periodo", values=metric, aggfunc="sum", fill_value=0).reset_index()
    if prev_period not in pivot.columns:
        pivot[prev_period] = 0
    if latest_period not in pivot.columns:
        pivot[latest_period] = 0
    pivot["anterior"] = pivot[prev_period]
    pivot["actual"] = pivot[latest_period]
    pivot["variacion"] = pivot["actual"] - pivot["anterior"]
    pivot["variacion_pct"] = pivot.apply(lambda row: pct(row["variacion"], row["anterior"]) if row["anterior"] else None, axis=1)
    pivot = pivot[[dim, "anterior", "actual", "variacion", "variacion_pct"]]
    pivot[dim] = pivot[dim].fillna("Sin dato").astype(str).map(lambda x: clip_string(x, 80))
    return pivot.sort_values("variacion", key=lambda s: s.abs(), ascending=False)


def select_entity_column(df: pd.DataFrame, ctx: Context) -> str | None:
    candidates = list(ctx.profile.get("categorical_columns", [])) + [c for c in ctx.profile.get("text_columns", []) if df[c].nunique(dropna=True) <= max(200, len(df) * 0.9)]
    priority = ["customer", "cliente", "client", "account", "cuenta", "company", "empresa", "user", "usuario", "lead"]
    best: tuple[int, str] | None = None
    for col in candidates:
        cn = normalize_text(col)
        score = 0
        for token in priority:
            if token in cn:
                score += 100
        unique = df[col].nunique(dropna=True)
        if 5 <= unique <= 200:
            score += 15
        if best is None or score > best[0]:
            best = (score, col)
    if best and best[0] > 0:
        return best[1]
    return ctx.dimension


def normalize_series(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    min_v = values.min()
    max_v = values.max()
    if pd.isna(min_v) or pd.isna(max_v) or max_v == min_v:
        return pd.Series([0.0] * len(values), index=values.index)
    return (values - min_v) / (max_v - min_v)


def chart_payload(chart_type: str, df: pd.DataFrame, x_key: str, y_key: str, title: str) -> dict[str, Any]:
    data = records_to_json(df[[x_key, y_key]].copy(), limit=40) if x_key in df.columns and y_key in df.columns else []
    return {"type": chart_type, "xKey": x_key, "yKey": y_key, "title": title, "data": data}


def finalize(res: dict[str, Any]) -> dict[str, Any]:
    if not res.get("executive_summary"):
        res["executive_summary"] = "Completé el análisis y preparé los resultados más relevantes para este conjunto de datos."
    res["calculation_note"] = res.get("calculation_note") or "Resultado calculado con herramientas seguras sobre el conjunto de datos cargado."
    res["findings"] = res.get("findings") or []
    res["recommendations"] = res.get("recommendations") or []
    res["limitations"] = res.get("limitations") or []
    return json_safe(res)
