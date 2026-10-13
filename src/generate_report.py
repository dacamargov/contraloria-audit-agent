# Databricks notebook source
# MAGIC %md
# MAGIC # Generar Informe Analitico (PDF)
# MAGIC Recupera evidencia de Vector Search por sujeto, redacta el informe con el LLM
# MAGIC (formato CGR, distinguiendo hallazgos comprobados de lineas a verificar) y lo
# MAGIC guarda como PDF en el Volume `informes-analiticos`. Lo dispara la app.

# COMMAND ----------
# MAGIC %pip install "markdown2>=2.4,<3" "xhtml2pdf>=0.2.11,<0.3" "matplotlib>=3.7,<4" "pypdf>=4,<5" "openai>=1.40,<2"
# MAGIC dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "dacamargovws_catalog")
dbutils.widgets.text("schema", "contraloria")
dbutils.widgets.text("volume_analiticos", "informes-analiticos")
dbutils.widgets.text("vs_endpoint", "contraloria_vs")
dbutils.widgets.text("llm_endpoint", "databricks-claude-opus-4-7")
dbutils.widgets.text("sector", "Medio Ambiente")
dbutils.widgets.text("sujetos", "CAR,CVC,PNNC,ANLA,FONDO_VIDA")  # siglas O nombres, separados por coma
dbutils.widgets.text("periodo", "2025-2026")
dbutils.widgets.text("tema", "")  # enfoque opcional (p.ej. "cobro coactivo y aduanas")
g = dbutils.widgets.get
CATALOG, SCHEMA, VOL = g("catalog"), g("schema"), g("volume_analiticos")
VS_ENDPOINT, LLM = g("vs_endpoint"), g("llm_endpoint")
SECTOR, PERIODO, TEMA = g("sector"), g("periodo"), g("tema").strip()
SUJETOS_IN = [s.strip() for s in g("sujetos").split(",") if s.strip()]
INDEX = f"{CATALOG}.{SCHEMA}.doc_chunks_index"

# COMMAND ----------
import json, re, datetime
import mlflow.deployments
from databricks.sdk import WorkspaceClient
w = WorkspaceClient()

# --- LLM: soporta serving endpoints clasicos Y model services de Unity Gateway ---
# Un nombre de 3 niveles (catalog.schema.name) es un model service gobernado: se invoca por el
# AI Gateway (API OpenAI-compatible en /ai-gateway/mlflow/v1, model = nombre UC completo). Un
# nombre plano usa la ruta clasica de serving endpoints (mlflow.deployments).
if "." in LLM:
    from openai import OpenAI
    _ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
    _host = "https://" + spark.conf.get("spark.databricks.workspaceUrl")
    _oa = OpenAI(api_key=_ctx.apiToken().get(), base_url=f"{_host}/ai-gateway/mlflow/v1")

    def llm_predict(messages, max_tokens):
        r = _oa.chat.completions.create(model=LLM, messages=messages, max_tokens=max_tokens)
        return r.choices[0].message.content or ""
else:
    _dc = mlflow.deployments.get_deploy_client("databricks")

    def llm_predict(messages, max_tokens):
        r = _dc.predict(endpoint=LLM, inputs={"messages": messages, "max_tokens": max_tokens})
        return r["choices"][0]["message"]["content"]

# --- Resolver los sujetos: aceptar sigla O nombre completo -> lista de siglas ---
sect = {r["sigla"].upper(): r.asDict() for r in spark.table(f"{CATALOG}.{SCHEMA}.sectorizacion").collect()}
def to_sigla(x):
    xu = x.strip().upper()
    if xu in sect:
        return xu
    for sig, row in sect.items():
        if xu in (row.get("sujeto") or "").upper() or (row.get("sujeto") or "").upper() in xu:
            return sig
    return xu  # se usa tal cual si no se resuelve
SIGLAS = list(dict.fromkeys(to_sigla(s) for s in SUJETOS_IN))
print("Sujetos:", SIGLAS, "| Tema:", TEMA or "(general)")

