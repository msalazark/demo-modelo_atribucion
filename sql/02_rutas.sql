-- 02_rutas.sql  (DuckDB)
-- Rutas de conversión: una fila por pedido (convertidas) o por usuario (no convertidas).
-- La venta sale de la tabla de pedidos del backend, no del evento purchase de GA4:
-- así entran también las compras que GA4 no vio (thank you page perdida,
-- transferencia, contraentrega). El vínculo es el client_id y el session_id de GA4
-- que el checkout guarda en el pedido.
--
-- Parámetros (tabla `parametros`):
--   inicio, corte ventana móvil de análisis (12 meses). Cuentan los pedidos dentro de la
--                 ventana; las sesiones previas a `inicio` solo se usan como lookback de
--                 quien compra dentro de ella.
--   ventana_dias  ventana de atribución (lookback). Convertidas: días previos al pedido.
--                 No convertidas: días previos a su última sesión, para que ambos grupos
--                 se midan con la misma ventana.
--
-- `dias_antes` guarda, para cada sesión de la ruta, cuántos días faltaban para la compra
-- (o para la última sesión, en las no convertidas). Lo usan el decaimiento temporal y el
-- análisis de tiempo hasta la compra.

CREATE OR REPLACE TABLE rutas AS
WITH conversiones AS (
  SELECT order_id, ga_client_id AS user_pseudo_id, created_at, revenue_pen, payment_method
  FROM orders
  WHERE status = 'pagado' AND ga_client_id IS NOT NULL
    AND created_at BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
),
convertidas AS (
  SELECT
    c.user_pseudo_id,
    c.order_id,
    c.revenue_pen,
    TRUE                                                              AS convirtio,
    any_value(us.device_category)                                     AS device_category,
    any_value(us.geo_region)                                          AS geo_region,
    any_value(us.customer_type)                                       AS customer_type,
    any_value(us.content_group)                                       AS content_group,
    list(s.canal ORDER BY s.inicio_sesion)                            AS ruta,
    list(round(epoch(c.created_at - s.inicio_sesion) / 86400.0, 2)
         ORDER BY s.inicio_sesion)                                    AS dias_antes
  FROM conversiones c
  JOIN usuarios us ON us.user_pseudo_id = c.user_pseudo_id
  JOIN sesiones s
    ON  s.user_pseudo_id = c.user_pseudo_id
    AND s.inicio_sesion <= c.created_at
    AND s.inicio_sesion >= c.created_at - to_days((SELECT ventana_dias FROM parametros)::INTEGER)
    AND NOT s.es_pasarela
  GROUP BY ALL
),
ultima AS (
  SELECT user_pseudo_id, max(inicio_sesion) AS ultima_sesion
  FROM sesiones
  WHERE NOT es_pasarela
    AND inicio_sesion BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
  GROUP BY 1
),
no_convertidas AS (
  SELECT
    s.user_pseudo_id,
    NULL::VARCHAR                                                     AS order_id,
    0.0                                                               AS revenue_pen,
    FALSE                                                             AS convirtio,
    any_value(us.device_category)                                     AS device_category,
    any_value(us.geo_region)                                          AS geo_region,
    any_value(us.customer_type)                                       AS customer_type,
    any_value(us.content_group)                                       AS content_group,
    list(s.canal ORDER BY s.inicio_sesion)                            AS ruta,
    list(round(epoch(u.ultima_sesion - s.inicio_sesion) / 86400.0, 2)
         ORDER BY s.inicio_sesion)                                    AS dias_antes
  FROM sesiones s
  JOIN ultima u USING (user_pseudo_id)
  JOIN usuarios us USING (user_pseudo_id)
  WHERE NOT s.es_pasarela
    AND s.inicio_sesion BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
    AND s.inicio_sesion >= u.ultima_sesion - to_days((SELECT ventana_dias FROM parametros)::INTEGER)
    AND s.user_pseudo_id NOT IN (SELECT user_pseudo_id FROM conversiones)
  GROUP BY ALL
)
SELECT * FROM convertidas
UNION ALL
SELECT * FROM no_convertidas;
