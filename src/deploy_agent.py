# Databricks notebook source
# MAGIC %md
# MAGIC # Deploy del agente a Model Serving
# MAGIC Registra el agente (`agent.py`) en Unity Catalog y lo despliega a un endpoint.
# MAGIC Correr **despues** de que el indice de Vector Search tenga datos (tras la ingesta).

# COMMAND ----------
# MAGIC %pip install -U mlflow databricks-langchain databricks-agents databricks-vectorsearch
# MAGIC dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "dacamargovws_catalog")
dbutils.widgets.text("schema", "contraloria")
dbutils.widgets.text("llm_endpoint", "databricks-claude-opus-4-7")
dbutils.widgets.text("embedding_endpoint", "databricks-gte-large-en")
dbutils.widgets.text("agent_endpoint", "contraloria_audit_agent")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
LLM = dbutils.widgets.get("llm_endpoint")
EMB = dbutils.widgets.get("embedding_endpoint")
AGENT_ENDPOINT = dbutils.widgets.get("agent_endpoint")

VS_INDEX = f"{CATALOG}.{SCHEMA}.doc_chunks_index"
UC_MODEL = f"{CATALOG}.{SCHEMA}.contraloria_audit_agent"

# COMMAND ----------
import os
import mlflow
from mlflow.models.resources import (
    DatabricksServingEndpoint, DatabricksVectorSearchIndex, DatabricksFunction,
)
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
print("LLMs habilitados para el agente:", llm_endpoints)
llm_resources = [DatabricksServingEndpoint(endpoint_name=e) for e in llm_endpoints]
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
agents.deploy(
    UC_MODEL, ver, scale_to_zero=True, endpoint_name=AGENT_ENDPOINT,
    environment_vars={
        "CONTRALORIA_CATALOG": CATALOG,
        "CONTRALORIA_SCHEMA": SCHEMA,
        "CONTRALORIA_LLM": default_llm,
    },
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
