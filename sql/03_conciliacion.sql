-- 03_conciliacion.sql  (DuckDB)
-- Cuántas ventas del backend ve GA4 y cuántas recupera el modelo, dentro de la ventana
-- móvil definida en `parametros(inicio, corte)`.
--
-- RQ-07: `pedidos_resueltos` (creada en 02_rutas.sql) ya trae, por pedido, la llave con la que se
-- unió a GA4 (o NULL si ninguna calzó); aquí se cuenta cuántos pedidos se unieron por cada una y
-- cuántos quedaron sin ruta por falta de unión.

CREATE OR REPLACE TABLE conciliacion AS
WITH ga4 AS (
  SELECT DISTINCT ecommerce.transaction_id AS order_id
  FROM events
  WHERE event_name = 'purchase'
    AND to_timestamp(event_timestamp / 1e6) BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
),
compras_en_sesion_pasarela AS (
  SELECT count(DISTINCT e.ecommerce.transaction_id) AS n
  FROM events e
  JOIN sesiones s
    ON s.user_pseudo_id = e.user_pseudo_id
   AND s.ga_session_id = list_filter(e.event_params, lambda p: p.key = 'ga_session_id')[1].value.int_value
  WHERE e.event_name = 'purchase' AND s.es_pasarela
    AND to_timestamp(e.event_timestamp / 1e6) BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
),
pedidos AS (
  SELECT * FROM orders
  WHERE created_at BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
),
resueltos AS (
  SELECT * FROM pedidos_resueltos
  WHERE created_at BETWEEN (SELECT inicio FROM parametros) AND (SELECT corte FROM parametros)
)
SELECT
  (SELECT count(*) FROM pedidos WHERE status {{ESTADOS_VALIDOS_PEDIDO}}) AS pedidos_backend,
  (SELECT count(*) FROM pedidos o JOIN ga4 USING (order_id))                      AS pedidos_vistos_en_ga4,
  (SELECT n FROM compras_en_sesion_pasarela)                                      AS compras_ga4_en_sesion_de_pasarela,
  (SELECT count(*) FROM pedidos WHERE status {{ESTADOS_VALIDOS_PEDIDO}} AND ga_client_id IS NULL) AS pedidos_sin_client_id,
  (SELECT count(*) FROM rutas WHERE convirtio)                                    AS pedidos_con_ruta,
  (SELECT count(*) FROM resueltos WHERE llave_union = 'ga_client_id')             AS unidos_por_ga_client_id,
  (SELECT count(*) FROM resueltos WHERE llave_union = 'transaction_id')          AS unidos_por_transaction_id,
  (SELECT count(*) FROM resueltos WHERE llave_union = 'user_id')                 AS unidos_por_user_id,
  (SELECT count(*) FROM resueltos WHERE user_pseudo_id IS NULL)                  AS pedidos_sin_union;
