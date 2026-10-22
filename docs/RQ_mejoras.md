# RQ · De la demo a la solución para clientes

**Repositorio:** `msalazark/demo-modelo_atribucion` (commit `c2534ef`)
**Autor:** Miguel Salazar · **Versión:** 1.0 · 22-oct-2026
**Uso:** cada requerimiento (RQ-XX) es una unidad de trabajo para Claude Code: una rama, un PR, con sus criterios de aceptación como definición de terminado.

---

## 0. Contexto

La demo ya cubre, sobre datos sintéticos, el flujo completo de las tres etapas de la propuesta:

| Etapa de la propuesta | Qué hay hoy en el repo | Qué falta para un cliente real |
|---|---|---|
| 1 · Medición confiable | Generador con estructura del export de GA4, pedidos y costos (`generar_datos.py`); sesiones, canales y conciliación (`sql/01`, `sql/03`) | Lectura del export real en BigQuery, pedidos de Salesforce Commerce Cloud, costos por campaña de Meta y Google Ads, controles de calidad de datos |
| 2 · Modelo de atribución | Reglas, último clic no directo, Markov y Shapley; roles; señales; 60 rebanadas (5 ventanas × 12 segmentos); estado del modelo; dashboard; intérprete con Claude | Definiciones de negocio unificadas, nivel campaña, identidad más robusta, rendimiento con volumen real, historia de resultados |
| 3 · Validación y siguientes pasos | Tiempo hasta la compra y diseño de prueba de holdout por usuario (`proximos_pasos.py`) | Diseño de pruebas geográficas y Conversion Lift, carga de resultados de experimentos, calibración del modelo y, como opción, MMM |

**Principios que se mantienen** (ya están en el código y no se rompen):

1. La lógica vive en el pipeline; el dashboard y el intérprete **solo leen tablas `mart_*`**.
2. El intérprete **no calcula cifras**: cita hechos ya calculados y cada cifra se verifica.
3. La venta sale del **backend**, no del evento `purchase` de GA4.
4. Toda señal es una **hipótesis**: el ROAS es promedio, no marginal.

---

## 1. Definiciones de negocio (canónicas)

Estas definiciones mandan sobre el código, el glosario del intérprete (`interprete/conocimiento/glosario.md`) y el dashboard. Hoy hay dos definiciones de roles distintas (`metricas_decision.calcular` y `atribucion.markov_roles`); RQ-11 las unifica con esta tabla.

| Término | Definición | Notas |
|---|---|---|
| Sesión | `user_pseudo_id` + `ga_session_id` | Una sesión sin `ga_session_id` se descarta y se cuenta en calidad de datos |
| Canal de la sesión | Fuente con que **entró** la sesión, según las reglas de canal configurables (RQ-06) | Nunca `session_traffic_source_last_click`: oculta el directo |
| Campaña de la sesión | `utm_id` si existe; si no, `utm_campaign` normalizada | Llave con las tablas de costos (RQ-09) |
| Conversión | Pedido del backend con `status` en la lista de estados válidos (configurable) | Fecha de la conversión: `created_at` (configurable a `paid_at`) |
| Ruta | Sesiones del comprador, ordenadas, dentro de la ventana de atribución antes del pedido y **después del pedido anterior** del mismo usuario | Hoy dos pedidos cercanos comparten sesiones (RQ-08) |
| Ruta no convertida | Sesiones de un usuario sin pedido en la ventana de análisis, dentro de la ventana de atribución antes de su última sesión | Se mantiene la lógica actual |
| Ventana de análisis | Últimos 12 meses que terminan en el último pedido; se mueve en cada corrida | Configurable |
| Ventana de atribución | Días antes del pedido en que una sesión cuenta; vigente 30 | Se prueban 7, 14, 30, 60 y 90 |
| **Abre** | El canal es la **primera** sesión de una ruta convertida con 2 o más sesiones | |
| **Asiste** | El canal aparece en la ruta convertida en una posición que no es la primera ni la última | Se cuenta una vez por pedido aunque aparezca varias veces |
| **Cierra** | El canal es la **última** sesión de una ruta convertida con 2 o más sesiones | Variante configurable: "último no directo" (comportamiento actual de `metricas_decision`) |
| **Único** | La ruta convertida tiene una sola sesión | Se reporta aparte; no suma a abre ni cierra |
| Cuota | Ventas atribuidas a un canal por un modelo / ventas con ruta × 100 | Suma 100 % por modelo |
| ROAS | Ingresos atribuidos / inversión del canal o campaña | Solo canales con costo |
| CPA | Inversión / ventas atribuidas | |
| MER | Ingresos totales del backend / inversión total en medios | No depende del modelo |
| Efecto incremental | Ventas que se pierden si el canal no existe | Solo se mide con experimentos; `efecto_real` existe únicamente en modo demo |

