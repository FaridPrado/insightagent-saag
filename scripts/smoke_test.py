from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd

from app.core.analyst import analyze_question
from app.core.profiler import prepare_dataframe, profile_dataframe

sample = ROOT / "samples" / "saas_sales_sample.csv"
df = prepare_dataframe(pd.read_csv(sample))
profile = profile_dataframe(df)

questions = [
    "Dame un resumen ejecutivo de este conjunto de datos.",
    "¿Cuáles son los 10 principales productos por ingresos?",
    "Detecta anomalías y dime qué debería investigar.",
    "¿Por qué cambiaron ingresos en el último periodo?",
    "¿Qué clientes tienen mayor riesgo?",
]

for question in questions:
    answer = analyze_question(df, question, profile)
    assert answer.get("executive_summary"), question
    assert "title" in answer, question
    assert answer.get("agent"), question
    print(f"OK: {question} -> {answer['title']}")

print("Prueba completa: InsightAgent responde correctamente.")
