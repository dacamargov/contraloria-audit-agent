"""
App Databricks (Streamlit) — Asistente de Auditoria de la Contraloria.

Tres usos:
  1) Chat: conversa con los informes (Q&A con citas doc+pagina) via el endpoint del agente.
  2) Informe analitico: dispara el job de generacion y permite descargar el PDF.
  3) Cargar PDF: sube un informe al Volume -> se ingiere e indexa automaticamente.
"""
import os
import io
import json
import time
import queue
import base64
import threading
import requests
import streamlit as st
import markdown2
from xhtml2pdf import pisa
from databricks.sdk import WorkspaceClient

# Sentinela: marca el fin del stream en el worker en segundo plano (pagina Chat).
_STREAM_DONE = object()


@st.cache_data(show_spinner=False)
def answer_to_pdf(md_text: str) -> bytes:
    """Convierte una respuesta (Markdown) a PDF con estilo CGR (para descargar)."""
    css = """
    @page { size: letter; margin: 2cm; }
    body { font-family: Helvetica, Arial, sans-serif; font-size: 10.5pt; color: #1a1a1a; line-height: 1.45; }
    h1 { font-size: 15pt; color: #b31b1b; } h2 { font-size: 12.5pt; color: #7a0f0f; } h3 { font-size: 11pt; }
    table { border-collapse: collapse; width: 100%; margin: 8px 0; font-size: 9pt; }
    th { background: #b31b1b; color: #fff; padding: 5px; text-align: left; }
    td { border: 1px solid #ccc; padding: 4px; vertical-align: top; }
    """
    html = (f'<html><head><meta charset="utf-8"><style>{css}</style></head><body>'
            "<h3 style='color:#7a0f0f'>Contraloria General de la Republica — Respuesta del asistente</h3>"
            # 'code-friendly': evita que los _ de nombres de archivo se vuelvan cursiva
            + markdown2.markdown(md_text, extras=["tables", "break-on-newline", "code-friendly"])
            + "</body></html>")
    buf = io.BytesIO()
    pisa.CreatePDF(src=html, dest=buf, encoding="utf-8")
    return buf.getvalue()


def _asset_b64(filename):
    path = os.path.join(os.path.dirname(__file__), "assets", filename)
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except Exception:
        return ""


def _escudo_b64():
    return _asset_b64("escudo_colombia.png")

# --- Config (inyectada por app.yaml / recursos del bundle) ---
AGENT_ENDPOINT = os.environ.get("AGENT_ENDPOINT", "contraloria_audit_agent")
REPORT_JOB_ID = os.environ.get("REPORT_JOB_ID", "")
REPORT_JOB_NAME_CONTAINS = os.environ.get("REPORT_JOB_NAME_CONTAINS", "generar informe analitico")
CATALOG = os.environ.get("CONTRALORIA_CATALOG", "dacamargovws_catalog")
SCHEMA = os.environ.get("CONTRALORIA_SCHEMA", "contraloria")
VOL_INFORMES = os.environ.get("VOL_INFORMES", "informes")
VOL_ANALITICOS = os.environ.get("VOL_ANALITICOS", "informes-analiticos")

# Cliente hacia el workspace donde viven el agente, los jobs y los Volumes.
# Si REMOTE_HOST/REMOTE_TOKEN estan definidos (app hospedada en otro workspace),
# se usan; si no, se usa la autenticacion local por defecto.
REMOTE_HOST = os.environ.get("REMOTE_HOST")
REMOTE_TOKEN = os.environ.get("REMOTE_TOKEN")
if REMOTE_HOST and REMOTE_TOKEN:
    w = WorkspaceClient(host=REMOTE_HOST, token=REMOTE_TOKEN)
else:
    w = WorkspaceClient()


def resolve_job_id():
    if REPORT_JOB_ID:
        return int(REPORT_JOB_ID)
    for j in w.jobs.list():
        if REPORT_JOB_NAME_CONTAINS.lower() in (j.settings.name or "").lower():
            return j.job_id
    return None

st.set_page_config(page_title="Contraloria · Asistente de Auditoria", page_icon="🏛️", layout="wide")