**Decisiones abiertas** (ver sección 8): estados válidos del pedido, fecha de conversión, variante de "cierra" que verá negocio.

---

## 2. Arquitectura objetivo

```
Fuentes                      Capas en BigQuery (o DuckDB en modo demo)        Consumo
-------                      -----------------------------------------        -------
GA4 export (events_*)  ──►   raw ──► staging ──► core ──────► mart_*  ──►     Dashboard (Streamlit en Cloud Run)
Pedidos SFCC           ──►   (tal cual) (tipado,   (sesiones,   (contrato   ──►  Looker Studio
Costos Meta/Google Ads ──►              limpio)    rutas,       estable)    ──►  Intérprete (Claude)
Resultados experimentos ─►                         pedidos)
```

- **Un solo código, dos modos** (`modo: demo | produccion`, RQ-01): demo usa DuckDB y `generar_datos.py`; producción usa BigQuery y los conectores reales.
- **SQL en dos dialectos**: DuckDB y BigQuery con la misma lógica y los mismos parámetros. Las diferencias se aíslan en archivos por dialecto o con una capa de transpilación (`sqlglot`) evaluada en RQ-04.
- **Orquestación**: Cloud Run job diario (ingesta y calidad) y mensual (modelos), programados con Cloud Scheduler (RQ-24).

---

## 3. Requerimientos

Prioridad: **P1** necesario para el primer cliente · **P2** importante para operar · **P3** mejora posterior.
Cada RQ indica archivos afectados y dependencias. Todo RQ incluye pruebas (`pytest`) y actualiza el README si cambia el uso.

### Épica A · Configuración y modos

#### RQ-01 · Configuración por cliente y modo de ejecución · P1
**Qué:** reemplazar constantes repartidas en el código por un archivo `config/<cliente>.yaml` validado con `pydantic`.
Debe cubrir: modo (`demo`/`produccion`), motor (`duckdb`/`bigquery`), proyecto y datasets de GCP, zona horaria, moneda, ventana de análisis, ventanas de atribución, ventana vigente, canales pagados, canales no invertibles, lista de pasarelas, estados válidos del pedido, campo de fecha de conversión, dimensiones de segmentación, umbrales de señales y de disparadores, número de remuestreos bootstrap.
**Aceptación:**
- No quedan listas duplicadas de canales pagados (hoy en `run_demo.py`, `dashboard_comun.py` y `limites.md`).
- `python run_demo.py --config config/demo.yaml` reproduce exactamente los `mart_*` actuales (prueba de regresión que compara los CSV de `resultados/`).
- Un YAML inválido falla con un mensaje que nombra el campo.
**Archivos:** nuevo `config/`, `run_demo.py`, `dashboard_comun.py`, `metricas_decision.py`, `interprete/datos.py`.

#### RQ-02 · Modo demo frente a producción · P1 · depende de RQ-01
**Qué:** en producción no existe la tabla `truth` ni `efecto_real`.
**Aceptación:**
- En modo producción el pipeline corre sin `truth`; `mart_calidad__error_modelo` no se genera y `mart_modelos__comparativo` no trae filas `efecto_real`.
- El dashboard oculta las vistas de "efecto real" y muestra en su lugar el estado de validación por experimentos (RQ-20).
- El intérprete no menciona datos sintéticos en modo producción (regla 6 de `INSTRUCCIONES`).

### Épica B · Fuentes de datos (etapa 1)

#### RQ-03 · Contratos de datos de entrada · P1
**Qué:** documentar y validar el esquema mínimo de cada fuente antes de procesarla.

