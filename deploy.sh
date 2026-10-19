#!/usr/bin/env bash
#
# Despliegue completo de la solucion en un solo comando.
#
#   ./deploy.sh <perfil-cli> [target]
#
# Ejemplo:  ./deploy.sh mi-perfil dev
#
# Antes de correr:
#   1) Edita SOLO databricks.yml (host del workspace, catalog, schema, warehouse_id).
#      El resto (app.yaml, LLMs) se sincroniza/autodetecta en el despliegue.
#   2) Autentica la CLI:  databricks auth login --host https://<tu-workspace>
#   3) Deja los PDFs de informes en /Volumes/<catalog>/<schema>/informes
#
set -euo pipefail

PROFILE="${1:-}"
TARGET="${2:-dev}"
if [ -z "$PROFILE" ]; then
  echo "Uso: ./deploy.sh <perfil-cli> [target]"; exit 1
fi
FLAGS=(-t "$TARGET" -p "$PROFILE")
APP_NAME="contraloria-audit-agent"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Detecta un interprete de Python 3 que REALMENTE funcione. En Windows el binario suele
# llamarse 'python' (no 'python3') y, ademas, el "App Execution Alias" de la Microsoft Store
# intercepta 'python'/'python3' con un stub que no ejecuta Python (por eso probamos import).
PY=""
for _cand in python3 python py; do
  if command -v "$_cand" >/dev/null 2>&1 && "$_cand" -c 'import sys; assert sys.version_info[0]==3' >/dev/null 2>&1; then
    PY="$_cand"; break
  fi
done
if [ -z "$PY" ]; then
  echo "ERROR: no se encontro un Python 3 funcional en el PATH."
  echo "  - Instala Python 3 desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH')."
  echo "  - En Windows, DESACTIVA los alias de la Microsoft Store:"
  echo "      Configuracion > Aplicaciones > Configuracion avanzada de aplicaciones >"
  echo "      Alias de ejecucion de aplicaciones  ->  apaga 'python.exe' y 'python3.exe'."
  echo "  - Cierra y reabre la terminal y verifica:  python --version"
  exit 1
fi

# Variables resueltas del bundle (unica fuente de verdad: databricks.yml).
CFG_JSON="$(databricks bundle validate "${FLAGS[@]}" -o json)"
read_var() { echo "$CFG_JSON" | "$PY" -c "import sys,json;print(json.load(sys.stdin)['variables']['$1']['value'])"; }
CATALOG="$(read_var catalog)"
SCHEMA="$(read_var schema)"
VOL_INF="$(read_var volume_informes)"
VOL_ANA="$(read_var volume_analiticos)"
AGENT_EP="$(read_var agent_endpoint)"
LLM_EP="$(read_var llm_endpoint)"
GOVERNED_LLMS="$(read_var governed_llm_endpoints)"
CREATE_EP="$(read_var create_llm_endpoint)"

echo "==> 0/6  Sincronizando app/app.yaml con las variables del bundle"
"$PY" - "$HERE/app/app.yaml" "$AGENT_EP" "$CATALOG" "$SCHEMA" "$VOL_INF" "$VOL_ANA" "$LLM_EP" "$GOVERNED_LLMS" <<'PY'
import re, sys
path, agent, cat, sch, vinf, vana, llm, governed = sys.argv[1:9]
gov_list = [x.strip() for x in governed.split(",") if x.strip()]
# Con AI Gateway activo, el modelo por defecto de la app es el primer endpoint gobernado.
default_llm = gov_list[0] if gov_list else llm
gov_val = ",".join(gov_list)
vals = {"AGENT_ENDPOINT": agent, "CONTRALORIA_CATALOG": cat, "CONTRALORIA_SCHEMA": sch,
        "VOL_INFORMES": vinf, "VOL_ANALITICOS": vana, "DEFAULT_LLM": default_llm,
        "GOVERNED_LLMS": gov_val}
