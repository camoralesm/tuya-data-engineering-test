#!/usr/bin/env python3
"""
Orquestador y Suite de Validación End-to-End para el Ejercicio 3 (Rachas en SQL).

Ejecuta el pipeline ETL (`01_etl_ingest_sqlite.py`), corre la consulta analítica
(`03_query_rachas.sql`) para distintos escenarios de `fecha_base` y `min_racha_n`,
y valida matemáticamente que los resultados de SQL coincidan 100% con un motor
de referencia en Python puro, además de verificar todas las reglas de negocio
y controles de calidad de datos.
"""

from __future__ import annotations

import argparse
import calendar
import datetime as dt
import importlib.util
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent
ETL_SCRIPT_PATH = BASE_DIR / "01_etl_ingest_sqlite.py"
QUERY_SQL_PATH = BASE_DIR / "03_query_rachas.sql"
DEFAULT_DB_PATH = BASE_DIR / "rachas.db"


def _load_etl_module():
    spec = importlib.util.spec_from_file_location("etl_ingest", ETL_SCRIPT_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"No fue posible cargar el módulo ETL desde {ETL_SCRIPT_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def classify_saldo(saldo: Optional[float]) -> str:
    """Clasifica un saldo numérico en su nivel de deuda (N0 a N4)."""
    if saldo is None or (0 <= saldo < 300_000):
        return "N0"
    if 300_000 <= saldo < 1_000_000:
        return "N1"
    if 1_000_000 <= saldo < 3_000_000:
        return "N2"
    if 3_000_000 <= saldo < 5_000_000:
        return "N3"
    return "N4"


def _generate_month_ends(start_date_iso: str, end_date_iso: str) -> List[str]:
    """Genera todos los cortes de fin de mes 'YYYY-MM-DD' <= end_date_iso."""
    start = dt.date.fromisoformat(start_date_iso)
    end = dt.date.fromisoformat(end_date_iso)
    year, month = start.year, start.month
    result: List[str] = []
    while True:
        last_day = calendar.monthrange(year, month)[1]
        corte = dt.date(year, month, last_day)
        if corte > end:
            break
        result.append(corte.isoformat())
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1
    return result


def execute_sql_rachas(
    db_path: Path,
    fecha_base: str,
    min_racha_n: int,
) -> List[Tuple[str, int, str, str]]:
    """
    Actualiza `parametros_ejecucion` y ejecuta `03_query_rachas.sql`.
    Retorna lista de tuplas (identificacion, racha, fecha_fin, nivel).
    """
    query_sql = QUERY_SQL_PATH.read_text(encoding="utf-8")
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE parametros_ejecucion SET fecha_base = ?, min_racha_n = ? WHERE id = 1",
                (fecha_base, min_racha_n),
            )
            cursor = conn.execute(query_sql)
            return [
                (str(row[0]), int(row[1]), str(row[2]), str(row[3]))
                for row in cursor.fetchall()
            ]
    finally:
        conn.close()