# Temas nucleo (cubren lo que pide el cliente). Menos consultas = mas rapido.
TEMAS = ["opinion contable presupuestal fenecimiento y control interno",
         "hallazgos administrativos disciplinarios y fiscales con sus cuantias",
         "plan de mejoramiento y efectividad de acciones de mejora",
         "contratacion supervision liquidacion y activos"]
# Si hay tema/enfoque, se usa ese en vez de los genericos (mas focalizado y rapido)
if TEMA:
    TEMAS = [TEMA, TEMA + " hallazgos y cuantias", "plan de mejoramiento " + TEMA]

K_POR_CONSULTA = 4
MAX_POR_SUJETO = 14  # tope de fragmentos por sujeto para acotar el prompt

def retrieve(sigla, query, k=K_POR_CONSULTA):
    r = w.vector_search_indexes.query_index(
        index_name=INDEX,
        columns=["documento", "pagina", "sujeto", "sigla", "vigencia", "texto"],
        query_text=query, num_results=k, filters_json=json.dumps({"sigla": sigla}))
    cols = [c.name for c in r.manifest.columns]
    return [dict(zip(cols, row)) for row in (r.result.data_array or [])]

# Recuperacion EN PARALELO (las consultas a Vector Search son I/O bound)
from concurrent.futures import ThreadPoolExecutor
tasks = [(sigla, tema) for sigla in SIGLAS for tema in TEMAS]
with ThreadPoolExecutor(max_workers=10) as ex:
    resultados = list(ex.map(lambda a: retrieve(a[0], a[1]), tasks))

seen, por_sujeto = set(), {}
for res in resultados:
    for row in res:
        sig = row.get("sigla")
        key = (row.get("documento"), row.get("pagina"), (row.get("texto") or "")[:60])
        if key in seen or len(por_sujeto.get(sig, [])) >= MAX_POR_SUJETO:
            continue
        seen.add(key)
        por_sujeto.setdefault(sig, []).append(row)
evidence = [r for rows in por_sujeto.values() for r in rows]
print("Fragmentos de evidencia:", len(evidence), "| por sujeto:", {k: len(v) for k, v in por_sujeto.items()})

# COMMAND ----------
SYSTEM = """Eres analista de la DIARI de la Contraloria General de la Republica. Redactas un INFORME
ANALITICO Y PRESCRIPTIVO consolidando informes de auditoria. Reglas: basa TODA afirmacion en la
EVIDENCIA dada, citando [documento, p. N]; distingue HALLAZGOS COMPROBADOS (con cita y cuantia) de
LINEAS A VERIFICAR (hipotesis a confirmar por el equipo auditor); no inventes cifras, paginas ni
documentos; reporta cuantias exactamente. Escribe en espanol tecnico y formal."""

_enfoque = f" El informe se ENFOCA en: {TEMA}. Prioriza y organiza el contenido alrededor de ese tema." if TEMA else ""
_multi = len(SIGLAS) > 1
STRUCTURE = f"""Produce el informe en Markdown, sector {SECTOR}, periodo {PERIODO}.{_enfoque}
REGLA DE CITAS EN TABLAS: dentro de CUALQUIER celda de tabla cita de forma COMPACTA como [p. N]
o [p. N, vigencia]; NUNCA escribas el nombre de archivo dentro de una tabla. El nombre de archivo
completo se cita como [documento, p. N] SOLO en el texto en prosa y en "Fuentes documentales".
# INFORME ANALITICO Y PRESCRIPTIVO - SECTOR {SECTOR}
## Resumen ejecutivo (parrafo + tabla de indicadores consolidados)
## 1. Alcance y fuentes (tabla: Sujeto | Vigencia | Tipo de auditoria). NO incluyas el nombre de archivo en esta tabla (las citas al documento van en el cuerpo del informe).

Luego, POR CADA SUJETO ({", ".join(SIGLAS)}) una seccion con:
- Antecedentes de auditoria disponibles (informes y vigencias cubiertas).
- Hallazgos mas relevantes, con sus cuantias fiscales (comprobados, con cita [documento, p. N]).
- Planes de mejoramiento (estado y efectividad de las acciones, si consta).
- Recurrencias entre vigencias y persistencia: que problemas se repiten y si persisten pese a las
  acciones de mejora.
- Riesgos para la proxima auditoria y aspectos a revisar, en una tabla (Riesgo | Señal | Prueba
  sugerida) claramente rotulada como LINEAS A VERIFICAR (no hallazgos comprobados).
"""
if _multi:
    STRUCTURE += """
## Riesgos y patrones compartidos (compara los sujetos: recurrencias y riesgos comunes, en tabla)
"""
STRUCTURE += """## Conclusion tecnica (sustentada en los informes fuente)
## Fuentes documentales"""

