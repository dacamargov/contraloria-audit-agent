# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy del agente a Model Serving
# MAGIC Registra el agente (`agent.py`) en Unity Catalog y lo despliega a un endpoint.
# MAGIC Correr **despues** de que el indice de Vector Search tenga datos (tras la ingesta).

# COMMAND ----------
# MAGIC %pip install -U mlflow databricks-langchain databricks-openai databricks-agents databricks-vectorsearch
# MAGIC dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "dacamargovws_catalog")
dbutils.widgets.text("schema", "contraloria")
dbutils.widgets.text("llm_endpoint", "databricks-claude-opus-4-7")
dbutils.widgets.text("embedding_endpoint", "databricks-gte-large-en")
dbutils.widgets.text("agent_endpoint", "contraloria_audit_agent")
dbutils.widgets.text("governed_llm_endpoints", "")  # AI Gateway opt-in: lista coma; vacio = FM sistema
# Secret con las credenciales M2M OAuth del SP dedicado que llama los model services del gateway.
dbutils.widgets.text("gw_secret_scope", "contraloria")
dbutils.widgets.text("gw_client_id_key", "gw_sp_client_id")
dbutils.widgets.text("gw_client_secret_key", "gw_sp_secret")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
LLM = dbutils.widgets.get("llm_endpoint")
EMB = dbutils.widgets.get("embedding_endpoint")
AGENT_ENDPOINT = dbutils.widgets.get("agent_endpoint")
GOVERNED_LLMS = [x.strip() for x in dbutils.widgets.get("governed_llm_endpoints").split(",") if x.strip()]
GW_SECRET_SCOPE = dbutils.widgets.get("gw_secret_scope")
GW_CLIENT_ID_KEY = dbutils.widgets.get("gw_client_id_key")
GW_CLIENT_SECRET_KEY = dbutils.widgets.get("gw_client_secret_key")

VS_INDEX = f"{CATALOG}.{SCHEMA}.doc_chunks_index"
UC_MODEL = f"{CATALOG}.{SCHEMA}.contraloria_audit_agent"

# COMMAND ----------
import os
import mlflow
from mlflow.models.resources import (
    DatabricksServingEndpoint, DatabricksVectorSearchIndex, DatabricksFunction,
)
# Model services de Unity Gateway (nombre de 3 niveles). Clase disponible en mlflow reciente;
# el fallback evita romper si la version instalada aun no la expone.
try:
    from mlflow.models.resources import DatabricksUCModelService
except Exception:
    DatabricksUCModelService = None
from pkg_resources import get_distribution

_ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
AGENT_FILE = "/Workspace" + os.path.dirname(_ctx.notebookPath().get()) + "/agent.py"
print("agent.py:", AGENT_FILE, os.path.exists(AGENT_FILE))

# AUTODETECCION de LLMs: el agente permite elegir el modelo por peticion. Detectamos los
# serving endpoints de chat de la cuenta (cambian segun el workspace) y habilitamos los
# modelos recomendados que existan (PREFERRED_LLMS); asi el endpoint puede consultarlos.
from databricks.sdk import WorkspaceClient


def _es_chat(e):
    task = (getattr(e, "task", None) or "").lower()
    if task:
        return task == "llm/v1/chat"
    n = (e.name or "").lower()  # fallback si el endpoint no expone 'task'
    return n.startswith("databricks-") and not any(k in n for k in ("embed", "gte", "bge", "bert"))


# Modelos recomendados (deben coincidir con los del app). Se conceden al agente solo los
# que existan en la cuenta; si no hay ninguno, los primeros detectados.
PREFERRED_LLMS = [
    "databricks-gpt-6-luna", "databricks-gpt-5-6-sol", "databricks-claude-opus-4-7",
    "databricks-claude-opus-5-5", "databricks-gpt-6-sol", "databricks-claude-sonnet-4-5",
    "databricks-meta-llama-3-3-70b-instruct", "databricks-gemini-2-5-pro",
]
detected = []
try:
    for e in WorkspaceClient().serving_endpoints.list():
        if _es_chat(e) and e.name not in (AGENT_ENDPOINT, EMB):
            detected.append(e.name)
except Exception as ex:
    print("Aviso: no se pudieron listar endpoints, uso solo el LLM por defecto:", ex)

offered = [m for m in PREFERRED_LLMS if m in detected] or detected[:6]
# El LLM por defecto debe existir en la cuenta; si no, se usa el primero ofrecido.
default_llm = LLM if (LLM in detected or not detected) else (offered[0] if offered else LLM)
llm_endpoints = list(dict.fromkeys([default_llm, *offered]))  # default primero, sin duplicados

