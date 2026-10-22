# Databricks notebook source
# MAGIC %md
# MAGIC # Ingesta incremental de PDFs
# MAGIC Lee de forma **incremental** los PDFs del Volume (Auto Loader), los parsea
# MAGIC pagina por pagina, los trocea conservando el numero de pagina, escribe en
# MAGIC `doc_chunks` y **sincroniza** el indice de Vector Search.
# MAGIC
# MAGIC Se dispara por **llegada de archivo**: cada PDF nuevo queda indexado solo.

# COMMAND ----------
# MAGIC %pip install "pypdf>=4,<5"
# MAGIC dbutils.library.restartPython()

# COMMAND ----------
dbutils.widgets.text("catalog", "dacamargovws_catalog")
dbutils.widgets.text("schema", "contraloria")
dbutils.widgets.text("volume_informes", "informes")
# Endpoint LLM para la deteccion AUTOMATICA de sigla/sujeto/sector (IA function ai_query) de
# informes de sujetos nuevos que no estan en 'sectorizacion'. Vacio = desactiva la deteccion IA.
dbutils.widgets.text("classify_llm_endpoint", "databricks-claude-opus-4-7")
CATALOG = dbutils.widgets.get("catalog")
SCHEMA = dbutils.widgets.get("schema")
VOL = dbutils.widgets.get("volume_informes")
CLASSIFY_LLM = dbutils.widgets.get("classify_llm_endpoint").strip()

VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOL}"
CHECKPOINT = f"{VOLUME_PATH}/_checkpoints/ingest"
CHUNKS_TBL = f"{CATALOG}.{SCHEMA}.doc_chunks"
INDEX_NAME = f"{CATALOG}.{SCHEMA}.doc_chunks_index"
CHUNK_SIZE, CHUNK_OVERLAP = 1600, 200

# COMMAND ----------
import io, re, hashlib, datetime
from pypdf import PdfReader
from pyspark.sql import Row
from pyspark.sql import functions as F
from pyspark.sql.types import StructType, StructField, StringType, IntegerType, TimestampType

# Esquema EXPLICITO de las filas de chunks. Imprescindible: si un informe trae una sigla que no
# esta en 'sectorizacion' (p.ej. un sujeto nuevo), sigla/sujeto/sector/delegada son None en TODO
# el lote y la inferencia de tipos de Spark falla con CANNOT_DETERMINE_TYPE. Con esquema fijo, esas
# columnas quedan como STRING aunque esten vacias.
_CHUNK_COLS = ["chunk_id", "documento", "path", "content_hash", "pagina", "chunk_index", "texto",
               "ingested_at", "sigla", "sujeto", "sector", "delegada", "tipo_auditoria", "vigencia"]
_CHUNK_SCHEMA = StructType([
    StructField("chunk_id", StringType()), StructField("documento", StringType()),
    StructField("path", StringType()), StructField("content_hash", StringType()),
    StructField("pagina", IntegerType()), StructField("chunk_index", IntegerType()),
    StructField("texto", StringType()), StructField("ingested_at", TimestampType()),
    StructField("sigla", StringType()), StructField("sujeto", StringType()),
    StructField("sector", StringType()), StructField("delegada", StringType()),
    StructField("tipo_auditoria", StringType()), StructField("vigencia", StringType()),
])

# Diccionario de sectorizacion para denormalizar sujeto/sector/delegada en cada chunk
SECT_TBL = f"{CATALOG}.{SCHEMA}.sectorizacion"
SECT = {r["sigla"].upper(): r.asDict() for r in spark.table(SECT_TBL).collect()}
# Las siglas a detectar salen de la tabla de sectorizacion (no hardcoded): al agregar un
# sujeto al seed, sus PDFs quedan auto-clasificados. Se prueba primero la sigla mas larga.
_SIGLAS_ORD = sorted(SECT.keys(), key=len, reverse=True)


def _detectar_sigla(fn: str):
    for s in _SIGLAS_ORD:
        for v in {s, s.replace("_", " ")}:      # admite 'FONDO_VIDA' y 'FONDO VIDA'
            if re.search(rf"(^|[_ ]){re.escape(v)}([_ ]|\.|$)", fn):
                return s
    return None