def fmt(e):
    return f'[FUENTE documento="{e.get("documento")}" pagina={e.get("pagina")} sujeto="{e.get("sujeto")}" vigencia="{e.get("vigencia")}"]\n{e.get("texto")}'

EVIDENCIA_TXT = "\n\n".join(fmt(e) for e in evidence)
chart_data = {}

if not evidence:
    md = "# Informe no generado\n\nNo hay evidencia suficiente para los sujetos solicitados."
else:
    # 1) Informe (markdown)
    md = llm_predict([
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": STRUCTURE + "\n\n=== EVIDENCIA (unica fuente permitida) ===\n\n" + EVIDENCIA_TXT},
    ], max_tokens=16000)

    # 2) Llamada dedicada: SOLO datos numericos para graficar (JSON puro)
    CHART_PROMPT = (
        "Extrae de la EVIDENCIA los datos numericos que consten explicitamente y responde SOLO un JSON "
        "(sin texto ni markdown). Omite cualquier clave o entrada cuyo dato NO conste; no inventes. Esquema:\n"
        "{"
        '"hallazgos_por_informe": {"CAR 2024": {"administrativos": num, "disciplinarios": num, "fiscales": num}, '
        '"CAR 2025": {"administrativos": num, "disciplinarios": num, "fiscales": num}}, '
        '"cuantias_fiscales_millones_cop": {"Fondo Vida": num, "CVC 2025": num}, '
        '"control_interno_calificacion": {"CAR 2024": num, "CAR 2025": num, "ANLA 2024": num}}\n'
        "Usa una entrada por informe/vigencia (p.ej. 'CAR 2024', 'CVC 2025'). Las calificaciones de control "
        "interno van de 1.0 (eficiente) a 2.6 (ineficiente).\n\n"
        "=== EVIDENCIA ===\n\n" + EVIDENCIA_TXT
    )
    try:
        ctext = llm_predict([
            {"role": "system", "content": "Eres un extractor de datos. Respondes unicamente JSON valido."},
            {"role": "user", "content": CHART_PROMPT},
        ], max_tokens=2000)
        cm = re.search(r"\{.*\}", ctext, re.DOTALL)
        chart_data = json.loads(cm.group(0)) if cm else {}
    except Exception as e:
        print("No se pudieron extraer datos de graficas:", e)

print(md[:800])
print("Datos de graficas:", chart_data)

# COMMAND ----------
import io
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import markdown2
from xhtml2pdf import pisa
from pypdf import PdfReader, PdfWriter

# Quita cualquier bloque ```json que el modelo pudiera haber dejado en el informe
md = re.sub(r"```json\s*.*?```", "", md, flags=re.DOTALL).strip()

# --- 1) Pagina de graficas (matplotlib -> PDF), estilo CGR colorido ---
import matplotlib.ticker as mticker

AZUL, DORADO, ROJO, TEAL, VERDE, MORADO = "#1F4E96", "#E6A700", "#C1121F", "#2A7F8E", "#4C8C3F", "#7B4FA3"
PALETA = [ROJO, TEAL, AZUL, DORADO, VERDE, MORADO, "#D2691E", "#5D6D7E"]
plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": "#c9ccd3"})

def _num(d):
    return {str(k): v for k, v in (d or {}).items() if isinstance(v, (int, float))}

def _style(ax, titulo):
    ax.set_title(titulo, fontsize=12, fontweight="bold", color="#1F3864", pad=12)
    ax.grid(axis="both", color="#e6e8ec", linewidth=0.8, zorder=0)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.tick_params(labelsize=8.5)

charts = []  # funciones que dibujan en un ax dado