# AI GATEWAY: si hay endpoints LLM gobernados, el agente usa SOLO esos (gobernanza no evitable:
# usage, rate limit, guardrails, fallbacks). Se convierten en los unicos LLM habilitados y se
# aplican como allowlist en el agente (ver CONTRALORIA_ALLOWED_LLMS en agent.py); el primero es
# el modelo por defecto. La app ofrece exactamente esta lista.
if GOVERNED_LLMS:
    default_llm = GOVERNED_LLMS[0]
    llm_endpoints = list(dict.fromkeys(GOVERNED_LLMS))
    print("AI Gateway ACTIVO: el agente usa solo endpoints gobernados ->", llm_endpoints)
print("LLMs habilitados para el agente:", llm_endpoints)


def _llm_resource(name):
    # Model service de Unity Gateway (catalog.schema.name) -> resource de tipo UC Model Service.
    # NOTA: el agente NO llama estos model services con su token nativo (auto-auth u OBO), porque
    # ese token es downscoped y el AI Gateway no resuelve model services -> 404. En su lugar usa un
    # SP dedicado via M2M OAuth (ver CONTRALORIA_GW_CLIENT_ID/SECRET). Declaramos el recurso igual
    # para dejar registrada la dependencia. Nombre plano -> serving endpoint clasico.
    if "." in name and DatabricksUCModelService is not None:
        return DatabricksUCModelService(model_service_name=name)
    return DatabricksServingEndpoint(endpoint_name=name)


llm_resources = [_llm_resource(e) for e in llm_endpoints]
resources = [
    *llm_resources,
    DatabricksServingEndpoint(endpoint_name=EMB),
    DatabricksVectorSearchIndex(index_name=VS_INDEX),
    DatabricksFunction(function_name=f"{CATALOG}.{SCHEMA}.buscar_sectorizacion"),
]
input_example = {"input": [{"role": "user",
    "content": "A que sector y delegada corresponde la CVC y que otros sujetos comparten esa delegada?"}]}

# COMMAND ----------
with mlflow.start_run():
    logged = mlflow.pyfunc.log_model(
        name="contraloria_agent", python_model=AGENT_FILE,
        input_example=input_example, resources=resources,
        pip_requirements=[
            f"mlflow=={get_distribution('mlflow').version}",
            f"databricks-langchain=={get_distribution('databricks-langchain').version}",
            # databricks-openai arma la URL del AI Gateway (use_ai_gateway -> /ai-gateway/mlflow/v1).
            # Se FIJA para que el entorno servido enrute los model services al gateway (si no se
            # fija, el serving puede instalar una version sin soporte y caer a /serving-endpoints).
            f"databricks-openai=={get_distribution('databricks-openai').version}",
            f"langchain-core=={get_distribution('langchain-core').version}",
            f"databricks-vectorsearch=={get_distribution('databricks-vectorsearch').version}",
        ],
    )

mlflow.set_registry_uri("databricks-uc")
ver = mlflow.register_model(model_uri=logged.model_uri, name=UC_MODEL).version
print("Version registrada:", ver)

# COMMAND ----------
from databricks import agents
# REPRODUCIBILIDAD: se inyecta la config de la cuenta como variables de entorno del endpoint,
# para que el agente servido use el catalog/schema/LLM correctos (no los defaults del codigo).
# Asi el mismo agent.py funciona en cualquier workspace sin editar codigo.
_env = {
    "CONTRALORIA_CATALOG": CATALOG,
    "CONTRALORIA_SCHEMA": SCHEMA,
    "CONTRALORIA_LLM": default_llm,
}
# Con AI Gateway activo, el agente solo acepta LLMs de la lista gobernada (allowlist); si la app
# pide otro, cae al gobernado por defecto. Asi ningun trafico escapa a la gobernanza.
if GOVERNED_LLMS:
    _env["CONTRALORIA_ALLOWED_LLMS"] = ",".join(llm_endpoints)
    # URL publica del workspace: el agente la usa para enrutar el AI Gateway con el host
    # publico (no el host interno de serving) al llamar los model services. Sin esto,
    # config.host seria el host interno -> el gateway da 404.
    _env["CONTRALORIA_WORKSPACE_HOST"] = WorkspaceClient().config.host
    # Credenciales M2M OAuth del SP dedicado para el gateway (via secret de Databricks). El SP
    # tiene EXECUTE sobre los model services -> token de identidad completa que el gateway resuelve.
    # Model Serving sustituye {{secrets/scope/key}} en tiempo de ejecucion.
    _env["CONTRALORIA_GW_CLIENT_ID"] = f"{{{{secrets/{GW_SECRET_SCOPE}/{GW_CLIENT_ID_KEY}}}}}"
    _env["CONTRALORIA_GW_CLIENT_SECRET"] = f"{{{{secrets/{GW_SECRET_SCOPE}/{GW_CLIENT_SECRET_KEY}}}}}"
