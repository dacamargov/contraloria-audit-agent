# Guía de instalación paso a paso (ambiente del cliente)

Guía **granular** para desplegar la solución en un workspace de Databricks **desde cero**.
Pensada para seguirse en orden, incluso sin experiencia previa con el Databricks CLI.

> Si solo quieres el resumen de arquitectura y configuración, mira el [`README.md`](README.md).
> La sección de gobernanza (model services / SP) también está detallada ahí.

**Tiempo estimado:** 30–60 min (la mayor parte es espera del despliegue del agente, ~15 min).

---

## 0. Checklist antes de empezar

Reúne estos datos del workspace del cliente (los necesitarás en el paso 6):

| Dato | Dónde se obtiene | Ejemplo |
|------|------------------|---------|
| **URL del workspace** | Barra del navegador al entrar a Databricks | `https://miempresa.cloud.databricks.com` |
| **Catalog** (Unity Catalog) | Catalog Explorer; puede existir o crearlo | `contraloria_catalog` |
| **Schema** | Dentro del catalog | `contraloria` |
| **SQL Warehouse serverless (ID)** | SQL Warehouses → tu warehouse (paso 5) | `61200af9c31dec2e` |

Y confirma los **prerrequisitos del workspace** (paso 5) y los **permisos** de quien despliega
(paso 1 del README → "Prerrequisitos").

---

## 1. Instalar el Databricks CLI (en tu máquina)

> Usa el **Databricks CLI nuevo** (v0.2xx+). El viejo (`pip install databricks-cli`) **no sirve**.

### macOS / Linux
```bash
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
```
(En macOS también: `brew tap databricks/tap && brew install databricks`.)