| Fuente | Campos obligatorios | Campos opcionales |
|---|---|---|
| Eventos GA4 | `event_date`, `event_timestamp`, `event_name`, `user_pseudo_id`, `event_params.ga_session_id`, `collected_traffic_source.*` | `user_id`, `device.category`, `geo.region`, `page_location`, `ecommerce.transaction_id` |
| Pedidos | `order_id`, `created_at`, `status`, `revenue`, `ga_client_id` | `paid_at`, `ga_session_id`, `fbp`, `fbc`, `customer_id`, `payment_method`, `customer_type`, `margen` |
| Costos | `date`, `platform`, `campaign_id`, `campaign_name`, `cost` | `impressions`, `clicks`, `reach`, `platform_conversions`, `platform_conversion_value` |

**Aceptación:** una función `validar_fuente(nombre, df_o_tabla)` falla si faltan obligatorios, informa el porcentaje de nulos por campo y se ejecuta antes de los SQL. Contratos en `docs/contratos_datos.md`.

#### RQ-04 · Lectura del export real de GA4 en BigQuery · P1 · depende de RQ-01, RQ-03
**Qué:** `sql_bigquery/` con la misma lógica que `sql/01_sesiones.sql` y `sql/02_rutas.sql`, parametrizada con ventana de análisis y ventana de atribución (hoy el README indica que no lo está).
- Filtrar por `_TABLE_SUFFIX` (ventana de análisis más la ventana de atribución máxima hacia atrás).
- Incluir el export streaming (`events_intraday_*`) solo si se configura.
- Evaluar `sqlglot` para mantener un solo SQL fuente; si no es confiable, mantener dos archivos con pruebas de paridad.
**Aceptación:**
- Con un dataset de muestra de GA4 las consultas corren y producen `sesiones` y `rutas` con el mismo esquema que DuckDB. El dataset público `bigquery-public-data.ga4_obfuscated_sample_ecommerce` sirve para probar la lectura de eventos y parámetros, pero es de 2020-2021 y no trae `collected_traffic_source`: para eso se usa una muestra del cliente o una tabla sintética con el esquema actual.
- Prueba de paridad: los mismos eventos cargados en DuckDB y BigQuery dan las mismas sesiones y rutas.
- El costo por corrida (bytes procesados) se registra en `mart_ejecucion`.

#### RQ-05 · Ingesta de pedidos y costos · P1 · depende de RQ-03
**Qué:**
- Pedidos de Salesforce Commerce Cloud: adaptador que lee un archivo diario (CSV o XML del job de exportación) o la API (OCAPI/SCAPI) y lo carga a `raw_orders`. El adaptador se elige por configuración.
- Costos: tablas del Data Transfer Service de Google Ads y de Meta Ads normalizadas a `stg_costs` (`date`, `platform`, `campaign_id`, `campaign_name`, `cost`, `impressions`, `clicks`, `platform_conversions`).
**Aceptación:** cargas idempotentes por fecha (volver a correr un día no duplica filas); pruebas con archivos de ejemplo en `tests/fixtures/`.

#### RQ-06 · Reglas de canal configurables · P1 · depende de RQ-01
**Qué:** reemplazar el `CASE` fijo de `sql/01_sesiones.sql` por reglas declaradas en YAML, evaluadas en orden:
1. UTMs (`utm_source`, `utm_medium`) con listas y expresiones regulares.
2. Identificadores de clic: `gclid` → Paid Search; `fbclid` en `page_location` sin UTMs → "Meta (sin UTM)" (canal propio, para medir cuánto tráfico de Meta llega sin etiquetar).
3. Referrer.
4. Sin fuente → Direct.
5. Lo que no calce → Unassigned (hoy no se genera en la demo, pero existe en datos reales).
También: valores de Meta `{{site_source_name}}` (`fb`, `ig`, `msg`, `an`) y pasarelas configurables.
**Aceptación:** prueba con una tabla de casos (fuente, medio, gclid, page_location → canal esperado) que cubra al menos 25 combinaciones; `mart_calidad__canales` reporta el porcentaje de sesiones en Unassigned, Direct y "Meta (sin UTM)".

### Épica C · Identidad y rutas

#### RQ-07 · Unión de pedidos con GA4 por varias llaves · P1
**Qué:** hoy un pedido sin `ga_client_id` se descarta. Orden de llaves:
1. `ga_client_id` del pedido.
2. `transaction_id` del evento `purchase` de GA4 = `order_id` → `user_pseudo_id`.
3. `user_id` (si el sitio lo envía) para unir dispositivos.
**Aceptación:** `mart_calidad__conciliacion` agrega cuántos pedidos se unieron por cada llave y cuántos quedaron sin ruta; prueba con pedidos sintéticos que solo tienen una de las tres llaves.
**Nota:** corregir en `sql/03_conciliacion.sql` que `pedidos_sin_client_id` hoy cuenta pedidos de cualquier estado.