# Grafico 1: hallazgos por informe (barras agrupadas admin/disciplinario/fiscal)
hpi = {k: v for k, v in (chart_data.get("hallazgos_por_informe") or {}).items() if isinstance(v, dict)}
if hpi:
    def _g1(ax, hpi=hpi):
        informes = list(hpi.keys())
        cats = [("administrativos", "Administrativos", AZUL),
                ("disciplinarios", "Disciplinarios", DORADO),
                ("fiscales", "Fiscales", ROJO)]
        x = range(len(informes)); w = 0.26
        for i, (key, lab, col) in enumerate(cats):
            vals = [(hpi[inf].get(key) or 0) for inf in informes]
            pos = [xi + (i - 1) * w for xi in x]
            ax.bar(pos, vals, w, label=lab, color=col, zorder=3)
            for p, v in zip(pos, vals):
                if v:
                    ax.text(p, v + 0.15, str(int(v) if v == int(v) else v),
                            ha="center", va="bottom", fontsize=7.5, color="#333")
        ax.set_xticks(list(x)); ax.set_xticklabels(informes, rotation=20, ha="right")
        ax.set_ylabel("Numero de hallazgos", fontsize=9)
        ax.legend(fontsize=8, ncol=3, frameon=False, loc="upper right")
        _style(ax, "Resultados de auditoria por informe analizado")
    charts.append(_g1)

# Grafico 2: hallazgos totales por sujeto (barras horizontales, un color c/u)
hps = _num(chart_data.get("hallazgos_administrativos_por_sujeto"))
if not hps and hpi:  # derivar desde el desglose si no vino aparte
    for inf, d in hpi.items():
        suj = inf.rsplit(" ", 1)[0]
        hps[suj] = hps.get(suj, 0) + (d.get("administrativos") or 0)
hps = {k: v for k, v in hps.items() if v}
if hps:
    def _g2(ax, hps=hps):
        sujetos = list(hps.keys()); vals = [hps[s] for s in sujetos]
        cols = [PALETA[i % len(PALETA)] for i in range(len(sujetos))]
        ax.barh(sujetos, vals, color=cols, zorder=3)
        for i, v in enumerate(vals):
            ax.text(v + max(vals) * 0.01, i, str(int(v) if v == int(v) else v),
                    va="center", fontsize=8, color="#333")
        ax.set_xlabel("Hallazgos", fontsize=9); ax.invert_yaxis()
        _style(ax, "Concentracion de hallazgos administrativos por sujeto")
    charts.append(_g2)

# Grafico 3: cuantias con incidencia fiscal (barras verticales rojas, etiqueta $ M)
cf = _num(chart_data.get("cuantias_fiscales_millones_cop"))
cf = {k: v for k, v in cf.items() if v}
if cf:
    def _g3(ax, cf=cf):
        keys = list(cf.keys()); vals = [cf[k] for k in keys]
        ax.bar(keys, vals, color=ROJO, zorder=3, width=0.5)
        for i, v in enumerate(vals):
            ax.text(i, v + max(vals) * 0.02, f"${v:,.1f} M", ha="center", fontsize=8, fontweight="bold", color="#7a0f0f")
        ax.set_ylabel("Millones de pesos", fontsize=9)
        ax.set_xticks(range(len(keys))); ax.set_xticklabels(keys, rotation=15, ha="right")
        _style(ax, "Cuantias con presunta incidencia fiscal (millones COP)")
    charts.append(_g3)

# Grafico 4: control interno con bandas de color (verde/ambar/rojo)
ci = _num(chart_data.get("control_interno_calificacion"))
ci = {k: v for k, v in ci.items() if v}
if ci:
    def _g4(ax, ci=ci):
        keys = list(ci.keys()); vals = [ci[k] for k in keys]
        ax.axhspan(1.0, 1.5, color="#DFF0D8", zorder=0)   # Eficiente
        ax.axhspan(1.5, 2.0, color="#FCF3CF", zorder=0)   # Con deficiencias
        ax.axhspan(2.0, 2.6, color="#F5B7B1", zorder=0)   # Ineficiente
        ax.bar(keys, vals, color=TEAL, width=0.5, zorder=3)
        for i, v in enumerate(vals):
            ax.text(i, v + 0.03, f"{v:.1f}", ha="center", fontsize=8, fontweight="bold", color="#1F3864")
        ax.set_ylim(1.0, 2.6); ax.set_ylabel("Calificacion CGR", fontsize=9)
        ax.set_xticks(range(len(keys))); ax.set_xticklabels(keys, rotation=15, ha="right")
        ax.text(0.995, 1.25, "Eficiente", transform=ax.get_yaxis_transform(), ha="right", fontsize=7, color="#4C8C3F")
        ax.text(0.995, 2.3, "Ineficiente", transform=ax.get_yaxis_transform(), ha="right", fontsize=7, color="#C1121F")
        _style(ax, "Calificacion del control fiscal interno")
    charts.append(_g4)