### Windows (recomendado: Git Bash)
`deploy.sh` es un script **bash**, así que en Windows corre dentro de **Git Bash** (viene con
[Git for Windows](https://git-scm.com/download/win)) o **WSL**. Dentro de Git Bash, instala el CLI
igual que en Linux:
```bash
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
```
(Alternativa en PowerShell: `winget install Databricks.DatabricksCLI`.)

### Verificar
```bash
databricks version
```
Debe imprimir algo como `Databricks CLI v0.2xx.x`. Si dice `0.1x` o "command not found", reinstala
con el método de arriba y abre una terminal nueva.

---

## 2. Instalar las demás herramientas locales

```bash
python --version     # (o python3) lo usa deploy.sh para leer el bundle. 3.9+ está bien.
git --version        # para clonar el repo
bash --version       # macOS/Linux ya lo traen. En Windows: Git Bash o WSL.
```

Si falta Python: instálalo desde [python.org](https://www.python.org/downloads/) o con tu gestor
de paquetes (`brew install python`, `apt install python3`, etc.).

> `deploy.sh` detecta automáticamente el intérprete (`python3`, `python` o `py`), así que funciona
> en macOS/Linux/Windows sin cambios.

### ⚠️ Windows: desactivar el alias de la Microsoft Store
En Windows, al escribir `python` suele aparecer:
*"No se encontró Python; ejecuta sin argumentos para instalar desde Microsoft Store..."*. Es un
**alias de ejecución** que intercepta `python`/`python3` aunque Python ya esté instalado. Desactívalo:

1. **Configuración → Aplicaciones → Configuración avanzada de aplicaciones → Alias de ejecución de
   aplicaciones** → **apaga** `python.exe` y `python3.exe`.
2. Al instalar desde python.org, marca **"Add python.exe to PATH"**.
3. Cierra y reabre Git Bash y verifica: `python --version` debe responder `Python 3.x` (sin abrir la Store).

---

## 3. Autenticar el CLI contra el workspace del cliente

Crea un **perfil** con nombre (lo usarás en cada comando). Reemplaza la URL por la del cliente:

```bash
databricks auth login --host https://<WORKSPACE-DEL-CLIENTE> --profile cliente
```

Se abrirá el navegador para iniciar sesión (OAuth). Al terminar, verifica:

```bash
databricks auth profiles                    # debe listar el perfil 'cliente'
databricks current-user me -p cliente       # debe mostrar tu usuario del cliente
```

> A partir de aquí, **`-p cliente`** (o `--profile cliente`) va en todos los comandos. Si usas otro
> nombre de perfil, cámbialo en todos lados.

---

## 4. Clonar el repositorio

```bash
git clone https://github.com/dacamargov/contraloria-audit-agent.git
cd contraloria-audit-agent
chmod +x deploy.sh          # asegura que el script sea ejecutable
```

---

## 5. Prerrequisitos en el workspace del cliente

Confirma (una sola vez) que el workspace tiene habilitado:

- [ ] **Unity Catalog** (con un metastore asignado al workspace).
- [ ] **SQL Warehouse serverless** encendido. Para obtener su **ID**:
  ```bash
  databricks warehouses list -p cliente
  ```
  Copia el `ID` del warehouse serverless (lo pondrás en `databricks.yml`). También aparece en la UI:
  **SQL → SQL Warehouses →** tu warehouse → el ID está en la URL y en "Overview".
- [ ] **Vector Search** habilitado (permiso para crear un endpoint de Vector Search).
- [ ] **Foundation Model APIs (pay-per-token)** activas: el modelo de embeddings
  `databricks-gte-large-en` y al menos un modelo de **chat**.
- [ ] **Databricks Apps** habilitado.

### 5.1 Crear catalog, schema y volúmenes

El despliegue **no** crea el catalog/schema/volúmenes: créalos tú primero. La forma más simple es
el **editor SQL** de la UI (**SQL → SQL Editor**), ejecutando (ajusta los nombres):

```sql
-- CREATE CATALOG solo si no existe y tienes permiso de metastore:
CREATE CATALOG IF NOT EXISTS contraloria_catalog;
CREATE SCHEMA  IF NOT EXISTS contraloria_catalog.contraloria;

-- Volúmenes (ojo: el segundo lleva guion -> va entre backticks):
CREATE VOLUME IF NOT EXISTS contraloria_catalog.contraloria.informes;
CREATE VOLUME IF NOT EXISTS contraloria_catalog.contraloria.`informes-analiticos`;
```

### 5.2 Subir los PDFs de informes al Volume

**Opción A — UI (simple):** Catalog Explorer → `contraloria_catalog` → `contraloria` → Volumes →
`informes` → botón **Upload**.

**Opción B — CLI:**
```bash
databricks fs cp -r ./ruta/local/con/pdfs \
  dbfs:/Volumes/contraloria_catalog/contraloria/informes/ -p cliente
```

> Puedes subir más PDFs después en cualquier momento: la ingesta es automática (Auto Loader).

---

## 6. Editar `databricks.yml` (ÚNICO archivo que editas)

Abre `databricks.yml` y cambia estos valores (busca los marcados con `<-- EDITAR`):

| Variable | Qué poner |
|----------|-----------|
| `targets.dev.workspace.host` | La URL del workspace del cliente (paso 0) |
| `variables.catalog.default` | Tu catalog (ej. `contraloria_catalog`) |
| `variables.schema.default` | Tu schema (ej. `contraloria`) |
| `variables.warehouse_id.default` | El ID del warehouse serverless (paso 5) |

> **Gobernanza (`governed_llm_endpoints`):** por defecto viene **vacío** (`""`), que usa los
> Foundation Models del sistema (Opción A, portable). Solo cámbialo si vas a gobernar con Unity
> Gateway (Opción B del paso 7), poniendo model services de **tu** catálogo. **Nunca** dejes nombres
> de otro workspace/catálogo: no existirán en el del cliente y el agente fallará.

---

## 7. Elegir el modo de LLM (gobernanza)

### Opción A — FM de sistema (lo más rápido para empezar, y es el valor por defecto)

Deja `governed_llm_endpoints` **vacío** en `databricks.yml` (ya viene así):

```yaml
  governed_llm_endpoints:
    default: ""
```

El agente y la app usarán los **Foundation Models de sistema** (p. ej. `databricks-claude-*`),
autodetectados en la cuenta. **No** necesitas crear SP ni secret. Puedes migrar a la Opción B
después. **Si eliges A, salta al paso 8.**

### Opción B — Unity Gateway model services (recomendado para producción)

Las llamadas al LLM pasan por **model services de Unity Gateway**, con **guardrails, rate limits,
usage tracking e inference tables** centralizados. Requiere 3 cosas:

**7.1 Crear los model services** en la UI (**Machine Learning → AI Gateway → Models**), uno por cada
LLM que quieras ofrecer. Anota sus nombres UC de 3 niveles, p. ej.:
`contraloria_catalog.contraloria.auditoria_opus` y `contraloria_catalog.contraloria.auditoria_gemini`.

Ponlos en `databricks.yml` (separados por coma; el primero será el default de la app):
```yaml
  governed_llm_endpoints:
    default: "contraloria_catalog.contraloria.auditoria_opus,contraloria_catalog.contraloria.auditoria_gemini"
```

**7.2 Crear un Service Principal dedicado y darle acceso a los model services.**
El agente desplegado **no** puede llamar los model services con su token nativo (es *downscoped* y
da `404 does not exist`); por eso usa un SP dedicado con token de identidad completa.

```bash
# Crea el SP y guarda los dos IDs que imprime:
databricks service-principals create --display-name contraloria-gw-sp -p cliente -o json
#   -> "id": 7702...            (SP_ID, numérico)
#   -> "applicationId": "510c..." (APP_ID, el client_id OAuth)
```

Guarda en variables de shell (reemplaza con lo que imprimió):
```bash
APP_ID=<applicationId>
SP_ID=<id-numerico>
CATALOG=contraloria_catalog
SCHEMA=contraloria
```

Concede permisos UC al SP sobre el catalog, schema y **cada** model service:
```bash
databricks grants update catalog "$CATALOG" -p cliente \
  --json "{\"changes\":[{\"principal\":\"$APP_ID\",\"add\":[\"USE_CATALOG\"]}]}"
databricks grants update schema "$CATALOG.$SCHEMA" -p cliente \
  --json "{\"changes\":[{\"principal\":\"$APP_ID\",\"add\":[\"USE_SCHEMA\"]}]}"

# Repite esta por CADA model service (cambia el nombre del servicio):
databricks api patch "/api/2.1/unity-catalog/permissions/model_service/$CATALOG.$SCHEMA.auditoria_opus" \
  -p cliente --json "{\"changes\":[{\"principal\":\"$APP_ID\",\"add\":[\"EXECUTE\"]}]}"
databricks api patch "/api/2.1/unity-catalog/permissions/model_service/$CATALOG.$SCHEMA.auditoria_gemini" \
  -p cliente --json "{\"changes\":[{\"principal\":\"$APP_ID\",\"add\":[\"EXECUTE\"]}]}"
```

**7.3 Crear el secret OAuth del SP y guardarlo en un secret scope** (el agente lo lee en runtime):
```bash
# Genera el secret OAuth del SP (el VALOR solo se muestra UNA vez: cópialo):
databricks service-principal-secrets-proxy create "$SP_ID" -p cliente -o json
#   -> "secret": "dose..."   (CLIENT_SECRET)

CLIENT_SECRET=<secret-que-imprimio>

# Crea el scope y guarda client_id + secret:
databricks secrets create-scope contraloria -p cliente
databricks secrets put-secret contraloria gw_sp_client_id --string-value "$APP_ID"        -p cliente
databricks secrets put-secret contraloria gw_sp_secret     --string-value "$CLIENT_SECRET" -p cliente
```

> El scope se llama `contraloria` por defecto. Si usas otro nombre o llaves distintas, pásalos como
> parámetros del job `deploy_agent` (`gw_secret_scope`, `gw_client_id_key`, `gw_client_secret_key`).
> Quien despliega el agente (crea el endpoint) debe tener `READ` sobre el scope — al crearlo tú,
> ya tienes `MANAGE`.

**7.4 (Opcional) Verifica que el SP puede llamar al gateway** antes de desplegar:
```bash
HOST=https://<WORKSPACE-DEL-CLIENTE>
TOK=$(curl -s -X POST "$HOST/oidc/v1/token" -u "$APP_ID:$CLIENT_SECRET" \
      --data 'grant_type=client_credentials&scope=all-apis' | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -X POST "$HOST/ai-gateway/mlflow/v1/chat/completions" \
  -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  --data "{\"model\":\"$CATALOG.$SCHEMA.auditoria_opus\",\"messages\":[{\"role\":\"user\",\"content\":\"OK\"}],\"max_tokens\":10}"
```
Si responde un JSON con `choices`, el SP está bien configurado.

---

## 8. Desplegar (un comando)

```bash
./deploy.sh cliente
```

Esto hace, en orden: sincroniza `app/app.yaml` ← variables del bundle → `bundle deploy` → `setup`
(sectorización + tabla de chunks + Vector Search) → `ingest` (PDFs → chunks → índice) → `deploy_agent`
(registra y despliega el agente a Model Serving; ~15 min) → publica la **app** → otorga al SP de la
app acceso a los Volumes. **Al final imprime la URL de la app.**

> El despliegue del agente tarda ~15 min (crea una versión del serving endpoint). Es normal.

---

## 9. Verificar que todo quedó bien

```bash
# 9.1 El endpoint del agente debe estar READY:
databricks serving-endpoints get contraloria_audit_agent -p cliente -o json \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print('ready:',d['state']['ready'])"

# 9.2 Probar el agente por CLI:
databricks api post /serving-endpoints/contraloria_audit_agent/invocations -p cliente \
  --json '{"input":[{"role":"user","content":"Que hallazgos fiscales tiene la CVC y sus cuantias?"}]}'

# 9.3 Abrir la app (la URL la imprime deploy.sh; o):
databricks apps get contraloria-audit-agent -p cliente -o json \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['url'])"
```

En la app, el **selector de modelo** debe mostrar solo los model services gobernados (Opción B) o los
FM autodetectados (Opción A). Haz una pregunta y verifica que responde con **citas [documento, p. N]**.

---

## 10. Dar acceso a los usuarios finales a la app

En la UI: **Compute → Apps → `contraloria-audit-agent` → Permissions** → agrega los usuarios/grupos
con **"Can use"**. Esos usuarios podrán abrir la URL de la app.

---

## 11. Operación continua

- **Nuevos informes:** sube más PDFs al Volume `informes` (UI o `databricks fs cp`). Se ingieren e
  indexan solos (Auto Loader + Delta Sync). No hay que reindexar a mano.
- **Cambiar modelos:** edita `governed_llm_endpoints` (o `PREFERRED_LLMS` en modo FM de sistema) y
  vuelve a correr `./deploy.sh cliente`.
- **Rotar el secret del SP (Opción B):** vuelve a correr el paso 7.3 (`service-principal-secrets-proxy
  create` + `put-secret gw_sp_secret`) y redespliega el agente (`databricks bundle run deploy_agent -t dev -p cliente`).

---

## 11.5 Actualizar el repo ya clonado (un solo comando)

Para traer los últimos cambios **y** redesplegar, ejecuta:

```bash
./update.sh <perfil-cli> [target]
# ej:  ./update.sh DEFAULT dev
```

`update.sh` descarta `app/app.yaml` (es un archivo **generado** por `deploy.sh`, no tu config),
preserva tus ediciones de `databricks.yml` (host/catalog/schema/warehouse_id…), hace `git pull` y
vuelve a correr `./deploy.sh` (idempotente). Tu configuración no se pierde.

> En Windows usa **Git Bash**: `bash update.sh DEFAULT dev`.

Si prefieres hacerlo a mano: `git restore app/app.yaml && git pull --ff-only && ./deploy.sh <perfil>`.
Si `git pull` reporta conflicto en `databricks.yml`, deja **tus** valores, borra las marcas
`<<<<<<< ======= >>>>>>>` y corre `./deploy.sh <perfil>`.

---

## 11.6 Alternativa: desplegar desde el Workspace (sin terminal local)

Si no quieres instalar el CLI en tu máquina, usa el notebook
[`notebooks/deploy_desde_workspace.py`](notebooks/deploy_desde_workspace.py):

1. Clona el repo como **Git folder** en el workspace (Workspace → Create → Git folder → URL del repo).
2. Edita `databricks.yml` en el workspace (host/catalog/schema/warehouse_id).
3. Sube los PDFs al Volume `informes`.
4. Abre el notebook, adjúntalo a un cluster y **ejecútalo de arriba a abajo**. Autentica con el token
   de contexto (sin `databricks auth login`), instala el CLI y corre `deploy.sh` desde Git Bash de `%sh`.

---

## 12. Problemas comunes

| Síntoma | Causa / solución |
|---------|------------------|
| `databricks: command not found` o versión `0.1x` | CLI mal instalado. Reinstala con el script del paso 1 y abre terminal nueva. |
| `./deploy.sh: Permission denied` | Falta `chmod +x deploy.sh` (paso 4). O ejecútalo como `bash deploy.sh <perfil>`. |
| *"No se encontró Python... Microsoft Store"* (Windows) | Alias de ejecución de la Store interceptando `python`. Desactívalo (paso 2, sección Windows) y verifica `python --version`. |
| `deploy.sh` corta con "no se encontro un Python 3 funcional" | No hay Python 3 en PATH, o el alias de la Store lo bloquea. Instala desde python.org + desactiva alias (paso 2). |
| `Error: cannot create resources.apps...: Git repository is required for Databricks Apps in this workspace` | El workspace exige desplegar Apps desde Git ("Only allow app deployments from Git"). Pide al admin desactivar esa política, **o** despliega la app desde un Git folder (Compute → Apps → Create app → Configure Git). |
| `deploy_agent` falla con `... .doc_chunks_index does not exist` | Index/catalog mal resueltos. Con el repo actualizado ya se corrige (la validación usa el catálogo real). Asegúrate de tener el último `main` (`git pull`). |
| Agente responde `404 ... 'catalog.schema.x' does not exist` | Opción B mal configurada: el SP no tiene `EXECUTE` sobre el model service, o el secret/scope no coincide, o `CONTRALORIA_WORKSPACE_HOST` no apunta al host público. Revisa el paso 7 y verifica con 7.4. |
| El selector de la app muestra modelos de otro workspace | `governed_llm_endpoints` tiene nombres de otro catálogo. Déjalo vacío (Opción A) o pon model services de **tu** catálogo (paso 6/7). |
| `setup` falla con "Volume not found" / ruta de Volumes | No creaste los volúmenes (paso 5.1) o los nombres no coinciden con `databricks.yml`. |
| Error de permisos al crear tablas/endpoints | Quien despliega necesita `CREATE` en el schema, crear serving endpoints, Vector Search, jobs y apps (ver "Prerrequisitos" del README). |
| En Windows `deploy.sh` no corre | Usa **Git Bash** o **WSL** (es un script bash). |
