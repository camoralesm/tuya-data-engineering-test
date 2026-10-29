# Prueba Técnica de Ingeniería de Datos — Tuya S.A.

Este repositorio contiene la solución integral de **Ingeniería de Datos** para la prueba técnica de **Tuya S.A.**, abarcando arquitectura DataOps y CI/CD, gobierno y observabilidad de datos (KPIs), procesamiento analítico avanzado en SQL (*Gaps and Islands* con control de calidad de datos sobre `Rachas.xlsx`) y procesamiento orientado a objetos de archivos HTML en Python utilizando exclusivamente la librería estándar (*Python Standard Library*).

---

## Estructura del Repositorio

```text
.
├── .gitignore
├── README.md
├── docs/
│   ├── 01_arquitectura_cicd_telefonos.md   # Ejercicio 1: Arquitectura Medallion + CI/CD (DataOps)
│   └── 02_gobierno_calidad_kpis.md         # Ejercicio 2: Gobierno, Linaje, Observabilidad y KPIs
├── sql_rachas/
│   ├── data/
│   │   └── Rachas.xlsx                     # Dataset fuente (hojas: historia y retiros)
│   ├── 01_etl_ingest_sqlite.py             # Extracción OpenXML sin dependencias externas + Auditoría DQ
│   ├── 02_ddl_schema.sql                   # Esquema DDL (Raw, Curated, Data Quality Log e Índices)
│   ├── 03_query_rachas.sql                 # Consulta SQL parametrizable (Recursive CTE + Gaps & Islands)
│   └── 04_run_and_validate.py              # Orquestador CLI y suite de validación vs. Oráculo Python
└── html_processor/
    ├── src/
    │   ├── __init__.py
    │   ├── processor.py                    # Motor OOP/SOLID (HTMLParser + Base64 Data URI)
    │   └── cli.py                          # Interfaz de línea de comandos + modo demostración (--demo)
    └── tests/
        ├── __init__.py
        └── test_processor.py               # Suite de pruebas unitarias e integración (unittest)
```

---

## Requisitos Previos

- **Python 3.9+** (100% compatible con Python 3.9, 3.10, 3.11, 3.12 y 3.13).
- **Cero dependencias externas obligatorias:** Tanto el ejercicio 4 (por restricción explícita de usar *standard library*) como el motor de ingesta `.xlsx` y validación SQLite del ejercicio 3 están construidos sobre módulos nativos de Python (`sqlite3`, `zipfile`, `xml.etree.ElementTree`, `html.parser`, `base64`, `unittest`, `pathlib`).

---

## Desarrollo de los Ejercicios

### 1. Ejercicio Conceptual: Creación de Dataset Confiable de Números de Teléfono (`docs/01_arquitectura_cicd_telefonos.md`)
- **Documento completo:** [`docs/01_arquitectura_cicd_telefonos.md`](docs/01_arquitectura_cicd_telefonos.md)
- **Puntos clave abordados:**
  - **Arquitectura Medallion (Bronze → Silver → Gold):** Ingesta multi-canal (Core Tarjetas, CRM, App Tuya, Feedback de Telcos y Listas de Consentimiento Ley 2300/1581), estandarización a formato internacional `E.164`, desvío de registros anómalos a tabla de cuarentena (`int_phones_quarantine`) y consolidación del *Golden Record* (`dim_customer_phones_golden`) con historia **SCD Tipo 2** y cálculo de `trust_score` (reglas de sobrevivencia).
  - **Data Contract y Seguridad PII:** Especificación formal de esquema, restricciones, llaves subrogadas y políticas de enmascaramiento dinámico (*Dynamic Data Masking*).
  - **Pipeline CI/CD Automatizado:** Linting estático (`SQLFluff`, `Ruff`, `Mypy`), pruebas unitarias de normalización, entornos efímeros (*Zero-Copy Clone* por Pull Request), *Data Diff* automatizado y despliegue en producción bajo el patrón **Write-Audit-Publish (WAP)** con *Circuit Breakers*.

---