#### RQ-08 · Rutas que se reinician tras cada compra · P1
**Qué:** una sesión no puede pertenecer a dos pedidos. La ruta de un pedido empieza después del pedido anterior del mismo usuario (o en el límite de la ventana de atribución, lo que ocurra después).
**Aceptación:** prueba con un usuario de dos pedidos en 10 días: las sesiones previas al primer pedido no aparecen en la ruta del segundo.

#### RQ-09 · Nivel campaña · P1 · depende de RQ-05, RQ-06
**Qué:** agregar `campaign_id` y `campaign_name` a sesiones y rutas; atribuir a nivel **canal** con los modelos actuales y repartir el crédito del canal entre sus campañas en proporción a las sesiones de cada campaña dentro de las rutas convertidas (Shapley a nivel campaña no escala: ver RQ-13).
**Aceptación:** nuevo `mart_decision__campana` con ventas atribuidas, ingresos, inversión, ROAS y CPA por campaña y modelo; la suma por canal coincide con `mart_modelos__comparativo` (tolerancia 0,1 %).

#### RQ-10 · Zona horaria y moneda · P2
**Qué:** cortes mensuales y diarios en la zona horaria del cliente (`America/Lima`); hoy `sql/04_kpi_mensual.sql` agrupa en UTC. Moneda e IGV configurables.
**Aceptación:** un pedido a las 22:00 del 31 de agosto en Lima cae en agosto.

### Épica D · Modelos (etapa 2)

#### RQ-11 · Roles abre, asiste, cierra y único · P1
**Qué:** una sola función `roles_por_canal(rutas, variante_cierre)` según la sección 1, que reemplaza los conteos de `metricas_decision.calcular` y deja `markov_roles` como diagnóstico técnico.
Salida por canal: ventas en que abre, asiste, cierra y es único; sus porcentajes sobre las apariciones del canal; asistencias por cierre.
**Aceptación:**
- Pruebas con rutas a mano: `A→B→C` (A abre, B asiste, C cierra), `A` (único), `A→A→B` (A abre una vez y asiste una vez; B cierra).
- El dashboard muestra la barra apilada abre / asiste / cierra / único por canal en el Resumen.
- El glosario del intérprete usa estas definiciones.

#### RQ-12 · Markov: orden superior, Direct y crédito de ingresos · P2
**Qué:**
- Parámetro `orden` (1 o 2).
- Opción para excluir Direct de la cadena (se observó que Markov le da demasiado crédito por frecuencia).
- Repartir ingresos con efecto de remoción ponderado por valor, no con la cuota global de conversiones como hoy.
**Aceptación:** en datos sintéticos se reporta el error frente al efecto real para cada variante; la configuración elige la variante vigente.

#### RQ-13 · Shapley: escalabilidad y diagnóstico · P1
**Qué:**
- Agregar las rutas por conjunto de canales (conteo de convertidas y no convertidas) antes de ajustar la logística; hoy se ajusta una fila por usuario.
- Límite configurable de jugadores (12 canales). Por encima, Shapley por Monte Carlo con muestreo de permutaciones.
- Diagnóstico del modelo de probabilidad en `mart_calidad__modelo`: AUC, log-loss, calibración por deciles, cantidad de `phi` negativos recortados a 0.
- Regularización `C` elegida por validación cruzada.
**Aceptación:** mismos resultados que hoy (diferencia de cuota ≤ 0,2 pp) con 10 veces menos tiempo en la vista por defecto; prueba de propiedades: eficiencia (los `phi` suman `v(T)`), simetría y jugador nulo.

#### RQ-14 · Robustez por segmento · P2
**Qué:** no publicar señales de un segmento con menos de N conversiones (configurable, por defecto 1 000; el glosario ya habla de 1 000 y 3 000). Intervalo bootstrap también para segmentos con volumen suficiente.
**Aceptación:** el dashboard marca "evidencia insuficiente" en lugar de la señal; el intérprete no recomienda acciones sobre esos segmentos.

### Épica E · Costos y plataformas