# --- Estilo moderno oscuro ---
st.markdown("""
<style>
/* Fondo: bandera de Colombia grande y tenue bajo un velo oscuro */
.stApp {
  background:
    linear-gradient(rgba(9,9,12,0.88), rgba(9,9,12,0.93)),
    linear-gradient(to bottom, #FCD116 0%, #FCD116 50%, #003893 50%, #003893 75%, #CE1126 75%, #CE1126 100%);
  background-attachment: fixed, fixed;
  color: #ECECEC;
}
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 1.2rem; max-width: 1150px; }
/* Header institucional */
.cgr-header { display:flex; align-items:center; gap:18px; padding:18px 22px; margin-bottom:14px;
  background: linear-gradient(90deg, rgba(244,196,48,0.10), rgba(255,255,255,0.02));
  border:1px solid rgba(244,196,48,0.25); border-radius:16px; }
.cgr-header img { height:64px; filter: drop-shadow(0 2px 6px rgba(0,0,0,0.5)); }
.cgr-title { font-size:1.55rem; font-weight:700; color:#fff; line-height:1.15; margin:0; }
.cgr-sub { color:#9aa0aa; font-size:0.92rem; margin-top:2px; }
.cgr-accent { color:#F4C430; }
/* Tabs */
.stTabs [data-baseweb="tab-list"] { gap:6px; }
.stTabs [data-baseweb="tab"] { background:#15151a; border:1px solid #26262e; border-radius:10px 10px 0 0; color:#c9ccd3; }
.stTabs [aria-selected="true"] { background:#1f1f27; color:#F4C430; border-bottom:2px solid #F4C430; }
/* Inputs y botones */
.stTextInput input, .stTextArea textarea { background:#15151a; color:#ECECEC; border:1px solid #2b2b34; border-radius:10px; }
.stButton>button { background:#F4C430; color:#111; border:0; border-radius:10px; font-weight:600; }
.stButton>button:hover { background:#ffd94d; color:#000; }
.stChatMessage { background:#141419; border:1px solid #24242c; border-radius:14px; }
[data-testid="stSidebar"] { background:#0e0e12; border-right:1px solid #20202a; }
[data-testid="stDataFrame"], table { background:#141419; }
a, a:visited { color:#F4C430; }
/* Botones de navegacion (sidebar) tipo tarjeta */
[data-testid="stSidebar"] .stButton>button {
  width:100%; text-align:left; background:#141419; color:#e6e6e6;
  border:1px solid #2a2a33; border-radius:14px; padding:14px 16px;
  font-weight:600; font-size:0.98rem; margin-bottom:10px; transition:all .16s ease; }
[data-testid="stSidebar"] .stButton>button:hover {
  background:#1c1c24; color:#fff; border-color:#F4C430;
  box-shadow:0 6px 18px rgba(244,196,48,0.16); transform:translateY(-1px); }
[data-testid="stSidebar"] .stButton>button[kind="primary"] {
  background:linear-gradient(135deg,#F4C430 0%, #E0A800 100%); color:#141414;
  border:0; box-shadow:0 6px 20px rgba(244,196,48,0.38); }
.side-label { color:#7f8794; font-size:0.72rem; letter-spacing:.14em; text-transform:uppercase;
  margin:14px 0 8px 2px; }
/* Logo Databricks anclado al fondo de la barra lateral (izquierda) */
section[data-testid="stSidebar"] div[data-testid="stSidebarUserContent"] {
  display:flex; flex-direction:column; min-height:calc(100vh - 5rem); }
.db-logo-side { margin-top:auto; padding-top:26px; text-align:left; }
.db-logo-side .by { display:block; color:#6f7682; font-size:8pt; letter-spacing:.08em; margin-bottom:5px; }
.db-logo-side img { height:50px; opacity:.95; filter:drop-shadow(0 2px 6px rgba(0,0,0,.4)); }
</style>
""", unsafe_allow_html=True)

_esc = _escudo_b64()
_esc_img = f'<img src="data:image/png;base64,{_esc}"/>' if _esc else ""
st.markdown(f"""
<div class="cgr-header">
  {_esc_img}
  <div>
    <p class="cgr-title">Asistente de Auditoria <span class="cgr-accent">·</span> Contraloria General de la Republica</p>
    <p class="cgr-sub">Conversa con los informes de auditoria y genera informes analiticos con citas a la fuente.</p>
  </div>
</div>
""", unsafe_allow_html=True)

