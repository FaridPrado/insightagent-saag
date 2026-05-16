from __future__ import annotations

import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from copy import deepcopy
from typing import Any

from .utils import json_safe

VALID_INTENTS = {
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

DEFAULT_PROVIDER_ORDER = "gemini,openrouter,cerebras,groq"
DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openrouter": "openrouter/free",
    "cerebras": "gpt-oss-120b",
    "groq": "llama-3.3-70b-versatile",
}
PROVIDER_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "cerebras": "CEREBRAS_API_KEY",
    "groq": "GROQ_API_KEY",
}
OPENAI_COMPATIBLE_ENDPOINTS = {
    "openrouter": "https://openrouter.ai/api/v1/chat/completions",
    "cerebras": "https://api.cerebras.ai/v1/chat/completions",
    "groq": "https://api.groq.com/openai/v1/chat/completions",
}


class LLMProviderError(RuntimeError):
    pass


def provider_order() -> list[str]:
    raw = os.getenv("LLM_PROVIDER_ORDER", DEFAULT_PROVIDER_ORDER)
    order: list[str] = []
    for item in raw.split(","):
        provider = item.strip().lower()
        if provider in PROVIDER_KEYS and provider not in order:
            order.append(provider)
    return order or ["gemini", "openrouter", "cerebras", "groq"]


def provider_model(provider: str) -> str:
    return os.getenv(f"{provider.upper()}_MODEL", DEFAULT_MODELS[provider])


def provider_has_key(provider: str) -> bool:
    return bool(os.getenv(PROVIDER_KEYS[provider]))


def available_providers() -> list[str]:
    if os.getenv("LLM_ENABLED", "true").lower() in {"0", "false", "no", "off"}:
        return []
    return [provider for provider in provider_order() if provider_has_key(provider)]


def llm_available() -> bool:
    return bool(available_providers())


def active_model() -> str:
    providers = available_providers()
    if not providers:
        return "analizador local"
    return provider_model(providers[0])


def agent_status() -> dict[str, Any]:
    providers = available_providers()
    if not providers:
        return {
            "provider": "local",
            "model": "analizador local",
            "llm_enabled": False,
            "provider_order": [],
            "available_providers": [],
        }
    return {
        "provider": "multi-provider",
        "primary_provider": providers[0],
        "model": provider_model(providers[0]),
        "llm_enabled": True,
        "provider_order": provider_order(),
        "available_providers": providers,
        "models": {provider: provider_model(provider) for provider in providers},
    }


def compact_profile(profile: dict[str, Any], max_columns: int = 36) -> dict[str, Any]:
    columns = []
    for col in profile.get("columns", [])[:max_columns]:
        item: dict[str, Any] = {
            "nombre": col.get("name"),
            "tipo": col.get("type"),
            "faltantes_pct": col.get("missing_pct"),
            "unicos": col.get("unique"),
        }
        if col.get("top_values"):
            item["valores_frecuentes"] = [x.get("value") for x in col.get("top_values", [])[:5]]
        if col.get("display_sum"):
            item["suma"] = col.get("display_sum")
        if col.get("display_mean"):
            item["promedio"] = col.get("display_mean")
        columns.append(item)
    return {
        "filas": profile.get("rows"),
        "columnas": profile.get("columns_count"),
        "metricas_numericas": profile.get("numeric_columns", []),
        "fechas": profile.get("date_columns", []),
        "dimensiones": profile.get("categorical_columns", []),
        "texto": profile.get("text_columns", []),
        "faltantes_pct": profile.get("missing_pct"),
        "modo": profile.get("mode"),
        "hoja_origen": profile.get("source_sheet"),
        "fila_encabezados": profile.get("header_row"),
        "hojas_libro": profile.get("workbook_sheets", []),
        "advertencias": profile.get("warnings", []),
        "columnas_detalle": columns,
    }


