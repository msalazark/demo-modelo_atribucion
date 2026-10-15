-- 02_rutas.sql  (DuckDB)
-- Rutas de conversión: una fila por pedido (convertidas) o por usuario (no convertidas).
-- La venta sale de la tabla de pedidos del backend, no del evento purchase de GA4:
-- así entran también las compras que GA4 no vio (thank you page perdida,
-- transferencia, contraentrega). El vínculo es el client_id y el session_id de GA4
-- que el checkout guarda en el pedido.

CREATE OR REPLACE TABLE rutas AS
WITH conversiones AS (
  SELECT order_id, ga_client_id AS user_pseudo_id, created_at, revenue_pen, payment_method
  FROM orders
  WHERE status = 'pagado' AND ga_client_id IS NOT NULL
),
convertidas AS (
  SELECT
    c.user_pseudo_id,
    c.order_id,
    c.revenue_pen,
    TRUE                                      AS convirtio,
    list(s.canal ORDER BY s.inicio_sesion)    AS ruta
  FROM conversiones c
  JOIN sesiones s
    ON  s.user_pseudo_id = c.user_pseudo_id
    AND s.inicio_sesion <= c.created_at
    AND s.inicio_sesion >= c.created_at - INTERVAL 30 DAY      -- ventana de lookback
    AND NOT s.es_pasarela
  GROUP BY ALL
),
no_convertidas AS (
  SELECT
    s.user_pseudo_id,
    NULL::VARCHAR                             AS order_id,
    0.0                                       AS revenue_pen,
    FALSE                                     AS convirtio,
    list(s.canal ORDER BY s.inicio_sesion)    AS ruta
  FROM sesiones s
  WHERE NOT s.es_pasarela
    AND s.user_pseudo_id NOT IN (SELECT user_pseudo_id FROM conversiones)
  GROUP BY ALL
)
SELECT * FROM convertidas
UNION ALL
SELECT * FROM no_convertidas;
