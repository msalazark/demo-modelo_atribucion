-- 04_kpi_mensual.sql  (DuckDB)
-- KPIs por mes calendario dentro de la ventana móvil (`parametros(inicio, corte)`): volumen,
-- inversión y eficiencia. Alimenta las tarjetas con tendencia del resumen ejecutivo.
-- La inversión solo incluye medios pagados (costs), por eso MER = ingresos / inversión en medios.
--
-- RQ-10: los cortes mensuales usan la zona horaria del cliente (`{{ZONA_HORARIA}}`, de
-- config/<cliente>.yaml), no UTC: un pedido a las 22:00 del 31 de agosto en America/Lima debe
-- caer en agosto, no en septiembre. `costs.date` ya es una fecha de calendario (sin hora), no
-- necesita conversión para agruparla, pero el filtro de ventana sí: `CAST(timestamptz AS DATE)`
-- usa la zona horaria de sesión de DuckDB, no UTC (ver RQ-18), así que hay que forzarla.

CREATE OR REPLACE TABLE kpi_mensual AS
WITH ped AS (
  SELECT strftime(created_at AT TIME ZONE '{{ZONA_HORARIA}}', '%Y-%m') AS periodo,
         count(*) AS pedidos, sum(revenue_pen) AS ingresos
  FROM orders
  WHERE status {{ESTADOS_VALIDOS_PEDIDO}}
    AND created_at BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
  GROUP BY 1
),
inv AS (
  SELECT strftime(date, '%Y-%m') AS periodo, sum(cost_pen) AS inversion_medios
  FROM costs
  WHERE date BETWEEN CAST((SELECT inicio FROM parametros) AT TIME ZONE 'UTC' AS DATE)
                 AND CAST((SELECT corte FROM parametros) AT TIME ZONE 'UTC' AS DATE)
  GROUP BY 1
),
ses AS (
  SELECT strftime(inicio_sesion AT TIME ZONE '{{ZONA_HORARIA}}', '%Y-%m') AS periodo,
         count(*) AS sesiones, count(DISTINCT user_pseudo_id) AS usuarios
  FROM sesiones
  WHERE NOT es_pasarela
    AND inicio_sesion BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
  GROUP BY 1
)
SELECT
  periodo,
  p.pedidos,
  round(p.ingresos, 0)                              AS ingresos,
  round(p.ingresos / p.pedidos, 1)                  AS ticket_promedio,
  round(i.inversion_medios, 0)                      AS inversion_medios,
  round(p.ingresos / i.inversion_medios, 2)         AS mer,
  round(i.inversion_medios / p.pedidos, 1)          AS cpa_blended,
  s.sesiones,
  s.usuarios,
  round(p.pedidos * 100.0 / s.sesiones, 2)          AS conv_sesion_pct
FROM ped p
JOIN inv i USING (periodo)
JOIN ses s USING (periodo)
ORDER BY periodo;