#### RQ-15 · Meta reporta frente al modelo · P1 · depende de RQ-05, RQ-09
**Qué:** comparar por campaña las conversiones e ingresos que reporta cada plataforma con los que asigna el modelo.
**Aceptación:** nuevo `mart_plataformas__comparacion` (`platform`, `campaign_id`, `conv_plataforma`, `conv_modelo`, `ingresos_plataforma`, `ingresos_modelo`, `brecha_pct`); vista en el dashboard con una nota fija: la brecha incluye vistas sin clic y cambios de dispositivo.

#### RQ-16 · Impresiones y alcance de anuncios · P3
**Qué:** traer impresiones, alcance y frecuencia por campaña y día al tablero (no entran a las rutas) y dejarlos listos para el MMM (RQ-22).

### Épica F · Rendimiento

#### RQ-17 · Tiempo de corrida con volumen real · P1 · depende de RQ-13
**Qué:** objetivo de 15 minutos para 12 meses de un cliente con 2 millones de sesiones al mes.
- Rutas agregadas por secuencia o por conjunto con sus conteos.
- Rebanadas en paralelo (`joblib`).
- Caché de resultados por (ventana, segmento, versión de datos).
**Aceptación:** `pytest -m rendimiento` genera 20 millones de sesiones sintéticas y mide el tiempo; el resultado queda en `mart_ejecucion`.

### Épica G · Calidad, monitoreo e historia

#### RQ-18 · Controles de calidad de datos · P1 · depende de RQ-03
**Qué:** controles que corren antes de los modelos y detienen la corrida si fallan los críticos.

| Control | Umbral por defecto | Severidad |
|---|---|---|
| Pedidos del día con ruta | ≥ 85 % | Crítico |
| Pedidos vistos en GA4 | ≥ 70 % | Alerta |
| Sesiones Unassigned | ≤ 5 % | Alerta |
| Tráfico de Meta sin UTM | ≤ 10 % | Alerta |
| Días sin costos de una plataforma activa | 0 | Crítico |
| Caída de eventos frente a la media de 28 días | ≥ −30 % | Crítico |

**Aceptación:** `mart_calidad__controles` con el resultado de cada control por corrida; el dashboard muestra un semáforo de calidad.

#### RQ-19 · Historia de resultados · P1
**Qué:** hoy las tablas `mart_*` se borran en cada corrida. Guardar además una copia por fecha de corte en `hist_*` (o una columna `corte` en tablas particionadas en BigQuery).
**Aceptación:** el dashboard puede mostrar la evolución mensual de la cuota y el ROAS por canal; `estado_modelo` usa la historia en lugar de recalcular el mes anterior.

### Épica H · Validación y calibración (etapa 3)

#### RQ-20 · Diseño de pruebas de incrementalidad · P2
**Qué:** ampliar `proximos_pasos.diseno_prueba_incrementalidad` con:
- Prueba geográfica por regiones (con la dimensión `geo_region` y, en producción, departamentos).
- Plantilla para Conversion Lift de Meta (insumos que pide la plataforma y duración sugerida).
- Costo de la prueba en ventas que se dejan de ganar.
**Aceptación:** `mart_siguientes_pasos__prueba_incrementalidad` incluye el tipo de prueba, duración, efecto mínimo detectable y costo estimado.

#### RQ-21 · Carga de resultados de experimentos y calibración · P2 · depende de RQ-20
**Qué:** tabla `experimentos` (canal, fechas, tipo, ventas incrementales, intervalo, fuente) cargada desde un CSV o un formulario. Con ella:
- Comparar el crédito atribuido con el efecto incremental medido.
- Factor de calibración por canal, visible y opcional (no se aplica por defecto).
**Aceptación:** `mart_validacion__experimentos`; el dashboard muestra "validado" o "sin validar" por canal; el intérprete distingue crédito atribuido de efecto medido.

#### RQ-22 · Marketing Mix Modeling (opcional) · P3 · depende de RQ-16, RQ-19
**Qué:** módulo `mmm/` con datos semanales (inversión, impresiones, ventas, controles de estacionalidad y feriados de Perú) usando Meridian o PyMC-Marketing, con los experimentos de RQ-21 como información previa. Requiere al menos un año de historia.
**Aceptación:** curvas de respuesta y ROAS marginal por canal en `mart_mmm__*`; vista de triangulación (atribución, experimentos y MMM lado a lado).

### Épica I · Dashboard

