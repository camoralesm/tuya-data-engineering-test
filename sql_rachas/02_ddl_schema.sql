-- ============================================================================
-- PRUEBA TÉCNICA INGENIERÍA DE DATOS - TUYA S.A.
-- Archivo: 02_ddl_schema.sql
-- Descripción: Definición de esquema relacional (DDL) en SQLite para el motor
--              de cálculo de rachas de saldos de clientes y auditoría de
--              calidad de datos (Data Quality).
-- ============================================================================

PRAGMA foreign_keys = ON;

-- 1. Tablas Capa Raw (Aterrizaje fiel al archivo fuente Rachas.xlsx)
DROP TABLE IF EXISTS raw_historia;
CREATE TABLE raw_historia (
    raw_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    identificacion  TEXT NOT NULL,
    corte_mes       TEXT NOT NULL,
    saldo           REAL NOT NULL,
    ingested_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

DROP TABLE IF EXISTS raw_retiros;
CREATE TABLE raw_retiros (
    raw_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    identificacion  TEXT NOT NULL,
    fecha_retiro    TEXT NOT NULL,
    ingested_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. Tabla de Auditoría de Calidad de Datos (Data Quality Log)
DROP TABLE IF EXISTS dq_audit_log;
CREATE TABLE dq_audit_log (
    audit_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name      TEXT NOT NULL,
    issue_type      TEXT NOT NULL,
    identificacion  TEXT,
    reference_date  TEXT,
    details         TEXT NOT NULL,
    resolution      TEXT NOT NULL,
    detected_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 3. Tablas Capa Curada (Silver / Gold Operacional con Integridad y Contratos)
DROP TABLE IF EXISTS historia_saldos;
CREATE TABLE historia_saldos (
    identificacion  TEXT NOT NULL,
    corte_mes       TEXT NOT NULL,
    saldo           REAL NOT NULL CHECK (saldo >= 0),
    is_deduplicated INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (identificacion, corte_mes)
);

DROP TABLE IF EXISTS retiros;
CREATE TABLE retiros (
    identificacion  TEXT PRIMARY KEY,
    fecha_retiro    TEXT NOT NULL,
    has_history     INTEGER NOT NULL DEFAULT 1
);

-- 4. Tabla de Parámetros de Ejecución (Permite parametrizar 03_query_rachas.sql)
DROP TABLE IF EXISTS parametros_ejecucion;
CREATE TABLE parametros_ejecucion (
    id              INTEGER PRIMARY KEY CHECK (id = 1),
    fecha_base      TEXT NOT NULL,
    min_racha_n     INTEGER NOT NULL CHECK (min_racha_n >= 1)
);

-- Valores por defecto (pueden sobreescribirse antes de ejecutar la consulta)
INSERT INTO parametros_ejecucion (id, fecha_base, min_racha_n)
VALUES (1, '2024-12-31', 3);

-- 5. Índices para optimización de consultas analíticas y funciones de ventana
CREATE INDEX IF NOT EXISTS idx_historia_identificacion_corte
    ON historia_saldos (identificacion, corte_mes);

CREATE INDEX IF NOT EXISTS idx_historia_corte_mes
    ON historia_saldos (corte_mes);

CREATE INDEX IF NOT EXISTS idx_retiros_fecha
    ON retiros (identificacion, fecha_retiro);

