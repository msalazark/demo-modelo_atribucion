# Atribución data-driven para ecommerce (demo)

Modelos de atribución por **cadenas de Markov** (efecto de remoción) y **valores de Shapley**
sobre rutas de conversión construidas desde el export de GA4 unido a los pedidos del backend.
Los datos son sintéticos, con la misma estructura del export de GA4 en BigQuery.

## Cómo correrlo

```bash
pip install -r requirements.txt
python generar_datos.py   # crea data/ecommerce.duckdb (~1,15 millones de eventos, 150 mil usuarios, 15 meses: 2025-07 a 2026-09)
python run_demo.py        # usa config/demo.yaml; SQL + modelos + validación; escribe resultados/*.csv (~2-3 min)
```

O con `make`: `make datos`, `make pipeline`, `make app`, `make test`.

Los datos son sintéticos (semilla fija, reproducibles): qué representa cada tabla, por qué el MMM
tiene intervalos anchos, por qué "lo que reporta la plataforma" es mucho más alto que lo que le
atribuye el modelo, etc. — ver `docs/datos_sinteticos.md`.

## Configuración (RQ-01)

Las constantes de negocio (canales pagados, ventanas, umbrales de señales, zona horaria, moneda,
estados válidos del pedido, etc.) viven en `config/<cliente>.yaml`, validado con `pydantic`
(`config/esquema.py`). `config/demo.yaml` reproduce el comportamiento actual de la demo;
`config/produccion.yaml` es la plantilla para un cliente real sobre BigQuery.

```bash
python run_demo.py --config config/produccion.yaml
```

`run_demo.py` no acepta argumentos para `streamlit run`, así que el dashboard y el intérprete leen
el mismo YAML mediante la variable de entorno `ATRIBUCION_CONFIG` (por defecto `config/demo.yaml`;
`run_demo.py` la fija automáticamente al correr).

## Modo demo vs. producción (RQ-02)

En `modo: produccion` no existe la tabla `truth` ni el "efecto real": no se genera
`mart_calidad__error_modelo`, `mart_modelos__comparativo` no trae filas `efecto_real`, el dashboard
oculta esas vistas y el intérprete no menciona datos sintéticos.

## Archivos

| Archivo | Qué hace |
|---|---|
| `generar_datos.py` | Datos sintéticos: `events` (formato export GA4), `orders` (backend), `costs`, `truth` |
| `contratos.py` | Esquema mínimo de cada fuente (`validar_fuente`, RQ-03); ver `docs/contratos_datos.md` |
| `reglas_canal.py` | Reglas de canal configurables: UTMs, gclid, fbclid sin UTM (RQ-06) |
| `sql/01_sesiones.sql` | Una fila por sesión con su canal de entrada (reglas de `reglas_canal.py`); marca sesiones de pasarela de pago |
| `sql/02_rutas.sql` | Rutas de conversión; une pedidos a GA4 por varias llaves (RQ-07) y las reinicia tras cada compra (RQ-08) |
| `sql/03_conciliacion.sql` | Pedidos del backend vs. compras vistas en GA4, por cada llave de unión |
| `atribucion.py` | Modelos: `markov()` (orden 1/2, RQ-12), `shapley()` (agregado + diagnóstico, RQ-13), `ultimo_no_directo()`, `efecto_real()` |
| `metricas_decision.py` | Alcance/conversión y roles canónicos abre/asiste/cierra/único (`roles_por_canal`, RQ-11) |
| `run_demo.py` | Orquesta todo, calcula ROAS, error vs. efecto real e intervalos bootstrap |
| `sql_bigquery/rutas_bigquery.sql` | Misma lógica de sesiones y rutas para el export real en BigQuery |

## Pasar a un cliente real

1. El checkout debe guardar en cada pedido el `client_id` y el `session_id` de GA4.
2. Ajustar `sql_bigquery/rutas_bigquery.sql` (proyecto, dataset, tabla de pedidos, lista de pasarelas)
   y programarlo como consulta recurrente.
3. Leer la tabla `rutas` desde BigQuery en lugar de DuckDB y correr `markov()` y `shapley()`.
4. `efecto_real()` solo existe en la demo: con datos reales se valida con experimentos de incrementalidad.

Para desplegar el pipeline y el dashboard en Cloud Run (Dockerfile, Cloud Scheduler, Secret
Manager, cuentas de servicio), ver `docs/despliegue.md` y los targets `make deploy*`.

## Dashboard

