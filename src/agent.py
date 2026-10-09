"""
Agente de auditoria de la Contraloria (Mosaic AI Agent Framework).

Loop de tool-calling sobre ChatDatabricks (sin langgraph, para evitar
incompatibilidades de version). Herramientas:
  - retrieve_audit_evidence: RAG sobre informes (Vector Search) con documento+pagina.
  - buscar_sectorizacion (funcion UC): sectorizacion sujeto -> sector -> delegada.

El system prompt obliga a: citar [documento, p. N]; distinguir HALLAZGOS
COMPROBADOS de LINEAS A VERIFICAR; y declarar cuando NO hay evidencia suficiente.
"""
import os
import json
from typing import Generator

import mlflow
from databricks_langchain import ChatDatabricks, VectorSearchRetrieverTool, UCFunctionToolkit
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from mlflow.pyfunc import ResponsesAgent
from mlflow.types.responses import (
    ResponsesAgentRequest, ResponsesAgentResponse, ResponsesAgentStreamEvent,
)

CATALOG = os.environ.get("CONTRALORIA_CATALOG", "dacamargovws_catalog")
SCHEMA = os.environ.get("CONTRALORIA_SCHEMA", "contraloria")
LLM_ENDPOINT = os.environ.get("CONTRALORIA_LLM", "databricks-claude-opus-4-7")
VS_INDEX = os.environ.get("CONTRALORIA_VS_INDEX", f"{CATALOG}.{SCHEMA}.doc_chunks_index")
NUM_RESULTS = int(os.environ.get("CONTRALORIA_NUM_RESULTS", "10"))
MAX_ITERS = int(os.environ.get("CONTRALORIA_MAX_ITERS", "14"))
# Con AI Gateway activo se fuerza el LLM gobernado: se ignora el 'llm_endpoint' que envie la app,
# para que TODO el trafico pase por la gobernanza (usage, rate limit, guardrails, fallbacks).
FORCE_LLM = os.environ.get("CONTRALORIA_FORCE_LLM", "").lower() in ("1", "true", "yes")

SYSTEM_PROMPT = """Eres el asistente analitico de la Contraloria General de la Republica para la
planeacion y focalizacion de auditorias. Conversas en lenguaje natural con el equipo auditor; el
usuario NO tiene que usar frases ni palabras clave especificas.

IDENTIFICACION DE SUJETOS
- El usuario puede referirse a un sujeto por su SIGLA (p.ej. "CAR", "DIAN") o por su NOMBRE COMPLETO
  ("Corporacion Autonoma Regional de Cundinamarca"). Debes reconocer ambos.
- Usa la herramienta 'buscar_sectorizacion' para resolver nombre<->sigla, confirmar el sector/delegada
  y, si aplica, encontrar los sujetos asociados a una delegada.

DOS TIPOS DE PETICION (deduce la intencion del lenguaje natural, sin depender de palabras exactas):
A) CONSULTA PUNTUAL: responde concreto, con citas.
B) SOLICITUD DE INFORME: cuando el usuario pide "un informe", "analisis", "resumen de antecedentes",
   "reporte", etc. de uno o varios sujetos, posiblemente delimitado a un TEMA
   (p.ej. "informe de la DIAN enfocado en cobro coactivo y aduanas"). En ese caso:

   1. Identifica sujeto(s), vigencias (si las indican) y el TEMA/enfoque si lo hay.
   2. Recupera evidencia con 'retrieve_audit_evidence' haciendo VARIAS busquedas dirigidas por sujeto
      (y por el tema si se delimito): antecedentes/informes y vigencias; hallazgos relevantes y sus
      cuantias fiscales; planes de mejoramiento; opiniones y fenecimiento.
   3. Estructura el informe POR CADA SUJETO con estas secciones:
      - Antecedentes de auditoria disponibles (informes y vigencias cubiertas).
      - Hallazgos mas relevantes (con cuantias fiscales cuando existan), comprobados y con cita.
      - Planes de mejoramiento (estado/efectividad si consta en la evidencia).
      - Recurrencias entre vigencias y persistencia: senala que problemas se repiten y si persisten
        pese a las acciones de mejora.
      - Riesgos para la proxima auditoria y aspectos a revisar (como "Lineas a verificar").
      - Conclusion tecnica sustentada en los informes fuente.
   4. Si son VARIOS sujetos: haz el analisis anterior para cada uno y agrega al final una seccion
      "Riesgos y patrones compartidos" que compare las recurrencias y riesgos comunes.
   5. Si se delimito un TEMA, prioriza y organiza el informe alrededor de ese tema.

REGLAS OBLIGATORIAS (siempre):
1. CITAS: toda afirmacion basada en los informes cita la fuente asi: [documento, p. N].
2. DISTINCION: separa "Hallazgos comprobados" (constan en informes, con cita y cuantia) de
   "Lineas a verificar (a confirmar por el equipo auditor)" (hipotesis/pruebas no comprobadas).
   Nunca presentes una linea a verificar como comprobada.
3. EVIDENCIA INSUFICIENTE: si no hay evidencia, dilo explicitamente y no inventes cifras, hallazgos,
   paginas ni documentos. Reporta cuantias exactamente como aparecen.
4. Responde en espanol, tono tecnico de control fiscal.
5. NO escribas texto de planeacion, comentarios, ni narracion antes o entre las llamadas a
   herramientas (nada de notas tipo "voy a buscar..." o "un intento mas"). Usa las herramientas
   en silencio y redacta UNICAMENTE la respuesta final para el usuario, siempre en espanol.
"""


