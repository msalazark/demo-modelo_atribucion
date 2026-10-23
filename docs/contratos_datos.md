# Contratos de datos de entrada

RQ-03 de `docs/RQ_mejoras.md`. Esquema mínimo de cada fuente antes de procesarla con los SQL de
`sql/`. Validado por `contratos.validar_fuente(nombre, df, alias=None)`, que se corre antes de los
SQL y falla si falta un campo obligatorio.

## Eventos GA4 (`eventos_ga4`)

| Campo | Obligatorio | Notas |
|---|---|---|
| `event_date` | Sí | `YYYYMMDD` |
| `event_timestamp` | Sí | microsegundos desde epoch |
| `event_name` | Sí | |
| `user_pseudo_id` | Sí | |
| `event_params.ga_session_id` | Sí | dentro del array `event_params` |
| `collected_traffic_source.*` | Sí | fuente/medio/campaña/gclid del primer contacto |
| `user_id` | No | para unir dispositivos (RQ-07) |
| `device.category` | No | dimensión de segmentación |
| `geo.region` | No | dimensión de segmentación |
| `page_location` | No | |
| `ecommerce.transaction_id` | No | para conciliar con el pedido del backend (RQ-07) |

## Pedidos (`pedidos`)

| Campo | Obligatorio | Notas |
|---|---|---|
| `order_id` | Sí | |
| `created_at` | Sí | fecha de conversión por defecto (configurable a `paid_at`, RQ-01) |
| `status` | Sí | se compara contra `estados_validos_pedido` (RQ-01) |
| `revenue` | Sí | esta demo usa `revenue_pen` — ver `alias` |
| `ga_client_id` | Sí | llave principal con GA4 (RQ-07) |
| `paid_at` | No | |
| `ga_session_id` | No | llave secundaria con GA4 |
| `fbp` / `fbc` | No | para Meta CAPI |
| `customer_id` | No | se guarda con hash (RQ-28) |
| `payment_method` | No | |
| `customer_type` | No | dimensión de segmentación |
| `margen` | No | si el ROAS se calcula sobre margen, no ingresos (decisión abierta #7) |

## Costos (`costos`)

| Campo | Obligatorio | Notas |
|---|---|---|
| `date` | Sí | |
| `platform` | Sí | Meta, Google Ads, etc. |
| `campaign_id` | Sí | nivel campaña (RQ-09); esta demo solo tiene costo por canal, no por campaña |
| `campaign_name` | Sí | |
| `cost` | Sí | esta demo usa `cost_pen` — ver `alias` |
| `impressions` / `clicks` / `reach` | No | para RQ-16 |
| `platform_conversions` / `platform_conversion_value` | No | para RQ-15 |

**Nota:** esta demo no tiene costos a nivel campaña (son por canal) hasta RQ-09, así que
`validar_fuente("costos", ...)` no se corre todavía dentro de `run_demo.py`: fallaría por diseño
hasta que exista esa columna. El contrato y la función ya están listos para cuando sí exista.

## Uso

```python
from contratos import validar_fuente

# Columnas de esta demo con nombres distintos al contrato
reporte = validar_fuente("pedidos", df_orders, alias={"revenue": "revenue_pen"})
# {"fuente": "pedidos", "filas": 125000, "pct_nulos": {"order_id": 0.0, "ga_client_id": 3.8, ...}}
```
