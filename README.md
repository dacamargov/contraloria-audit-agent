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
resources/app.yml         # app
src/setup.py              # sectorizacion + tabla chunks + Vector Search (una vez)
src/ingest.py             # PDF -> chunks + sync indice (trigger por archivo)
src/agent.py              # definicion del agente (codigo del modelo)
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
