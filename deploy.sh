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

# Variables resueltas del bundle (unica fuente de verdad: databricks.yml).
CFG_JSON="$(databricks bundle validate "${FLAGS[@]}" -o json)"
read_var() { echo "$CFG_JSON" | python3 -c "import sys,json;print(json.load(sys.stdin)['variables']['$1']['value'])"; }
CATALOG="$(read_var catalog)"
SCHEMA="$(read_var schema)"
VOL_INF="$(read_var volume_informes)"
VOL_ANA="$(read_var volume_analiticos)"
AGENT_EP="$(read_var agent_endpoint)"
LLM_EP="$(read_var llm_endpoint)"

echo "==> 0/6  Sincronizando app/app.yaml con las variables del bundle"
python3 - "$HERE/app/app.yaml" "$AGENT_EP" "$CATALOG" "$SCHEMA" "$VOL_INF" "$VOL_ANA" "$LLM_EP" <<'PY'
import re, sys
path, agent, cat, sch, vinf, vana, llm = sys.argv[1:8]
vals = {"AGENT_ENDPOINT": agent, "CONTRALORIA_CATALOG": cat, "CONTRALORIA_SCHEMA": sch,
        "VOL_INFORMES": vinf, "VOL_ANALITICOS": vana, "DEFAULT_LLM": llm}
s = open(path).read()
for k, v in vals.items():
    # Reemplaza el 'value:' que sigue a '- name: K' (solo si la clave existe).
    s, n = re.subn(rf'(- name: {k}\n\s*value: ).*', rf'\g<1>{v}', s)
    if n == 0 and k == "DEFAULT_LLM":  # DEFAULT_LLM es opcional: lo agrega si falta
        s = s.rstrip() + f"\n  - name: DEFAULT_LLM\n    value: {v}\n"
open(path, "w").write(s)
print("    app.yaml sincronizado")
PY

echo "==> 1/6  Desplegando recursos del bundle (jobs + app)"
databricks bundle deploy "${FLAGS[@]}"

echo "==> 2/6  Setup (sectorizacion + tabla de chunks + Vector Search)"
databricks bundle run setup "${FLAGS[@]}"

echo "==> 3/6  Ingesta inicial de PDFs (parseo + chunks + indexacion)"
databricks bundle run ingest "${FLAGS[@]}"

echo "==> 4/6  Desplegando el agente (autodetecta los LLMs disponibles en la cuenta)"
databricks bundle run deploy_agent "${FLAGS[@]}"

echo "==> 5/6  Publicando la app"
databricks bundle run contraloria_app "${FLAGS[@]}"

echo "==> 6/6  Otorgando acceso a los Volumes al service principal de la app"
APP_SP="$(databricks apps get "$APP_NAME" -p "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin)['service_principal_client_id'])")"
grant() {  # grant <securable_type> <full_name> <priv1,priv2,...>
  local privs; privs="$(python3 -c "import sys,json;print(json.dumps(sys.argv[1].split(',')))" "$3")"
  databricks grants update "$1" "$2" -p "$PROFILE" \
    --json "{\"changes\":[{\"principal\":\"$APP_SP\",\"add\":$privs}]}" >/dev/null
}
grant catalog "$CATALOG"                         "USE_CATALOG"
grant schema  "$CATALOG.$SCHEMA"                 "USE_SCHEMA"
grant volume  "$CATALOG.$SCHEMA.$VOL_INF"        "READ_VOLUME,WRITE_VOLUME"
grant volume  "$CATALOG.$SCHEMA.$VOL_ANA"        "READ_VOLUME,WRITE_VOLUME"
echo "    grants aplicados al SP $APP_SP"

echo ""
echo "Listo. App: $(databricks apps get "$APP_NAME" -p "$PROFILE" -o json | python3 -c "import sys,json;print(json.load(sys.stdin).get('url',''))")"