agents.deploy(
    UC_MODEL, ver, scale_to_zero=True, endpoint_name=AGENT_ENDPOINT,
    environment_vars=_env,
)
print("Despliegue iniciado ->", AGENT_ENDPOINT, "| default LLM:", default_llm)

# COMMAND ----------
# ESTABILIDAD: deja servida SOLO la version recien desplegada. Cada 'agents.deploy'
# agrega una served entity y conserva las anteriores; con el tiempo el endpoint acumula
# muchas versiones y una version vieja incompatible puede ABORTAR los updates del endpoint.
# Se espera a que el endpoint termine de actualizar (los deletes fallan si esta IN_PROGRESS)
# y luego se eliminan los deployments distintos al actual (idempotente, best-effort).
import time as _time

def _esperar_estable(timeout_s=1200, intervalo=20):
    # "Estable" = el update termino, sea con exito (NOT_UPDATING) o fallo (UPDATE_FAILED).
    # Tratar UPDATE_FAILED como terminal permite proceder a limpiar las versiones viejas
    # (p.ej. una incompatible que bloquea el update) y asi DESATASCAR el endpoint.
    for _ in range(timeout_s // intervalo):
        try:
            st = WorkspaceClient().serving_endpoints.get(AGENT_ENDPOINT).state
            cu = getattr(getattr(st, "config_update", None), "value", None) or str(getattr(st, "config_update", ""))
            if "NOT_UPDATING" in cu or "UPDATE_FAILED" in cu:
                return True
        except Exception:
            pass
        _time.sleep(intervalo)
    return False

def _viejos():
    try:
        return [int(getattr(d, "model_version", None) or getattr(d, "version", 0))
                for d in agents.list_deployments()
                if getattr(d, "model_name", None) == UC_MODEL
                and str(getattr(d, "model_version", None) or getattr(d, "version", None)) != str(ver)]
    except Exception as e:
        print("Aviso: no se pudieron listar deployments:", e)
        return []

if _esperar_estable():
    for _ in range(4):  # varias pasadas: un delete falla si hay update en curso -> reintenta
        pend = _viejos()
        if not pend:
            break
        print("Limpiando versiones viejas:", pend)
        for mv in pend:
            try:
                agents.delete_deployment(UC_MODEL, mv)
                print("  eliminada v", mv)
            except Exception as de:
                print("  aviso v", mv, ":", de)
        _esperar_estable(timeout_s=900)
    print("Versiones servidas tras limpieza:", _viejos() or "solo la actual (v%s)" % ver)
else:
    print("Aviso: el endpoint no se estabilizo a tiempo; limpieza de versiones omitida.")

# COMMAND ----------
# AI GATEWAY: concede EXECUTE sobre los model services gobernados al SP del agente. La
# declaracion de recursos (DatabricksUCModelService) concede USE CATALOG/USE SCHEMA, pero el
# EXECUTE sobre el securable 'model_service' puede no aplicarse automaticamente; se concede aqui
# (best-effort, idempotente) a los SPs que tengan USE_SCHEMA en el schema (incluye el SP
# autogenerado del agente). Solo se concede lo que el que despliega ya posee (debe ser owner/MANAGE
# del model service). Sin este EXECUTE, el agente recibe 404 'does not exist' al llamar el gateway.
if GOVERNED_LLMS:
    import re as _re
    _ms_list = [m for m in GOVERNED_LLMS if "." in m]
    try:
        _sg = WorkspaceClient().api_client.do(
            "GET", f"/api/2.1/unity-catalog/permissions/schema/{CATALOG}.{SCHEMA}")
        _sps = sorted({a.get("principal") for a in (_sg.get("privilege_assignments") or [])
                       if any("USE_SCHEMA" in str(p) for p in (a.get("privileges") or []))
                       and _re.match(r"^[0-9a-f-]{36}$", a.get("principal") or "")})
        for _ms in _ms_list:
            for _sp in _sps:
                try:
                    WorkspaceClient().api_client.do(
                        "PATCH", f"/api/2.1/unity-catalog/permissions/model_service/{_ms}",
                        body={"changes": [{"principal": _sp, "add": ["EXECUTE"]}]})
                except Exception as _e:
                    print("  aviso grant EXECUTE", _ms, _sp, ":", _e)
        print("EXECUTE en model services concedido a SPs:", _sps or "(ninguno detectado)")
    except Exception as _e:
        print("Aviso: no se pudo auto-conceder EXECUTE en model services:", _e)