### 2. Ejercicio Conceptual: Gobierno, Trazabilidad y KPIs de Calidad (`docs/02_gobierno_calidad_kpis.md`)
- **Documento completo:** [`docs/02_gobierno_calidad_kpis.md`](docs/02_gobierno_calidad_kpis.md)
- **Puntos clave abordados:**
  - **Linaje y Trazabilidad en Dos Niveles:** Linaje técnico a nivel de columna mediante **OpenLineage** integrado al catálogo de datos (DataHub/Dataplex) y trazabilidad a nivel de fila (*Row-Level Provenance*) registrando fuente ganadora, canal de captura, `survivorship_reason` y versión del código (`git_commit_sha`).
  - **Catálogo de KPIs Técnicos (DAMA) y de Negocio:** Fórmulas y metas (SLOs) para *Cobertura de Teléfono Móvil*, *Validez Sintáctica E.164*, *Índice de Teléfonos Verificados (OTP)*, *Tasa de Colisión/Uso Compartido Anómalo*, *Tasa de Contactabilidad Efectiva (RPC)*, *Hard Bounce Rate* y *Base Alcanzable Cumpliendo Ley 2300*.
  - **Diseño del Tablero de Veeduría:** Tres vistas especializadas (Ejecutiva de Negocio, Auditoría de Captura por Canal/Almacén e Inspector de Trazabilidad para Data Stewards).

---

### 3. Ejercicio Práctico SQL: Rachas de Saldos de Clientes (`sql_rachas/`)

#### 3.1. Control de Calidad de Datos (Data Quality) sobre `Rachas.xlsx`
Durante la auditoría automatizada implementada en [`sql_rachas/01_etl_ingest_sqlite.py`](sql_rachas/01_etl_ingest_sqlite.py) sobre las **2,925 filas** de la hoja `historia` (150 clientes únicos) y las **5 filas** de la hoja `retiros`, se detectaron y controlaron **5 anomalías de calidad de datos**, las cuales quedan registradas en la tabla de auditoría `dq_audit_log`:

| # | Tabla | Tipo de Hallazgo (`issue_type`) | Cliente (`identificacion`) | Fecha Referencia | Detalle del Hallazgo | Resolución Aplicada |
| :- | :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `historia` | `EXACT_DUPLICATE` | `9NWFWJ38XN31WBFXG` | `2023-08-31` | Registro duplicado exacto (2 ocurrencias con `saldo = 4,695,833`). | Deduplicado conservando una única fila en `historia_saldos`. |
| 2 | `historia` | `PRIMARY_KEY_CONFLICT_SALDO` | `R7Q4Z9AULIORDJQ9D` | `2024-12-31` | Colisión de llave `(identificacion, corte_mes)` con dos saldos distintos: `571,481` (N1) y `1,142,962` (N2). | Resolución conservadora de riesgo financiero: `MAX(saldo) = 1,142,962` (`is_deduplicated = 1`). |
| 3 | `retiros` | `ORPHAN_RETIRO_WITHOUT_HISTORIA` | `1LFTDYT2H0I9ZGED3S8` | `2023-11-11` | Cliente en `retiros` no existe en `historia` (posible error tipográfico frente a `1LFTDYT2H0I9ZG3S8`). | Almacenado con bandera `has_history = 0` y auditado sin corromper joins. |
| 4 | `historia_vs_retiros` | `POST_RETIREMENT_ACTIVITY` | `0TTW5R9RRCJ0A9E5F` | `2024-10-10` | Presenta 3 cortes reportados posteriores a su fecha de retiro (`2024-10-31`, `2024-11-30`, `2024-12-31`). | Se respetan los saldos reales reportados y se bloquea la imputación de `N0` en meses ausentes posteriores al retiro. |
| 5 | `historia_vs_retiros` | `POST_RETIREMENT_ACTIVITY` | `THJ9OBJH3W6ANRCM` | `2024-01-20` | Presenta 11 cortes reportados en 2024 posteriores a su fecha de retiro y ausencia en `2024-12-31`. | En `2024-12-31` no se imputa `N0` por ser posterior a `fecha_retiro` (`2024-01-20`). |

