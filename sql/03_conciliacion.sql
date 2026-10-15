-- 03_conciliacion.sql  (DuckDB)
-- Cuántas ventas del backend ve GA4 y cuántas recupera el modelo.

CREATE OR REPLACE TABLE conciliacion AS
WITH ga4 AS (
  SELECT DISTINCT ecommerce.transaction_id AS order_id
  FROM events
  WHERE event_name = 'purchase'
),
compras_en_sesion_pasarela AS (
  SELECT count(DISTINCT e.ecommerce.transaction_id) AS n
  FROM events e
  JOIN sesiones s
    ON s.user_pseudo_id = e.user_pseudo_id
   AND s.ga_session_id = list_filter(e.event_params, lambda p: p.key = 'ga_session_id')[1].value.int_value
  WHERE e.event_name = 'purchase' AND s.es_pasarela
)
SELECT
  (SELECT count(*) FROM orders WHERE status = 'pagado')                                  AS pedidos_backend,
  (SELECT count(*) FROM orders o JOIN ga4 USING (order_id))                              AS pedidos_vistos_en_ga4,
  (SELECT n FROM compras_en_sesion_pasarela)                                             AS compras_ga4_en_sesion_de_pasarela,
  (SELECT count(*) FROM orders WHERE ga_client_id IS NULL)                               AS pedidos_sin_client_id,
  (SELECT count(*) FROM rutas WHERE convirtio)                                           AS pedidos_con_ruta;
