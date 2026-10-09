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

## Gobernanza con Mosaic AI Gateway (opt-in)

Por defecto el agente llama a los **foundation models de sistema** (`databricks-claude-*`), que
son gestionados por Databricks y no se pueden gobernar a nivel de usuario. Para aplicar
**gobernanza completa** sobre las llamadas al LLM —**usage tracking**, **rate limiting** global
por endpoint, **guardrails** (deteccion de PII + safety en entrada y salida) y **fallbacks**— se
usa un **endpoint External Model propio** gobernado por Mosaic AI Gateway, y se **enruta el
agente por el**.

> **Por que no en el endpoint del agente:** el endpoint tipo `agent/v1/responses` solo soporta
> *inference tables* (ya activas). Rate limits, usage tracking y guardrails solo existen en la
> **capa de chat** (`llm/v1/chat`), de ahi el endpoint External Model dedicado.

**Activarlo (3 pasos):**

1. Guarda la API key del proveedor como **secreto** (una vez):
   ```bash
   databricks secrets create-scope contraloria
   databricks secrets put-secret contraloria anthropic_api_key   # pega la API key
   # opcional, para fallback:  databricks secrets put-secret contraloria openai_api_key
   ```
2. En `databricks.yml` define las variables de gateway (el resto tiene defaults):
   ```yaml
   governed_llm_endpoint: contraloria_llm_gov   # nombre del endpoint gobernado a crear
   ext_provider: anthropic                      # anthropic | openai | cohere
   ext_model: claude-opus-4-20250514            # id del modelo del proveedor
   # opcional (fallback):
   ext_fallback_provider: openai
   ext_fallback_model: gpt-4o
   # opcional: rate_limit_calls: "120"  (llamadas/min, global)   pii_behavior: BLOCK
   ```
3. Vuelve a desplegar:
   ```bash
   ./deploy.sh <perfil-cli>
   ```
   El script, al ver `governed_llm_endpoint` definido, ejecuta `setup_ai_gateway` (crea/actualiza
   el endpoint gobernado con todo el AI Gateway) **antes** de `deploy_agent`, que entonces enruta
   **todo** el trafico del agente por ese endpoint y **fuerza** la gobernanza (ignora el modelo
   que elija la app: `CONTRALORIA_FORCE_LLM`).

**Mientras `governed_llm_endpoint` este vacio, todo sigue igual** (one-click con los FM de
sistema); el job `setup_ai_gateway` es seguro de correr: si esta deshabilitado o falta el
secreto, termina sin cambios.

> **Nota de este entorno (FE sandbox):** aqui no se pudo validar en vivo porque (a) el endpoint
> del agente no soporta estas funciones por tipo y (b) no se tienen permisos de admin sobre los
> FM de sistema para gobernarlos. La configuracion queda **versionada y lista** para la cuenta
> del cliente, donde se habilita con los 3 pasos de arriba.

## Notas

- Embeddings: `databricks-gte-large-en`. LLM por defecto: `databricks-claude-opus-4-7`
  (configurable en `databricks.yml`); los modelos de chat se autodetectan (ver arriba).
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
