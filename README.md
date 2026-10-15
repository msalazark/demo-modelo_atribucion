# Atribución data-driven para ecommerce (demo)

Modelos de atribución por **cadenas de Markov** (efecto de remoción) y **valores de Shapley**
sobre rutas de conversión construidas desde el export de GA4 unido a los pedidos del backend.
Los datos son sintéticos, con la misma estructura del export de GA4 en BigQuery.

## Cómo correrlo

```bash
pip install duckdb pandas numpy scikit-learn
python generar_datos.py   # crea data/ecommerce.duckdb (~290 mil eventos, 40 mil usuarios)
python run_demo.py        # SQL + modelos + validación; escribe resultados/*.csv (~30 s)
```

## Archivos

| Archivo | Qué hace |
|---|---|
| `generar_datos.py` | Datos sintéticos: `events` (formato export GA4), `orders` (backend), `costs`, `truth` |
| `sql/01_sesiones.sql` | Una fila por sesión con su canal de entrada; marca sesiones de pasarela de pago |
| `sql/02_rutas.sql` | Rutas de conversión con lookback de 30 días; la venta sale de `orders` |
| `sql/03_conciliacion.sql` | Pedidos del backend vs. compras vistas en GA4 |
| `atribucion.py` | Modelos: `markov()`, `shapley()`, `ultimo_no_directo()` (referencia), `efecto_real()` |
| `run_demo.py` | Orquesta todo, calcula ROAS, error vs. efecto real e intervalos bootstrap |
| `sql_bigquery/rutas_bigquery.sql` | Misma lógica de sesiones y rutas para el export real en BigQuery |

## Pasar a un cliente real

1. El checkout debe guardar en cada pedido el `client_id` y el `session_id` de GA4.
2. Ajustar `sql_bigquery/rutas_bigquery.sql` (proyecto, dataset, tabla de pedidos, lista de pasarelas)
   y programarlo como consulta recurrente.
3. Leer la tabla `rutas` desde BigQuery en lugar de DuckDB y correr `markov()` y `shapley()`.
4. `efecto_real()` solo existe en la demo: con datos reales se valida con experimentos de incrementalidad.
