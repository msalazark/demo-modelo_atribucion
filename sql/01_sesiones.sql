-- 01_sesiones.sql  (DuckDB)
-- Una fila por sesión con su canal, a partir del export de GA4.
-- El canal se toma de la fuente/medio con que ENTRÓ la sesión (collected_traffic_source
-- del primer evento). No se usa session_traffic_source_last_click porque aplica
-- último clic no directo y ocultaría las sesiones directas de la ruta.
--
-- RQ-06: las reglas de UTM, la lista de site_source_name de Meta y las pasarelas vienen de
-- config/<cliente>.yaml; run_demo._sql() sustituye los dos placeholders de más abajo por el SQL
-- generado en reglas_canal.py a partir de esas reglas. El orden es: 1) UTMs, 2) gclid -> Paid
-- Search, 3) fbclid en la URL sin UTMs -> "Meta (sin UTM)", 4) sin fuente -> Direct, 5) Unassigned.

CREATE OR REPLACE TABLE sesiones AS
WITH ev AS (
  SELECT
    user_pseudo_id,
    list_filter(event_params, lambda p: p.key = 'ga_session_id')[1].value.int_value AS ga_session_id,
    list_filter(event_params, lambda p: p.key = 'page_location')[1].value.string_value AS page_location,
    event_timestamp,
    collected_traffic_source AS cts
  FROM events
),
por_sesion AS (
  SELECT
    user_pseudo_id,
    ga_session_id,
    to_timestamp(min(event_timestamp) / 1e6)                    AS inicio_sesion,
    arg_min(cts.manual_source, event_timestamp) FILTER (WHERE cts IS NOT NULL) AS source,
    arg_min(cts.manual_medium, event_timestamp) FILTER (WHERE cts IS NOT NULL) AS medium,
    arg_min(cts.manual_campaign_name, event_timestamp) FILTER (WHERE cts IS NOT NULL) AS campaign,
    arg_min(cts.gclid, event_timestamp) FILTER (WHERE cts IS NOT NULL) AS gclid,
    arg_min(page_location, event_timestamp) AS page_location
  FROM ev
  GROUP BY ALL
)
SELECT
  * EXCLUDE (page_location, gclid),
  -- Agrupación de canales (RQ-06): reglas de config/<cliente>.yaml
  {{CASE_CANAL}} AS canal,
  -- Sesiones abiertas por la pasarela de pago al volver a la thank you page:
  -- no son un canal de marketing y se excluyen de la ruta.
  {{ES_PASARELA}} AS es_pasarela
FROM por_sesion;


-- Atributos del usuario (filtros del dashboard). En GA4 vienen de device.category, geo.region,
-- una propiedad de usuario (cliente nuevo o recurrente) y el grupo de contenido; aquí están
-- aplanados. Se toma el valor del primer evento del usuario.
CREATE OR REPLACE TABLE usuarios AS
SELECT
  user_pseudo_id,
  arg_min(device_category, event_timestamp) AS device_category,
  arg_min(geo_region,      event_timestamp) AS geo_region,
  arg_min(customer_type,   event_timestamp) AS customer_type,
  arg_min(content_group,   event_timestamp) AS content_group
FROM events
GROUP BY user_pseudo_id;
