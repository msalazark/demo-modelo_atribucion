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
--
-- RQ-08: una sesión no puede pertenecer a dos pedidos. La ruta de un pedido empieza después
-- del pedido anterior del mismo usuario (`pedido_anterior`, calculado sobre todos sus pedidos,
-- no solo los de la ventana) o en el límite de la ventana de atribución, lo que ocurra después
-- (el mayor de los dos límites).
--
-- RQ-07: un pedido se une a GA4 por la primera llave que calce, en orden:
--   1. ga_client_id (el checkout lo guarda directamente en el pedido).
--   2. transaction_id del evento `purchase` de GA4 == order_id -> su user_pseudo_id.
--   3. user_id (si el sitio lo envía al loguearse) -> cualquier user_pseudo_id del mismo usuario.
-- `pedidos_resueltos` queda como tabla aparte (no solo CTE) para que 03_conciliacion.sql reporte
-- cuántos pedidos se unieron por cada llave sin repetir esta lógica.

CREATE OR REPLACE TABLE pedidos_resueltos AS
WITH purchase_ga4 AS (
  SELECT ecommerce.transaction_id AS order_id, user_pseudo_id,
         row_number() OVER (PARTITION BY ecommerce.transaction_id ORDER BY event_timestamp) AS rn
  FROM events
  WHERE event_name = 'purchase' AND ecommerce.transaction_id IS NOT NULL
),
usuarios_por_login AS (
  SELECT user_id, user_pseudo_id,
         row_number() OVER (PARTITION BY user_id ORDER BY event_timestamp) AS rn
  FROM events
  WHERE user_id IS NOT NULL
)
SELECT
  p.order_id, p.created_at, p.revenue_pen, p.payment_method,
  coalesce(p.ga_client_id, g.user_pseudo_id, u.user_pseudo_id) AS user_pseudo_id,
  CASE WHEN p.ga_client_id IS NOT NULL THEN 'ga_client_id'
       WHEN g.user_pseudo_id IS NOT NULL THEN 'transaction_id'
       WHEN u.user_pseudo_id IS NOT NULL THEN 'user_id'
  END AS llave_union
FROM orders p
LEFT JOIN purchase_ga4 g ON g.order_id = p.order_id AND g.rn = 1
LEFT JOIN usuarios_por_login u ON u.user_id = p.customer_id AND u.rn = 1
WHERE p.status {{ESTADOS_VALIDOS_PEDIDO}};

CREATE OR REPLACE TABLE rutas AS
WITH conversiones AS (
  SELECT *, LAG(created_at) OVER (PARTITION BY user_pseudo_id ORDER BY created_at, order_id) AS pedido_anterior
  FROM pedidos_resueltos
  WHERE user_pseudo_id IS NOT NULL
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
    list(s.campaign ORDER BY s.inicio_sesion)                         AS ruta_campana,
    list(round(epoch(c.created_at - s.inicio_sesion) / 86400.0, 2)
         ORDER BY s.inicio_sesion)                                    AS dias_antes
  FROM conversiones c
  JOIN usuarios us ON us.user_pseudo_id = c.user_pseudo_id
  JOIN sesiones s
    ON  s.user_pseudo_id = c.user_pseudo_id
    AND s.inicio_sesion <= c.created_at
    AND s.inicio_sesion > GREATEST(
          c.created_at - to_days((SELECT ventana_dias FROM parametros)::INTEGER),
          coalesce(c.pedido_anterior, TIMESTAMP '1970-01-01')
        )
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
    list(s.campaign ORDER BY s.inicio_sesion)                         AS ruta_campana,
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