# --- Selector de modelo: AUTODETECTA que LLMs de chat tiene la cuenta y ofrece los
#     recomendados que esten disponibles (asi se adapta a cada workspace). ---
DEFAULT_LLM = os.environ.get("DEFAULT_LLM", "databricks-claude-opus-4-7")
# Modelos recomendados (orden = como aparecen). Solo se muestran los que existan en la cuenta.
PREFERRED_LLMS = [
    "databricks-gpt-6-luna", "databricks-gpt-5-6-sol", "databricks-claude-opus-4-7",
    "databricks-claude-opus-5-5", "databricks-gpt-6-sol", "databricks-claude-sonnet-4-5",
    "databricks-meta-llama-3-3-70b-instruct", "databricks-gemini-2-5-pro",
]
KNOWN_LABELS = {
    "databricks-gpt-6-luna": "GPT-6 Luna · rapido / menor costo",
    "databricks-gpt-5-6-sol": "GPT-5.6 Sol · balance",
    "databricks-gpt-6-sol": "GPT-6 Sol · flagship GPT-6",
    "databricks-claude-opus-4-7": "Claude Opus 4.7 · alta precision",
    "databricks-claude-opus-5-5": "Claude Opus 5.5 · top Claude",
    "databricks-claude-sonnet-4-5": "Claude Sonnet 4.5",
    "databricks-meta-llama-3-3-70b-instruct": "Llama 3.3 70B",
    "databricks-gemini-2-5-pro": "Gemini 2.5 Pro",
}


def _pretty_llm(name):
    return KNOWN_LABELS.get(name) or name.replace("databricks-", "").replace("-", " ").strip().title()


@st.cache_data(ttl=600, show_spinner=False)
def _available_chat_llms():
    """Endpoints de chat visibles para la app en esta cuenta ([] si no puede listar)."""
    names = []
    try:
        for e in w.serving_endpoints.list():
            n = e.name or ""
            task = (getattr(e, "task", None) or "").lower()
            is_chat = (task == "llm/v1/chat") if task else (
                n.lower().startswith("databricks-")
                and not any(k in n.lower() for k in ("embed", "gte", "bge", "bert")))
            if is_chat and n != AGENT_ENDPOINT:
                names.append(n)
    except Exception:
        names = []
    return names


def list_chat_llms():
    av = _available_chat_llms()
    if not av:
        return list(PREFERRED_LLMS)                    # sin permiso para listar: lista curada
    sel = [m for m in PREFERRED_LLMS if m in av]       # recomendados que existen en la cuenta
    return sel or sorted(av)[:8]                       # si ninguno, primeros detectados


if "page" not in st.session_state:
    st.session_state.page = "chat"

with st.sidebar:
    st.subheader("⚙️ Modelo (LLM)")
    _llms = list_chat_llms()
    _idx = _llms.index(DEFAULT_LLM) if DEFAULT_LLM in _llms else 0
    SELECTED_LLM = st.selectbox("Selecciona el modelo", _llms, index=_idx, format_func=_pretty_llm)
    st.caption(f"En uso: `{SELECTED_LLM}` — aplica al chat y a los informes.")

    st.markdown('<div class="side-label">Navegacion</div>', unsafe_allow_html=True)

    def _nav(label, page_id):
        kind = "primary" if st.session_state.page == page_id else "secondary"
        if st.button(label, key=f"nav_{page_id}", type=kind, use_container_width=True):
            st.session_state.page = page_id
            st.rerun()

    _nav("💬  Chat", "chat")
    _nav("📄  Informe analitico", "informe")
    _nav("⬆️  Cargar PDF", "upload")

    # Logo Databricks anclado al fondo de la barra lateral (esquina inferior izquierda)
    _dblogo = _asset_b64("databricks_logo_white.png")
    if _dblogo:
        st.markdown(
            f'<div class="db-logo-side"><span class="by">Powered by</span>'
            f'<img src="data:image/png;base64,{_dblogo}"/></div>',
            unsafe_allow_html=True)

PAGE = st.session_state.page