def metadata(filename: str):
    fn = filename.upper()
    sigla = _detectar_sigla(fn)
    tipo = "Cumplimiento" if "CUMPLIMIENTO" in fn else ("Financiera" if "FINANCIERA" in fn else "No determinado")
    # Quita el id inicial del documento (ej. "202601005_") antes de buscar vigencias
    vig = re.findall(r"20\d{2}", re.sub(r"^\d+[_ ]", "", fn))
    m = SECT.get(sigla, {}) if sigla else {}
    return dict(sigla=sigla, sujeto=m.get("sujeto"), sector=m.get("sector"),
                delegada=m.get("delegada"), tipo_auditoria=tipo,
                vigencia="-".join(sorted(set(vig))) if vig else None)

def chunk(text):
    text = re.sub(r"[ \t]+", " ", text or "").strip()
    out, start = [], 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        out.append(text[start:end])
        if end == len(text):
            break
        start = end - CHUNK_OVERLAP
    return out

def process_pdf(path, content, content_hash):
    fn, recs = path.split("/")[-1], []
    meta = metadata(fn)
    try:
        reader = PdfReader(io.BytesIO(content))
    except Exception as e:
        print("[WARN] no se pudo leer", fn, e); return recs
    for pageno, page in enumerate(reader.pages, start=1):
        try:
            ptext = page.extract_text() or ""
        except Exception:
            ptext = ""
        for ci, ch in enumerate(chunk(ptext)):
            cid = hashlib.md5(f"{fn}|{pageno}|{ci}".encode()).hexdigest()
            # Tupla posicional en el orden EXACTO de _CHUNK_SCHEMA (evita inferencia de tipos).
            recs.append((cid, fn, path, content_hash, pageno, ci, ch, datetime.datetime.now(),
                         meta.get("sigla"), meta.get("sujeto"), meta.get("sector"),
                         meta.get("delegada"), meta.get("tipo_auditoria"), meta.get("vigencia")))
    return recs

def upsert(batch_df, _):
    # Dedup por CONTENIDO: si un PDF con el mismo hash ya existe bajo OTRO nombre, se omite
    # (evita duplicar el mismo informe subido con distinto nombre de archivo).
    try:
        existing = {r["content_hash"]: r["documento"] for r in spark.sql(
            f"SELECT DISTINCT content_hash, documento FROM {CHUNKS_TBL} "
            f"WHERE content_hash IS NOT NULL").collect()}
    except Exception:
        existing = {}
    recs = []
    for r in batch_df.select("path", "content").collect():
        content = bytes(r["content"])
        chash = hashlib.md5(content).hexdigest()
        fn = r["path"].split("/")[-1]
        if chash in existing and existing[chash] != fn:
            print(f"[SKIP] {fn}: contenido duplicado de '{existing[chash]}', se omite")
            continue
        recs += process_pdf(r["path"], content, chash)
    if not recs:
        return
    spark.createDataFrame(recs, schema=_CHUNK_SCHEMA).createOrReplaceTempView("_new")
    spark.sql(f"MERGE INTO {CHUNKS_TBL} t USING _new s ON t.chunk_id=s.chunk_id "
              f"WHEN MATCHED THEN UPDATE SET * WHEN NOT MATCHED THEN INSERT *")
    print(f"{len(recs)} chunks upsertados")

# COMMAND ----------
# Backfill: calcula content_hash para documentos ingeridos ANTES de habilitar el dedup
# por contenido (quedaron con hash NULL). Asi tambien participan en la deteccion de duplicados.
# Tras la primera corrida no quedan filas NULL, por lo que este paso es un no-op barato.
_missing = [r["path"] for r in spark.sql(
    f"SELECT DISTINCT path FROM {CHUNKS_TBL} WHERE content_hash IS NULL").collect()]
if _missing:
    _bf = []
    for _p in _missing:
        try:
            _b = spark.read.format("binaryFile").load(_p).select("content").collect()[0]["content"]
            _bf.append(Row(path=_p, chash=hashlib.md5(bytes(_b)).hexdigest()))
        except Exception as e:
            print("[WARN] backfill hash", _p, e)
    if _bf:
        spark.createDataFrame(_bf).createOrReplaceTempView("_bf")
        spark.sql(f"MERGE INTO {CHUNKS_TBL} t USING _bf s ON t.path=s.path "
                  f"WHEN MATCHED THEN UPDATE SET t.content_hash=s.chash")
        print(f"Backfill content_hash: {len(_bf)} documentos")

