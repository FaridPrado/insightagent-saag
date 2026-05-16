from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

out = Path(__file__).resolve().parents[1] / "samples" / "saas_sales_sample.csv"
out.parent.mkdir(parents=True, exist_ok=True)

clientes = [f"Cliente {i:03d}" for i in range(1, 91)]
segmentos = ["Pyme", "Mediana empresa", "Enterprise"]
paises = ["Colombia", "México", "Chile", "Perú", "Estados Unidos"]
ciudades = {
    "Colombia": ["Bogotá", "Medellín", "Cali"],
    "México": ["CDMX", "Guadalajara", "Monterrey"],
    "Chile": ["Santiago", "Valparaíso"],
    "Perú": ["Lima", "Arequipa"],
    "Estados Unidos": ["Miami", "Austin", "Nueva York"],
}
responsables = ["Ana Torres", "Luis Rivera", "Carlos Méndez", "Sofía Vega", "Daniel Ortiz"]
productos = ["Analítica", "Automatización", "Sincronización CRM", "Soporte IA", "Pagos"]
planes = ["Inicio", "Crecimiento", "Escala", "Enterprise"]
canales = ["Entrada", "Aliado", "Prospección", "Referido"]
estados = ["Activo", "Expansión", "En riesgo", "Perdido"]
comentarios = [
    "El cliente pidió reportes más rápidos y dashboards más claros",
    "Alta adopción por parte del equipo de operaciones",
    "Necesita apoyo de onboarding y documentación más clara",
    "Preocupación de precio durante la conversación de renovación",
    "Sponsor ejecutivo positivo y oportunidad de expansión",
    "Varios tickets sobre confiabilidad de la integración",
    "Bajo uso durante el último mes",
    "Está satisfecho con la automatización pero quiere más campos del CRM",
]

inicio = date(2025, 1, 1)
filas = []
for i in range(720):
    dia = inicio + timedelta(days=i % 455)
    cliente = random.choice(clientes)
    segmento = random.choices(segmentos, weights=[0.52, 0.32, 0.16])[0]
    pais = random.choices(paises, weights=[0.38, 0.24, 0.16, 0.12, 0.10])[0]
    ciudad = random.choice(ciudades[pais])
    responsable = random.choice(responsables)
    producto = random.choice(productos)
    plan = random.choices(planes, weights=[0.34, 0.33, 0.22, 0.11])[0]
    canal = random.choice(canales)

    base = {"Pyme": 650, "Mediana empresa": 1900, "Enterprise": 6200}[segmento]
    plan_mult = {"Inicio": 0.8, "Crecimiento": 1.15, "Escala": 1.65, "Enterprise": 2.6}[plan]
    producto_mult = {"Analítica": 1.2, "Automatización": 1.35, "Sincronización CRM": 1.0, "Soporte IA": 1.15, "Pagos": 0.95}[producto]
    estacionalidad = 1.0 + ((dia.month - 6) * 0.015)
    responsable_mult = {"Ana Torres": 1.12, "Luis Rivera": 1.02, "Carlos Méndez": 0.9, "Sofía Vega": 1.08, "Daniel Ortiz": 0.98}[responsable]
    ruido = random.uniform(0.72, 1.36)
    if responsable == "Carlos Méndez" and dia >= date(2026, 2, 1):
        responsable_mult *= 0.68
    ingresos = round(base * plan_mult * producto_mult * estacionalidad * responsable_mult * ruido, 2)
    cantidad = max(1, int(random.gauss(4 if segmento == "Pyme" else 9 if segmento == "Mediana empresa" else 18, 2)))
    margen = round(ingresos * random.uniform(0.42, 0.78), 2)
    tickets = max(0, int(random.gauss(2.2 if segmento == "Enterprise" else 1.1, 1.4)))
    nps = int(max(0, min(10, random.gauss(7.4, 1.8) - (tickets * 0.35))))
    riesgo_churn = round(max(0, min(100, (tickets * 9) + ((7 - nps) * 8) + random.uniform(-6, 14))), 1)
    estado = random.choices(estados, weights=[0.62, 0.18, 0.15, 0.05])[0]
    if riesgo_churn > 70:
        estado = "En riesgo"
    if riesgo_churn < 22 and random.random() < 0.20:
        estado = "Expansión"

    filas.append(
        {
            "fecha": dia.isoformat(),
            "cliente": cliente,
            "segmento": segmento,
            "pais": pais,
            "ciudad": ciudad,
            "responsable_cuenta": responsable,
            "producto": producto,
            "plan": plan,
            "canal": canal,
            "estado": estado,
            "ingresos": ingresos,
            "cantidad": cantidad,
            "margen_bruto": margen,
            "tickets_soporte": tickets,
            "nps": nps,
            "riesgo_churn": riesgo_churn,
            "comentarios": random.choice(comentarios),
        }
    )

with out.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(filas[0].keys()))
    writer.writeheader()
    writer.writerows(filas)
print(out)