# --------------------------------------------------------------------------- #
# 1) CHAT
# --------------------------------------------------------------------------- #
def query_agent(messages, llm_endpoint=None):
    host = w.config.host
    if not host.startswith("http"):
        host = "https://" + host
    headers = w.config.authenticate()
    headers["Content-Type"] = "application/json"
    url = f"{host}/serving-endpoints/{AGENT_ENDPOINT}/invocations"
    payload = {"input": messages}
    if llm_endpoint:
        payload["custom_inputs"] = {"llm_endpoint": llm_endpoint}
    resp = requests.post(url, headers=headers, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    last_text = None
    for item in data.get("output", []):
        if isinstance(item, dict) and item.get("type") == "message":
            for c in item.get("content", []):
                if c.get("type") == "output_text" and c.get("text"):
                    last_text = c["text"]
    return last_text or "No pude generar una respuesta. Intenta de nuevo."


def stream_agent(messages, llm_endpoint=None):
    """Genera la respuesta en streaming (token a token) leyendo SSE del endpoint."""
    host = w.config.host
    if not host.startswith("http"):
        host = "https://" + host
    headers = w.config.authenticate()
    headers["Content-Type"] = "application/json"
    url = f"{host}/serving-endpoints/{AGENT_ENDPOINT}/invocations"
    payload = {"input": messages, "stream": True}
    if llm_endpoint:
        payload["custom_inputs"] = {"llm_endpoint": llm_endpoint}
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=300) as r:
        r.raise_for_status()
        for raw in r.iter_lines():
            if not raw:
                continue
            line = raw.decode("utf-8")
            if line.startswith("data:"):
                data = line[len("data:"):].strip()
                if data == "[DONE]":
                    break
                try:
                    ev = json.loads(data)
                except Exception:
                    continue
                if ev.get("type") == "response.output_text.delta" and ev.get("delta"):
                    yield ev["delta"]


def _md(text):
    """Escapa caracteres que Streamlit interpreta como formato:
    '$' (LaTeX en montos) y '_' (cursiva en nombres de archivo con guion bajo)."""
    return (text or "").replace("$", "\\$").replace("_", "\\_")


if PAGE == "chat":
    ss = st.session_state
    ss.setdefault("messages", [])
    ss.setdefault("generating", False)   # hay una consulta en curso
    ss.setdefault("partial", "")         # texto recibido hasta ahora (para conservarlo al detener)
    ss.setdefault("stop", False)         # el usuario pidio detener

    # --- Historial ---
    for i, m in enumerate(ss.messages):
        with st.chat_message(m["role"]):
            st.markdown(_md(m["content"]))
            if m["role"] == "assistant" and m["content"]:
                st.download_button(
                    "⬇️ Descargar respuesta (PDF)",
                    data=answer_to_pdf(m["content"]),
                    file_name=f"respuesta_contraloria_{i}.pdf",
                    mime="application/pdf",
                    key=f"dl_{i}",
                )

    # --- Consulta en curso: boton DETENER + streaming interrumpible ---
    if ss.generating:
        if st.button("⏸️  Detener consulta", key="stop_btn", type="secondary"):
            ss.stop = True  # el click re-ejecuta el script; se maneja abajo

        with st.chat_message("assistant"):
            ph = st.empty()

            if ss.stop:
                # El usuario detuvo: conserva lo recibido, libera el chat y avisa al worker.
                ev = ss.pop("_cancel_event", None)
                if ev:
                    ev.set()
                txt = ss.partial
                ph.markdown(_md(txt) if txt else "_Consulta detenida._")
                ss.messages.append({"role": "assistant",
                                    "content": txt or "(Consulta detenida por el usuario.)"})
                ss.generating, ss.stop, ss.partial = False, False, ""
                st.rerun()
            else:
                # La consulta corre en un hilo para poder interrumpirla AUN mientras el
                # agente "piensa" (consulta herramientas en el servidor, sin enviar datos).
                q = queue.Queue()
                ev = threading.Event()
                ss["_cancel_event"] = ev
                _msgs, _llm = list(ss.messages), SELECTED_LLM

                def _worker(msgs=_msgs, llm=_llm, q=q, ev=ev):
                    try:
                        for delta in stream_agent(msgs, llm):
                            if ev.is_set():
                                break
                            q.put(("delta", delta))
                    except Exception as e:
                        q.put(("error", str(e)))
                    finally:
                        q.put(_STREAM_DONE)

                threading.Thread(target=_worker, daemon=True).start()
                ss.partial = ""
                err = None
                ph.markdown("🔎 &nbsp;*Consultando informes...*")
                while True:
                    try:
                        item = q.get(timeout=0.25)
                    except queue.Empty:
                        # Heartbeat: cada 0.25s se escribe en pantalla, lo que permite que
                        # el click en "Detener" interrumpa el script aunque no lleguen datos.
                        ph.markdown((_md(ss.partial) + " ▌") if ss.partial
                                    else "🔎 &nbsp;*Consultando informes...* ▌")
                        continue
                    if item is _STREAM_DONE:
                        break
                    kind, val = item
                    if kind == "error":
                        err = val
                        break
                    ss.partial += val
                    ph.markdown(_md(ss.partial) + " ▌")

                answer = ss.partial
                if not answer:  # sin texto en streaming: error o fallback sin stream
                    if err:
                        answer = f"Error al consultar el agente: {err}"
                    else:
                        try:
                            answer = query_agent(list(ss.messages), SELECTED_LLM)
                        except Exception as e:
                            answer = f"Error al consultar el agente: {e}"
                ph.markdown(_md(answer))
                ss.messages.append({"role": "assistant", "content": answer})
                ss.generating, ss.partial = False, ""
                ss.pop("_cancel_event", None)
                st.rerun()

    # --- Nueva conversacion ABAJO (no hay que subir hasta arriba) ---
    if ss.messages and not ss.generating:
        if st.button("🆕  Nueva conversacion", key="new_chat"):
            ss.messages = []
            st.rerun()

    # --- Entrada (Streamlit la fija abajo); deshabilitada mientras hay una consulta ---
    if prompt := st.chat_input(
            "Escribe tu pregunta o pide un informe (ej: 'informe de la CVC 2024 y 2025')...",
            disabled=ss.generating):
        ss.messages.append({"role": "user", "content": prompt})
        ss.generating, ss.stop, ss.partial = True, False, ""
        st.rerun()