# COMMAND ----------
(spark.readStream.format("cloudFiles")
    .option("cloudFiles.format", "binaryFile").option("pathGlobFilter", "*.pdf")
    .load(VOLUME_PATH)
    .writeStream.foreachBatch(upsert)
    .option("checkpointLocation", CHECKPOINT)
    .trigger(availableNow=True).start().awaitTermination())

# COMMAND ----------
# Reclasificacion AUTOSANADORA: un documento ingerido ANTES de que su sigla estuviera en
# 'sectorizacion' quedo con sigla/sujeto/sector/delegada en NULL (y por tanto INVISIBLE para el
# job de informes, que filtra la recuperacion por sigla). Al correr de nuevo -ya con la sigla en
# el seed- se re-detecta desde el nombre de archivo y se completan esas columnas. Idempotente.
_null_docs = [r["documento"] for r in spark.sql(
    f"SELECT DISTINCT documento FROM {CHUNKS_TBL} WHERE sigla IS NULL").collect()]
_fix = []
for _doc in _null_docs:
    _m = metadata(_doc)
    if _m.get("sigla"):
        _fix.append(Row(documento=_doc, sigla=_m["sigla"], sujeto=_m.get("sujeto"),
                        sector=_m.get("sector"), delegada=_m.get("delegada")))
if _fix:
    spark.createDataFrame(_fix).createOrReplaceTempView("_fix")
    spark.sql(f"MERGE INTO {CHUNKS_TBL} t USING _fix s ON t.documento=s.documento "
              f"WHEN MATCHED THEN UPDATE SET t.sigla=s.sigla, t.sujeto=s.sujeto, "
              f"t.sector=s.sector, t.delegada=s.delegada")
    print(f"Reclasificados {len(_fix)} documentos:", [(f['documento'], f['sigla']) for f in _fix])
else:
    print("Reclasificacion: no hay documentos con sigla NULL por completar")

# COMMAND ----------
# DETECCION AUTOMATICA CON IA (ai_query): para los documentos cuya sigla NO se pudo resolver por
# nombre contra 'sectorizacion' (sujeto nuevo), una IA infiere sigla/sujeto/sector/delegada a
# partir del nombre de archivo + una muestra del texto. Luego: (1) hace APPEND de las siglas
# nuevas a 'sectorizacion' (sin pisar filas curadas existentes) y (2) clasifica los chunks de
# esos documentos. Asi, un informe de un sujeto nuevo queda integrado sin intervencion manual.
# Resiliente: si la IA falla, los chunks quedan con sigla NULL (recuperables en una corrida futura).
import json as _json, re as _re

_still_null = [r["documento"] for r in spark.sql(
    f"SELECT DISTINCT documento FROM {CHUNKS_TBL} WHERE sigla IS NULL").collect()]

