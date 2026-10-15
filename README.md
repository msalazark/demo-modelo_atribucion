# Atribución data-driven para ecommerce (demo)

Modelos de atribución por **cadenas de Markov** (efecto de remoción) y **valores de Shapley**
sobre rutas de conversión construidas desde el export de GA4 unido a los pedidos del backend.
Los datos son sintéticos, con la misma estructura del export de GA4 en BigQuery.

## Cómo correrlo

```bash
pip install duckdb pandas numpy scikit-learn
python generar_datos.py   # crea data/ecommerce.duckdb (~920 mil eventos, 120 mil usuarios, 12 meses: 2025-10 a 2026-09)
python run_demo.py        # SQL + modelos + validación; recalcula los modelos por mes acumulado y escribe resultados/*.csv (~5 min)
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

## Dashboard de decisión

La lógica vive en `run_demo.py` (y `atribucion.py`, `metricas_decision.py`). El reporte es **mensual acumulado**:
el periodo `2026-03` es desde el primer dato hasta el cierre de marzo, con los modelos recalculados
en cada corte (las cuotas de distintos meses no se suman). Todas las tablas `mart_*` traen `periodo`. El dashboard
solo lee las tablas `mart_*` de DuckDB y arma reportes.

```bash
python run_demo.py            # atribución + alcance/asistencia/conversión -> tablas mart_* + CSV
streamlit run dashboard.py
```

| Tabla en DuckDB | Contenido |
|---|---|
| `mart_atribucion__canal` | Conversiones, ingresos, ROAS por modelo y efecto real |
| `mart_decision__canal` | Alcance, asistencia, conversión, Shapley, CPA y ROAS por canal, más `senal`, `motivo` y `confianza` |
| `mart_decision__pares_asistencia` | Qué canal asiste a cuál cierra |
| `mart_decision__rutas_top` | Rutas que más venden |
| `mart_periodos` | Rango de fechas, pedidos, semáforo de evidencia y si el último mes está incompleto |
| `mart_kpi__mensual` | Pedidos, ingresos, inversión, MER y CPA del mes (no acumulado) |
| `mart_calidad__conciliacion` / `__error_modelo` | Conciliación con backend y error de cada modelo |

Cada tabla también se exporta a `resultados/<tabla>.csv`, lista para cargar a BigQuery.
