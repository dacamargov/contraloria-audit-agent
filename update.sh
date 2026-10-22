#!/usr/bin/env bash
# ============================================================================
# Actualiza el repo y redespliega TODO con un solo comando.
#
#   ./update.sh <perfil-cli> [target]
#   (ej:  ./update.sh DEFAULT dev )
#
# Hace, de forma segura:
#   1) descarta app/app.yaml (es un archivo GENERADO por deploy.sh; no es tu config),
#      y preserva tus ediciones de databricks.yml (host/catalog/schema/warehouse_id...),
#   2) git pull (trae los ultimos cambios de 'main'),
#   3) ./deploy.sh (idempotente: bundle deploy + setup + ingest + agente + app + grants).
#
# Tu configuracion propia vive en databricks.yml y NO se pierde.
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

if [ "$#" -lt 1 ]; then
  echo "Uso: ./update.sh <perfil-cli> [target]   (ej: ./update.sh DEFAULT dev)"
  exit 1
fi

echo "==> 1/3  Preparando el arbol de trabajo"
# app/app.yaml lo REGENERA deploy.sh desde las variables del bundle -> se descarta sin perder nada.
git restore app/app.yaml 2>/dev/null || git checkout -- app/app.yaml 2>/dev/null || true
# Preserva tus ediciones de databricks.yml mientras se actualiza (se reaplican despues del pull).
STASHED=0
if ! git diff --quiet -- databricks.yml 2>/dev/null; then
  git stash push -q -m "update.sh: databricks.yml" -- databricks.yml && STASHED=1 || true
fi

echo "==> 2/3  Trayendo ultimos cambios (git pull)"
git pull --ff-only

if [ "$STASHED" = "1" ]; then
  echo "       reaplicando tu databricks.yml"
  if ! git stash pop -q; then
    echo "AVISO: hubo un conflicto al reaplicar databricks.yml."
    echo "       Abre databricks.yml, deja TUS valores (host/catalog/schema/warehouse_id),"
    echo "       borra las marcas <<<<<<< ======= >>>>>>> y corre:  ./deploy.sh $*"
    exit 1
  fi
fi

echo "==> 3/3  Redesplegando (deploy.sh)"
./deploy.sh "$@"

echo ""
echo "Actualizacion completa."