if _still_null and CLASSIFY_LLM:
    from pyspark.sql.functions import expr, lit, concat, col
    # Muestra de texto (primeras 2 paginas) por documento, para dar contexto al modelo.
    spark.sql(f"""
        CREATE OR REPLACE TEMP VIEW _toclass AS
        SELECT documento, substring(concat_ws(' ', collect_list(texto)), 1, 2500) AS muestra
        FROM (SELECT documento, texto FROM {CHUNKS_TBL}
              WHERE sigla IS NULL AND pagina <= 2)
        GROUP BY documento
    """)
    _INSTR = (
        "Eres un clasificador de sujetos de control fiscal de la Contraloria General de la "
        "Republica de Colombia. A partir del NOMBRE DE ARCHIVO y una MUESTRA del informe, "
        "identifica el sujeto auditado y responde UNICAMENTE un objeto JSON (sin texto adicional "
        "ni markdown) con las claves exactas: "
        '{"sigla": "sigla oficial en MAYUSCULAS, p.ej. DIAN, CAR, CVC", '
        '"sujeto": "nombre completo oficial de la entidad", '
        '"sector": "sector tematico, p.ej. Impuestos, Medio Ambiente, Salud, Minas y Energia, '
        'Infraestructura", '
        '"delegada": "Contraloria Delegada responsable si la conoces con certeza, si no null"}. '
        "No inventes: si un campo no es determinable con seguridad usa null (sigla y sujeto son "
        "obligatorios). Si no logras identificar el sujeto, responde {\"sigla\": null}."
    )
    _rows = (spark.table("_toclass")
             .withColumn("_prompt", concat(
                 lit(_INSTR + "\n\nNOMBRE DE ARCHIVO: "), col("documento"),
                 lit("\n\nMUESTRA:\n"), col("muestra")))
             .withColumn("_out", expr(f"ai_query('{CLASSIFY_LLM}', _prompt)"))
             .select("documento", "_out").collect())

    _new_sect, _doc_sigla = {}, {}
    for _r in _rows:
        try:
            _mm = _re.search(r"\{.*\}", _r["_out"] or "", _re.DOTALL)
            _d = _json.loads(_mm.group(0)) if _mm else {}
        except Exception:
            _d = {}
        _sig = (_d.get("sigla") or "").strip().upper().replace(" ", "_")
        _suj = (_d.get("sujeto") or "").strip()
        if not _sig or not _suj:
            print("[IA] no se pudo clasificar:", _r["documento"]); continue
        _doc_sigla[_r["documento"]] = _sig
        _new_sect.setdefault(_sig, dict(sujeto=_suj, sector=(_d.get("sector") or None),
                                        delegada=(_d.get("delegada") or None)))

    # (1) APPEND de siglas NUEVAS a sectorizacion (WHEN NOT MATCHED -> nunca pisa filas curadas).
    if _new_sect:
        _seed = [Row(sujeto=v["sujeto"], sigla=k, sector=v["sector"], delegada=v["delegada"],
                     delegado_titular=None, nit=None, observaciones="Clasificado por IA en ingesta")
                 for k, v in _new_sect.items()]
        _sch = StructType([StructField(c, StringType(), True) for c in
                           ["sujeto", "sigla", "sector", "delegada", "delegado_titular", "nit", "observaciones"]])
        spark.createDataFrame(_seed, schema=_sch).createOrReplaceTempView("_ai_sect")
        spark.sql(f"""
            MERGE INTO {SECT_TBL} t USING _ai_sect s ON t.sigla = s.sigla
            WHEN NOT MATCHED THEN INSERT *
        """)
        print("[IA] siglas agregadas/confirmadas en sectorizacion:", sorted(_new_sect))

    # (2) Clasifica los chunks: asigna la sigla detectada y toma sujeto/sector/delegada de la
    #     sectorizacion (asi, si la sigla ya existia curada, ganan los valores curados).
    if _doc_sigla:
        _map = [Row(documento=d, sigla=s) for d, s in _doc_sigla.items()]
        spark.createDataFrame(_map).createOrReplaceTempView("_docmap")
        spark.sql(f"""
            MERGE INTO {CHUNKS_TBL} t USING (
                SELECT m.documento, m.sigla, x.sujeto, x.sector, x.delegada
                FROM _docmap m JOIN {SECT_TBL} x ON x.sigla = m.sigla) s
            ON t.documento = s.documento
            WHEN MATCHED THEN UPDATE SET
                t.sigla = s.sigla, t.sujeto = s.sujeto, t.sector = s.sector, t.delegada = s.delegada
        """)
        print("[IA] documentos clasificados:", [(d, s) for d, s in _doc_sigla.items()])
elif _still_null:
    print("Deteccion IA desactivada (classify_llm_endpoint vacio); documentos sin sigla:", _still_null)

# COMMAND ----------
# Sincroniza el indice de Vector Search (via databricks-sdk, sin conflictos de deps)
from databricks.sdk import WorkspaceClient
try:
    WorkspaceClient().vector_search_indexes.sync_index(INDEX_NAME)
    print("Sync del indice disparado")
except Exception as e:
    print("Aviso al sincronizar:", e)

display(spark.table(CHUNKS_TBL).groupBy("documento", "sigla", "vigencia")
        .agg(F.count("*").alias("chunks"), F.max("pagina").alias("paginas")).orderBy("documento"))
