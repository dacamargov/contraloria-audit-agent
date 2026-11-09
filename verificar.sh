#!/usr/bin/env bash
#
# Verificacion post-despliegue: confirma que la APP y el AGENTE quedaron desplegados
# y en la ultima version en el workspace del cliente, sin entrar a la UI.
#
#   bash verificar.sh <perfil-cli> [target]
#
# Ejemplo:  bash verificar.sh admin dev
#
set -euo pipefail

PROFILE="${1:-}"
TARGET="${2:-dev}"
if [ -z "$PROFILE" ]; then
  echo "Uso: bash verificar.sh <perfil-cli> [target]"; exit 1
fi
FLAGS=(-t "$TARGET" -p "$PROFILE")
APP_NAME="contraloria-audit-agent"

# Detecta un Python 3 que REALMENTE funcione (igual que deploy.sh: Windows usa 'python'/'py'
# y el alias de la Microsoft Store intercepta 'python'; por eso probamos un import real).
PY=""
for _cand in python3 python py; do
  if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c 'import sys; assert sys.version_info[0]==3' >/dev/null 2>&1; then
    PY="$_cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: no se encontro un Python 3 funcional en el PATH (ver deploy.sh para la ayuda de Windows)."
  exit 1
fi

# Nombre del endpoint del agente desde la unica fuente de verdad (databricks.yml).
CFG_JSON="$(databricks bundle validate "${FLAGS[@]}" -o json)"
AGENT_EP="$(echo "$CFG_JSON" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['variables']['agent_endpoint']['value'])")"

echo "================================================================"
echo " Verificacion post-despliegue   (target: $TARGET)"
echo "================================================================"

echo
echo "== App: $APP_NAME =="
APP_JSON="$(databricks apps get "$APP_NAME" -p "$PROFILE" -o json)" "$PY" - <<'PY'
import os, json
d = json.loads(os.environ["APP_JSON"])
ad = d.get("active_deployment") or {}
print("  estado app     :", (d.get("app_status") or {}).get("state"))
print("  estado compute :", (d.get("compute_status") or {}).get("state"))
print("  deployment     :", ad.get("deployment_id"), "| estado:", (ad.get("status") or {}).get("state"))
print("  actualizado    :", ad.get("update_time") or d.get("update_time"))
print("  URL            :", d.get("url"))
PY

echo
echo "== Agente de serving: $AGENT_EP =="
EP_JSON="$(databricks serving-endpoints get "$AGENT_EP" -p "$PROFILE" -o json)" "$PY" - <<'PY'
import os, json
d = json.loads(os.environ["EP_JSON"])
st = d.get("state") or {}
print("  ready          :", st.get("ready"))
print("  config_update  :", st.get("config_update"))
cfg = d.get("config") or d.get("pending_config") or {}
import re
for e in (cfg.get("served_entities") or cfg.get("served_models") or []):
    name = e.get("name") or ""
    ver = e.get("model_version")
    if not ver:
        m = re.search(r"_(\d+)$", name)
        ver = m.group(1) if m else "?"
    print("  servido        :", name, "| version:", ver)
PY

echo
echo "----------------------------------------------------------------"
echo "OK si:  estado app = RUNNING,  estado compute = ACTIVE,  ready = true,"
echo "        config_update = NOT_UPDATING  y  la fecha de 'actualizado' es de hoy."
echo "Abre la URL de la app para una prueba final (primera consulta puede tardar"
echo "unos minutos si el agente estaba apagado -> arranque en frio)."
echo "----------------------------------------------------------------"