print("Graficas a generar:", len(charts))
charts_pdf = None
if charts:
    fig, axes = plt.subplots(len(charts), 1, figsize=(8.0, 3.4 * len(charts)), facecolor="white")
    if len(charts) == 1:
        axes = [axes]
    fig.suptitle("Graficos consolidados — Sector " + SECTOR, color="#1F3864", fontsize=14, fontweight="bold", y=0.995)
    for draw, ax in zip(charts, axes):
        ax.set_facecolor("white")
        draw(ax)
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    charts_pdf = io.BytesIO()
    fig.savefig(charts_pdf, format="pdf", facecolor="white")
    plt.close(fig)
    charts_pdf.seek(0)

# --- 2) PDF de texto (xhtml2pdf) ---
FOOTER = ("Carrera 69 No. 44-35 Piso 1 &bull; PBX 518 7000<br/>"
          "cgr@contraloria.gov.co &bull; www.contraloria.gov.co &bull; Bogota, D. C., Colombia")
CSS = """@page{size:letter;margin:2.5cm 2cm 3cm 2cm;@frame footer{-pdf-frame-content:f;bottom:1cm;margin-left:2cm;margin-right:2cm;height:1.5cm;}}
body{font-family:Helvetica,Arial,sans-serif;font-size:10pt;color:#1a1a1a;line-height:1.4;}
h1{font-size:16pt;color:#b31b1b;border-bottom:2px solid #b31b1b;padding-bottom:4px;}
h2{font-size:13pt;color:#7a0f0f;margin-top:16px;} h3{font-size:11pt;}
table{border-collapse:collapse;width:100%;margin:8px 0;font-size:8.5pt;table-layout:fixed;}
th{background:#b31b1b;color:#fff;padding:5px;text-align:left;} td{border:1px solid #ccc;padding:4px;vertical-align:top;word-wrap:break-word;word-break:break-all;}
.f{font-size:7pt;color:#666;text-align:center;}"""
html = (f'<html><head><meta charset="utf-8"><style>{CSS}</style></head><body>'
        f'<div id="f" class="f">{FOOTER}<br/>Pagina <pdf:pagenumber> de <pdf:pagecount></div>'
        # 'code-friendly' desactiva _ y __ como enfasis (los nombres de archivo con
        # guion bajo, p.ej. 202501010_Informe_..., ya no se interpretan como cursiva)
        + markdown2.markdown(md, extras=["tables", "break-on-newline", "code-friendly"]) + "</body></html>")
text_pdf = io.BytesIO()
pisa.CreatePDF(src=html, dest=text_pdf, encoding="utf-8")
text_pdf.seek(0)

# --- 3) Merge: pagina 1 (resumen) + graficas + resto del informe ---
ts = datetime.datetime.now().strftime("%Y%m%d_%H%M")
safe = re.sub(r"[^A-Za-z0-9]+", "_", SECTOR)
out_path = f"/Volumes/{CATALOG}/{SCHEMA}/{VOL}/Informe_Analitico_{safe}_{PERIODO}_{ts}.pdf"

reader = PdfReader(text_pdf)
writer = PdfWriter()
writer.add_page(reader.pages[0])
if charts_pdf:
    for pg in PdfReader(charts_pdf).pages:
        writer.add_page(pg)
for pg in reader.pages[1:]:
    writer.add_page(pg)
with open(out_path, "wb") as fh:
    writer.write(fh)
print("PDF generado:", out_path)

dbutils.notebook.exit(out_path)
