#!/usr/bin/env python3
"""
ETL e Ingesta con Control de Calidad de Datos (Data Quality) para Ejercicio 3 (Rachas).

Lee el archivo Excel `sql_rachas/data/Rachas.xlsx` sin depender de librerías externas
(mediante el parser nativo OpenXML sobre `zipfile` y `xml.etree.ElementTree`),
aplica validaciones de calidad de datos, registra hallazgos en `dq_audit_log`
y carga las tablas curadas `historia_saldos` y `retiros` en SQLite.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("etl_rachas")

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL_PATH = BASE_DIR / "data" / "Rachas.xlsx"
DEFAULT_DDL_PATH = BASE_DIR / "02_ddl_schema.sql"
DEFAULT_DB_PATH = BASE_DIR / "rachas.db"

NS_MAIN = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
EXCEL_EPOCH = dt.date(1899, 12, 30)


def _col_letters_to_index(cell_ref: str) -> int:
    """Convierte la referencia de celda (ej. 'A1', 'BC23') en índice base 0 de columna."""
    letters = "".join(ch for ch in cell_ref if ch.isalpha()).upper()
    idx = 0
    for ch in letters:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _excel_serial_to_iso_date(value: str) -> str:
    """Convierte un número serial de fecha de Excel o string ISO a formato 'YYYY-MM-DD'."""
    val_str = str(value).strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}", val_str):
        return val_str[:10]
    try:
        serial = int(float(val_str))
        return (EXCEL_EPOCH + dt.timedelta(days=serial)).isoformat()
    except ValueError as exc:
        raise ValueError(f"Formato de fecha inválido: {value!r}") from exc


def read_xlsx_sheets(xlsx_path: Path) -> Dict[str, List[Dict[str, str]]]:
    """
    Lee todas las hojas de un archivo .xlsx usando únicamente la librería estándar de Python.
    Retorna un diccionario {nombre_hoja: [ {col: valor, ...}, ... ]}.
    """
    if not xlsx_path.exists():
        raise FileNotFoundError(f"No se encontró el archivo Excel en: {xlsx_path}")

    with zipfile.ZipFile(xlsx_path, "r") as zf:
        # 1. Cargar tabla de strings compartidos (sharedStrings.xml)
        shared_strings: List[str] = []
        if "xl/sharedStrings.xml" in zf.namelist():
            ss_root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in ss_root.findall("main:si", NS_MAIN):
                texts = [t.text or "" for t in si.findall(".//main:t", NS_MAIN)]
                shared_strings.append("".join(texts))

        # 2. Mapear rId -> ruta de worksheet desde workbook.xml.rels
        rels_root = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rid_to_target: Dict[str, str] = {}
        for rel in rels_root:
            rid = rel.attrib.get("Id", "")
            target = rel.attrib.get("Target", "").lstrip("/")
            if not target.startswith("xl/"):
                target = f"xl/{target}"
            rid_to_target[rid] = target

        # 3. Obtener nombres de hojas desde workbook.xml
        wb_root = ET.fromstring(zf.read("xl/workbook.xml"))
        sheets_info: List[Tuple[str, str]] = []
        for sheet in wb_root.findall(".//main:sheet", NS_MAIN):
            name = sheet.attrib.get("name", "")
            rid = sheet.attrib.get(
                "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id",
                "",
            )
            if name and rid in rid_to_target:
                sheets_info.append((name, rid_to_target[rid]))

        # 4. Parsear filas de cada hoja
        result: Dict[str, List[Dict[str, str]]] = {}
        for sheet_name, target_path in sheets_info:
            ws_root = ET.fromstring(zf.read(target_path))
            rows_data: List[List[str]] = []

            for row_elem in ws_root.findall(".//main:sheetData/main:row", NS_MAIN):
                row_cells: Dict[int, str] = {}
                max_col = -1
                for cell in row_elem.findall("main:c", NS_MAIN):
                    ref = cell.attrib.get("r", "A1")
                    col_idx = _col_letters_to_index(ref)
                    max_col = max(max_col, col_idx)
                    cell_type = cell.attrib.get("t", "")

                    val_elem = cell.find("main:v", NS_MAIN)
                    inline_elem = cell.find(".//main:is/main:t", NS_MAIN)

                    raw_val = ""
                    if cell_type == "s" and val_elem is not None and val_elem.text is not None:
                        raw_val = shared_strings[int(val_elem.text)]
                    elif cell_type == "inlineStr" and inline_elem is not None:
                        raw_val = inline_elem.text or ""
                    elif val_elem is not None and val_elem.text is not None:
                        raw_val = val_elem.text

                    row_cells[col_idx] = raw_val.strip()

                if max_col >= 0:
                    row_list = [row_cells.get(i, "") for i in range(max_col + 1)]
                    if any(cell_val != "" for cell_val in row_list):
                        rows_data.append(row_list)

            if not rows_data:
                result[sheet_name] = []
                continue

            headers = [h.strip().lower() for h in rows_data[0]]
            records: List[Dict[str, str]] = []
            for r in rows_data[1:]:
                padded = r + [""] * max(0, len(headers) - len(r))
                rec = {headers[i]: padded[i] for i in range(len(headers))}
                records.append(rec)

            result[sheet_name] = records

    return result


def run_etl(
    excel_path: Path = DEFAULT_EXCEL_PATH,
    ddl_path: Path = DEFAULT_DDL_PATH,
    db_path: Path = DEFAULT_DB_PATH,
) -> Dict[str, Any]:
    """
    Ejecuta el proceso completo de extracción, auditoría de calidad y carga en SQLite.
    Retorna un diccionario con las métricas de ingesta y calidad de datos.
    """
    logger.info("Iniciando ETL desde archivo fuente: %s", excel_path)
    sheets = read_xlsx_sheets(excel_path)

    if "historia" not in sheets or "retiros" not in sheets:
        raise KeyError(
            f"El archivo Excel debe contener las hojas 'historia' y 'retiros'. Hojas encontradas: {list(sheets.keys())}"
        )

    raw_historia_rows = sheets["historia"]
    raw_retiros_rows = sheets["retiros"]
    logger.info(
        "Filas extraídas -> historia: %d | retiros: %d",
        len(raw_historia_rows),
        len(raw_retiros_rows),
    )

    conn = sqlite3.connect(db_path)
    try:
        with conn:
            ddl_sql = ddl_path.read_text(encoding="utf-8")
            conn.executescript(ddl_sql)

            # 1. Poblar tablas Raw y normalizar formatos
            parsed_historia: List[Tuple[str, str, float]] = []
            for row in raw_historia_rows:
                ident = row["identificacion"].strip()
                corte = _excel_serial_to_iso_date(row["corte_mes"])
                saldo = float(row["saldo"])
                parsed_historia.append((ident, corte, saldo))

            conn.executemany(
                "INSERT INTO raw_historia (identificacion, corte_mes, saldo) VALUES (?, ?, ?)",
                parsed_historia,
            )

            parsed_retiros: List[Tuple[str, str]] = []
            for row in raw_retiros_rows:
                ident = row["identificacion"].strip()
                fecha_ret = _excel_serial_to_iso_date(row["fecha_retiro"])
                parsed_retiros.append((ident, fecha_ret))

            conn.executemany(
                "INSERT INTO raw_retiros (identificacion, fecha_retiro) VALUES (?, ?)",
                parsed_retiros,
            )

            # 2. Reglas de Calidad de Datos sobre `historia`
            # Agrupar por (identificacion, corte_mes) para detectar duplicados exactos y colisiones de llave
            grouped_historia: Dict[Tuple[str, str], List[float]] = {}
            for ident, corte, saldo in parsed_historia:
                if saldo < 0:
                    conn.execute(
                        """
                        INSERT INTO dq_audit_log (table_name, issue_type, identificacion, reference_date, details, resolution)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "historia",
                            "NEGATIVE_BALANCE",
                            ident,
                            corte,
                            f"Saldo negativo detectado: {saldo}",
                            "EXCLUDED_FROM_CURATED",
                        ),
                    )
                    continue
                grouped_historia.setdefault((ident, corte), []).append(saldo)

            curated_historia: List[Tuple[str, str, float, int]] = []
            exact_duplicates_count = 0
            conflicting_duplicates_count = 0

            for (ident, corte), saldos in sorted(grouped_historia.items()):
                if len(saldos) == 1:
                    curated_historia.append((ident, corte, saldos[0], 0))
                else:
                    unique_saldos = sorted(set(saldos))
                    chosen_saldo = max(saldos)
                    if len(unique_saldos) == 1:
                        exact_duplicates_count += 1
                        conn.execute(
                            """
                            INSERT INTO dq_audit_log (table_name, issue_type, identificacion, reference_date, details, resolution)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                "historia",
                                "EXACT_DUPLICATE",
                                ident,
                                corte,
                                f"Registro duplicado exacto ({len(saldos)} ocurrencias) con saldo={chosen_saldo:.0f}",
                                f"DEDUPLICATED_KEEP_SINGLE (saldo={chosen_saldo:.0f})",
                            ),
                        )
                    else:
                        conflicting_duplicates_count += 1
                        conn.execute(
                            """
                            INSERT INTO dq_audit_log (table_name, issue_type, identificacion, reference_date, details, resolution)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                "historia",
                                "PRIMARY_KEY_CONFLICT_SALDO",
                                ident,
                                corte,
                                f"Colisión de llave (identificacion, corte_mes) con saldos distintos: {saldos}",
                                f"RESOLVED_MAX_SALDO_CONSERVATIVE (saldo={chosen_saldo:.0f})",
                            ),
                        )
                    curated_historia.append((ident, corte, chosen_saldo, 1))

            conn.executemany(
                """
                INSERT INTO historia_saldos (identificacion, corte_mes, saldo, is_deduplicated)
                VALUES (?, ?, ?, ?)
                """,
                curated_historia,
            )

            # 3. Reglas de Calidad de Datos sobre `retiros`
            known_clients = {ident for (ident, _) in grouped_historia}
            grouped_retiros: Dict[str, List[str]] = {}
            for ident, fecha_ret in parsed_retiros:
                grouped_retiros.setdefault(ident, []).append(fecha_ret)

            curated_retiros: List[Tuple[str, str, int]] = []
            orphan_retiros_count = 0
            post_retirement_records_count = 0

            for ident, fechas in sorted(grouped_retiros.items()):
                chosen_fecha = max(fechas)
                has_hist = 1 if ident in known_clients else 0
                if not has_hist:
                    orphan_retiros_count += 1
                    conn.execute(
                        """
                        INSERT INTO dq_audit_log (table_name, issue_type, identificacion, reference_date, details, resolution)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "retiros",
                            "ORPHAN_RETIRO_WITHOUT_HISTORIA",
                            ident,
                            chosen_fecha,
                            "Cliente en hoja 'retiros' no existe en 'historia' (posible error de digitación de ID en origen)",
                            "STORED_WITH_HAS_HISTORY_0",
                        ),
                    )
                else:
                    # Auditar si existen cortes posteriores a la fecha de retiro en historia
                    post_cortes = [
                        c for (i, c) in grouped_historia if i == ident and c > chosen_fecha
                    ]
                    if post_cortes:
                        post_retirement_records_count += len(post_cortes)
                        conn.execute(
                            """
                            INSERT INTO dq_audit_log (table_name, issue_type, identificacion, reference_date, details, resolution)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (
                                "historia_vs_retiros",
                                "POST_RETIREMENT_ACTIVITY",
                                ident,
                                chosen_fecha,
                                f"El cliente presenta {len(post_cortes)} cortes en 'historia' posteriores a su fecha_retiro ({chosen_fecha}): {sorted(post_cortes)}",
                                "HANDLED_BY_RETENTION_RULE_IN_SQL",
                            ),
                        )

                curated_retiros.append((ident, chosen_fecha, has_hist))

            conn.executemany(
                "INSERT INTO retiros (identificacion, fecha_retiro, has_history) VALUES (?, ?, ?)",
                curated_retiros,
            )

            total_audit_logs = conn.execute("SELECT COUNT(*) FROM dq_audit_log").fetchone()[0]

        metrics = {
            "db_path": str(db_path),
            "raw_historia_count": len(parsed_historia),
            "curated_historia_count": len(curated_historia),
            "unique_clients_historia": len(known_clients),
            "raw_retiros_count": len(parsed_retiros),
            "curated_retiros_count": len(curated_retiros),
            "exact_duplicates_count": exact_duplicates_count,
            "conflicting_duplicates_count": conflicting_duplicates_count,
            "orphan_retiros_count": orphan_retiros_count,
            "post_retirement_records_count": post_retirement_records_count,
            "total_dq_issues_logged": total_audit_logs,
        }
        logger.info("ETL completado exitosamente. Resumen: %s", metrics)
        return metrics
    finally:
        conn.close()


if __name__ == "__main__":
    run_etl()

