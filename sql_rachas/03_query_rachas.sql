-- ============================================================================
-- PRUEBA TÉCNICA INGENIERÍA DE DATOS - TUYA S.A.
-- Archivo: 03_query_rachas.sql
-- Descripción: Consulta analítica parametrizable (Time-Travel / Point-in-Time)
--              que implementa la técnica "Gaps and Islands" mediante CTEs y
--              Window Functions para identificar la racha más larga y reciente
--              por nivel de deuda de cada cliente a una `fecha_base` dada.
-- ============================================================================

WITH RECURSIVE
-- 1. Parámetros de ejecución (leídos desde la tabla parametros_ejecucion)
params AS (
    SELECT
        fecha_base,
        min_racha_n
    FROM parametros_ejecucion
    WHERE id = 1
),

-- 2. Deduplicación defensiva en lectura y filtrado Point-in-Time (<= fecha_base)
historia_filtrada AS (
    SELECT
        h.identificacion,
        h.corte_mes,
        MAX(h.saldo) AS saldo
    FROM historia_saldos AS h
    CROSS JOIN params AS p
    WHERE h.corte_mes <= p.fecha_base
      AND h.saldo >= 0
    GROUP BY
        h.identificacion,
        h.corte_mes
),

-- 3. Primera aparición histórica de cada cliente (hasta fecha_base)
clientes_primera_aparicion AS (
    SELECT
        identificacion,
        MIN(corte_mes) AS fecha_primera_aparicion
    FROM historia_filtrada
    GROUP BY identificacion
),

-- 4. Generación dinámica del calendario mensual de cortes hasta fecha_base
limites_calendario AS (
    SELECT
        date(MIN(fecha_primera_aparicion), 'start of month') AS mes_min,
        date((SELECT fecha_base FROM params), 'start of month') AS mes_max
    FROM clientes_primera_aparicion
),
calendario_meses AS (
    SELECT
        mes_min AS inicio_mes,
        date(mes_min, '+1 month', '-1 day') AS corte_mes
    FROM limites_calendario
    WHERE mes_min IS NOT NULL
      AND date(mes_min, '+1 month', '-1 day') <= (SELECT fecha_base FROM params)

    UNION ALL

    SELECT
        date(inicio_mes, '+1 month') AS inicio_mes,
        date(inicio_mes, '+2 months', '-1 day') AS corte_mes
    FROM calendario_meses
    WHERE date(inicio_mes, '+2 months', '-1 day') <= (SELECT fecha_base FROM params)
),

-- 5. Malla completa (Cliente x Corte Mensual desde primera aparición hasta fecha_base)
--    Se aplica la regla de negocio de retiros:
--    Si el cliente no aparece en un mes posterior a su primera aparición, se asume N0,
--    EXCEPTO si el corte_mes es superior a su fecha_retiro.
malla_cliente_mes AS (
    SELECT
        c.identificacion,
        m.corte_mes,
        h.saldo AS saldo_reportado,
        r.fecha_retiro,
        CASE
            WHEN h.saldo IS NULL THEN 0.0
            ELSE h.saldo
        END AS saldo_efectivo,
        CASE
            WHEN h.saldo IS NULL THEN 'N0'
            WHEN h.saldo >= 0       AND h.saldo < 300000  THEN 'N0'
            WHEN h.saldo >= 300000  AND h.saldo < 1000000 THEN 'N1'
            WHEN h.saldo >= 1000000 AND h.saldo < 3000000 THEN 'N2'
            WHEN h.saldo >= 3000000 AND h.saldo < 5000000 THEN 'N3'
            WHEN h.saldo >= 5000000                       THEN 'N4'
        END AS nivel
    FROM clientes_primera_aparicion AS c
    INNER JOIN calendario_meses AS m
        ON m.corte_mes >= c.fecha_primera_aparicion
    LEFT JOIN historia_filtrada AS h
        ON h.identificacion = c.identificacion
       AND h.corte_mes = m.corte_mes
    LEFT JOIN retiros AS r
        ON r.identificacion = c.identificacion
    WHERE
        -- Si existe saldo en historia se conserva; si no aparece en el mes,
        -- solo se imputa N0 cuando no tiene retiro o el corte_mes <= fecha_retiro.
        h.saldo IS NOT NULL
        OR r.fecha_retiro IS NULL
        OR m.corte_mes <= r.fecha_retiro
),

-- 6. Identificación de Islas (Gaps and Islands) por cliente y nivel de deuda
--    Usamos el índice absoluto de mes (año * 12 + mes) menos ROW_NUMBER()
--    para garantizar contigüidad estricta mes a mes dentro del mismo nivel.
rachas_identificadas AS (
    SELECT
        identificacion,
        corte_mes,
        nivel,
        (CAST(strftime('%Y', corte_mes) AS INTEGER) * 12
         + CAST(strftime('%m', corte_mes) AS INTEGER))
        - ROW_NUMBER() OVER (
            PARTITION BY identificacion, nivel
            ORDER BY corte_mes ASC
        ) AS grupo_racha
    FROM malla_cliente_mes
),

-- 7. Agrupación de cada racha continua y filtro por longitud mínima (racha >= n)
rachas_agrupadas AS (
    SELECT
        r.identificacion,
        r.nivel,
        COUNT(*) AS racha,
        MIN(r.corte_mes) AS fecha_inicio,
        MAX(r.corte_mes) AS fecha_fin
    FROM rachas_identificadas AS r
    CROSS JOIN params AS p
    GROUP BY
        r.identificacion,
        r.nivel,
        r.grupo_racha
    HAVING COUNT(*) >= MAX(p.min_racha_n)
),

-- 8. Ranking de rachas por cliente:
--    1° Racha más larga (racha DESC)
--    2° Término más reciente y <= fecha_base (fecha_fin DESC)
rachas_rankeadas AS (
    SELECT
        identificacion,
        racha,
        fecha_fin,
        nivel,
        ROW_NUMBER() OVER (
            PARTITION BY identificacion
            ORDER BY
                racha DESC,
                fecha_fin DESC
        ) AS rn_seleccion
    FROM rachas_agrupadas
)

-- 9. Proyección final con la estructura exacta solicitada
SELECT
    identificacion,
    racha,
    fecha_fin,
    nivel
FROM rachas_rankeadas
WHERE rn_seleccion = 1
ORDER BY
    racha DESC,
    fecha_fin DESC,
    identificacion ASC;

