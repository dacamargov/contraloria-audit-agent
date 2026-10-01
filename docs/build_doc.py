#!/usr/bin/env python3
"""Genera la documentacion tecnica (PDF) renderizando HTML con Chrome headless."""
import base64
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ESCUDO = os.path.join(HERE, "..", "app", "assets", "escudo_colombia.png")
HTML_OUT = os.path.join(HERE, "documentacion_tecnica.html")
PDF_OUT = os.path.join(HERE, "Documentacion_Tecnica_Contraloria.pdf")

esc_b64 = ""
try:
    with open(ESCUDO, "rb") as f:
        esc_b64 = base64.b64encode(f.read()).decode()
except Exception as e:
    print("escudo no encontrado:", e)

HTML = r"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<style>
@page { size: A4; margin: 16mm 15mm 18mm 15mm; }
* { box-sizing: border-box; }
html { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
body { font-family: 'Helvetica Neue', Arial, sans-serif; color:#20242c; font-size:10.5pt; line-height:1.5; margin:0; }
h1,h2,h3,h4 { color:#7a0f0f; margin:0 0 6px; line-height:1.2; }
h2 { font-size:17pt; border-bottom:2.5px solid #b31b1b; padding-bottom:5px; margin-top:6px; }
h3 { font-size:12.5pt; color:#1F3864; margin-top:16px; }
h4 { font-size:11pt; color:#3a3f4a; margin-top:12px; }
p { margin:6px 0; }
code { font-family:'SF Mono', Menlo, Consolas, monospace; background:#f2f3f5; padding:1px 5px; border-radius:4px; font-size:9pt; color:#b3391b; }
pre { background:#0f1220; color:#e6e8ef; padding:12px 14px; border-radius:8px; font-size:8.6pt;
      line-height:1.45; overflow:hidden; white-space:pre-wrap; word-break:break-word; margin:8px 0; }
pre code { background:none; color:inherit; padding:0; }
table { border-collapse:collapse; width:100%; margin:10px 0; font-size:9pt; }
th { background:#b31b1b; color:#fff; text-align:left; padding:6px 8px; font-weight:600; }
td { border:1px solid #d7dae0; padding:6px 8px; vertical-align:top; }
tr:nth-child(even) td { background:#f7f8fa; }
ul,ol { margin:6px 0 6px 0; padding-left:20px; }
li { margin:3px 0; }
.tag { display:inline-block; background:#eef1f6; color:#1F3864; border:1px solid #cfd6e4;
       border-radius:20px; padding:2px 10px; font-size:8pt; font-weight:600; margin:2px 3px 2px 0; }
.note { background:#fff8e6; border-left:4px solid #E6A700; padding:9px 12px; border-radius:0 6px 6px 0; margin:10px 0; font-size:9.5pt; }
.kv { background:#f7f8fa; border:1px solid #e2e5ea; border-radius:8px; padding:10px 14px; margin:8px 0; }
.page-break { page-break-before: always; }
.small { font-size:8.6pt; color:#5b616b; }
.center { text-align:center; }
.svgwrap { text-align:center; margin:12px 0; }

/* ---- Portada ---- */
.cover { height:265mm; display:flex; flex-direction:column; justify-content:center; align-items:center;
         text-align:center; background:linear-gradient(160deg,#0b1a3a 0%, #12245100 60%), #0a0f1e; color:#fff;
         border-radius:0; margin:-16mm -15mm 0 -15mm; padding:0 24mm; }
.cover .flag { height:8px; width:60%; margin:18px 0 26px; border-radius:6px;
               background:linear-gradient(to right,#FCD116 0 50%,#003893 50% 75%,#CE1126 75% 100%); }
.cover img { height:150px; filter:drop-shadow(0 4px 16px rgba(0,0,0,.5)); margin-bottom:14px; }
.cover h1 { color:#fff; font-size:30pt; margin:6px 0; letter-spacing:.5px; }
.cover .sub { color:#f0c33c; font-size:14pt; font-weight:600; }
.cover .meta { color:#aeb6c4; font-size:10.5pt; margin-top:30px; line-height:1.8; }
.toc a { color:#20242c; text-decoration:none; }
.toc li { margin:5px 0; }
.footerline { color:#8b929e; font-size:8pt; }
</style></head><body>

<!-- ============ PORTADA ============ -->
<div class="cover">
  <img src="data:image/png;base64,__ESCUDO__"/>
  <div class="flag"></div>
  <h1>Asistente de Auditoría</h1>
  <div class="sub">Contraloría General de la República</div>
  <div class="meta">
    Documentación técnica de la solución<br/>
    Arquitectura · Datos · ETL e ingesta · Auto Loader · Vector Search · Agente · Aplicación<br/>
    <span class="small">Plataforma: Databricks (Unity Catalog, Mosaic AI, Model Serving, Apps)</span><br/><br/>
    <span style="color:#f0c33c; font-weight:600; font-size:11pt;">Daniel Vargas — Databricks</span>
  </div>
</div>

<!-- ============ TOC ============ -->
<div class="page-break"></div>
<h2>Contenido</h2>
<ol class="toc">
  <li><a href="#vision">Visión general y objetivos</a></li>
  <li><a href="#arq">Arquitectura de la solución</a></li>
  <li><a href="#datos">Modelo de datos (Unity Catalog)</a></li>
  <li><a href="#etl">ETL e ingesta dinámica (Auto Loader)</a></li>
  <li><a href="#vs">Vector Search (índice Delta Sync)</a></li>
  <li><a href="#agente">Agente de auditoría (Mosaic AI Agent Framework)</a></li>
  <li><a href="#informe">Generación del informe analítico (PDF)</a></li>
  <li><a href="#app">Aplicación (Databricks App / Streamlit)</a></li>
  <li><a href="#deploy">Despliegue (Asset Bundles) y prerrequisitos</a></li>
  <li><a href="#seg">Seguridad, permisos y trazabilidad</a></li>
  <li><a href="#flujo">Flujo de una consulta de extremo a extremo</a></li>
  <li><a href="#apendice">Apéndice: parámetros y archivos</a></li>
</ol>

<!-- ============ 1. VISION ============ -->
<div class="page-break"></div>
<h2 id="vision">1. Visión general y objetivos</h2>
<p>La solución habilita dos usos complementarios sobre los informes de auditoría de la Contraloría,
con foco en <b>planeación y focalización de auditorías</b> del sector Medio Ambiente (extensible a
otros sectores):</p>
<ul>
  <li><b>Chat analítico</b>: preguntas y respuestas sobre los informes, con <b>citas a documento y
      página</b>, que distingue <b>hallazgos comprobados</b> de <b>líneas a verificar</b> y declara
      cuándo <b>no hay evidencia</b> suficiente. También redacta informes conversando en lenguaje
      natural (por sigla o nombre, con o sin tema, para uno o varios sujetos).</li>
  <li><b>Informe analítico (PDF)</b>: el mismo contenido en formato CGR descargable, con gráficas.</li>
</ul>
<p>Además, al <b>cargar un PDF</b> se ingiere e indexa automáticamente, ampliando la base de
conocimiento sin intervención manual.</p>
<div class="kv"><b>Principios de diseño:</b>
  <span class="tag">Citas verificables</span>
  <span class="tag">Comprobado ≠ hipótesis</span>
  <span class="tag">Sin alucinaciones de cifras</span>
  <span class="tag">Ingesta dinámica</span>
  <span class="tag">Réplica en pocos comandos</span>
  <span class="tag">LLMs autodetectados</span>
</div>

<h3>Capacidades que responde</h3>
<table>
  <tr><th>Necesidad del negocio</th><th>Cómo la resuelve</th></tr>
  <tr><td>¿A qué sector/delegada pertenece un sujeto y qué otros sujetos comparten esa delegada?</td>
      <td>Tabla <code>sectorizacion</code> + función UC <code>buscar_sectorizacion</code> (herramienta del agente).</td></tr>
  <tr><td>Informes de auditoría y periodos cubiertos</td>
      <td>Metadata por chunk (<code>documento</code>, <code>vigencia</code>, <code>tipo_auditoria</code>) recuperada vía Vector Search.</td></tr>
  <tr><td>Hallazgos, recurrencias e incidencia fiscal con cuantías</td>
      <td>RAG sobre <code>doc_chunks</code>; el prompt exige cita <code>[documento, p. N]</code> y cuantías exactas.</td></tr>
  <tr><td>Riesgos para la próxima auditoría y qué revisar</td>
      <td>Sección "Líneas a verificar" separada de lo comprobado, con prueba sugerida.</td></tr>
  <tr><td>Comparar varios sujetos</td>
      <td>Análisis por sujeto + sección de riesgos y patrones compartidos.</td></tr>
</table>

<!-- ============ 2. ARQUITECTURA ============ -->
<div class="page-break"></div>
<h2 id="arq">2. Arquitectura de la solución</h2>
<p>Todo se ejecuta dentro del workspace de Databricks del cliente, sobre Unity Catalog. Los datos
nunca salen del perímetro de gobierno del cliente.</p>

<div class="svgwrap">
<svg width="720" height="430" viewBox="0 0 720 430" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial" font-size="11">
  <defs>
    <marker id="ar" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L9,3 L0,6 Z" fill="#5b616b"/>
    </marker>
  </defs>
  <!-- Usuario -->
  <rect x="20" y="185" width="120" height="60" rx="10" fill="#1F3864"/>
  <text x="80" y="210" fill="#fff" text-anchor="middle" font-weight="bold">Equipo auditor</text>
  <text x="80" y="228" fill="#cfd6e4" text-anchor="middle" font-size="9">navegador web</text>
  <!-- App -->
  <rect x="190" y="175" width="140" height="80" rx="10" fill="#b31b1b"/>
  <text x="260" y="200" fill="#fff" text-anchor="middle" font-weight="bold">Databricks App</text>
  <text x="260" y="218" fill="#ffe" text-anchor="middle" font-size="9">Streamlit</text>
  <text x="260" y="234" fill="#ffd" text-anchor="middle" font-size="8.5">Chat · Informe · Cargar PDF</text>
  <!-- Agente serving -->
  <rect x="390" y="60" width="150" height="80" rx="10" fill="#2A7F8E"/>
  <text x="465" y="85" fill="#fff" text-anchor="middle" font-weight="bold">Agente</text>
  <text x="465" y="102" fill="#e8f6f9" text-anchor="middle" font-size="8.5">Model Serving</text>
  <text x="465" y="118" fill="#e8f6f9" text-anchor="middle" font-size="8.5">(Mosaic AI Agent FW)</text>
  <!-- Job report -->
  <rect x="390" y="175" width="150" height="80" rx="10" fill="#4C8C3F"/>
  <text x="465" y="200" fill="#fff" text-anchor="middle" font-weight="bold">Job informe</text>
  <text x="465" y="217" fill="#eafae4" text-anchor="middle" font-size="8.5">genera PDF + gráficas</text>
  <!-- Job ingest -->
  <rect x="390" y="290" width="150" height="80" rx="10" fill="#7B4FA3"/>
  <text x="465" y="315" fill="#fff" text-anchor="middle" font-weight="bold">Job ingesta</text>
  <text x="465" y="332" fill="#f0e8f9" text-anchor="middle" font-size="8.5">Auto Loader (file arrival)</text>
  <!-- LLM -->
  <rect x="590" y="60" width="110" height="80" rx="10" fill="#E6A700"/>
  <text x="645" y="90" fill="#3a2b00" text-anchor="middle" font-weight="bold">Foundation</text>
  <text x="645" y="107" fill="#3a2b00" text-anchor="middle" font-weight="bold">Models</text>
  <text x="645" y="124" fill="#5a4400" text-anchor="middle" font-size="8.5">LLMs de chat</text>
  <!-- Vector Search -->
  <rect x="590" y="175" width="110" height="80" rx="10" fill="#1F4E96"/>
  <text x="645" y="205" fill="#fff" text-anchor="middle" font-weight="bold">Vector</text>
  <text x="645" y="222" fill="#fff" text-anchor="middle" font-weight="bold">Search</text>
  <text x="645" y="239" fill="#d5e0f2" text-anchor="middle" font-size="8.5">índice Delta Sync</text>
  <!-- UC data -->
  <rect x="560" y="290" width="140" height="80" rx="10" fill="#334155"/>
  <text x="630" y="312" fill="#fff" text-anchor="middle" font-weight="bold">Unity Catalog</text>
  <text x="630" y="329" fill="#cbd5e1" text-anchor="middle" font-size="8.5">Volumes + tablas Delta</text>
  <text x="630" y="345" fill="#cbd5e1" text-anchor="middle" font-size="8.5">doc_chunks · sectorización</text>
  <!-- arrows -->
  <line x1="140" y1="215" x2="188" y2="215" stroke="#5b616b" stroke-width="2" marker-end="url(#ar)"/>
  <line x1="330" y1="205" x2="388" y2="120" stroke="#5b616b" stroke-width="2" marker-end="url(#ar)"/>
  <line x1="330" y1="215" x2="388" y2="212" stroke="#5b616b" stroke-width="2" marker-end="url(#ar)"/>
  <line x1="540" y1="100" x2="588" y2="100" stroke="#5b616b" stroke-width="2" marker-end="url(#ar)"/>
  <line x1="540" y1="115" x2="588" y2="200" stroke="#5b616b" stroke-width="2" marker-end="url(#ar)"/>
  <line x1="540" y1="215" x2="588" y2="215" stroke="#5b616b" stroke-width="2" marker-end="url(#ar)"/>
  <line x1="540" y1="330" x2="558" y2="330" stroke="#5b616b" stroke-width="2" marker-end="url(#ar)"/>
  <line x1="645" y1="255" x2="645" y2="288" stroke="#5b616b" stroke-width="2" marker-end="url(#ar)"/>
  <text x="360" y="150" fill="#5b616b" font-size="8.5" text-anchor="middle">consulta</text>
</svg>
</div>

<h3>Componentes</h3>
<table>
  <tr><th>Capa</th><th>Servicio Databricks</th><th>Rol</th></tr>
  <tr><td>Presentación</td><td>Databricks Apps (Streamlit)</td><td>Chat, generación de informes, carga de PDFs.</td></tr>
  <tr><td>Razonamiento</td><td>Model Serving + Mosaic AI Agent Framework</td><td>Agente con herramientas (RAG + función UC).</td></tr>
  <tr><td>Modelos</td><td>Foundation Model APIs</td><td>LLMs de chat (autodetectados) y embeddings.</td></tr>
  <tr><td>Recuperación</td><td>Mosaic AI Vector Search</td><td>Índice Delta Sync sobre <code>doc_chunks</code>.</td></tr>
  <tr><td>Procesamiento</td><td>Lakeflow Jobs + Spark (Auto Loader)</td><td>Ingesta incremental, generación de informe.</td></tr>
  <tr><td>Datos y gobierno</td><td>Unity Catalog (Volumes, tablas Delta, funciones)</td><td>Almacenamiento gobernado y permisos.</td></tr>
</table>

<!-- ============ 3. DATOS ============ -->
<div class="page-break"></div>
<h2 id="datos">3. Modelo de datos (Unity Catalog)</h2>
<p>Todo vive bajo un <code>catalog.schema</code> configurable (por defecto
<code>&lt;catalog&gt;.contraloria</code>). Objetos:</p>

<h3>3.1 Volumes (almacenamiento de archivos)</h3>
<table>
  <tr><th>Volume</th><th>Contenido</th><th>Uso</th></tr>
  <tr><td><code>informes</code></td><td>PDFs fuente de auditoría (insumo)</td><td>Origen del Auto Loader; destino de "Cargar PDF".</td></tr>
  <tr><td><code>informes-analiticos</code></td><td>PDFs generados por el sistema</td><td>Salida del job de informe; descarga desde la app.</td></tr>
</table>
<p class="small">El Auto Loader mantiene su estado en <code>informes/_checkpoints/ingest</code>.</p>

<h3>3.2 Tabla <code>sectorizacion</code> + función UC</h3>
<p>Relaciona cada sujeto de control con su <b>sigla</b>, <b>sector</b> y <b>Contraloría Delegada</b>.
Se consulta mediante una función de Unity Catalog que el agente invoca como herramienta.</p>
<table>
  <tr><th>Columna</th><th>Descripción</th></tr>
  <tr><td><code>sujeto</code></td><td>Nombre completo del sujeto de control</td></tr>
  <tr><td><code>sigla</code></td><td>Sigla (CAR, CVC, PNNC, ANLA, FONDO_VIDA, MADS)</td></tr>
  <tr><td><code>sector</code> / <code>delegada</code></td><td>Sector y Contraloría Delegada</td></tr>
  <tr><td><code>delegado_titular</code>, <code>nit</code>, <code>observaciones</code></td><td>Metadatos adicionales</td></tr>
</table>
<pre><code>CREATE OR REPLACE FUNCTION buscar_sectorizacion(termino STRING)
RETURNS TABLE(sujeto, sigla, sector, delegada, delegado_titular)
RETURN SELECT ... FROM sectorizacion
       WHERE lower(sujeto) LIKE '%'||lower(termino)||'%'
          OR lower(sigla)  LIKE '%'||lower(termino)||'%'
          OR lower(sector) LIKE '%'||lower(termino)||'%'
          OR lower(delegada) LIKE '%'||lower(termino)||'%';</code></pre>
<p class="small">La carga inicial (seed) se hace con un <code>MERGE</code> idempotente por <code>sigla</code>,
de modo que re-ejecutar el setup no duplica filas.</p>

<h3>3.3 Tabla <code>doc_chunks</code> (base del RAG)</h3>
<p>Un registro por <b>fragmento (chunk)</b> de PDF, con la metadata necesaria para citar la fuente.
Tiene <b>Change Data Feed</b> activo para que Vector Search sincronice de forma incremental.</p>
<table>
  <tr><th>Columna</th><th>Tipo</th><th>Descripción</th></tr>
  <tr><td><code>chunk_id</code></td><td>STRING (PK)</td><td>MD5 de <code>documento|página|índice</code> (idempotencia).</td></tr>
  <tr><td><code>documento</code></td><td>STRING</td><td>Nombre del PDF (se usa en la cita).</td></tr>
  <tr><td><code>path</code></td><td>STRING</td><td>Ruta completa en el Volume.</td></tr>
  <tr><td><code>sigla, sujeto, sector, delegada</code></td><td>STRING</td><td>Denormalizados desde <code>sectorizacion</code>.</td></tr>
  <tr><td><code>tipo_auditoria</code></td><td>STRING</td><td>Financiera / Cumplimiento / No determinado.</td></tr>
  <tr><td><code>vigencia</code></td><td>STRING</td><td>Año(s) detectados en el nombre del archivo.</td></tr>
  <tr><td><code>pagina</code></td><td>INT</td><td>Página del PDF (para la cita <code>[doc, p. N]</code>).</td></tr>
  <tr><td><code>chunk_index</code></td><td>INT</td><td>Orden del fragmento dentro de la página.</td></tr>
  <tr><td><code>texto</code></td><td>STRING</td><td>Texto del fragmento (columna que se vectoriza).</td></tr>
  <tr><td><code>ingested_at</code></td><td>TIMESTAMP</td><td>Marca de ingesta.</td></tr>
</table>

<!-- ============ 4. ETL ============ -->
<div class="page-break"></div>
<h2 id="etl">4. ETL e ingesta dinámica (Auto Loader)</h2>
<p>El objetivo es que <b>dejar caer un PDF en el Volume</b> baste para que quede consultable. Se logra
con un job disparado por <b>llegada de archivo</b> que corre Auto Loader de forma incremental.</p>

<div class="svgwrap">
<svg width="720" height="150" viewBox="0 0 720 150" xmlns="http://www.w3.org/2000/svg" font-family="Helvetica, Arial" font-size="9.5">
  <defs><marker id="a2" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L9,3 L0,6 Z" fill="#5b616b"/></marker></defs>
  <rect x="8"  y="45" width="96" height="60" rx="9" fill="#334155"/><text x="56" y="72" fill="#fff" text-anchor="middle">PDF nuevo</text><text x="56" y="88" fill="#cbd5e1" text-anchor="middle" font-size="8">Volume /informes</text>
  <rect x="132" y="45" width="104" height="60" rx="9" fill="#7B4FA3"/><text x="184" y="70" fill="#fff" text-anchor="middle">Auto Loader</text><text x="184" y="86" fill="#eee" text-anchor="middle" font-size="8">binaryFile · *.pdf</text>
  <rect x="264" y="45" width="104" height="60" rx="9" fill="#2A7F8E"/><text x="316" y="70" fill="#fff" text-anchor="middle">pypdf</text><text x="316" y="86" fill="#eaf6f9" text-anchor="middle" font-size="8">texto por página</text>
  <rect x="396" y="45" width="104" height="60" rx="9" fill="#1F4E96"/><text x="448" y="70" fill="#fff" text-anchor="middle">Chunking</text><text x="448" y="86" fill="#d5e0f2" text-anchor="middle" font-size="8">1600 / 200 + meta</text>
  <rect x="528" y="45" width="86" height="60" rx="9" fill="#4C8C3F"/><text x="571" y="70" fill="#fff" text-anchor="middle">MERGE</text><text x="571" y="86" fill="#eafae4" text-anchor="middle" font-size="8">doc_chunks</text>
  <rect x="640" y="45" width="72" height="60" rx="9" fill="#b31b1b"/><text x="676" y="68" fill="#fff" text-anchor="middle" font-size="9">sync</text><text x="676" y="84" fill="#ffe" text-anchor="middle" font-size="8">índice VS</text>
  <line x1="104" y1="75" x2="130" y2="75" stroke="#5b616b" stroke-width="2" marker-end="url(#a2)"/>
  <line x1="236" y1="75" x2="262" y2="75" stroke="#5b616b" stroke-width="2" marker-end="url(#a2)"/>
  <line x1="368" y1="75" x2="394" y2="75" stroke="#5b616b" stroke-width="2" marker-end="url(#a2)"/>
  <line x1="500" y1="75" x2="526" y2="75" stroke="#5b616b" stroke-width="2" marker-end="url(#a2)"/>
  <line x1="614" y1="75" x2="638" y2="75" stroke="#5b616b" stroke-width="2" marker-end="url(#a2)"/>
</svg>
</div>

<h3>4.1 Disparo por llegada de archivo</h3>
<p>El job <code>ingest</code> define un <i>trigger</i> de tipo <code>file_arrival</code> sobre la URL del
Volume. Databricks vigila el Volume y lanza el job cuando aparece un archivo nuevo.</p>
<pre><code>trigger:
  file_arrival:
    url: /Volumes/${catalog}/${schema}/informes/</code></pre>

<h3>4.2 Lectura incremental (Auto Loader)</h3>
<p>Se lee en modo <code>cloudFiles</code> con formato <code>binaryFile</code> (el PDF llega como bytes),
filtrando <code>*.pdf</code>. El <b>checkpoint</b> garantiza que cada archivo se procese una sola vez;
el trigger <code>availableNow</code> procesa lo pendiente y termina.</p>
<pre><code>(spark.readStream.format("cloudFiles")
   .option("cloudFiles.format", "binaryFile")
   .option("pathGlobFilter", "*.pdf")
   .load(VOLUME_PATH)
   .writeStream.foreachBatch(upsert)
   .option("checkpointLocation", CHECKPOINT)
   .trigger(availableNow=True).start())</code></pre>

<h3>4.3 Parseo y troceado (chunking)</h3>
<ul>
  <li><b>Por página</b>: <code>pypdf</code> extrae el texto de cada página; el número de página se
      conserva para la cita.</li>
  <li><b>Chunks</b>: ventana de <code>CHUNK_SIZE = 1600</code> caracteres con
      <code>OVERLAP = 200</code> (solape que evita cortar ideas entre fragmentos).</li>
  <li><b>Metadata derivada del nombre del archivo</b>:
      <ul>
        <li><code>sigla</code>: por patrón (ANLA, PNNC, CVC, CAR, MADS, FONDO_VIDA).</li>
        <li><code>tipo_auditoria</code>: Financiera / Cumplimiento.</li>
        <li><code>vigencia</code>: años <code>20\d\d</code>, tras remover el ID inicial del documento
            (p. ej. <code>202601005_</code>) para no confundirlo con la vigencia.</li>
      </ul>
      El resto (<code>sujeto, sector, delegada</code>) se toma de <code>sectorizacion</code>.</li>
</ul>

<h3>4.4 Escritura idempotente</h3>
<p>Cada lote hace <code>MERGE INTO doc_chunks</code> por <code>chunk_id</code>: si el mismo PDF se re-sube,
se actualizan los chunks en vez de duplicarlos. Al final del job se dispara
<code>sync_index()</code> de Vector Search para refrescar el índice.</p>
<div class="note"><b>Resultado:</b> subir un PDF (por la app o directo al Volume) ⇒ ingesta automática ⇒
chunks en <code>doc_chunks</code> ⇒ índice sincronizado ⇒ disponible en chat e informes, sin pasos manuales.</div>

<!-- ============ 5. VECTOR SEARCH ============ -->
<div class="page-break"></div>
<h2 id="vs">5. Vector Search (índice Delta Sync)</h2>
<p>La recuperación semántica usa un índice <b>Delta Sync</b> gestionado, que se mantiene sincronizado
con la tabla <code>doc_chunks</code> a través del Change Data Feed.</p>
<table>
  <tr><th>Aspecto</th><th>Configuración</th></tr>
  <tr><td>Endpoint</td><td><code>contraloria_vs</code> (tipo STANDARD)</td></tr>
  <tr><td>Índice</td><td><code>&lt;catalog&gt;.&lt;schema&gt;.doc_chunks_index</code></td></tr>
  <tr><td>Tabla origen</td><td><code>doc_chunks</code> (con Change Data Feed)</td></tr>
  <tr><td>Clave primaria</td><td><code>chunk_id</code></td></tr>
  <tr><td>Columna vectorizada</td><td><code>texto</code></td></tr>
  <tr><td>Modelo de embeddings</td><td><code>databricks-gte-large-en</code></td></tr>
  <tr><td>Tipo de pipeline</td><td>TRIGGERED (se sincroniza bajo demanda tras cada ingesta)</td></tr>
</table>
<p>Las consultas devuelven, además del <code>texto</code>, los campos de metadata
(<code>documento, pagina, sigla, sujeto, sector, delegada, tipo_auditoria, vigencia</code>) que permiten
<b>citar</b> y <b>filtrar</b> (p. ej. por <code>sigla</code> en la generación de informe).</p>

<!-- ============ 6. AGENTE ============ -->
<div class="page-break"></div>
<h2 id="agente">6. Agente de auditoría (Mosaic AI Agent Framework)</h2>
<p>Es un único agente implementado como <code>ResponsesAgent</code> de MLflow y desplegado en Model
Serving. Ejecuta un <b>bucle de tool-calling</b> sobre un LLM de chat (<code>ChatDatabricks</code> +
<code>bind_tools</code>), sin dependencias de orquestación pesadas.</p>

<h3>6.1 Herramientas</h3>
<table>
  <tr><th>Herramienta</th><th>Qué hace</th></tr>
  <tr><td><code>retrieve_audit_evidence</code></td><td>RAG sobre Vector Search; devuelve fragmentos con
      <code>documento</code> y <code>pagina</code> para citar. Es la fuente de hallazgos, cuantías,
      opiniones y antecedentes.</td></tr>
  <tr><td><code>buscar_sectorizacion</code></td><td>Función UC: resuelve sigla↔nombre, sector, delegada y
      sujetos asociados.</td></tr>
</table>

<h3>6.2 Reglas del sistema (system prompt)</h3>
<ul>
  <li>Reconoce al sujeto por <b>sigla o nombre completo</b>.</li>
  <li>Toda afirmación basada en informes cita <code>[documento, p. N]</code>.</li>
  <li>Separa <b>Hallazgos comprobados</b> (con cita y cuantía) de <b>Líneas a verificar</b> (hipótesis
      a confirmar por el equipo auditor).</li>
  <li>Si no hay evidencia, lo declara y <b>no inventa</b> cifras, páginas ni documentos.</li>
  <li>Para "informe", estructura por sujeto: antecedentes, hallazgos + cuantías, planes de mejoramiento,
      recurrencias/persistencia, riesgos/líneas a verificar y conclusión técnica.</li>
</ul>

<h3>6.3 Una consulta = varias llamadas</h3>
<p>Cada turno del usuario puede implicar <b>varias llamadas</b> al LLM: el modelo decide llamar
herramientas (búsquedas en Vector Search y/o sectorización), recibe los resultados y vuelve a razonar,
hasta producir la respuesta final (tope <code>MAX_ITERS = 14</code>). Cada consulta a Vector Search es,
a su vez, una llamada al modelo de embeddings.</p>

<h3>6.4 Selección dinámica de modelo y streaming</h3>
<ul>
  <li><b>LLM por petición</b>: el cliente envía <code>custom_inputs.llm_endpoint</code> y el agente usa
      ese modelo (cachea un <code>ChatDatabricks</code> por endpoint). Para modelos GPT de razonamiento
      añade <code>reasoning_effort="none"</code> para habilitar tool-calling.</li>
  <li><b>Streaming</b> (<code>predict_stream</code>): emite la respuesta final token a token. Se
      <b>descarta</b> el texto de los turnos que llaman herramientas y los bloques de "razonamiento"
      de los modelos con <i>thinking</i>, para que no se filtren al usuario.</li>
</ul>

<h3>6.5 Autodetección de LLMs</h3>
<p>Al desplegar, se listan los serving endpoints de chat (<code>task = llm/v1/chat</code>) de la cuenta
y se conceden al agente los <b>modelos recomendados que existan</b> (con <i>fallback</i> a los primeros
detectados). Así la solución se adapta a los modelos de cada workspace sin edición manual.</p>
<div class="kv"><b>Recursos del modelo (auth passthrough):</b> endpoints de LLM + endpoint de embeddings +
índice de Vector Search + función <code>buscar_sectorizacion</code>. El endpoint del agente obtiene
permiso para invocarlos.</div>

<!-- ============ 7. INFORME ============ -->
<div class="page-break"></div>
<h2 id="informe">7. Generación del informe analítico (PDF)</h2>
<p>Un job dedicado produce el informe en formato CGR. Lo dispara la app (o se corre con parámetros).</p>
<ol>
  <li><b>Resolución de sujetos</b>: acepta siglas o nombres y los normaliza a siglas.</li>
  <li><b>Recuperación en paralelo</b>: por cada sujeto y cada tema núcleo se consulta Vector Search
      (<code>ThreadPoolExecutor</code>), con tope de fragmentos por sujeto para acotar el prompt. Si se
      indica un <b>tema/enfoque</b>, las consultas se focalizan en él.</li>
  <li><b>Dos llamadas al LLM</b>: (a) redacta el informe en Markdown (estructura CGR, hasta 16k tokens);
      (b) extrae <b>solo datos numéricos</b> en JSON para graficar (sin inventar).</li>
  <li><b>Gráficas</b>: matplotlib genera hasta cuatro visualizaciones coloridas (hallazgos por informe,
      concentración por sujeto, cuantías fiscales, calificación de control interno con bandas).</li>
  <li><b>Ensamblado PDF</b>: el texto se renderiza con xhtml2pdf (encabezados, tablas, pie CGR) y se
      <b>fusiona</b> con la página de gráficas usando pypdf; el resultado se guarda en el Volume
      <code>informes-analiticos</code>.</li>
</ol>
<p class="small">El mismo contenido se puede pedir conversando en el chat; el job es la vía para obtener
el PDF con gráficas.</p>

<!-- ============ 8. APP ============ -->
<div class="page-break"></div>
<h2 id="app">8. Aplicación (Databricks App / Streamlit)</h2>
<p>Interfaz institucional (tema oscuro, escudo y bandera de Colombia) con tres páginas y un selector de
modelo global en la barra lateral.</p>
<table>
  <tr><th>Página</th><th>Función</th></tr>
  <tr><td><b>Chat</b></td><td>Conversa con el agente. Respuesta en <b>streaming</b> con indicador
      "Consultando informes"; <b>memoria</b> de conversación (se reenvía el historial en cada turno);
      botón "Nueva conversación"; descarga de cada respuesta como PDF.</td></tr>
  <tr><td><b>Informe analítico</b></td><td>Formulario (sector, sujetos, periodo, tema) que dispara el job
      y permite descargar el PDF cuando termina.</td></tr>
  <tr><td><b>Cargar PDF</b></td><td>Sube un informe al Volume <code>informes</code>; la ingesta e
      indexación se disparan solas.</td></tr>
</table>
<h3>8.1 Detalles de implementación</h3>
<ul>
  <li><b>Selector de LLM dinámico</b>: lista los modelos de chat disponibles (recomendados que existan),
      con lista curada de respaldo.</li>
  <li><b>Streaming SSE</b>: lee los eventos <code>response.output_text.delta</code> del endpoint del
      agente; hace <i>fallback</i> a modo no-streaming si no está disponible.</li>
  <li><b>Montos en pesos</b>: se escapan los <code>$</code> al renderizar para que Streamlit no los
      interprete como fórmulas LaTeX.</li>
  <li><b>Memoria</b>: es a nivel de sesión; al reenviar el historial completo, el agente mantiene el hilo.</li>
</ul>

<!-- ============ 9. DESPLIEGUE ============ -->
<div class="page-break"></div>
<h2 id="deploy">9. Despliegue (Asset Bundles) y prerrequisitos</h2>
<p>Toda la solución se empaqueta como un <b>Databricks Asset Bundle</b>. Un solo script la despliega de
extremo a extremo.</p>
<pre><code>./deploy.sh &lt;perfil-cli&gt;
# bundle deploy -> setup -> ingest -> deploy_agent (autodetecta LLMs)
#              -> publica la app -> concede al SP de la app acceso a los Volumes</code></pre>
<h3>9.1 Qué editar antes de desplegar</h3>
<table>
  <tr><th>En <code>databricks.yml</code></th><th>Valor</th></tr>
  <tr><td><code>workspace.host</code></td><td>URL del workspace del cliente</td></tr>
  <tr><td><code>catalog</code> / <code>schema</code></td><td>Dónde viven los datos</td></tr>
  <tr><td><code>warehouse_id</code></td><td>SQL Warehouse serverless</td></tr>
</table>
<h3>9.2 Prerrequisitos</h3>
<ul>
  <li>Unity Catalog habilitado (catalog + schema para la solución).</li>
  <li>SQL Warehouse serverless; Vector Search habilitado; Databricks Apps habilitado.</li>
  <li>Foundation Model APIs activas: al menos un modelo de chat y <code>databricks-gte-large-en</code>.</li>
  <li>Rol de quien despliega: crear tablas/funciones/Volumes, registrar modelos en UC, crear serving
      endpoints, Vector Search endpoints, jobs y apps; MANAGE/OWNER sobre los securables para los grants.</li>
</ul>

<!-- ============ 10. SEGURIDAD ============ -->
<div class="page-break"></div>
<h2 id="seg">10. Seguridad, permisos y trazabilidad</h2>
<ul>
  <li><b>Datos en el perímetro del cliente</b>: PDFs, chunks y vectores viven en Unity Catalog del
      workspace; no se exportan a terceros.</li>
  <li><b>Service principals</b>: la app y el endpoint del agente corren con SP propios; se les concede
      lo mínimo (la app: <code>USE CATALOG/SCHEMA</code> + <code>READ/WRITE VOLUME</code>; el agente:
      invocar LLMs, embeddings, índice y función).</li>
  <li><b>Gobierno UC</b>: los permisos sobre tablas, funciones y Volumes se administran con Unity Catalog.</li>
  <li><b>Trazabilidad</b>: MLflow Tracing en el agente y la tabla de <i>payload/inferencia</i> del
      endpoint permiten auditar cada conversación (entradas, herramientas usadas, salida).</li>
  <li><b>Antialucinación</b>: el prompt prohíbe inventar cifras/páginas/documentos y exige citar la
      fuente; las cuantías se reportan tal como aparecen.</li>
</ul>

<!-- ============ 11. FLUJO ============ -->
<h2 id="flujo">11. Flujo de una consulta de extremo a extremo</h2>
<ol>
  <li>El usuario escribe en el <b>Chat</b> (elige modelo en la barra lateral).</li>
  <li>La app envía el historial al <b>endpoint del agente</b> con <code>stream: true</code> y
      <code>custom_inputs.llm_endpoint</code>.</li>
  <li>El agente razona y, si hace falta, llama <code>buscar_sectorizacion</code> y/o
      <code>retrieve_audit_evidence</code> (Vector Search + embeddings).</li>
  <li>Con la evidencia, redacta la respuesta citando <code>[documento, p. N]</code> y separando
      comprobado de líneas a verificar.</li>
  <li>La app muestra la respuesta en streaming y ofrece descargarla en PDF.</li>
</ol>

<!-- ============ 12. APENDICE ============ -->
<div class="page-break"></div>
<h2 id="apendice">12. Apéndice: parámetros y archivos</h2>
<h3>Parámetros configurables (bundle)</h3>
<table>
  <tr><th>Variable</th><th>Por defecto</th><th>Descripción</th></tr>
  <tr><td><code>catalog</code> / <code>schema</code></td><td>—/ <code>contraloria</code></td><td>Ubicación de los datos.</td></tr>
  <tr><td><code>volume_informes</code></td><td><code>informes</code></td><td>PDFs fuente.</td></tr>
  <tr><td><code>volume_analiticos</code></td><td><code>informes-analiticos</code></td><td>PDFs generados.</td></tr>
  <tr><td><code>vs_endpoint</code></td><td><code>contraloria_vs</code></td><td>Endpoint de Vector Search.</td></tr>
  <tr><td><code>embedding_endpoint</code></td><td><code>databricks-gte-large-en</code></td><td>Embeddings.</td></tr>
  <tr><td><code>llm_endpoint</code></td><td><code>databricks-claude-opus-4-7</code></td><td>LLM por defecto del agente.</td></tr>
  <tr><td><code>agent_endpoint</code></td><td><code>contraloria_audit_agent</code></td><td>Endpoint del agente.</td></tr>
  <tr><td><code>warehouse_id</code></td><td>(editar)</td><td>SQL Warehouse serverless.</td></tr>
</table>
<h3>Estructura del repositorio</h3>
<table>
  <tr><th>Archivo</th><th>Rol</th></tr>
  <tr><td><code>deploy.sh</code></td><td>Despliegue completo en un comando (incluye grants).</td></tr>
  <tr><td><code>databricks.yml</code></td><td>Bundle: variables y target.</td></tr>
  <tr><td><code>resources/jobs.yml</code></td><td>Jobs: setup, ingest, deploy_agent, generate_report.</td></tr>
  <tr><td><code>resources/app.yml</code></td><td>Recurso de la app y sus permisos.</td></tr>
  <tr><td><code>src/setup.py</code></td><td>Sectorización + función UC + tabla chunks + Vector Search.</td></tr>
  <tr><td><code>src/ingest.py</code></td><td>Auto Loader: PDF → chunks → MERGE → sync índice.</td></tr>
  <tr><td><code>src/agent.py</code></td><td>Definición del agente (código del modelo).</td></tr>
  <tr><td><code>src/deploy_agent.py</code></td><td>Registra y despliega el agente (autodetecta LLMs).</td></tr>
  <tr><td><code>src/generate_report.py</code></td><td>Genera el informe analítico en PDF.</td></tr>
  <tr><td><code>app/</code></td><td>App Streamlit (app.py, app.yaml, requirements, assets).</td></tr>
</table>

<p class="center footerline">Contraloría General de la República · Documentación técnica de la solución
"Asistente de Auditoría" · Databricks<br/>Elaborado por <b>Daniel Vargas — Databricks</b></p>

</body></html>"""

HTML = HTML.replace("__ESCUDO__", esc_b64)
with open(HTML_OUT, "w", encoding="utf-8") as f:
    f.write(HTML)

chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
subprocess.run([
    chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
    "--no-pdf-header-footer", "--print-to-pdf=" + PDF_OUT,
    "file://" + HTML_OUT,
], check=True, timeout=120)
print("PDF:", PDF_OUT, os.path.getsize(PDF_OUT), "bytes")
