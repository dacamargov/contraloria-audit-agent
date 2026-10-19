# Databricks notebook source
# MAGIC %md
# MAGIC # Despliegue desde el Workspace (sin terminal local)
# MAGIC
# MAGIC Este notebook despliega **toda la solución** (jobs de setup/ingesta, agente de
# MAGIC serving, Vector Search, app y grants) ejecutando el mismo `deploy.sh` del repo,
# MAGIC pero **desde dentro de Databricks**, sin necesidad de instalar la CLI en tu máquina.
# MAGIC
# MAGIC ### Requisitos previos (una sola vez)
# MAGIC 1. **Clona el repo como Git Folder**: barra lateral → *Workspace* → `Create` →
# MAGIC    `Git folder` → URL `https://github.com/dacamargov/contraloria-audit-agent`.
# MAGIC 2. **Edita `databricks.yml`** en el workspace (abre el archivo y ajusta lo marcado
# MAGIC    `<-- EDITAR`): `targets.dev.workspace.host`, `catalog`, `schema`, `warehouse_id`
# MAGIC    y, si aplica, `governed_llm_endpoints`.
# MAGIC 3. **Sube los PDFs insumo** al volumen `informes` (Catalog Explorer → Volume → Upload).
# MAGIC 4. **Adjunta este notebook a un cluster** (o usa serverless con `%sh` habilitado) y
# MAGIC    ejecútalo **de arriba hacia abajo**.
# MAGIC
# MAGIC > La autenticación es automática: se usa el **token de contexto del propio notebook**,
# MAGIC > así no necesitas `databricks auth login` ni PATs manuales. El token hereda tus
# MAGIC > permisos, así que debes tener permisos para crear jobs, endpoints, VS y la app.

# COMMAND ----------
# MAGIC %md
# MAGIC ## Parámetros

# COMMAND ----------
dbutils.widgets.text("target", "dev", "Target del bundle (databricks.yml)")
dbutils.widgets.text("repo_root", "", "Ruta de la Git Folder (vacío = autodetectar)")
TARGET = dbutils.widgets.get("target").strip() or "dev"

# COMMAND ----------
# MAGIC %md
# MAGIC ## 1. Autenticación + localización del repo
# MAGIC Escribe un perfil `DEFAULT` en `~/.databrickscfg` con el host y el token del contexto
# MAGIC del notebook, y detecta la raíz del repo (la carpeta que contiene `deploy.sh`).

# COMMAND ----------
import os

ctx = dbutils.notebook.entry_point.getDbutils().notebook().getContext()
host = "https://" + spark.conf.get("spark.databricks.workspaceUrl")
token = ctx.apiToken().get()

# Perfil DEFAULT para que deploy.sh (que recibe un perfil) funcione sin login interactivo.
cfg_path = os.path.expanduser("~/.databrickscfg")
with open(cfg_path, "w") as f:
    f.write(f"[DEFAULT]\nhost = {host}\ntoken = {token}\n")
os.chmod(cfg_path, 0o600)

# Detecta la raíz del repo: por defecto, el padre de la carpeta 'notebooks/' donde vive
# este notebook. Se puede sobre-escribir con el widget 'repo_root'.
repo_root = dbutils.widgets.get("repo_root").strip()
if not repo_root:
    nb_fs = "/Workspace" + ctx.notebookPath().get()           # ruta FUSE del notebook
    repo_root = os.path.dirname(os.path.dirname(nb_fs))        # sube de notebooks/ a la raíz

assert os.path.exists(os.path.join(repo_root, "deploy.sh")), (
    f"No encuentro deploy.sh en {repo_root!r}. Ajusta el widget 'repo_root' a la ruta de la "
    f"Git Folder (p.ej. /Workspace/Repos/<usuario>/contraloria-audit-agent)."
)

# Deja las variables disponibles para las celdas %sh (que no heredan el entorno de Python).
with open("/tmp/deploy_env.sh", "w") as f:
    f.write(f'export REPO_ROOT="{repo_root}"\n')
    f.write(f'export TARGET="{TARGET}"\n')

print("host      :", host)
print("perfil    : DEFAULT ->", cfg_path)
print("repo_root :", repo_root)
print("target    :", TARGET)

# COMMAND ----------
# MAGIC %md
# MAGIC ## 2. Instalar la Databricks CLI (binario Go) en el cluster

# COMMAND ----------
# MAGIC %sh
# MAGIC set -e
# MAGIC curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
# MAGIC echo "---"
# MAGIC databricks version

# COMMAND ----------
# MAGIC %md
# MAGIC ## 3. Validar el bundle
# MAGIC Comprueba que `databricks.yml` resuelve bien (host, catalog, schema, warehouse_id, LLMs).

# COMMAND ----------
# MAGIC %sh
# MAGIC set -e
# MAGIC source /tmp/deploy_env.sh
# MAGIC cd "$REPO_ROOT"
# MAGIC databricks bundle validate -t "$TARGET" -p DEFAULT

# COMMAND ----------
# MAGIC %md
# MAGIC ## 4. Desplegar todo (reutiliza `deploy.sh`)
# MAGIC Esto ejecuta, en orden: sync de `app.yaml`, `bundle deploy`, `setup`, `ingest`,
# MAGIC `deploy_agent`, publicación de la **app** y los **grants** al service principal de la app.
# MAGIC Puede tardar varios minutos (sobre todo la ingesta y el Vector Search).

# COMMAND ----------
# MAGIC %sh
# MAGIC set -e
# MAGIC source /tmp/deploy_env.sh
# MAGIC cd "$REPO_ROOT"
# MAGIC chmod +x deploy.sh
# MAGIC ./deploy.sh DEFAULT "$TARGET"

# COMMAND ----------
# MAGIC %md
# MAGIC ## 5. Verificación
# MAGIC Al terminar, `deploy.sh` imprime la **URL de la app**. También puedes verificar:
# MAGIC - **Compute → Apps**: la app `contraloria-audit-agent` en estado `RUNNING`.
# MAGIC - **Serving**: el endpoint del agente (`contraloria_audit_agent`) en `READY`.
# MAGIC - **Catalog Explorer**: el índice de Vector Search y las tablas creadas por `setup`.
# MAGIC
# MAGIC Para dar acceso a usuarios finales: **Compute → Apps → (la app) → Permissions → `Can use`**.