def python_reference_rachas(
    db_path: Path,
    fecha_base: str,
    min_racha_n: int,
) -> List[Tuple[str, int, str, str]]:
    """
    Oráculo de referencia en Python puro para validar independientemente el resultado de SQL.
    """
    conn = sqlite3.connect(db_path)
    try:
        hist_rows = conn.execute(
            """
            SELECT identificacion, corte_mes, MAX(saldo)
            FROM historia_saldos
            WHERE corte_mes <= ? AND saldo >= 0
            GROUP BY identificacion, corte_mes
            """,
            (fecha_base,),
        ).fetchall()
        ret_rows = conn.execute(
            "SELECT identificacion, fecha_retiro FROM retiros"
        ).fetchall()
    finally:
        conn.close()

    if not hist_rows:
        return []

    retiros_map: Dict[str, str] = {r[0]: r[1] for r in ret_rows}
    client_hist: Dict[str, Dict[str, float]] = {}
    for ident, corte, saldo in hist_rows:
        client_hist.setdefault(ident, {})[corte] = float(saldo)

    min_global_corte = min(corte for _, corte, _ in hist_rows)
    all_months = _generate_month_ends(min_global_corte, fecha_base)

    output: List[Tuple[str, int, str, str]] = []

    for ident, cortes_dict in client_hist.items():
        first_corte = min(cortes_dict.keys())
        fecha_retiro = retiros_map.get(ident)

        # Construir serie mensual del cliente
        timeline: List[Tuple[str, str, int]] = []
        for m in all_months:
            if m < first_corte:
                continue
            saldo = cortes_dict.get(m)
            if saldo is None and fecha_retiro is not None and m > fecha_retiro:
                continue
            nivel = classify_saldo(saldo)
            y, mo = int(m[:4]), int(m[5:7])
            timeline.append((m, nivel, y * 12 + mo))

        # Calcular rachas consecutivas
        streaks: List[Tuple[int, str, str]] = []  # (racha_len, fecha_fin, nivel)
        cur_len = 0
        cur_nivel = ""
        cur_end = ""
        prev_month_idx = -999

        for corte_m, nivel, month_idx in timeline:
            if cur_len > 0 and nivel == cur_nivel and month_idx == prev_month_idx + 1:
                cur_len += 1
                cur_end = corte_m
            else:
                if cur_len >= min_racha_n:
                    streaks.append((cur_len, cur_end, cur_nivel))
                cur_len = 1
                cur_nivel = nivel
                cur_end = corte_m
            prev_month_idx = month_idx

        if cur_len >= min_racha_n:
            streaks.append((cur_len, cur_end, cur_nivel))

        if streaks:
            # Ordenar por racha más larga DESC, fecha_fin más reciente DESC
            streaks.sort(key=lambda x: (x[0], x[1]), reverse=True)
            best_len, best_end, best_nivel = streaks[0]
            output.append((ident, best_len, best_end, best_nivel))

    output.sort(key=lambda x: (-x[1], -int(x[2].replace("-", "")), x[0]))
    return output


def run_validation_suite(db_path: Path) -> None:
    """Ejecuta aserciones automatizadas de calidad de datos y equivalencia SQL vs Python."""
    print("\n" + "=" * 80)
    print(" EJECUTANDO SUITE DE VALIDACIÓN AUTOMATIZADA (SQL vs ORÁCULO PYTHON)")
    print("=" * 80)

    conn = sqlite3.connect(db_path)
    try:
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_historia").fetchone()[0]
        cur_count = conn.execute("SELECT COUNT(*) FROM historia_saldos").fetchone()[0]
        dq_rows = conn.execute(
            "SELECT issue_type, identificacion, reference_date, resolution FROM dq_audit_log ORDER BY audit_id"
        ).fetchall()

        assert raw_count == 2925, f"Se esperaban 2925 filas en raw_historia, se obtuvieron {raw_count}"
        assert cur_count == 2923, f"Se esperaban 2923 filas en historia_saldos, se obtuvieron {cur_count}"
        assert len(dq_rows) == 5, f"Se esperaban 5 hallazgos en dq_audit_log, se obtuvieron {len(dq_rows)}"

        # Verificar resolución conservadora de colisión de llave para R7Q4Z9AULIORDJQ9D
        r7_saldo = conn.execute(
            "SELECT saldo FROM historia_saldos WHERE identificacion='R7Q4Z9AULIORDJQ9D' AND corte_mes='2024-12-31'"
        ).fetchone()[0]
        assert r7_saldo == 1142962.0, f"Resolución de saldo inesperada para R7Q4Z9AULIORDJQ9D: {r7_saldo}"

        print("[OK] Controles de Calidad de Datos (Deduplicación, Colisiones y Huérfanos) verificados:")
        for issue_type, ident, ref_date, resolution in dq_rows:
            print(f"     - {issue_type:<32} | ID: {ident:<20} | Fecha: {ref_date} | {resolution}")
    finally:
        conn.close()

    scenarios = [
        ("2024-12-31", 3, "Escenario Principal (Historia completa hasta Dic 2024, n >= 3)"),
        ("2023-12-31", 3, "Time-Travel al cierre de 2023 (fecha_base='2023-12-31', n >= 3)"),
        ("2024-06-30", 4, "Time-Travel a mitad de 2024 con racha exigente (fecha_base='2024-06-30', n >= 4)"),
        ("2024-12-31", 5, "Filtro de rachas largas (fecha_base='2024-12-31', n >= 5)"),
    ]

    for fecha_base, min_n, description in scenarios:
        sql_res = execute_sql_rachas(db_path, fecha_base=fecha_base, min_racha_n=min_n)
        py_res = python_reference_rachas(db_path, fecha_base=fecha_base, min_racha_n=min_n)
        assert sql_res == py_res, (
            f"Discrepancia detectada en escenario {description}: "
            f"SQL={len(sql_res)} filas vs Python={len(py_res)} filas"
        )
        # Verificar que ninguna fecha_fin supere fecha_base y todas las rachas >= min_n
        for ident, racha, fecha_fin, nivel in sql_res:
            assert racha >= min_n, f"Cliente {ident} tiene racha {racha} < {min_n}"
            assert fecha_fin <= fecha_base, f"Cliente {ident} tiene fecha_fin {fecha_fin} > {fecha_base}"
            assert nivel in {"N0", "N1", "N2", "N3", "N4"}, f"Nivel inválido: {nivel}"

        print(
            f"[OK] {description}: {len(sql_res)} clientes identificados "
            "(100% coincidencia exacta entre SQL y Oráculo Python)."
        )