#### RQ-23 · Vistas nuevas y ajustes · P1
- Resumen: roles abre / asiste / cierra / único (RQ-11) y semáforo de calidad (RQ-18).
- Explorar: pestaña Campañas (RQ-09) y pestaña Plataformas, con la comparación entre lo que reporta Meta y lo que asigna el modelo (RQ-15).
- Modelos y robustez: evolución histórica (RQ-19) y diagnóstico de Shapley (RQ-13).
- Siguientes pasos: estado de validación por canal (RQ-21).
- Descarga en CSV de cada tabla visible.
**Aceptación:** ninguna página calcula métricas (revisión de código: solo lecturas de `mart_*` y formato); prueba de humo con `streamlit.testing.v1.AppTest` por página.

#### RQ-24 · Despliegue · P2
**Qué:** Dockerfile; pipeline como Cloud Run job con Cloud Scheduler; dashboard como servicio de Cloud Run detrás de Identity-Aware Proxy; secretos en Secret Manager; cuentas de servicio con permisos mínimos (lectura de datasets fuente, escritura del dataset de marts).
**Aceptación:** `make deploy` documentado; el dashboard no es accesible sin autenticación de Google del dominio del cliente.

### Épica J · Intérprete con Claude

#### RQ-25 · Evaluación y robustez · P2
- Banco de 30 preguntas de negocio con respuestas esperadas (qué cifras y qué cautelas deben aparecer) en `tests/evals/`.
- El verificador reconoce formatos de Perú (`S/ 1,234.56`, `12.5 %`, `3,5 pp`) y porcentajes calculados como texto.
- Registro de tokens y costo por consulta en una tabla de uso.
- El conocimiento (`conocimiento/*.md`) se actualiza con las definiciones de la sección 1 y con las vistas nuevas.
**Aceptación:** `pytest -m evals` (opcional, gasta API) reporta el porcentaje de respuestas que cumplen; las pruebas actuales siguen pasando sin API.

### Épica K · Ingeniería

#### RQ-26 · Estructura, calidad de código e integración continua · P1
- Paquete `src/atribucion/` con submódulos (`config`, `fuentes`, `sql`, `modelos`, `metricas`, `marts`, `app`, `interprete`); `pyproject.toml`.
- `ruff` y `mypy` en modo básico; `pre-commit`.
- GitHub Actions: lint, pruebas sin API y prueba de regresión de marts con datos sintéticos pequeños.
- `Makefile` con `datos`, `pipeline`, `app`, `test`.
**Aceptación:** CI en verde en cada PR; `make test` corre en menos de 3 minutos.

#### RQ-27 · Pruebas de modelos y SQL · P1
- Modelos: casos a mano para cada regla, Markov (efecto de remoción con una cadena de 2 canales calculada a mano) y Shapley (propiedades de RQ-13).
- SQL: fixtures pequeños de eventos y pedidos con resultados esperados de sesiones, canales, rutas y conciliación.
- Regresión: con la semilla actual, el error de Shapley frente al efecto real no supera 2 pp.
**Aceptación:** cobertura ≥ 80 % en `modelos` y `metricas`.

### Épica L · Seguridad y privacidad

#### RQ-28 · Datos personales · P1
- El pipeline no lee ni guarda correo, teléfono, nombre ni dirección. `customer_id` se guarda solo con hash.
- Las tablas `mart_*` no contienen identificadores de usuario.
- Política de retención configurable (por defecto 13 meses de eventos crudos).
- Cumplimiento de la Ley 29733 documentado en `docs/privacidad.md`.
**Aceptación:** prueba que falla si una columna de un `mart_*` coincide con una lista de nombres sensibles.

---

## 4. Tablas `mart_*` nuevas o modificadas

| Tabla | Cambio | RQ |
|---|---|---|
| `mart_decision__canal` | Columnas de roles: `ventas_abre`, `ventas_asiste`, `ventas_cierra`, `ventas_unico` y sus porcentajes | RQ-11 |
| `mart_decision__campana` | Nueva | RQ-09 |
| `mart_plataformas__comparacion` | Nueva | RQ-15 |
| `mart_calidad__conciliacion` | Pedidos unidos por llave | RQ-07 |
| `mart_calidad__canales` | Nueva: % Unassigned, Direct, Meta sin UTM | RQ-06 |
| `mart_calidad__controles` | Nueva | RQ-18 |
| `mart_calidad__modelo` | Nueva: diagnóstico de Shapley | RQ-13 |
| `mart_calidad__error_modelo` | Solo en modo demo | RQ-02 |
| `mart_validacion__experimentos` | Nueva | RQ-21 |
| `mart_mmm__*` | Nuevas (opcional) | RQ-22 |
| `hist_*` | Copia por fecha de corte | RQ-19 |
| `mart_ejecucion` | Bytes procesados, versión de configuración y de código | RQ-04 |

