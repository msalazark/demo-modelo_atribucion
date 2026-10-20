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

## Dashboard

La lógica vive en `run_demo.py` (con `atribucion.py`, `metricas_decision.py` y `proximos_pasos.py`). El dashboard
solo lee las tablas `mart_*` de DuckDB. El análisis usa una **ventana móvil de 12 meses** que termina en el último
pedido y se reajusta con cada corrida (mensual); los 3 meses previos de los datos sirven de historia de lookback y de
ventana anterior para vigilar la estabilidad del modelo.

```bash
python generar_datos.py       # datos sintéticos: 15 meses, 150 mil usuarios, ~920 mil eventos (~3 min)
python run_demo.py            # ~3 min: 5 ventanas de atribución x 12 segmentos, estado del modelo y narrativa
streamlit run dashboard.py
python -m pytest tests        # pruebas del intérprete (no gastan API)
```

### Filtros (menú lateral)

| Filtro | Efecto |
|---|---|
| Ventana de atribución (7, 14, 30, 60, 90 días) | Recalcula las rutas y los modelos con esa ventana |
| Modelo (Shapley, Markov y seis reglas) | Cambia cuota, ROAS y señales |
| Segmentar por (dispositivo, región, tipo de cliente, categoría) | Recalcula el modelo solo con los usuarios del segmento; sin costo por canal, no hay ROAS |
| Tipo de canal, canales, excluir Direct | Filtran lo que se muestra |

Los modelos no son aditivos, así que cada filtro es una rebanada precalculada en `run_demo.py` (60 en total).

### Páginas

| Página | Para qué sirve |
|---|---|
| Resumen | KPIs con tendencia, mejor alcance / asistidor / conversión, señal por canal (clic en una fila para ver el canal) e interpretación |
| Explorar | Alcance, asistencia, conversión, inversión, comparación entre segmentos y rutas |
| Modelos y robustez | Reglas vs. Markov vs. Shapley, ventana de atribución, roles, estado del modelo y disparadores de reajuste |
| Siguientes pasos | Plan interpretado, tiempo hasta la compra y diseño de una prueba de incrementalidad |
| Pregunta a los datos | Chat con el intérprete sobre la vista actual |

### Intérprete de resultados (`interprete/`)

- **A. Sin IA:** `plantilla.py` redacta una lectura por reglas de cualquier vista; siempre disponible.
- **C. Pregenerada:** al terminar, `run_demo.py` guarda en `mart_narrativa` la interpretación de la vista por defecto.
- **B. En vivo:** botón «Interpretar con IA» y chat. Claude recibe solo cifras ya calculadas (`datos.py`), el
  conocimiento fijo de `conocimiento/*.md` y herramientas de solo lectura (`herramientas.py`); cada cifra de la
  respuesta se verifica (`verificador.py`). Si no hay credenciales o falla la llamada, se muestra la plantilla.

Credenciales: `ANTHROPIC_API_KEY` como variable de entorno o en `.streamlit/secrets.toml` (ignorado por git); nunca en
el código. El modelo se cambia con `INTERPRETE_MODELO` (por defecto `claude-opus-5-5`; `claude-sonnet-5-5` o
`claude-haiku-5-5` abaratan) y el esfuerzo con `INTERPRETE_ESFUERZO`.

### Tablas mart

Las de rebanada traen `ventana_dias`, `dim` y `segmento` como llaves.

| Tabla | Contenido |
|---|---|
| `mart_decision__canal` | Alcance, asistencia, conversión, roles de Markov y costo por canal |
| `mart_modelos__comparativo` | Cuota, ROAS, CPA, intervalo y ranking de cada canal según cada modelo (y el efecto real) |
| `mart_decision__senal` | Señal, motivo y confianza por canal y modelo |
| `mart_decision__pares_asistencia` / `__rutas_top` | Qué canal asiste a cuál cierra; rutas que más venden |
| `mart_calidad__error_modelo` / `__conciliacion` | Error de cada modelo vs. el efecto real; conciliación con el backend |
| `mart_kpi__mensual` | Pedidos, ingresos, inversión, MER y CPA por mes de la ventana |
| `mart_estado__modelo` / `__disparadores` | Cambio frente al mes anterior y reglas de reajuste anticipado |
| `mart_tiempo__a_compra` / `__histograma` | Días entre el primer contacto y la compra (medido a 90 días) |
| `mart_siguientes_pasos__prueba_incrementalidad` | Efecto mínimo detectable de una prueba de holdout por canal pagado |
| `mart_ejecucion` / `mart_narrativa` | Datos de la última corrida; interpretación pregenerada |

Cada tabla también se exporta a `resultados/<tabla>.csv`, lista para cargar a BigQuery.
`sql_bigquery/rutas_bigquery.sql` aún no recibe ventana móvil ni ventana de atribución como parámetros.
