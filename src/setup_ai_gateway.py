# Databricks notebook source
# MAGIC %md
# MAGIC # Mosaic AI Gateway  -  Endpoint LLM gobernado (opt-in)
# MAGIC
# MAGIC Crea/actualiza un **endpoint de chat External Model** gobernado por Mosaic AI Gateway
# MAGIC con TODAS las funciones de gobernanza para las llamadas al LLM del agente:
# MAGIC   - **Usage tracking** (consumo por usuario/endpoint en system tables).
# MAGIC   - **Inference tables** (payload de cada request/response en Unity Catalog).
# MAGIC   - **Rate limiting** GLOBAL por endpoint (calls/minuto).
# MAGIC   - **Guardrails**: deteccion de PII (BLOCK) + safety, en entrada y salida.
# MAGIC   - **Fallbacks**: si el proveedor primario falla, cae al secundario (si se configura).
# MAGIC
# MAGIC ## Por que un endpoint propio
# MAGIC El endpoint del agente (`task=agent/v1/responses`) NO soporta rate limits/guardrails/usage;
# MAGIC y los foundation models de sistema (`databricks-claude-*`) no son gobernables por el usuario.
# MAGIC Por eso se gobierna la **capa LLM** con un endpoint External Model propio y se enruta el
# MAGIC agente hacia el (ver `deploy_agent.py`, variable `governed_llm_endpoint`).
# MAGIC
# MAGIC ## Requisito previo (una vez): guardar la API key del proveedor como secreto
# MAGIC ```bash
# MAGIC databricks secrets create-scope contraloria            # si no existe
# MAGIC databricks secrets put-secret contraloria anthropic_api_key   # pega la key
# MAGIC # (opcional, para fallback)  databricks secrets put-secret contraloria openai_api_key
# MAGIC ```
# MAGIC Es seguro ejecutar este notebook aunque este deshabilitado o sin secreto: no falla,
# MAGIC solo imprime instrucciones y termina.

# COMMAND ----------
dbutils.widgets.text("catalog", "dacamargovws_catalog")
dbutils.widgets.text("schema", "contraloria")
dbutils.widgets.text("governed_llm_endpoint", "")   # vacio = deshabilitado (opt-in)
dbutils.widgets.text("ext_provider", "anthropic")
dbutils.widgets.text("ext_model", "claude-opus-4-20250514")
dbutils.widgets.text("ext_secret_scope", "contraloria")
dbutils.widgets.text("ext_secret_key", "anthropic_api_key")
dbutils.widgets.text("ext_fallback_provider", "")   # vacio = sin fallback
dbutils.widgets.text("ext_fallback_model", "")
dbutils.widgets.text("ext_fallback_secret_key", "openai_api_key")
dbutils.widgets.text("rate_limit_calls", "120")      # llamadas por minuto, global por endpoint
dbutils.widgets.text("pii_behavior", "BLOCK")        # BLOCK | NONE

CATALOG = dbutils.widgets.get("catalog").strip()
SCHEMA = dbutils.widgets.get("schema").strip()
GOV_EP = dbutils.widgets.get("governed_llm_endpoint").strip()
PROVIDER = dbutils.widgets.get("ext_provider").strip().lower()
MODEL = dbutils.widgets.get("ext_model").strip()
SCOPE = dbutils.widgets.get("ext_secret_scope").strip()
KEY = dbutils.widgets.get("ext_secret_key").strip()
FB_PROVIDER = dbutils.widgets.get("ext_fallback_provider").strip().lower()
FB_MODEL = dbutils.widgets.get("ext_fallback_model").strip()
FB_KEY = dbutils.widgets.get("ext_fallback_secret_key").strip()
RATE_CALLS = int(dbutils.widgets.get("rate_limit_calls").strip() or "120")
PII = dbutils.widgets.get("pii_behavior").strip().upper() or "BLOCK"

# COMMAND ----------
# Opt-in: si no se definio el endpoint gobernado, no hay nada que hacer.
if not GOV_EP:
    print("AI Gateway DESHABILITADO (governed_llm_endpoint vacio). "
          "Para activarlo, define la variable 'governed_llm_endpoint' en databricks.yml, "
          "guarda la API key como secreto y vuelve a desplegar. Saliendo sin cambios.")
    dbutils.notebook.exit("disabled")

# COMMAND ----------
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()

# Verifica que el secreto exista; si no, imprime instrucciones y termina sin fallar.
def _secret_existe(scope, key):
    try:
        return any(s.key == key for s in w.secrets.list_secrets(scope))
    except Exception:
        return False