_REASONING_TYPES = {"reasoning", "thinking", "redacted_thinking", "summary_text"}


def _is_reasoning(x):
    """True si la estructura es un bloque de razonamiento/thinking (no respuesta)."""
    if isinstance(x, list):
        return bool(x) and all(_is_reasoning(i) for i in x)
    if isinstance(x, dict):
        return x.get("type") in _REASONING_TYPES
    return False


def _clean_text(content):
    """Extrae solo el texto de respuesta, descartando bloques de razonamiento de los
    modelos con 'thinking' (Claude), que a veces llegan como dict o como JSON serializado."""
    if not content:
        return ""
    if isinstance(content, list):
        out = []
        for p in content:
            if isinstance(p, dict):
                if p.get("type") in _REASONING_TYPES:
                    continue
                out.append(p.get("text", "") or "")
            elif isinstance(p, str):
                out.append(_clean_text(p))
        return "".join(out)
    if isinstance(content, str):
        s = content.strip()
        if s.startswith("[") or s.startswith("{"):
            try:
                if _is_reasoning(json.loads(s)):
                    return ""
            except Exception:
                pass
        return content
    return ""


def _tools():
    retriever = VectorSearchRetrieverTool(
        index_name=VS_INDEX, num_results=NUM_RESULTS, tool_name="retrieve_audit_evidence",
        tool_description=("Recupera fragmentos de los informes de auditoria relevantes a la consulta; "
                          "devuelve texto con 'documento' y 'pagina' para citar. Usalo para hallazgos, "
                          "incidencia fiscal/disciplinaria, opiniones, cuantias, gestion aduanera y "
                          "cambiaria, y antecedentes de un sujeto."),
        columns=["documento", "pagina", "sigla", "sujeto", "sector", "delegada",
                 "tipo_auditoria", "vigencia", "texto"],
    )
    uc = UCFunctionToolkit(function_names=[f"{CATALOG}.{SCHEMA}.buscar_sectorizacion"]).tools
    return [retriever, *uc]


mlflow.langchain.autolog()