Todas las tablas nuevas entran en la lista blanca `TABLAS` de `interprete/datos.py` solo si el intérprete debe leerlas.

---

## 5. Requerimientos no funcionales

| Tema | Requerimiento |
|---|---|
| Reproducibilidad | Misma configuración y mismos datos → mismos `mart_*` (semillas fijas en bootstrap y Monte Carlo) |
| Tiempo | Pipeline completo ≤ 15 min con 2 M de sesiones al mes; dashboard responde en ≤ 2 s por vista |
| Costo | Consultas de BigQuery por corrida diaria ≤ 50 GB en el escenario medio; se registran en `mart_ejecucion` |
| Trazabilidad | Cada `mart_*` lleva `corte`, `version_config` y `version_codigo` (hash de git) |
| Idioma | Código, tablas y textos en español, como hoy |
| Fallas | Un control crítico fallido detiene la corrida y deja los `mart_*` anteriores intactos |

---

## 6. Plan de ejecución sugerido

| Lote | RQ | Resultado |
|---|---|---|
| 1 · Base | RQ-26, RQ-27, RQ-01, RQ-02 | Proyecto ordenado, con pruebas y configurable, sin cambiar resultados |
| 2 · Definiciones y modelos | RQ-11, RQ-08, RQ-13, RQ-12 | Roles canónicos, rutas correctas, Shapley escalable |
| 3 · Datos reales | RQ-03, RQ-06, RQ-07, RQ-04, RQ-05, RQ-10 | Corre sobre BigQuery con GA4, pedidos y costos |
| 4 · Campañas y plataformas | RQ-09, RQ-15, RQ-17 | ROAS por campaña, comparación con Meta, rendimiento real |
| 5 · Operación | RQ-18, RQ-19, RQ-28, RQ-23, RQ-24 | Controles, historia, privacidad, dashboard desplegado |
| 6 · Etapa 3 | RQ-20, RQ-21, RQ-25, RQ-14 | Validación con experimentos e intérprete evaluado |
| 7 · Opcional | RQ-16, RQ-22 | Impresiones y MMM |

---

## 7. Cómo trabajar cada RQ con Claude Code

1. Una rama por RQ: `rq-XX-nombre-corto`.
2. Pedido a Claude: *"Implementa RQ-XX de `docs/RQ_mejoras.md`. Antes de cambiar código, resume el plan y los archivos que tocarás. Respeta `CLAUDE.md`."*
3. Definición de terminado:
   - Criterios de aceptación cumplidos y verificados con pruebas.
   - `make test` en verde y `run_demo.py` sin errores en modo demo.
   - La prueba de regresión de marts pasa, o el PR explica qué cifra cambia y por qué.
   - README, glosario del intérprete y este RQ actualizados si cambia una definición.
4. Un PR por RQ, con el resultado de las pruebas en la descripción.

---

## 8. Decisiones abiertas

| # | Pregunta | Afecta a |
|---|---|---|
| 1 | ¿Qué estados del pedido cuentan como venta (pagado, despachado, entregado) y se descuentan devoluciones? | RQ-01, RQ-07 |
| 2 | ¿La fecha de conversión es la creación o el pago del pedido? | RQ-01, RQ-08 |
| 3 | ¿"Cierra" es la última sesión o el último canal no directo? (La sección 1 propone la última sesión, con la otra como variante.) | RQ-11 |
| 4 | ¿El cliente envía `user_id` a GA4 cuando el usuario inicia sesión? | RQ-07 |
| 5 | ¿Los pedidos llegan por API o por archivo del job de exportación de Commerce Cloud? | RQ-05 |
| 6 | ¿Dashboard en Streamlit, Looker Studio sobre los `mart_*`, o ambos? | RQ-23, RQ-24 |
| 7 | ¿El ROAS se calcula sobre ingresos o sobre margen? | RQ-03, RQ-09 |
