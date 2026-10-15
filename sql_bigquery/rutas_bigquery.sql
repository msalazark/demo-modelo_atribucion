-- rutas_bigquery.sql
-- Versión BigQuery de sql/01_sesiones.sql + sql/02_rutas.sql para el export real de GA4.
-- Reemplazar: `proyecto`, `analytics_XXXXXXXXX`, el dataset de salida y la tabla de pedidos.
-- Nota: escrito con la misma lógica que la versión DuckDB probada en la demo;
-- validar contra el export del cliente antes de programarlo como consulta recurrente.

DECLARE fecha_ini DATE DEFAULT DATE '2026-08-01';
DECLARE fecha_fin DATE DEFAULT DATE '2026-09-29';
DECLARE lookback_dias INT64 DEFAULT 30;

-- 1. Sesiones con su canal de entrada --------------------------------------------
CREATE OR REPLACE TABLE `proyecto.atribucion.sesiones` AS
WITH ev AS (
  SELECT
    user_pseudo_id,
    (SELECT value.int_value FROM UNNEST(event_params) WHERE key = 'ga_session_id') AS ga_session_id,
    event_timestamp,
    collected_traffic_source AS cts
  FROM `proyecto.analytics_XXXXXXXXX.events_*`
  WHERE _TABLE_SUFFIX BETWEEN FORMAT_DATE('%Y%m%d', DATE_SUB(fecha_ini, INTERVAL lookback_dias DAY))
                          AND FORMAT_DATE('%Y%m%d', fecha_fin)
),
por_sesion AS (
  SELECT
    user_pseudo_id,
    ga_session_id,
    TIMESTAMP_MICROS(MIN(event_timestamp)) AS inicio_sesion,
    -- Primer origen registrado en la sesión (collected_traffic_source no aplica
    -- último clic no directo, así que una sesión directa queda como directa)
    ARRAY_AGG(
      IF(cts.manual_source IS NULL AND cts.gclid IS NULL, NULL,
         STRUCT(cts.manual_source AS source, cts.manual_medium AS medium,
                cts.manual_campaign_name AS campaign, cts.gclid AS gclid))
      IGNORE NULLS ORDER BY event_timestamp LIMIT 1
    )[SAFE_OFFSET(0)] AS t
  FROM ev
  WHERE ga_session_id IS NOT NULL
  GROUP BY 1, 2
)
SELECT
  user_pseudo_id,
  ga_session_id,
  inicio_sesion,
  t.source,
  t.medium,
  t.campaign,
  CASE
    WHEN t.gclid IS NOT NULL THEN 'Paid Search'
    WHEN t.source IS NULL OR t.source = '(direct)' THEN 'Direct'
    WHEN REGEXP_CONTAINS(LOWER(t.medium), r'^(.*cp.*|ppc|retargeting|paid.*)$')
         AND LOWER(t.source) IN ('fb','ig','facebook','instagram','m.facebook.com','l.facebook.com','tiktok','linkedin')
      THEN 'Paid Social'
    WHEN REGEXP_CONTAINS(LOWER(t.medium), r'^(.*cp.*|ppc|retargeting|paid.*)$')
         AND LOWER(t.source) IN ('google','bing','yahoo')
      THEN 'Paid Search'
    WHEN LOWER(t.medium) IN ('display','banner','cpm','interstitial','expandable') THEN 'Display'
    WHEN LOWER(t.medium) = 'organic' THEN 'Organic Search'
    WHEN LOWER(t.medium) IN ('email','e-mail','e_mail','e mail') THEN 'Email'
    WHEN LOWER(t.medium) = 'referral' THEN 'Referral'
    ELSE 'Unassigned'
  END AS canal,
  COALESCE(LOWER(t.source) IN ('niubiz.com.pe','mercadopago.com.pe','paypal.com','izipay.pe'), FALSE) AS es_pasarela
FROM por_sesion;

-- 2. Rutas de conversión ---------------------------------------------------------
-- `proyecto.ecommerce.orders` = pedidos del backend con el client_id y session_id
-- de GA4 capturados en el checkout.
CREATE OR REPLACE TABLE `proyecto.atribucion.rutas` AS
WITH conversiones AS (
  SELECT order_id, ga_client_id AS user_pseudo_id, created_at, revenue_pen
  FROM `proyecto.ecommerce.orders`
  WHERE status = 'pagado'
    AND ga_client_id IS NOT NULL
    AND DATE(created_at) BETWEEN fecha_ini AND fecha_fin
),
convertidas AS (
  SELECT
    c.user_pseudo_id, c.order_id, c.revenue_pen, TRUE AS convirtio,
    ARRAY_AGG(s.canal ORDER BY s.inicio_sesion) AS ruta
  FROM conversiones c
  JOIN `proyecto.atribucion.sesiones` s
    ON  s.user_pseudo_id = c.user_pseudo_id
    AND s.inicio_sesion <= c.created_at
    AND s.inicio_sesion >= TIMESTAMP_SUB(c.created_at, INTERVAL lookback_dias DAY)
    AND NOT s.es_pasarela
  GROUP BY 1, 2, 3
),
no_convertidas AS (
  SELECT
    s.user_pseudo_id, CAST(NULL AS STRING) AS order_id, 0.0 AS revenue_pen, FALSE AS convirtio,
    ARRAY_AGG(s.canal ORDER BY s.inicio_sesion) AS ruta
  FROM `proyecto.atribucion.sesiones` s
  WHERE NOT s.es_pasarela
    AND DATE(s.inicio_sesion) BETWEEN fecha_ini AND fecha_fin
    AND s.user_pseudo_id NOT IN (SELECT user_pseudo_id FROM conversiones)
  GROUP BY 1
)
SELECT * FROM convertidas
UNION ALL
SELECT * FROM no_convertidas;