def print_results_summary(
    results: List[Tuple[str, int, str, str]],
    fecha_base: str,
    min_racha_n: int,
    top_k: int = 25,
) -> None:
    """Imprime en consola la tabla de resultados y distribución estadística."""
    print("\n" + "=" * 80)
    print(f" RESULTADOS DE LA CONSULTA DE RACHAS (fecha_base = {fecha_base}, n >= {min_racha_n})")
    print("=" * 80)
    print(f"Total clientes que cumplen el criterio: {len(results)}\n")

    by_nivel: Dict[str, int] = {}
    for _, _, _, nivel in results:
        by_nivel[nivel] = by_nivel.get(nivel, 0) + 1

    print("Distribución de rachas seleccionadas por nivel de deuda:")
    for niv in sorted(by_nivel.keys()):
        print(f"  - Nivel {niv}: {by_nivel[niv]} clientes")

    print(f"\nTop {min(top_k, len(results))} clientes (ordenados por racha DESC, fecha_fin DESC):")
    print(f"{'IDENTIFICACION':<22} | {'RACHA':>5} | {'FECHA_FIN':<12} | {'NIVEL':<5}")
    print("-" * 54)
    for ident, racha, fecha_fin, nivel in results[:top_k]:
        print(f"{ident:<22} | {racha:>5} | {fecha_fin:<12} | {nivel:<5}")
    print("-" * 54)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Ejecuta el ETL, la consulta SQL de rachas y la suite de validación."
    )
    parser.add_argument(
        "--fecha-base",
        default="2024-12-31",
        help="Fecha de corte base en formato YYYY-MM-DD (default: 2024-12-31)",
    )
    parser.add_argument(
        "-n",
        "--min-racha",
        type=int,
        default=3,
        help="Número mínimo de meses consecutivos (default: 3)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=25,
        help="Cantidad de registros a mostrar en el resumen en consola (default: 25)",
    )
    args = parser.parse_args(argv)

    etl_mod = _load_etl_module()
    etl_mod.run_etl(db_path=DEFAULT_DB_PATH)

    run_validation_suite(DEFAULT_DB_PATH)

    results = execute_sql_rachas(
        DEFAULT_DB_PATH,
        fecha_base=args.fecha_base,
        min_racha_n=args.min_racha,
    )
    print_results_summary(
        results,
        fecha_base=args.fecha_base,
        min_racha_n=args.min_racha,
        top_k=args.top,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