s = open(path).read()
for k, v in vals.items():
    repl_v = f'"{v}"' if k == "GOVERNED_LLMS" else v   # GOVERNED_LLMS siempre entre comillas
    # Reemplaza el 'value:' que sigue a '- name: K' (solo si la clave existe).
    s, n = re.subn(rf'(- name: {k}\n\s*value: ).*', lambda m: m.group(1) + repl_v, s)
    if n == 0 and k in ("DEFAULT_LLM", "GOVERNED_LLMS"):  # opcionales: se agregan si faltan
        s = s.rstrip() + f"\n  - name: {k}\n    value: {repl_v}\n"
open(path, "w").write(s)
print("    app.yaml sincronizado")
PY

echo "==> 1/6  Desplegando recursos del bundle (jobs + app)"
databricks bundle deploy "${FLAGS[@]}"

echo "==> 2/6  Setup (sectorizacion + tabla de chunks + Vector Search)"
databricks bundle run setup "${FLAGS[@]}"

echo "==> 3/6  Ingesta inicial de PDFs (parseo + chunks + indexacion)"
databricks bundle run ingest "${FLAGS[@]}"

# Mosaic AI Gateway (opt-in): crea UN endpoint gobernado solo si se define create_llm_endpoint.
# (Si creas los endpoints por tu cuenta, deja create_llm_endpoint vacio y solo llena
#  governed_llm_endpoints con sus nombres; el agente y la app los usaran.)
if [ -n "$CREATE_EP" ]; then
  echo "==> 3.5/6  AI Gateway: creando/actualizando el endpoint LLM gobernado '$CREATE_EP'"
  databricks bundle run setup_ai_gateway "${FLAGS[@]}"
fi

echo "==> 4/6  Desplegando el agente (autodetecta los LLMs disponibles en la cuenta)"
databricks bundle run deploy_agent "${FLAGS[@]}"

echo "==> 5/6  Publicando la app"
databricks bundle run contraloria_app "${FLAGS[@]}"

echo "==> 6/6  Otorgando acceso a los Volumes al service principal de la app"
APP_SP="$(databricks apps get "$APP_NAME" -p "$PROFILE" -o json | "$PY" -c "import sys,json;print(json.load(sys.stdin)['service_principal_client_id'])")"
grant() {  # grant <securable_type> <full_name> <priv1,priv2,...>
  local privs; privs="$("$PY" -c "import sys,json;print(json.dumps(sys.argv[1].split(',')))" "$3")"
  databricks grants update "$1" "$2" -p "$PROFILE" \
    --json "{\"changes\":[{\"principal\":\"$APP_SP\",\"add\":$privs}]}" >/dev/null
}
grant catalog "$CATALOG"                         "USE_CATALOG"
grant schema  "$CATALOG.$SCHEMA"                 "USE_SCHEMA"
grant volume  "$CATALOG.$SCHEMA.$VOL_INF"        "READ_VOLUME,WRITE_VOLUME"
grant volume  "$CATALOG.$SCHEMA.$VOL_ANA"        "READ_VOLUME,WRITE_VOLUME"
echo "    grants de Unity Catalog aplicados al SP $APP_SP"

# CAN_QUERY al SP de la app sobre el endpoint del agente. Va aqui (y no como recurso del bundle)
# porque el endpoint lo crea 'deploy_agent' DESPUES de que el bundle crea la app; asi el orden
# funciona en workspaces nuevos donde el endpoint aun no existia al desplegar.
EP_ID="$(databricks serving-endpoints get "$AGENT_EP" -p "$PROFILE" -o json | "$PY" -c "import sys,json;print(json.load(sys.stdin)['id'])")"
databricks permissions update serving-endpoints "$EP_ID" -p "$PROFILE" \
  --json "{\"access_control_list\":[{\"service_principal_name\":\"$APP_SP\",\"permission_level\":\"CAN_QUERY\"}]}" >/dev/null
echo "    CAN_QUERY otorgado al SP $APP_SP sobre el endpoint '$AGENT_EP'"

echo ""
echo "Listo. App: $(databricks apps get "$APP_NAME" -p "$PROFILE" -o json | "$PY" -c "import sys,json;print(json.load(sys.stdin).get('url',''))")"