#### 3.2. Diseño de la Consulta SQL (`sql_rachas/03_query_rachas.sql`)
La consulta utiliza buenas prácticas de SQL moderno en **SQLite**:
1. **Parametrización Point-in-Time (`fecha_base` y `min_racha_n`):** Lee los parámetros desde la tabla `parametros_ejecucion` y filtra toda la historia a `corte_mes <= fecha_base`.
2. **Generación Dinámica de Calendario Mensual (`WITH RECURSIVE calendario_meses`):** Construye todos los cortes de fin de mes desde la primera aparición global hasta `fecha_base` manejando años bisiestos (ej. `2024-02-29`).
3. **Imputación Inteligente de Nivel `N0` y Regla de Retiros (`malla_cliente_mes`):** Cruza cada cliente desde su `fecha_primera_aparicion` con el calendario mensual; si no aparece en un mes específico, le asigna `N0`, excepto cuando `corte_mes > fecha_retiro`.
4. **Algoritmo *Gaps and Islands* Exacto (`rachas_identificadas`):** Calcula la diferencia entre el índice absoluto del mes `(año * 12 + mes)` y `ROW_NUMBER() OVER (PARTITION BY identificacion, nivel ORDER BY corte_mes)` para agrupar meses estrictamente consecutivos en el mismo nivel de deuda.
5. **Selección y Desempate (`rachas_rankeadas`):** Filtra `COUNT(*) >= min_racha_n` y selecciona una única fila por cliente priorizando `ORDER BY racha DESC, fecha_fin DESC`.

#### 3.3. Cómo Ejecutar el Ejercicio 3

```bash
# 1. Ejecutar solo la ingesta ETL y auditoría de calidad (crea sql_rachas/rachas.db)
python3 sql_rachas/01_etl_ingest_sqlite.py

# 2. Ejecutar la suite completa de validación (SQL vs Oráculo Python) y ver el reporte
python3 sql_rachas/04_run_and_validate.py --fecha-base 2024-12-31 --min-racha 3

# 3. Ejecutar la consulta SQL directamente desde el cliente CLI de SQLite
sqlite3 -header -column sql_rachas/rachas.db < sql_rachas/03_query_rachas.sql
```

---

### 4. Ejercicio Práctico Python: Procesador de Archivos HTML a Base64 (`html_processor/`)

#### 4.1. Diseño Orientado a Objetos y Principios SOLID
El módulo [`html_processor/src/processor.py`](html_processor/src/processor.py) fue diseñado utilizando exclusivamente la **librería estándar de Python** (`html.parser`, `base64`, `mimetypes`, `urllib.parse`, `pathlib`, `abc`):
- **`ImageEncoderStrategy` (ABC) & `Base64ImageEncoder`:** Encapsula la resolución de rutas relativas al HTML, limpieza de *query strings* (`?v=1`) y secuencias URL-encoded (`%20`), inferencia de MIME type y codificación Base64 (Principios **SRP**, **OCP** y **DIP**).
- **`HtmlFileDiscovery`:** Recibe tanto rutas individuales de archivos HTML como directorios, recorriendo recursivamente todos los subdirectorios y omitiendo archivos de salida previos (`.b64.html`) para garantizar **idempotencia**.
- **`_HtmlImgRewriterParser(HTMLParser)`:** Analiza el árbol HTML preservando intactos comentarios, declaraciones `<!DOCTYPE>`, entidades y atributos, reemplazando únicamente el atributo `src` en etiquetas `<img>` cuando la codificación es exitosa.
- **`HtmlImageProcessor`:** Orquesta el procesamiento creando un **nuevo archivo HTML** (ej. `archivo.b64.html`) sin modificar jamás el archivo original y retorna un objeto `ProcessingReport` con la estructura exacta solicitada:
  ```json
  {
    "success": {
      "/ruta/archivo.html": ["assets/logo.png"]
    },
    "fail": {
      "/ruta/archivo.html": ["assets/no_existe.jpg"]
    }
  }
  ```

#### 4.2. Cómo Ejecutar las Pruebas y el CLI del Ejercicio 4

```bash
# 1. Ejecutar la suite de pruebas unitarias y de integración
python3 -m unittest discover -s html_processor/tests -v

# 2. Ejecutar la demostración autocontenida del CLI
python3 html_processor/src/cli.py --demo

# 3. Procesar archivos o directorios específicos desde la línea de comandos
python3 html_processor/src/cli.py ruta/a/directorio_html ruta/a/archivo.html --suffix .b64.html
```

