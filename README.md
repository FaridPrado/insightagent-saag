# InsightAgent SaaG

**InsightAgent** es un agente conversacional de inteligencia de negocio que permite analizar archivos CSV, Excel y documentos mediante lenguaje natural.

El usuario puede cargar un archivo, explorar su estructura, conversar con los datos, generar gráficos, detectar anomalías, revisar múltiples hojas de Excel y exportar reportes ejecutivos sin escribir SQL ni construir dashboards manualmente.

[![Live Demo](https://img.shields.io/badge/live-demo-22c55e)](https://insightagent-saag.onrender.com)
![Backend](https://img.shields.io/badge/backend-FastAPI-009688)
![Data](https://img.shields.io/badge/data-Pandas-150458)
![Frontend](https://img.shields.io/badge/frontend-Vanilla_JS-f7df1e)
![LLM](https://img.shields.io/badge/LLM-multi_provider-2563eb)
![License](https://img.shields.io/badge/license-MIT-white)

---

## Live demo

**https://insightagent-saag.onrender.com**

> La primera carga puede tardar unos segundos si el servicio está en reposo.

---

## Qué problema resuelve

Muchos equipos trabajan con datos repartidos en hojas de cálculo, reportes internos, exportaciones de CRM, archivos de soporte o libros de Excel con varias pestañas. El problema no siempre es almacenar datos, sino convertirlos rápidamente en respuestas claras.

InsightAgent permite hacer preguntas como:

```text
Dame un resumen ejecutivo de este archivo.
Haz una gráfica de barras con los 10 principales clientes por ingresos.
Detecta anomalías y dime qué debería investigar.
¿Qué columnas encontraste y cuál parece ser la métrica principal?
¿Qué hojas tiene este Excel?
Genera una recomendación ejecutiva para una reunión de gerencia.
```

El objetivo es ofrecer una primera lectura accionable para usuarios de negocio, sin depender de un analista para cada pregunta exploratoria.

---

## Funcionalidades principales

- Carga de archivos **CSV, XLS, XLSX, TXT, MD y JSON**.
- Perfilado automático de columnas, métricas, fechas, dimensiones, valores faltantes y vista previa.
- Lectura inteligente de Excel:
  - detección de múltiples hojas;
  - selección automática de la hoja más relevante;
  - selector manual de **Hoja activa**;
  - detección de encabezados aunque exista metadata arriba;
  - clasificación de hojas analíticas y auxiliares.
- Chat ejecutivo sobre el archivo cargado.
- Respuestas con evidencia:
  - KPIs;
  - tablas de soporte;
  - notas de cálculo;
  - gráficos;
  - hallazgos;
  - recomendaciones.
- Gráficos SVG generados en la interfaz:
  - barras;
  - línea;
  - pastel;
  - dispersión;
  - histograma.
- Exportación de reporte ejecutivo.
- Exportación del chat completo en HTML con JSON técnico para revisión y depuración.
- Modo oscuro por defecto y modo claro.
- Arquitectura multi-proveedor LLM con fallback local seguro.

---

## Arquitectura

InsightAgent usa una arquitectura híbrida: el LLM interpreta la intención y redacta la respuesta, pero los cálculos se ejecutan con funciones controladas en el backend.

```text
Usuario pregunta
      ↓
Frontend envía pregunta + dataset_id
      ↓
Backend perfila columnas y contexto
      ↓
Router determina intención, métrica, dimensión y tipo de análisis
      ↓
Pandas ejecuta cálculos seguros
      ↓
LLM redacta una respuesta ejecutiva basada en evidencia
      ↓
Frontend renderiza KPIs, tablas, gráficos y recomendaciones
```

El modelo no ejecuta código arbitrario ni calcula libremente los números. Los resultados cuantitativos se obtienen desde herramientas de análisis controladas.

---

## Multi-provider LLM

La aplicación no depende de un único proveedor. Usa el primer proveedor disponible según `LLM_PROVIDER_ORDER` y cambia al siguiente si ocurre un error, timeout o límite de uso.

Orden recomendado:

```env
LLM_PROVIDER_ORDER=gemini,openrouter,cerebras,groq
```

Proveedores soportados:

| Proveedor | Uso recomendado |
|---|---|
| Gemini | Proveedor principal para demos públicas. |
| OpenRouter | Fallback con acceso a modelos gratuitos o alternativos. |
| Cerebras | Fallback compatible con Chat Completions. |
| Groq | Fallback opcional de baja latencia. |
| Local | Último fallback para mantener la demo funcionando sin API keys. |

La app también puede funcionar sin API keys usando análisis local seguro.

---

## Stack técnico

| Capa | Tecnología |
|---|---|
| Backend | FastAPI |
| Análisis de datos | Pandas, NumPy, OpenPyXL |
| Frontend | HTML, CSS, JavaScript vanilla |
| Visualización | SVG generado en frontend |
| LLM orchestration | Gemini, OpenRouter, Cerebras, Groq, fallback local |
| Deploy | Render / Docker |

---

## Instalación local

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn app.main:app --reload
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload
```

Abre:

```text
http://127.0.0.1:8000
```

---

## Configuración de entorno

Copia `.env.example` como `.env` y configura al menos un proveedor LLM si quieres respuestas enriquecidas:

```env
LLM_ENABLED=true
LLM_PROVIDER_ORDER=gemini,openrouter,cerebras,groq
GEMINI_API_KEY=tu_api_key
GEMINI_MODEL=gemini-2.5-flash
```

Variables principales:

| Variable | Descripción |
|---|---|
| `LLM_ENABLED` | Activa o desactiva el uso de proveedores LLM. |
| `LLM_PROVIDER_ORDER` | Orden de proveedores para fallback automático. |
| `GEMINI_API_KEY` | API key de Google AI Studio. |
| `OPENROUTER_API_KEY` | API key de OpenRouter. |
| `CEREBRAS_API_KEY` | API key de Cerebras. |
| `GROQ_API_KEY` | API key de Groq. |
| `LLM_TIMEOUT_SECONDS` | Timeout por llamada al proveedor. |
| `LLM_RETRIES_PER_PROVIDER` | Reintentos por proveedor. |
| `LLM_TEMPERATURE` | Temperatura de redacción. |

---

## Datos de prueba

La carpeta `sample_data/` incluye archivos para validar escenarios distintos:

| Archivo | Objetivo |
|---|---|
| `00_demo_saas_sales_sample.csv` | Dataset simple para la demo inicial. |
| `01_saas_ventas_crm_limpio.xlsx` | Excel tabular limpio de ventas SaaS/CRM. |
| `02_soporte_cx_formato_mixto.xlsx` | Excel con metadata, encabezados desplazados y datos de soporte. |
| `03_finanzas_operaciones_multiformato.xlsx` | Libro multihoja con finanzas, operaciones e inventario. |

---

## Pruebas rápidas

Ejecuta el smoke test:

```bash
python scripts/smoke_test.py
```

También puedes validar manualmente con estas preguntas:

```text
Hola, ¿cómo estás?
Dame un resumen ejecutivo de este archivo.
¿Qué columnas detectaste y cuál parece ser la métrica principal?
Haz una gráfica de barras con los principales clientes por ingresos_mrr.
Haz una tendencia mensual de ingresos_mrr.
¿Qué ves raro aquí?
¿Qué hojas tiene este archivo?
Genera una recomendación ejecutiva para una reunión de gerencia.
```

---

## Estructura del proyecto

```text
insightagent-saag/
  app/
    main.py              API FastAPI y endpoints principales
    core/
      agent.py           Orquestación multi-proveedor LLM
      analyst.py         Herramientas seguras de análisis tabular
      document_agent.py  Chat sobre archivos documentales
      profiler.py        Perfilado automático de archivos
      utils.py           Limpieza y serialización
    static/
      index.html         Interfaz principal
      app.js             Lógica frontend
      styles.css         Diseño responsive
      logo.png           Branding del producto
  sample_data/           Archivos de prueba
  samples/               Dataset usado por el botón de demo
  scripts/               Generación de datos y smoke tests
  Dockerfile
  render.yaml
  requirements.txt
```

---

## Decisiones de diseño

- El análisis numérico se ejecuta en backend con Pandas, no directamente en el modelo.
- El LLM se usa para interpretar intención, seleccionar el enfoque y redactar una respuesta legible.
- La app selecciona una hoja activa en archivos Excel multihoja para evitar combinaciones incorrectas entre tablas no relacionadas.
- El fallback local permite que la demo siga funcionando aunque no haya API keys o un proveedor externo falle.
- Las exportaciones incluyen evidencia y datos técnicos para facilitar auditoría y depuración.

---

## Alcance actual

InsightAgent está diseñado como una demo funcional de producto y arquitectura. Actualmente trabaja en memoria durante la sesión del servidor y no incluye autenticación, persistencia por usuario ni detección automática de relaciones entre hojas.

Estas decisiones mantienen el proyecto simple de ejecutar, fácil de desplegar y enfocado en demostrar análisis conversacional sobre archivos de negocio.

---

## Licencia

MIT. Consulta `LICENSE`.
