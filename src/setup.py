# Databricks notebook source
# MAGIC %md
# MAGIC # Setup (una sola vez)
# MAGIC Crea todo lo estructural: tabla de **sectorizacion** (+ funcion UC), tabla de
# MAGIC **chunks** de documentos, y el **endpoint + indice de Vector Search**.
# MAGIC Es idempotente: se puede re-ejecutar sin romper nada.

# COMMAND ----------
dbutils.widgets.text("catalog", "dacamargovws_catalog")
dbutils.widgets.text("schema", "contraloria")
dbutils.widgets.text("vs_endpoint", "contraloria_vs")
dbutils.widgets.text("embedding_endpoint", "databricks-gte-large-en")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
VS_ENDPOINT = dbutils.widgets.get("vs_endpoint")
EMB = dbutils.widgets.get("embedding_endpoint")

CHUNKS_TBL = f"{CATALOG}.{SCHEMA}.doc_chunks"
INDEX_NAME = f"{CATALOG}.{SCHEMA}.doc_chunks_index"
COLS = ["chunk_id", "documento", "sigla", "sujeto", "sector", "delegada",
        "tipo_auditoria", "vigencia", "pagina", "chunk_index", "texto"]

spark.sql(f"USE CATALOG {CATALOG}")
spark.sql(f"USE SCHEMA {SCHEMA}")

# COMMAND ----------
# MAGIC %md ## 1. Sectorizacion (sujeto -> sector -> delegada) + funcion UC

# COMMAND ----------
from pyspark.sql import Row
from pyspark.sql.types import StructType, StructField, StringType

SECT_TBL = f"{CATALOG}.{SCHEMA}.sectorizacion"
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {SECT_TBL} (
  sujeto STRING, sigla STRING, sector STRING, delegada STRING,
  delegado_titular STRING, nit STRING, observaciones STRING
) COMMENT 'Relaciona sujetos de control con su sector y Contraloria Delegada'
""")

DELEGADA = "Contraloria Delegada para el Medio Ambiente"
TITULAR = "Ada America Millares Escamilla"
seed = [
    ("Corporacion Autonoma Regional de Cundinamarca", "CAR", "Medio Ambiente", DELEGADA, TITULAR, None, "Corporacion Autonoma Regional"),
    ("Corporacion Autonoma Regional del Valle del Cauca", "CVC", "Medio Ambiente", DELEGADA, TITULAR, None, "Corporacion Autonoma Regional"),
    ("Parques Nacionales Naturales de Colombia", "PNNC", "Medio Ambiente", DELEGADA, TITULAR, None, None),
    ("Autoridad Nacional de Licencias Ambientales", "ANLA", "Medio Ambiente", DELEGADA, TITULAR, None, None),
    ("Fondo para la Vida y la Biodiversidad", "FONDO_VIDA", "Medio Ambiente", DELEGADA, TITULAR, None, "Adscrito al MADS"),
    ("Ministerio de Ambiente y Desarrollo Sostenible", "MADS", "Medio Ambiente", DELEGADA, TITULAR, None, "Cabeza del sector"),
]
schema = StructType([StructField(c, StringType(), True) for c in
                     ["sujeto", "sigla", "sector", "delegada", "delegado_titular", "nit", "observaciones"]])
spark.createDataFrame([Row(*r) for r in seed], schema=schema).createOrReplaceTempView("_seed")
spark.sql(f"""
MERGE INTO {SECT_TBL} t USING _seed s ON t.sigla = s.sigla
WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *
""")

spark.sql(f"""
CREATE OR REPLACE FUNCTION {CATALOG}.{SCHEMA}.buscar_sectorizacion(termino STRING)
RETURNS TABLE(sujeto STRING, sigla STRING, sector STRING, delegada STRING, delegado_titular STRING)
COMMENT 'Busca sujetos por sigla, nombre, sector o delegada; util para saber a que sector/delegada pertenece un sujeto y que otros sujetos comparten esa delegada.'
RETURN SELECT sujeto, sigla, sector, delegada, delegado_titular FROM {SECT_TBL}
       WHERE lower(sujeto) LIKE '%'||lower(termino)||'%' OR lower(sigla) LIKE '%'||lower(termino)||'%'
          OR lower(sector) LIKE '%'||lower(termino)||'%' OR lower(delegada) LIKE '%'||lower(termino)||'%'
""")
# EXECUTE para usuarios (el SP del endpoint del agente lo concede 'deploy_agent' via resources)
spark.sql(f"GRANT EXECUTE ON FUNCTION {CATALOG}.{SCHEMA}.buscar_sectorizacion TO `account users`")
display(spark.table(SECT_TBL))

# COMMAND ----------
# MAGIC %md ## 2. Tabla de chunks (vacia; la puebla el job de ingesta)

# COMMAND ----------
spark.sql(f"""
CREATE TABLE IF NOT EXISTS {CHUNKS_TBL} (
  chunk_id STRING, documento STRING, path STRING, content_hash STRING, sigla STRING, sujeto STRING,
  sector STRING, delegada STRING, tipo_auditoria STRING, vigencia STRING,
  pagina INT, chunk_index INT, texto STRING, ingested_at TIMESTAMP
) TBLPROPERTIES (delta.enableChangeDataFeed = true)
COMMENT 'Chunks de informes de auditoria con metadata de pagina para RAG con citas'
""")
# Para despliegues ya existentes: agrega la columna si falta (idempotente).
try:
    spark.sql(f"ALTER TABLE {CHUNKS_TBL} ADD COLUMNS (content_hash STRING)")
except Exception:
    pass  # ya existe

# COMMAND ----------
# MAGIC %md ## 3. Vector Search: endpoint + indice Delta Sync (via databricks-sdk)

# COMMAND ----------
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.vectorsearch import (
    EndpointType, VectorIndexType, DeltaSyncVectorIndexSpecRequest,
    EmbeddingSourceColumn, PipelineType,
)
w = WorkspaceClient()

if VS_ENDPOINT not in [e.name for e in (w.vector_search_endpoints.list_endpoints() or [])]:
    print("Creando endpoint", VS_ENDPOINT)
    w.vector_search_endpoints.create_endpoint_and_wait(name=VS_ENDPOINT, endpoint_type=EndpointType.STANDARD)

try:
    w.vector_search_indexes.get_index(INDEX_NAME)
    print("Indice ya existe:", INDEX_NAME)
except Exception:
    print("Creando indice", INDEX_NAME)
    w.vector_search_indexes.create_index(
        name=INDEX_NAME, endpoint_name=VS_ENDPOINT, primary_key="chunk_id",
        index_type=VectorIndexType.DELTA_SYNC,
        delta_sync_index_spec=DeltaSyncVectorIndexSpecRequest(
            source_table=CHUNKS_TBL, pipeline_type=PipelineType.TRIGGERED,
            embedding_source_columns=[EmbeddingSourceColumn(name="texto", embedding_model_endpoint_name=EMB)],
            columns_to_sync=COLS,
        ),
    )
print("Setup completo. Ahora corre el job 'ingest' para cargar los PDFs.")