# --------------------------------------------------------------------------- #
# 2) INFORME ANALITICO
# --------------------------------------------------------------------------- #
elif PAGE == "informe":
    st.subheader("Generar Informe Analitico y Prescriptivo")
    st.caption("Tambien puedes pedir informes conversando en la pestaña Chat "
               "(ej: 'Genera un informe de la CAR 2025 y 2026' o 'informe de la DIAN enfocado en cobro coactivo y aduanas').")
    sector = st.text_input("Sector", value="Medio Ambiente")
    sujetos = st.text_input("Sujetos (siglas o nombres, separados por coma)", value="CAR,CVC,PNNC,ANLA,FONDO_VIDA")
    periodo = st.text_input("Periodo", value="2025-2026")
    tema = st.text_input("Enfoque / tema (opcional)", value="", placeholder="ej: cobro coactivo y aduanas")

    if st.button("Generar informe", type="primary"):
        job_id = resolve_job_id()
        if not job_id:
            st.error("No se pudo resolver el job de generacion de informe.")
        else:
            n_suj = len([s for s in sujetos.split(",") if s.strip()])
            est = "1-2 min" if n_suj <= 2 else "2-3 min"
            with st.spinner(f"Generando informe (recuperando evidencia y redactando)... puede tardar {est}. "
                            "Tip: menos sujetos o un enfoque/tema lo hacen mas rapido."):
                run = w.jobs.run_now(
                    job_id=job_id,
                    notebook_params={"sector": sector, "sujetos": sujetos, "periodo": periodo,
                                     "tema": tema, "llm_endpoint": SELECTED_LLM},
                )
                run_id = run.response.run_id
                pdf_path = None
                while True:
                    r = w.jobs.get_run(run_id)
                    state = r.state.life_cycle_state.value
                    if state in ("TERMINATED", "SKIPPED", "INTERNAL_ERROR"):
                        result_state = r.state.result_state.value if r.state.result_state else "?"
                        if result_state == "SUCCESS":
                            out = w.jobs.get_run_output(r.tasks[0].run_id)
                            pdf_path = out.notebook_output.result
                        else:
                            st.error(f"El job termino con estado {result_state}.")
                        break
                    time.sleep(5)
            if pdf_path:
                st.success(f"Informe generado: {pdf_path}")
                data = w.files.download(pdf_path).contents.read()
                st.download_button(
                    "⬇️ Descargar PDF",
                    data=data,
                    file_name=pdf_path.split("/")[-1],
                    mime="application/pdf",
                )


# --------------------------------------------------------------------------- #
# 3) CARGAR PDF (añade conocimiento dinamicamente)
# --------------------------------------------------------------------------- #
elif PAGE == "upload":
    st.subheader("Cargar un informe de auditoria (PDF)")
    st.caption("Al subirlo se ingiere y se indexa automaticamente para el chat y los informes.")
    up = st.file_uploader("Selecciona un PDF", type=["pdf"])
    if up and st.button("Subir al repositorio de informes"):
        dest = f"/Volumes/{CATALOG}/{SCHEMA}/{VOL_INFORMES}/{up.name}"
        try:
            w.files.upload(dest, up.getvalue(), overwrite=True)
            st.success(f"Subido a {dest}. La ingesta se disparara automaticamente.")
        except Exception as e:
            st.error(f"Error subiendo el archivo: {e}")