if not _secret_existe(SCOPE, KEY):
    print(f"[FALTA SECRETO] No encuentro el secreto '{KEY}' en el scope '{SCOPE}'.\n"
          f"Crealo con:\n"
          f"  databricks secrets create-scope {SCOPE}\n"
          f"  databricks secrets put-secret {SCOPE} {KEY}\n"
          f"Luego vuelve a ejecutar. Saliendo sin cambios.")
    dbutils.notebook.exit("missing-secret")

# COMMAND ----------
# Mapa proveedor -> nombre del bloque de config y campo de la API key (referencia a secreto).
# Soporta los proveedores externos mas comunes para chat; para otros, ver docs de External Models.
_PROVIDER_CFG = {
    "anthropic": ("anthropic_config", "anthropic_api_key"),
    "openai":    ("openai_config", "openai_api_key"),
    "cohere":    ("cohere_config", "cohere_api_key"),
}


def _external_model(provider, model, scope, key, name):
    if provider not in _PROVIDER_CFG:
        raise ValueError(
            f"Proveedor '{provider}' no soportado por este script ({list(_PROVIDER_CFG)}). "
            f"Agregalo en _PROVIDER_CFG segun la doc de External Models, o usa anthropic/openai/cohere.")
    cfg_block, key_field = _PROVIDER_CFG[provider]
    return {
        "name": name,
        "external_model": {
            "name": model,
            "provider": provider,
            "task": "llm/v1/chat",
            cfg_block: {key_field: f"{{{{secrets/{scope}/{key}}}}}"},
        },
    }


served = [_external_model(PROVIDER, MODEL, SCOPE, KEY, "primary")]

use_fallback = bool(FB_PROVIDER and FB_MODEL and _secret_existe(SCOPE, FB_KEY))
if FB_PROVIDER and FB_MODEL and not use_fallback:
    print(f"[AVISO] Fallback solicitado ({FB_PROVIDER}/{FB_MODEL}) pero falta el secreto "
          f"'{FB_KEY}' en '{SCOPE}'. Se omite el fallback.")
if use_fallback:
    served.append(_external_model(FB_PROVIDER, FB_MODEL, SCOPE, FB_KEY, "fallback"))

# COMMAND ----------
# Configuracion de Mosaic AI Gateway (TODAS las funciones de gobernanza).
ai_gateway = {
    "usage_tracking_config": {"enabled": True},
    "inference_table_config": {
        "enabled": True,
        "catalog_name": CATALOG,
        "schema_name": SCHEMA,
        "table_name_prefix": GOV_EP,
    },
    "rate_limits": [
        {"calls": RATE_CALLS, "renewal_period": "minute", "key": "endpoint"},
    ],
    "guardrails": {
        "input":  {"safety": True, "pii": {"behavior": PII}},
        "output": {"safety": True, "pii": {"behavior": PII}},
    },
    # fallback_config solo tiene efecto con 2+ served_entities (primary + fallback).
    "fallback_config": {"enabled": use_fallback},
}

body = {"name": GOV_EP, "config": {"served_entities": served}, "ai_gateway": ai_gateway}

# COMMAND ----------
# Crea el endpoint si no existe; si existe, actualiza served_entities y la config de gateway.
# Se usa REST directo (api_client.do) para que la forma del payload sea estable y coincida
# con la documentacion, independiente de la version del SDK.
def _existe(name):
    try:
        w.serving_endpoints.get(name)
        return True
    except Exception:
        return False


if _existe(GOV_EP):
    print(f"Endpoint '{GOV_EP}' ya existe -> actualizando served_entities y AI Gateway...")
    w.api_client.do("PUT", f"/api/2.0/serving-endpoints/{GOV_EP}/config",
                    body={"served_entities": served})
    w.api_client.do("PUT", f"/api/2.0/serving-endpoints/{GOV_EP}/ai-gateway", body=ai_gateway)
else:
    print(f"Creando endpoint gobernado '{GOV_EP}'...")
    w.api_client.do("POST", "/api/2.0/serving-endpoints", body=body)

# COMMAND ----------
import json

final = w.serving_endpoints.get(GOV_EP)
print("Endpoint gobernado listo:", GOV_EP)
print("Proveedor primario:", PROVIDER, "/", MODEL, "| fallback:",
      f"{FB_PROVIDER}/{FB_MODEL}" if use_fallback else "ninguno")
print("Gateway aplicado:\n", json.dumps(ai_gateway, indent=2, ensure_ascii=False))
print("\nSiguiente paso: redesplegar el agente con governed_llm_endpoint =", GOV_EP,
      "(deploy_agent.py enruta el agente por este endpoint y fuerza la gobernanza).")