def plan_analysis(question: str, profile: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Use an LLM as a planner, but always fall back to the local router."""
    base_plan = {
        "intent": fallback.get("intent") or "groupby",
        "metric": fallback.get("metric"),
        "dimension": fallback.get("dimension"),
        "date_col": fallback.get("date_col"),
        "confidence": 0.55,
        "reason": "Plan local por reglas.",
        "source": "local",
        "provider": "local",
        "model": "analizador local",
    }
    if not llm_available():
        return base_plan

    schema = compact_profile(profile)
    system = (
        "Eres el planificador de InsightAgent, un agente de inteligencia de negocio. "
        "Tu trabajo es elegir UNA herramienta segura para responder la pregunta del usuario. "
        "No calcules resultados. No inventes columnas. Usa solamente columnas que existan en el perfil. "
        "Si el usuario pide una granularidad temporal concreta como mensual, semanal, diaria, trimestral o anual, conserva esa intención. "
        "Responde exclusivamente con JSON válido."
    )
    user = {
        "pregunta_usuario": question,
        "perfil_conjunto_datos": schema,
        "herramientas_disponibles": sorted(VALID_INTENTS),
        "instrucciones": {
            "summary": "resumen ejecutivo general del conjunto de datos",
            "trend": "evolucion temporal de una metrica usando una columna fecha",
            "change": "explicacion del cambio entre el ultimo periodo y el anterior",
            "ranking_desc": "top/mejores/mayores por metrica",
            "ranking_asc": "peores/menores/bajo rendimiento por metrica",
            "anomalies": "valores inusuales o anomalias",
            "risk": "clientes/cuentas/registros con mayor riesgo",
            "correlation": "relaciones entre metricas numericas",
            "average": "promedio de una metrica",
            "total": "suma o total de una metrica",
            "distribution": "distribucion de una metrica o histograma",
            "themes": "temas/palabras frecuentes en texto",
            "chart": "generar grafico solicitado: barras, linea, pastel, dispersion o histograma",
            "profile": "explicar columnas detectadas, metrica principal, fechas y dimensiones",
            "file_assessment": "explicar si el archivo parece dataset, documento o archivo mixto",
            "executive_recommendation": "recomendacion ejecutiva para reunion, gerencia o toma de decisiones",
            "groupby": "segmentacion por dimension cuando la pregunta no encaja en otra herramienta",
        },
        "formato_respuesta": {
            "intent": "uno de herramientas_disponibles",
            "metric": "nombre exacto de columna numerica o null",
            "dimension": "nombre exacto de columna categorica/texto o null",
            "date_col": "nombre exacto de columna fecha o null",
            "confidence": "numero entre 0 y 1",
            "reason": "explicación breve",
        },
    }
    try:
        data = _chat_json([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ], max_tokens=700, temperature=0.05)
    except Exception as exc:
        base_plan["reason"] = f"Plan local por fallo del agente: {type(exc).__name__}."
        return base_plan

    provider = str(data.pop("__provider", "llm"))
    model = str(data.pop("__model", "modelo activo"))
    allowed_columns = {c.get("name") for c in profile.get("columns", [])}
    plan = base_plan | {
        "intent": data.get("intent") if data.get("intent") in VALID_INTENTS else base_plan["intent"],
        "metric": _valid_column(data.get("metric"), allowed_columns) or base_plan.get("metric"),
        "dimension": _valid_column(data.get("dimension"), allowed_columns) or base_plan.get("dimension"),
        "date_col": _valid_column(data.get("date_col"), allowed_columns) or base_plan.get("date_col"),
        "confidence": _safe_float(data.get("confidence"), default=0.75),
        "reason": str(data.get("reason") or "Plan elegido por el agente."),
        "source": "llm",
        "provider": provider,
        "model": model,
    }
    return json_safe(plan)


def polish_response(answer: dict[str, Any], profile: dict[str, Any], question: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Let the model write the business explanation without changing computed evidence."""
    enriched = deepcopy(answer)
    enriched["agent"] = {
        "provider": plan.get("provider", "local"),
        "model": plan.get("model", "analizador local"),
        "llm_used": plan.get("source") == "llm" and llm_available(),
        "planner": plan.get("source", "local"),
        "confidence": plan.get("confidence"),
        "reason": plan.get("reason"),
    }
    if not llm_available():
        return json_safe(enriched)

    evidence = {
        "titulo_actual": answer.get("title"),
        "resumen_actual": answer.get("executive_summary"),
        "hallazgos": answer.get("findings", [])[:8],
        "recomendaciones": answer.get("recommendations", [])[:8],
        "limitaciones": answer.get("limitations", [])[:5],
        "kpis": answer.get("kpis", [])[:8],
        "tabla_titulo": answer.get("table_title"),
        "tabla_muestra": answer.get("table", [])[:10],
        "base_calculo": answer.get("calculation_note"),
        "grafico": {
            "tipo": (answer.get("chart") or {}).get("type"),
            "titulo": (answer.get("chart") or {}).get("title"),
            "x": (answer.get("chart") or {}).get("xKey"),
            "y": (answer.get("chart") or {}).get("yKey"),
        } if answer.get("chart") else None,
    }
    system = (
        "Eres un analista ejecutivo de datos para gerentes. "
        "Redacta con estilo natural, claro y profesional. "
        "Mantén la respuesta enfocada en la decisión de negocio y no agregues contexto externo. "
        "No inventes números, columnas ni conclusiones que no estén en la evidencia. "
        "Si mencionas un ranking, incluye cifras concretas; no listes entidades sin valores. "
        "Conserva el sentido de los cálculos y evita exagerar conclusiones. "
        "No uses jerga innecesaria ni frases como 'métrica usada' salvo que el usuario lo pida. "
        "Responde solamente con JSON válido."
    )
    user = {
        "pregunta_usuario": question,
        "plan_del_agente": plan,
        "perfil_resumido": compact_profile(profile, max_columns=24),
        "evidencia_calculada_por_herramientas": evidence,
        "formato_respuesta": {
            "title": "título breve",
            "executive_summary": "respuesta ejecutiva de 1 a 3 frases, basada en evidencia",
            "findings": ["3 a 6 hallazgos concretos con cifras cuando existan en la evidencia"],
            "recommendations": ["2 a 5 acciones recomendadas"],
            "limitations": ["limitaciones importantes, o lista vacia"],
        },
    }
    try:
        refined = _chat_json([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ], max_tokens=1100, temperature=float(os.getenv("LLM_TEMPERATURE", "0.15")))
    except Exception as exc:
        enriched["agent"]["llm_used"] = False
        enriched["agent"]["reason"] = f"Respuesta local por fallo del agente: {type(exc).__name__}."
        return json_safe(enriched)

    provider = str(refined.pop("__provider", enriched["agent"].get("provider", "llm")))
    model = str(refined.pop("__model", enriched["agent"].get("model", "modelo activo")))
    enriched["agent"].update({"provider": provider, "model": model, "llm_used": True})
    for key in ["title", "executive_summary"]:
        if isinstance(refined.get(key), str) and refined[key].strip():
            enriched[key] = refined[key].strip()
    for key in ["findings", "recommendations", "limitations"]:
        if isinstance(refined.get(key), list):
            enriched[key] = [str(x).strip() for x in refined[key] if str(x).strip()][:8]
    return json_safe(enriched)


def _chat_json(messages: list[dict[str, str]], max_tokens: int, temperature: float) -> dict[str, Any]:
    errors: list[str] = []
    for provider in available_providers():
        model = provider_model(provider)
        for attempt in range(max(1, int(os.getenv("LLM_RETRIES_PER_PROVIDER", "2")))):
            try:
                if provider == "gemini":
                    data = _chat_json_gemini(messages, model=model, max_tokens=max_tokens, temperature=temperature)
                else:
                    data = _chat_json_openai_compatible(provider, messages, model=model, max_tokens=max_tokens, temperature=temperature)
                data["__provider"] = provider
                data["__model"] = model
                return data
            except Exception as exc:
                errors.append(f"{provider}/{model}: {type(exc).__name__}: {exc}")
                if attempt == 0:
                    time.sleep(0.45 + random.random() * 0.35)
                continue
    raise LLMProviderError("Todos los proveedores LLM fallaron: " + " | ".join(errors[-6:]))


def _chat_json_gemini(messages: list[dict[str, str]], model: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    api_key = os.environ["GEMINI_API_KEY"]
    system_text, prompt_text = _split_messages_for_gemini(messages)
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "response_mime_type": "application/json",
        },
    }
    if system_text:
        payload["system_instruction"] = {"parts": [{"text": system_text}]}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    raw = _post_json(url, payload, headers={"Content-Type": "application/json"})
    try:
        parsed = json.loads(raw)
        text = "".join(part.get("text", "") for part in parsed["candidates"][0]["content"].get("parts", []))
    except Exception as exc:
        raise LLMProviderError(f"Respuesta Gemini inesperada: {raw[:500]}") from exc
    return _parse_json_text(text)