class ContraloriaAgent(ResponsesAgent):
    def __init__(self):
        self.tools = _tools()
        self.tools_by_name = {t.name: t for t in self.tools}
        self._llm_cache = {}

    def _llm(self, endpoint=None):
        ep = endpoint or LLM_ENDPOINT
        if ep not in self._llm_cache:
            kwargs = {"endpoint": ep}
            # Los modelos GPT de razonamiento requieren reasoning_effort='none' para
            # habilitar tool-calling via chat completions.
            if "gpt" in ep.lower():
                kwargs["extra_params"] = {"reasoning_effort": "none"}
            self._llm_cache[ep] = ChatDatabricks(**kwargs).bind_tools(self.tools)
        return self._llm_cache[ep]

    def _override_llm(self, request):
        if FORCE_LLM:            # gobernanza no evitable: siempre el LLM gobernado por defecto
            return None
        ci = getattr(request, "custom_inputs", None) or {}
        return ci.get("llm_endpoint") if isinstance(ci, dict) else None

    def _to_lc(self, request):
        out = []
        for m in request.input:
            d = m.model_dump() if hasattr(m, "model_dump") else dict(m)
            role, content = d.get("role", "user"), d.get("content", "")
            if isinstance(content, list):
                content = " ".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
            out.append({"assistant": AIMessage, "system": SystemMessage}.get(role, HumanMessage)(content=content))
        return out

    def _run(self, lc_messages, llm_endpoint=None):
        llm = self._llm(llm_endpoint)
        messages, ai = [SystemMessage(content=SYSTEM_PROMPT), *lc_messages], None
        for _ in range(MAX_ITERS):
            ai = llm.invoke(messages)
            messages.append(ai)
            calls = getattr(ai, "tool_calls", None) or []
            if not calls:
                break
            for tc in calls:
                tool = self.tools_by_name.get(tc["name"])
                try:
                    res = tool.invoke(tc["args"]) if tool else f"Herramienta {tc['name']} no encontrada"
                except Exception as e:
                    res = f"Error ejecutando {tc['name']}: {e}"
                messages.append(ToolMessage(content=str(res), tool_call_id=tc["id"]))
        content = _clean_text(getattr(ai, "content", "") if ai else "")
        return content or "(sin respuesta)"

    def predict(self, request: ResponsesAgentRequest) -> ResponsesAgentResponse:
        text = self._run(self._to_lc(request), self._override_llm(request))
        return ResponsesAgentResponse(output=[self.create_text_output_item(text=text, id="msg-1")])

    def predict_stream(self, request: ResponsesAgentRequest) -> Generator[ResponsesAgentStreamEvent, None, None]:
        llm = self._llm(self._override_llm(request))
        messages = [SystemMessage(content=SYSTEM_PROMPT), *self._to_lc(request)]
        item_id, final_text = "msg-1", ""
        for _ in range(MAX_ITERS):
            gathered, turn_text = None, ""
            for chunk in llm.stream(messages):
                gathered = chunk if gathered is None else gathered + chunk
                c = _clean_text(getattr(chunk, "content", None))  # descarta bloques de razonamiento
                if c:
                    turn_text += c
            messages.append(gathered)
            tool_calls = getattr(gathered, "tool_calls", None) or []
            if not tool_calls:
                # Turno final: solo aqui transmitimos texto al usuario. El texto de los
                # turnos que llaman herramientas es narracion interna y NO se emite.
                final_text = turn_text
                buf = ""
                for ch in turn_text:                    # replay en fragmentos -> efecto "generandose"
                    buf += ch
                    if len(buf) >= 24 or ch in ".\n,;:":
                        yield ResponsesAgentStreamEvent(
                            type="response.output_text.delta", item_id=item_id, delta=buf)
                        buf = ""
                if buf:
                    yield ResponsesAgentStreamEvent(
                        type="response.output_text.delta", item_id=item_id, delta=buf)
                break
            for tc in tool_calls:                       # ejecuta herramientas y continua (sin emitir texto)
                tool = self.tools_by_name.get(tc["name"])
                try:
                    res = tool.invoke(tc["args"]) if tool else f"Herramienta {tc['name']} no encontrada"
                except Exception as e:
                    res = f"Error ejecutando {tc['name']}: {e}"
                messages.append(ToolMessage(content=str(res), tool_call_id=tc["id"]))
        yield ResponsesAgentStreamEvent(
            type="response.output_item.done",
            item=self.create_text_output_item(text=final_text or "(sin respuesta)", id=item_id))


mlflow.models.set_model(ContraloriaAgent())