La lógica vive en `run_demo.py` (con `atribucion.py`, `metricas_decision.py` y `proximos_pasos.py`). El dashboard
solo lee las tablas `mart_*` de DuckDB. El análisis usa una **ventana móvil de 12 meses** que termina en el último
pedido y se reajusta con cada corrida (mensual); los 3 meses previos de los datos sirven de historia de lookback y de
ventana anterior para vigilar la estabilidad del modelo.

```bash
python generar_datos.py       # datos sintéticos: 15 meses, 150 mil usuarios, ~920 mil eventos (~3 min)
python run_demo.py            # ~2-3 min: 5 ventanas de atribución x 12 segmentos, estado del modelo y narrativa
streamlit run dashboard.py
python -m pytest tests        # modelos, métricas, SQL e intérprete (no gastan API)
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
| Resumen | KPIs con tendencia, mejor alcance / asistidor / conversión, señal por canal (clic en una fila para ver el canal), semáforo de calidad de datos e interpretación |
| Explorar | Alcance, asistencia, conversión, inversión, campañas (RQ-09), plataformas vs. modelo (RQ-15/16), comparación entre segmentos y rutas |
| Modelos y robustez | Reglas vs. Markov vs. Shapley, ventana de atribución, roles, estado del modelo, disparadores de reajuste, diagnóstico de Shapley, evolución histórica y triangulación con el MMM (RQ-22, opcional) |
| Siguientes pasos | Plan interpretado, tiempo hasta la compra, diseño de una prueba de incrementalidad y validación con experimentos (RQ-21) |
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
| `mart_decision__canal` | Alcance, conversión, roles canónicos abre/asiste/cierra/único (RQ-11), roles de Markov (diagnóstico) y costo por canal |
| `mart_modelos__comparativo` | Cuota, ROAS, CPA, intervalo y ranking de cada canal según cada modelo (y el efecto real) |
| `mart_decision__senal` | Señal, motivo y confianza por canal y modelo |
| `mart_decision__pares_asistencia` / `__rutas_top` | Qué canal asiste a cuál cierra; rutas que más venden |
| `mart_calidad__error_modelo` / `__conciliacion` | Error de cada modelo vs. el efecto real (solo modo demo, RQ-02); conciliación con el backend, con el desglose de llaves de unión (RQ-07) |
| `mart_calidad__canales` | % de sesiones en Unassigned, Direct y "Meta (sin UTM)" (RQ-06) |
| `mart_calidad__controles` | Controles de calidad de datos: valor, umbral y estado ok/alerta/crítico (RQ-18) |
| `mart_calidad__modelo` | Diagnóstico de Shapley: AUC, log-loss, calibración por deciles, phi negativos recortados (RQ-13) |
| `mart_kpi__mensual` | Pedidos, ingresos, inversión, MER y CPA por mes de la ventana |
| `mart_estado__modelo` / `__disparadores` | Cambio frente al mes anterior y reglas de reajuste anticipado |
| `mart_tiempo__a_compra` / `__histograma` | Días entre el primer contacto y la compra (medido a 90 días) |
| `mart_siguientes_pasos__prueba_incrementalidad` | Diseño de prueba de incrementalidad por canal pagado: holdout por usuario, geográfica y plantilla de Meta Conversion Lift (RQ-20) |
| `mart_validacion__experimentos` / `__canal` | Crédito atribuido vs. efecto medido por experimentos cargados, factor de calibración informativo y estado Validado/Sin validar/Sin probar por canal (RQ-21) |
| `mart_decision__campana` | Crédito de canal repartido entre sus campañas en proporción a sesiones en rutas convertidas, con costo, ROAS y CPA (RQ-09) |
| `mart_plataformas__comparacion` | Conversiones e ingresos que reclama cada plataforma (Meta/Google Ads) vs. los que le asigna el modelo, por campaña (RQ-15) |
| `mart_plataformas__alcance` | Impresiones, alcance y frecuencia por campaña; no entra a las rutas, insumo para un futuro MMM (RQ-16/RQ-22) |
| `mart_mmm__curvas` / `__resumen` | Marketing Mix Model ligero (opcional): curva de respuesta e intervalo del ROAS marginal por canal (RQ-22, ver `mmm.py`) |
| `mart_ejecucion` / `mart_narrativa` | Datos de la última corrida; interpretación pregenerada |

Cada tabla también se exporta a `resultados/<tabla>.csv`, lista para cargar a BigQuery.
`sql_bigquery/rutas_bigquery.sql` aún no recibe ventana móvil ni ventana de atribución como parámetros.