def _chat_json_openai_compatible(provider: str, messages: list[dict[str, str]], model: str, max_tokens: int, temperature: float) -> dict[str, Any]:
    url = OPENAI_COMPATIBLE_ENDPOINTS[provider]
    api_key = os.environ[PROVIDER_KEYS[provider]]
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if provider == "openrouter":
        headers["HTTP-Referer"] = os.getenv("OPENROUTER_SITE_URL", "http://localhost:8000")
        headers["X-Title"] = os.getenv("OPENROUTER_APP_NAME", "InsightAgent")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    try:
        raw = _post_json(url, payload, headers=headers)
    except LLMProviderError as exc:
        # Algunos modelos gratuitos no aceptan json_object. Reintenta sin ese campo.
        if "400" not in str(exc) and "response_format" not in str(exc).lower():
            raise
        payload.pop("response_format", None)
        raw = _post_json(url, payload, headers=headers)
    parsed = json.loads(raw)
    try:
        content = parsed["choices"][0]["message"].get("content") or "{}"
    except Exception as exc:
        raise LLMProviderError(f"Respuesta {provider} inesperada: {raw[:500]}") from exc
    return _parse_json_text(content)


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> str:
    timeout = float(os.getenv("LLM_TIMEOUT_SECONDS", "28"))
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise LLMProviderError(f"HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise LLMProviderError(str(exc)) from exc


def _split_messages_for_gemini(messages: list[dict[str, str]]) -> tuple[str, str]:
    system_parts: list[str] = []
    prompt_parts: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        if role == "system":
            system_parts.append(content)
        else:
            prompt_parts.append(f"{role.upper()}:\n{content}")
    return "\n\n".join(system_parts), "\n\n".join(prompt_parts)


def _parse_json_text(text: str) -> dict[str, Any]:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if not match:
            raise
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise LLMProviderError("La respuesta JSON no es un objeto.")
    return data


def _valid_column(value: Any, allowed_columns: set[str]) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text in allowed_columns else None


def _safe_float(value: Any, default: float = 0.5) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    return max(0.0, min(1.0, number))
