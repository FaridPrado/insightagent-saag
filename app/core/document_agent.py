from __future__ import annotations

import json
import os
from typing import Any

from .agent import active_model, llm_available
from .utils import clip_string, json_safe


def document_status(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": "document",
        "title": profile.get("title") or "Archivo cargado",
        "summary": profile.get("summary") or "El archivo no parece ser un conjunto tabular de negocio. El chat responderá sobre su contenido.",
    }


def answer_document_question(content: str, question: str, profile: dict[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or {}
    context = clip_string(content, int(os.getenv("DOCUMENT_CONTEXT_CHARS", "28000")))
    if not context.strip():
        return json_safe({
            "mode": "document",
            "title": "No hay contenido legible",
            "executive_summary": "El archivo fue cargado, pero no encontré texto suficiente para responder con confianza.",
            "findings": [],
            "recommendations": ["Revisa que el archivo tenga texto legible o una tabla con encabezados."],
            "limitations": ["No hay contenido textual suficiente para analizar."],
            "table": [],
            "kpis": [],
            "agent": {"provider": "local", "model": "validador local", "llm_used": False},
        })

    if not llm_available():
        return json_safe(_local_document_answer(context, question, profile))

    system = (
        "Eres InsightAgent, un analista de archivos para usuarios de negocio. "
        "El archivo cargado no fue clasificado como dataset tabular analítico, por lo que debes responder como analista documental. "
        "Usa solamente el contenido proporcionado. No inventes datos, cifras ni secciones. "
        "Si la respuesta no aparece en el archivo, dilo claramente. "
        "Responde en español natural, profesional y directo. Devuelve solo JSON válido."
    )
    user = {
        "pregunta_usuario": question,
        "perfil_archivo": {
            "nombre": profile.get("filename"),
            "modo": "documento",
            "razon": profile.get("mode_reason"),
            "filas_detectadas": profile.get("rows"),
            "columnas_detectadas": profile.get("columns_count"),
        },
        "contenido_archivo": context,
        "formato_respuesta": {
            "title": "título breve",
            "executive_summary": "respuesta directa de 1 a 4 frases",
            "findings": ["hallazgos o puntos relevantes con evidencia del archivo"],
            "recommendations": ["acciones sugeridas si aplica"],
            "limitations": ["limitaciones si la respuesta no está en el archivo"],
        },
    }
    try:
        data = _chat_json([
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ], max_tokens=1200, temperature=float(os.getenv("GROQ_TEMPERATURE", "0.15")))
    except Exception as exc:
        answer = _local_document_answer(context, question, profile)
        answer["agent"] = {"provider": "local", "model": "lectura básica", "llm_used": False, "reason": f"Respuesta local por fallo del agente: {type(exc).__name__}."}
        return json_safe(answer)

    return json_safe({
        "mode": "document",
        "title": str(data.get("title") or "Análisis del archivo").strip(),
        "executive_summary": str(data.get("executive_summary") or "No encontré una respuesta clara en el archivo.").strip(),
        "findings": _list(data.get("findings"))[:8],
        "recommendations": _list(data.get("recommendations"))[:5],
        "limitations": _list(data.get("limitations"))[:5],
        "calculation_note": "Respuesta generada a partir del contenido textual extraído del archivo; no se aplicó análisis tabular avanzado.",
        "table": [],
        "kpis": [
            {"label": "Modo", "value": "Documento"},
            {"label": "Caracteres analizados", "value": len(context)},
        ],
        "agent": {"provider": "groq", "model": active_model(), "llm_used": True},
    })


def _local_document_answer(context: str, question: str, profile: dict[str, Any]) -> dict[str, Any]:
    words = [w.lower() for w in question.split() if len(w) > 3]
    snippets: list[str] = []
    for paragraph in context.splitlines():
        p = paragraph.strip()
        if len(p) < 20:
            continue
        p_norm = p.lower()
        if any(w in p_norm for w in words):
            snippets.append(clip_string(p, 260))
        if len(snippets) >= 5:
            break
    if not snippets:
        snippets = [clip_string(x.strip(), 260) for x in context.splitlines() if len(x.strip()) > 30][:3]
    return {
        "mode": "document",
        "title": "Lectura básica del archivo",
        "executive_summary": "El archivo no fue tratado como dataset tabular. Sin un agente LLM activo, solo puedo mostrar fragmentos relevantes del contenido extraído.",
        "findings": snippets,
        "recommendations": ["Activa Groq para obtener respuestas documentales más completas sobre este archivo."],
        "limitations": ["Modo local limitado: no interpreta el documento con profundidad semántica."],
        "calculation_note": "Lectura básica de texto extraído; no se aplicó análisis tabular avanzado.",
        "table": [],
        "kpis": [{"label": "Modo", "value": "Documento"}, {"label": "Caracteres", "value": len(context)}],
        "agent": {"provider": "local", "model": "lectura básica", "llm_used": False},
    }


def _chat_json(messages: list[dict[str, str]], max_tokens: int, temperature: float) -> dict[str, Any]:
    from groq import Groq

    client = Groq(api_key=os.environ["GROQ_API_KEY"], timeout=float(os.getenv("LLM_TIMEOUT_SECONDS", "25")))
    response = client.chat.completions.create(
        model=active_model(),
        messages=messages,
        response_format={"type": "json_object"},
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return json.loads(response.choices[0].message.content or "{}")


def _list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []
