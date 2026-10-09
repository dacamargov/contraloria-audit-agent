# Contraloria · Asistente de Auditoria

Solucion en Databricks para la Contraloria General de la Republica con **dos usos**:

1. **Chat** con los informes de auditoria: Q&A con **citas a documento y pagina**, que
   distingue hallazgos comprobados de lineas a verificar y avisa si no hay evidencia.
   Tambien genera informes conversando en lenguaje natural, reconociendo el sujeto por
   **sigla o nombre completo**, con o sin **tema/enfoque**, para uno o varios sujetos
   (ej: "Genera un informe de la CAR 2024 y 2025" o "informe de la DIAN enfocado en
   cobro coactivo y aduanas"). Para varios sujetos, analiza cada uno y compara riesgos/patrones.
   Cada informe reune: antecedentes, hallazgos relevantes y cuantias fiscales, planes de
   mejoramiento, recurrencias/persistencia entre vigencias, riesgos para la proxima auditoria
   y una conclusion tecnica sustentada.
2. **Informe analitico (PDF)**: mismo contenido en formato CGR **descargable**, con **graficas**;
   acepta sujetos por sigla o nombre y un tema opcional.

Ademas, al **cargar un PDF** al Volume se ingiere e indexa automaticamente.

## Arquitectura

```
PDFs (Volume /informes) --(Auto Loader + file arrival)--> parse por pagina + chunks
   --> tabla doc_chunks --(Vector Search Delta Sync)--> indice auto-actualizado
sectorizacion (tabla + funcion UC)  ----------------------------\
                                                                 v
Agente (Mosaic AI Agent Framework): retrieve_audit_evidence + buscar_sectorizacion
   --> Model Serving (contraloria_audit_agent)
App (Streamlit): Chat | Informe analitico (PDF) | Cargar PDF
```

## Estructura (minima)

```
deploy.sh                 # despliegue completo en un comando
databricks.yml            # bundle: variables + targets  (EDITAR host/catalog/schema/warehouse)
resources/jobs.yml        # jobs: setup, ingest, deploy_agent, generate_report
resources/ai_gateway.yml  # job opt-in: endpoint LLM gobernado por Mosaic AI Gateway
resources/app.yml         # app
src/setup.py              # sectorizacion + tabla chunks + Vector Search (una vez)
src/ingest.py             # PDF -> chunks + sync indice (trigger por archivo)
src/agent.py              # definicion del agente (codigo del modelo)
src/setup_ai_gateway.py   # crea el endpoint LLM gobernado (AI Gateway, opt-in)
src/deploy_agent.py       # registra + despliega el agente (autodetecta LLMs)
src/generate_report.py    # genera el informe analitico en PDF
app/                      # app Streamlit (app.py, app.yaml, requirements.txt)
```

## Prerrequisitos

**En la cuenta / workspace:**
- Unity Catalog habilitado, con un **catalog + schema** para la solucion.
- **SQL Warehouse serverless** (se usa su `warehouse_id`).
- **Vector Search** habilitado (permiso para crear un endpoint).
- **Foundation Model APIs** (pay-per-token) activas: al menos un modelo de **chat** y el
  de embeddings `databricks-gte-large-en`. Los modelos de chat se **autodetectan**; no hay
  que configurarlos a mano (ver "Autodeteccion de LLMs").
- **Databricks Apps** habilitado en el workspace.

**Permisos de quien despliega (rol tipico):**
- `CREATE` sobre el schema (tablas, funcion UC, Volumes) y `USE CATALOG`/`USE SCHEMA`.
- Permiso para **crear serving endpoints** y **registrar modelos en UC** (`CREATE MODEL`).
- Permiso para **crear Vector Search endpoints**, **jobs** y **apps**.
- Para el paso de grants automatico: ser `OWNER`/admin de los securables (catalog/schema/Volumes)
  o tener `MANAGE` sobre ellos.
  (Un workspace admin con permisos de UC sobre el schema cumple todo lo anterior.)

**Local:**
- Databricks CLI autenticada: `databricks auth login --host https://<tu-workspace>`.
- `python3` disponible (lo usa `deploy.sh` para leer valores del bundle).
- PDFs de informes en `/Volumes/<catalog>/<schema>/informes`.

## Como desplegar (un comando)

1. Edita en `databricks.yml` los 4 valores marcados con `<-- EDITAR` (host, catalog, schema, warehouse_id).
2. Ejecuta:

```bash
./deploy.sh <perfil-cli>          # perfil de ~/.databrickscfg
```

El script hace todo en orden: **sincroniza `app/app.yaml`** con las variables del bundle
(catalog/schema/volumenes/agente) -> `bundle deploy` -> `setup` -> `ingest` -> `deploy_agent`
(autodetecta LLMs) -> publica la app -> otorga al service principal de la app acceso a los
Volumes. Al final imprime la URL de la app.

> **Unica fuente de verdad:** solo editas `databricks.yml`. El resto (config del agente
> servido y del app, LLMs) se **deriva/autodetecta** en el despliegue, para que la solucion
> sea reproducible en cualquier cuenta sin tocar codigo.

<details><summary>Alternativa manual (paso a paso)</summary>

```bash
P=<perfil-cli>
databricks bundle deploy      -t dev -p $P    # recursos (jobs + app)
databricks bundle run setup   -t dev -p $P    # sectorizacion + chunks + Vector Search
databricks bundle run ingest  -t dev -p $P    # PDFs -> chunks + indice
databricks bundle run deploy_agent -t dev -p $P   # agente a Model Serving
databricks bundle run contraloria_app -t dev -p $P # publica la app
```

Luego otorga al SP de la app (campo `service_principal_client_id` de
`databricks apps get contraloria-audit-agent -o json`) acceso a los Volumes:

```bash
databricks grants update volume <catalog>.<schema>.informes \
  --json '{"changes":[{"principal":"<app_sp>","add":["READ_VOLUME","WRITE_VOLUME"]}]}'
databricks grants update volume <catalog>.<schema>.informes-analiticos \
  --json '{"changes":[{"principal":"<app_sp>","add":["READ_VOLUME","WRITE_VOLUME"]}]}'
```
</details>

## Autodeteccion de LLMs

Los modelos de chat **cambian segun la cuenta**, asi que no estan fijos:
- **Agente** (`deploy_agent.py`): lista los serving endpoints de chat (`task = llm/v1/chat`) y
  concede acceso a los **recomendados que existan** en la cuenta (`PREFERRED_LLMS`); si no hay
  ninguno de la lista, usa los primeros detectados.
- **App**: el selector de modelo se llena dinamicamente con esos mismos recomendados disponibles
  (con fallback a la lista curada si el SP no puede listar endpoints).

Para cambiar la oferta de modelos, edita `PREFERRED_LLMS` (esta igual en `src/deploy_agent.py`
y en `app/app.py`) y vuelve a correr `deploy.sh` (o `deploy_agent` + republicar la app).

## Usar el agente sin la app

- **AI Playground**: `.../ml/playground` -> selecciona el endpoint `contraloria_audit_agent`.
- **CLI**:
  ```bash
  databricks api post /serving-endpoints/contraloria_audit_agent/invocations -p $P \
    --json '{"input":[{"role":"user","content":"Que hallazgos fiscales tiene la CVC y sus cuantias?"}]}'
  ```

## Gobernanza con Unity Gateway (model services)

Por defecto el agente llama a los **foundation models de sistema** (`databricks-claude-*`). Para
**gobernar** las llamadas al LLM —**usage tracking**, **rate limiting**, **guardrails** (PII +
safety) e **inference tables**, con **fallbacks** entre proveedores— se usan **model services de
Unity Gateway**: objetos de Unity Catalog con nombre de 3 niveles (`catalog.schema.name`) donde la
gobernanza se configura **en la UI de Unity Gateway**. El agente y la app se enrutan por ellos.

> **Por que no en el endpoint del agente:** el endpoint tipo `agent/v1/responses` solo soporta
> *inference tables*. El resto de la gobernanza vive en la capa de chat; los model services la
> aplican de forma centralizada en Unity Catalog y se invocan por el **AI Gateway**
> (`/ai-gateway/mlflow/v1`, API OpenAI-compatible, `model = <nombre UC de 3 niveles>`).

**Como activarlo:**

1. Crea **un model service por cada LLM** que quieras ofrecer, en la UI de Unity Gateway
   (`.../ml/ai-gateway` → Models). Ahi defines destino(s), guardrails, rate limits, usage e
   inference tables. Ejemplo (los de esta solucion):
   - `dacamargovws_catalog.contraloria.contraloria_auditoria_opus5`  (Claude Opus 5)
   - `dacamargovws_catalog.contraloria.contraloria_auditoria_genimi_flash`  (Gemini Flash)
2. Listalos en `databricks.yml` (nombres UC completos, separados por coma):
   ```yaml
   governed_llm_endpoints: "catalog.schema.servicio_a, catalog.schema.servicio_b"
   ```
3. Vuelve a desplegar:
   ```bash
   ./deploy.sh <perfil-cli>
   ```

Con esto: la app ofrece **solo** estos modelos (el primero es el default); el agente los usa como
**allowlist** (`CONTRALORIA_ALLOWED_LLMS`) —si la app pide otro, cae al gobernado por defecto, asi
**ningun trafico escapa** a la gobernanza. `deploy_agent` detecta los nombres de 3 niveles y los
declara como recursos **UC Model Service** (`DatabricksUCModelService`).

**Autenticacion al gateway (importante).** Un agente desplegado llama a sus LLM con un **token
*downscoped*** (auth automatica del SP del agente, o incluso OBO). Ese token **no resuelve los model
services del Unity Gateway** (`/ai-gateway/mlflow/v1` responde `404 ... does not exist`), aunque el
SP tenga `EXECUTE`. Por eso el agente usa un **Service Principal dedicado via M2M OAuth**, que
produce un **token de identidad completa** (no *downscoped*) y el gateway si resuelve:

1. Crea un SP y dale `EXECUTE` (+ `USE CATALOG`/`USE SCHEMA`) sobre cada model service:
   ```bash
   databricks service-principals create --display-name contraloria-gw-sp     # -> id, applicationId
   databricks grants update catalog <catalog> --json '{"changes":[{"principal":"<applicationId>","add":["USE_CATALOG"]}]}'
   databricks grants update schema  <catalog>.<schema> --json '{"changes":[{"principal":"<applicationId>","add":["USE_SCHEMA"]}]}'
   databricks api patch /api/2.1/unity-catalog/permissions/model_service/<catalog>.<schema>.<servicio> \
     --json '{"changes":[{"principal":"<applicationId>","add":["EXECUTE"]}]}'
   ```
2. Crea un **secret OAuth** del SP y guardalo en un **secret scope** de Databricks:
   ```bash
   databricks service-principal-secrets-proxy create <sp_id>                  # -> secret (una sola vez)
   databricks secrets create-scope contraloria
   databricks secrets put-secret contraloria gw_sp_client_id --string-value <applicationId>
   databricks secrets put-secret contraloria gw_sp_secret    --string-value <secret>
   ```
   (El creador del endpoint del agente debe tener `READ` sobre el scope; Model Serving sustituye
   `{{secrets/scope/key}}` en tiempo de ejecucion.)
3. `deploy_agent` inyecta estas credenciales como env vars (`CONTRALORIA_GW_CLIENT_ID` /
   `CONTRALORIA_GW_CLIENT_SECRET`, por defecto desde el scope `contraloria`) y la URL publica del
   workspace (`CONTRALORIA_WORKSPACE_HOST`). El agente construye
   `WorkspaceClient(host=<publico>, client_id=..., client_secret=...)` y lo pasa a
   `ChatDatabricks(model=<nombre UC>, use_ai_gateway=True, workspace_client=...)`.

> El scope/llaves del secret son configurables con los widgets `gw_secret_scope`,
> `gw_client_id_key`, `gw_client_secret_key` del job `deploy_agent` (defaults: `contraloria`,
> `gw_sp_client_id`, `gw_sp_secret`).

- `deploy_agent` **fija `databricks-openai`** en los `pip_requirements` para asegurar ruteo al
  gateway (`/ai-gateway/mlflow/v1`) en el entorno servido.
- La generacion de informes (`generate_report.py`) tambien enruta por el gateway cuando el modelo
  es un nombre de 3 niveles; corre bajo la identidad del job (`run_as`), que debe tener `EXECUTE`
  sobre los model services.

**Mientras `governed_llm_endpoints` este vacio, todo sigue igual** (one-click con los FM de sistema).

<details><summary>Alternativa legacy: endpoint External Model propio</summary>

Si tu workspace no usa Unity Gateway model services, puedes crear un endpoint **External Model**
clasico gobernado por Mosaic AI Gateway con el helper `setup_ai_gateway`:

1. Guarda la API key del proveedor como secreto: `databricks secrets put-secret contraloria anthropic_api_key`.
2. En `databricks.yml`: `create_llm_endpoint: gov-claude-opus`, `ext_provider`, `ext_model`
   (opcional fallback + `rate_limit_calls` + `pii_behavior`).
3. `databricks bundle run setup_ai_gateway -t dev -p <perfil>` (uno por modelo), luego agrega los
   nombres a `governed_llm_endpoints` (nombres planos, sin puntos) y redesplega.
</details>

## Notas

- Embeddings: `databricks-gte-large-en`. Si `governed_llm_endpoints` esta definido, el agente y la
  app usan esos **model services de Unity Gateway** (el primero es el default). Si esta vacio, el
  LLM por defecto es `databricks-claude-opus-4-7` (configurable) y los modelos de chat se autodetectan.
- El indice es Delta Sync: los PDFs nuevos quedan disponibles sin reindexar a mano.
- Los prompts (agente e informe) exigen citar la fuente y separar comprobado vs. a verificar.
- **Deduplicacion por contenido**: la ingesta calcula un hash MD5 del PDF; si sube el **mismo
  contenido con otro nombre**, se omite (`[SKIP] ... contenido duplicado`) y no genera chunks
  repetidos. Documentos previos a esta funcion se rellenan (backfill) en la primera corrida de
  `ingest`. Nota: un PDF **distinto** con el mismo nombre si se reprocesa (Auto Loader).
- **Versiones de librerias fijadas**: `app/requirements.txt` y los `%pip install` de los
  notebooks usan rangos con tope de version mayor (p. ej. `markdown2>=2.4,<3`). Esto permite
  parches de seguridad pero **bloquea** una release mayor que rompa la app. Si una libreria se
  deprecia, se ajusta el rango en un solo lugar y se vuelve a desplegar; el entorno del modelo
  servido queda ademas congelado por MLflow al momento de registrar el agente.
- **Reproducibilidad del agente**: `deploy_agent` inyecta el catalog/schema/LLM de la cuenta
  como variables de entorno del endpoint, de modo que el mismo `agent.py` sirve correctamente
  en cualquier workspace (no depende de los valores por defecto del codigo).
- **Endpoint de una sola version**: tras cada despliegue del agente se **eliminan las versiones
  servidas anteriores**, dejando solo la ultima. Evita que se acumulen versiones (una version
  vieja incompatible podria bloquear las actualizaciones del endpoint).
