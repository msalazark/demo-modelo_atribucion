-- 01_sesiones.sql  (DuckDB)
-- Una fila por sesión con su canal, a partir del export de GA4.
-- El canal se toma de la fuente/medio con que ENTRÓ la sesión (collected_traffic_source
-- del primer evento). No se usa session_traffic_source_last_click porque aplica
-- último clic no directo y ocultaría las sesiones directas de la ruta.

CREATE OR REPLACE TABLE sesiones AS
WITH ev AS (
  SELECT
    user_pseudo_id,
    list_filter(event_params, lambda p: p.key = 'ga_session_id')[1].value.int_value AS ga_session_id,
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
    arg_min(cts.manual_campaign_name, event_timestamp) FILTER (WHERE cts IS NOT NULL) AS campaign
  FROM ev
  GROUP BY ALL
)
SELECT
  *,
  -- Agrupación de canales simplificada a partir de las reglas por defecto de GA4
  CASE
    WHEN source IS NULL THEN 'Direct'
    WHEN regexp_matches(lower(medium), '^(.*cp.*|ppc|retargeting|paid.*)$')
         AND lower(source) IN ('fb','ig','facebook','instagram','m.facebook.com','l.facebook.com','tiktok','linkedin')
      THEN 'Paid Social'
    WHEN regexp_matches(lower(medium), '^(.*cp.*|ppc|retargeting|paid.*)$')
         AND lower(source) IN ('google','bing','yahoo')
      THEN 'Paid Search'
    WHEN lower(medium) IN ('display','banner','cpm','interstitial','expandable') THEN 'Display'
    WHEN lower(medium) = 'organic' THEN 'Organic Search'
    WHEN lower(medium) IN ('email','e-mail','e_mail','e mail') THEN 'Email'
    WHEN lower(medium) = 'referral' THEN 'Referral'
    ELSE 'Unassigned'
  END AS canal,
  -- Sesiones abiertas por la pasarela de pago al volver a la thank you page:
  -- no son un canal de marketing y se excluyen de la ruta.
  coalesce(lower(source) IN ('niubiz.com.pe','mercadopago.com.pe','paypal.com','izipay.pe'), FALSE) AS es_pasarela
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
