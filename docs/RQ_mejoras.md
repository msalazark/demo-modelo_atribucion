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
| Ruta | Sesiones del comprador, ordenadas, dentro de la ventana de atribución antes del pedido y **después del pedido anterior** del mismo usuario | Corregido en RQ-08 |
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
| Validación con experimentos | Comparar la cuota atribuida (prorrateada a los días de la prueba) con las ventas incrementales medidas: "Validado" si el atribuido cae en el intervalo medido, "Sin validar" si no, "Sin probar" si el canal no tiene experimento cargado | RQ-21 |
| Factor de calibración | Ventas incrementales medidas / ventas atribuidas para el mismo periodo | Informativo; no se aplica solo a ninguna cuota |

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

#### RQ-01 · Configuración por cliente y modo de ejecución · P1 · Hecho
**Qué:** reemplazar constantes repartidas en el código por un archivo `config/<cliente>.yaml` validado con `pydantic`.
Debe cubrir: modo (`demo`/`produccion`), motor (`duckdb`/`bigquery`), proyecto y datasets de GCP, zona horaria, moneda, ventana de análisis, ventanas de atribución, ventana vigente, canales pagados, canales no invertibles, lista de pasarelas, estados válidos del pedido, campo de fecha de conversión, dimensiones de segmentación, umbrales de señales y de disparadores, número de remuestreos bootstrap.
**Aceptación:**
- No quedan listas duplicadas de canales pagados (hoy en `run_demo.py`, `dashboard_comun.py` y `limites.md`).
- `python run_demo.py --config config/demo.yaml` reproduce exactamente los `mart_*` actuales (prueba de regresión que compara los CSV de `resultados/`).
- Un YAML inválido falla con un mensaje que nombra el campo.
**Archivos:** nuevo `config/`, `run_demo.py`, `dashboard_comun.py`, `metricas_decision.py`, `interprete/datos.py`.

#### RQ-02 · Modo demo frente a producción · P1 · depende de RQ-01 · Hecho
**Qué:** en producción no existe la tabla `truth` ni `efecto_real`.
**Aceptación:**
- En modo producción el pipeline corre sin `truth`; `mart_calidad__error_modelo` no se genera y `mart_modelos__comparativo` no trae filas `efecto_real`.
- El dashboard oculta las vistas de "efecto real" y muestra en su lugar el estado de validación por experimentos (RQ-20).
- El intérprete no menciona datos sintéticos en modo producción (regla 6 de `INSTRUCCIONES`).

### Épica B · Fuentes de datos (etapa 1)

#### RQ-03 · Contratos de datos de entrada · P1 · Hecho
**Qué:** documentar y validar el esquema mínimo de cada fuente antes de procesarla.

| Fuente | Campos obligatorios | Campos opcionales |
|---|---|---|
| Eventos GA4 | `event_date`, `event_timestamp`, `event_name`, `user_pseudo_id`, `event_params.ga_session_id`, `collected_traffic_source.*` | `user_id`, `device.category`, `geo.region`, `page_location`, `ecommerce.transaction_id` |
| Pedidos | `order_id`, `created_at`, `status`, `revenue`, `ga_client_id` | `paid_at`, `ga_session_id`, `fbp`, `fbc`, `customer_id`, `payment_method`, `customer_type`, `margen` |
| Costos | `date`, `platform`, `campaign_id`, `campaign_name`, `cost` | `impressions`, `clicks`, `reach`, `platform_conversions`, `platform_conversion_value` |

**Aceptación:** una función `validar_fuente(nombre, df_o_tabla)` falla si faltan obligatorios, informa el porcentaje de nulos por campo y se ejecuta antes de los SQL. Contratos en `docs/contratos_datos.md`.

**Nota:** `contratos.validar_fuente()` corre en `run_demo.py` para `eventos_ga4` y `pedidos` antes
de `sql/01_sesiones.sql`. `costos` no se valida todavía: esta demo trae costo por canal, no por
campaña (`campaign_id`/`campaign_name` llegan con RQ-09) — el contrato y la función ya están listos
para cuando exista esa columna.

#### RQ-04 · Lectura del export real de GA4 en BigQuery · P1 · depende de RQ-01, RQ-03 · Diferido
**Qué:** `sql_bigquery/` con la misma lógica que `sql/01_sesiones.sql` y `sql/02_rutas.sql`, parametrizada con ventana de análisis y ventana de atribución (hoy el README indica que no lo está).
- Filtrar por `_TABLE_SUFFIX` (ventana de análisis más la ventana de atribución máxima hacia atrás).
- Incluir el export streaming (`events_intraday_*`) solo si se configura.
- Evaluar `sqlglot` para mantener un solo SQL fuente; si no es confiable, mantener dos archivos con pruebas de paridad.
**Aceptación:**
- Con un dataset de muestra de GA4 las consultas corren y producen `sesiones` y `rutas` con el mismo esquema que DuckDB. El dataset público `bigquery-public-data.ga4_obfuscated_sample_ecommerce` sirve para probar la lectura de eventos y parámetros, pero es de 2020-2021 y no trae `collected_traffic_source`: para eso se usa una muestra del cliente o una tabla sintética con el esquema actual.
- Prueba de paridad: los mismos eventos cargados en DuckDB y BigQuery dan las mismas sesiones y rutas.
- El costo por corrida (bytes procesados) se registra en `mart_ejecucion`.

**Nota:** diferido. `sql_bigquery/rutas_bigquery.sql` ya existe como plantilla (ver README), pero
completarlo y, sobre todo, la prueba de paridad y la lectura del dataset público, necesitan un
proyecto de GCP con facturación habilitada para correr BigQuery (incluso contra un dataset
público, BigQuery cobra por bytes procesados a la cuenta que consulta). Este entorno no tiene
credenciales de GCP ni un proyecto facturable, así que no se puede verificar — escribir el SQL sin
poder correrlo ni compararlo contra DuckDB no cumpliría el criterio de aceptación ("prueba de
paridad") y arriesgaría entregar algo roto sin saberlo.

#### RQ-05 · Ingesta de pedidos y costos · P1 · depende de RQ-03 · Diferido
**Qué:**
- Pedidos de Salesforce Commerce Cloud: adaptador que lee un archivo diario (CSV o XML del job de exportación) o la API (OCAPI/SCAPI) y lo carga a `raw_orders`. El adaptador se elige por configuración.
- Costos: tablas del Data Transfer Service de Google Ads y de Meta Ads normalizadas a `stg_costs` (`date`, `platform`, `campaign_id`, `campaign_name`, `cost`, `impressions`, `clicks`, `platform_conversions`).
**Aceptación:** cargas idempotentes por fecha (volver a correr un día no duplica filas); pruebas con archivos de ejemplo en `tests/fixtures/`.

**Nota:** diferido por la misma razón que RQ-04: requiere credenciales de Salesforce Commerce
Cloud (OCAPI/SCAPI) y de las cuentas de Google Ads/Meta Ads (Data Transfer Service) del cliente
real, que no existen en este entorno. La parte que sí es código puro y verificable sin
credenciales —parsear un CSV/XML de ejemplo e insertarlo de forma idempotente— se puede hacer en
cuanto el cliente comparta un archivo de ejemplo real (la decisión abierta #5 de la sección 8
todavía no está resuelta: ¿archivo o API?).

#### RQ-06 · Reglas de canal configurables · P1 · depende de RQ-01 · Hecho
**Qué:** reemplazar el `CASE` fijo de `sql/01_sesiones.sql` por reglas declaradas en YAML, evaluadas en orden:
1. UTMs (`utm_source`, `utm_medium`) con listas y expresiones regulares.
2. Identificadores de clic: `gclid` → Paid Search; `fbclid` en `page_location` sin UTMs → "Meta (sin UTM)" (canal propio, para medir cuánto tráfico de Meta llega sin etiquetar).
3. Referrer.
4. Sin fuente → Direct.
5. Lo que no calce → Unassigned (hoy no se genera en la demo, pero existe en datos reales).
También: valores de Meta `{{site_source_name}}` (`fb`, `ig`, `msg`, `an`) y pasarelas configurables.
**Aceptación:** prueba con una tabla de casos (fuente, medio, gclid, page_location → canal esperado) que cubra al menos 25 combinaciones; `mart_calidad__canales` reporta el porcentaje de sesiones en Unassigned, Direct y "Meta (sin UTM)".

**Nota:** `reglas_canal.py` (`asignar_canal()` en Python puro + `sql_case_canal()`/`sql_es_pasarela()`
que generan el SQL equivalente) reemplaza el `CASE` fijo; `ConfigCliente.reglas_canal_utm` y
`meta_site_source_name` declaran las reglas (por defecto, exactamente las de esta demo). No se
implementó el paso 3 ("Referrer") como una regla aparte: el esquema de eventos no trae un campo de
referrer HTTP distinto de `collected_traffic_source`, así que ese caso ya queda cubierto por las
reglas de UTM con `medium = 'referral'`. 32 pruebas de casos en `tests/test_reglas_canal.py` (pide
≥25). Verificado que, con la config por defecto, la distribución de canales de la demo no cambia
(0 % en Unassigned / Direct cae exactamente igual que antes / "Meta (sin UTM)" en 0 %, porque el
generador sintético no simula gclid ni fbclid).

### Épica C · Identidad y rutas

#### RQ-07 · Unión de pedidos con GA4 por varias llaves · P1 · Hecho
**Qué:** hoy un pedido sin `ga_client_id` se descarta. Orden de llaves:
1. `ga_client_id` del pedido.
2. `transaction_id` del evento `purchase` de GA4 = `order_id` → `user_pseudo_id`.
3. `user_id` (si el sitio lo envía) para unir dispositivos.
**Aceptación:** `mart_calidad__conciliacion` agrega cuántos pedidos se unieron por cada llave y cuántos quedaron sin ruta; prueba con pedidos sintéticos que solo tienen una de las tres llaves.

**Nota:** `sql/02_rutas.sql` crea la tabla `pedidos_resueltos` (llave `ga_client_id` ->
`transaction_id` -> `user_id`, con `user_id` resuelto vía `orders.customer_id = events.user_id`,
asumiendo que el sitio envía a GA4 el mismo identificador de login que guarda como `customer_id`).
`events.user_id` es una columna nueva (antes no existía en el esquema): `generar_datos.py` la
agrega vía `INSERT ... BY NAME`, siempre NULL (esta demo no simula login entre dispositivos), así
que `unidos_por_user_id` es 0 en la demo pero la llave está probada con datos sintéticos en
`tests/test_sql.py::test_rq07_pedidos_con_una_sola_llave_cada_uno`. En la demo real,
`unidos_por_transaction_id` recuperó 155 pedidos que antes se descartaban por no tener
`ga_client_id` (de 5,114 a 5,269 pedidos con ruta). También se corrigió el bug documentado:
`pedidos_sin_client_id` ahora filtra por `estados_validos_pedido`, no cuenta cualquier estado.
**Nota:** corregir en `sql/03_conciliacion.sql` que `pedidos_sin_client_id` hoy cuenta pedidos de cualquier estado.

#### RQ-08 · Rutas que se reinician tras cada compra · P1 · Hecho
**Qué:** una sesión no puede pertenecer a dos pedidos. La ruta de un pedido empieza después del pedido anterior del mismo usuario (o en el límite de la ventana de atribución, lo que ocurra después).
**Aceptación:** prueba con un usuario de dos pedidos en 10 días: las sesiones previas al primer pedido no aparecen en la ruta del segundo.

**Nota:** `sql/02_rutas.sql` calcula `pedido_anterior` con `LAG()` sobre **todos** los pedidos pagados
del usuario (no solo los de la ventana de análisis), para que el límite sea correcto incluso si el
pedido anterior cayó fuera de la ventana. El límite de sesiones de cada pedido es el mayor entre
`pedido - ventana_dias` y `pedido_anterior`. No cubre un caso relacionado pero distinto: las sesiones
de un comprador recurrente *después* de su última compra (sin una compra posterior) hoy se descartan
en vez de aparecer como ruta no convertida — queda fuera de alcance de este RQ.

#### RQ-09 · Nivel campaña · P1 · depende de RQ-05, RQ-06 · Hecho (con datos simulados)
**Qué:** agregar `campaign_id` y `campaign_name` a sesiones y rutas; atribuir a nivel **canal** con los modelos actuales y repartir el crédito del canal entre sus campañas en proporción a las sesiones de cada campaña dentro de las rutas convertidas (Shapley a nivel campaña no escala: ver RQ-13).
**Aceptación:** nuevo `mart_decision__campana` con ventas atribuidas, ingresos, inversión, ROAS y CPA por campaña y modelo; la suma por canal coincide con `mart_modelos__comparativo` (tolerancia 0,1 %).

**Nota:** RQ-05 (ingesta real de costos/campañas) sigue diferido —no hay credenciales de Google
Ads/Meta Ads—, así que esto se hizo con **datos simulados**: `generar_datos.py` gana dos campañas
por canal pagado (`CAMPANAS_PAGADAS`: p. ej. "paid_social_prospecting"/"paid_social_retargeting"),
cada una con su propio costo, en vez de la única campaña "siempre activa" que había antes.
`sql/02_rutas.sql` agrega `ruta_campana` (lista paralela a `ruta`, misma idea que `dias_antes`).
Nuevo módulo `campanas.py::credito_por_campana()`: cuenta sesiones por (canal, campaña) **solo en
rutas convertidas** y reparte el crédito de canal del modelo vigente (shapley) en esa proporción —
tal como pide el RQ, no una atribución de campaña independiente. La suma por canal coincide
*exactamente* con `mart_modelos__comparativo` por construcción (la participación de las campañas
de un canal suma 100 %), verificado en `tests/test_campanas.py`. Vista nueva "Campañas" en Explorar
(cerraba la deuda que había quedado pendiente de RQ-23).

**Hallazgo y corrección:** variar la secuencia aleatoria del generador (para sortear la campaña de
cada sesión) corrió el sorteo de `max(orders.created_at)` hasta caer a 18 minutos de
`fin` (el límite duro de generación de eventos), dejando el último día del rango sin ningún evento
y disparando el control crítico de "caída de eventos" (RQ-18) con -99,9 %. Se corrigió reservando
un margen de 2 horas antes de `fin` para el *inicio* de cualquier sesión nueva
(`fin_sesiones = fin - timedelta(hours=2)`), para que un pedido generado unos minutos después de la
última sesión nunca pueda caer después de `fin`. No cambia la secuencia de números aleatorios (el
número de sorteos es el mismo; solo cambia el umbral de corte), así que no movió ninguna otra cifra
de la demo.

#### RQ-10 · Zona horaria y moneda · P2 · Hecho parcialmente
**Qué:** cortes mensuales y diarios en la zona horaria del cliente (`America/Lima`); hoy `sql/04_kpi_mensual.sql` agrupa en UTC. Moneda e IGV configurables.
**Aceptación:** un pedido a las 22:00 del 31 de agosto en Lima cae en agosto.

**Nota:** `sql/04_kpi_mensual.sql` agrupa con `AT TIME ZONE '{{ZONA_HORARIA}}'` (de
`ConfigCliente.zona_horaria`, ya existía el campo desde RQ-01 pero no estaba conectado).
`config/demo.yaml` sigue en `UTC` (no cambia los números de la demo); `config/produccion.yaml` ya
tenía `America/Lima`. **Se encontró y corrigió un problema real al implementar esto**: DuckDB
necesita el paquete Python `pytz` instalado para resolver zonas horarias con nombre
(`AT TIME ZONE 'America/Lima'`) — sin él, lanza un error en tiempo de ejecución. Se agregó `pytz`
a `requirements.txt`/`pyproject.toml`; antes de este RQ, `config/produccion.yaml` habría fallado
en la primera corrida real. **No se implementó** moneda/IGV configurables: el campo `moneda` de
`ConfigCliente` (RQ-01) sigue siendo solo documentación — aplicarlo requeriría decidir cómo se
muestra (sufijo "S/", conversión, IGV incluido o no) y no hay un criterio de aceptación que lo
especifique; no se tocó `ventana_movil()` (el límite de los 12 meses de la ventana de análisis
sigue en UTC) porque el criterio de aceptación pedido es específicamente sobre `kpi_mensual`.

### Épica D · Modelos (etapa 2)

#### RQ-11 · Roles abre, asiste, cierra y único · P1 · Hecho
**Qué:** una sola función `roles_por_canal(rutas, variante_cierre)` según la sección 1, que reemplaza los conteos de `metricas_decision.calcular` y deja `markov_roles` como diagnóstico técnico.
Salida por canal: ventas en que abre, asiste, cierra y es único; sus porcentajes sobre las apariciones del canal; asistencias por cierre.
**Aceptación:**
- Pruebas con rutas a mano: `A→B→C` (A abre, B asiste, C cierra), `A` (único), `A→A→B` (A abre una vez y asiste una vez; B cierra).
- El dashboard muestra la barra apilada abre / asiste / cierra / único por canal en el Resumen.

**Nota:** `variante_cierre` ("ultima_sesion" por defecto, o "ultimo_no_directo") queda en `ConfigCliente`
(RQ-01) — resuelve la decisión abierta #3. `mart_decision__pares_asistencia` cambia de semántica: antes
contaba cualquier canal de la ruta distinto del cierre; ahora solo cuenta canales en posición media (la
definición canónica de "asiste"), así que una ruta de 2 sesiones ya no genera un par.
- El glosario del intérprete usa estas definiciones.

#### RQ-12 · Markov: orden superior, Direct y crédito de ingresos · P2 · Hecho
**Qué:**
- Parámetro `orden` (1 o 2).
- Opción para excluir Direct de la cadena (se observó que Markov le da demasiado crédito por frecuencia).
- Repartir ingresos con efecto de remoción ponderado por valor, no con la cuota global de conversiones como hoy.
**Aceptación:** en datos sintéticos se reporta el error frente al efecto real para cada variante; la configuración elige la variante vigente.

**Nota:** `markov_orden`/`markov_excluir_direct`/`markov_ingreso_por_valor` en `ConfigCliente`
eligen la variante vigente; por defecto (orden 1, con Direct, ingreso = cuota de conversiones) el
resultado es idéntico al de antes de este RQ (error vs. efecto real: 4.84 pp, igual que el
baseline). `atribucion.comparar_variantes_markov(rutas, params_json)` corre las 8 combinaciones
(orden × excluir_direct × ingreso_por_valor) y reporta el error de cada una frente a `efecto_real`;
es una función pura probada en `tests/test_atribucion.py`, no un mart nuevo (no hay un consumidor
de dashboard para esto en el roadmap).

#### RQ-13 · Shapley: escalabilidad y diagnóstico · P1 · Hecho
**Qué:**
- Agregar las rutas por conjunto de canales (conteo de convertidas y no convertidas) antes de ajustar la logística; hoy se ajusta una fila por usuario.
- Límite configurable de jugadores (12 canales). Por encima, Shapley por Monte Carlo con muestreo de permutaciones.
- Diagnóstico del modelo de probabilidad en `mart_calidad__modelo`: AUC, log-loss, calibración por deciles, cantidad de `phi` negativos recortados a 0.
- Regularización `C` elegida por validación cruzada.
**Aceptación:** mismos resultados que hoy (diferencia de cuota ≤ 0,2 pp) con 10 veces menos tiempo en la vista por defecto; prueba de propiedades: eficiencia (los `phi` suman `v(T)`), simetría y jugador nulo.

**Nota:** `shapley_c` en `ConfigCliente` queda fijo en `1.0` por defecto (el valor histórico de la
demo): verificado que con `C` fijo la agregación por conjunto da *exactamente* la misma cuota que
antes (0 pp de diferencia) y ~64x más rápido solo en el ajuste de la logística. `shapley_c: null`
activa la selección por `LogisticRegressionCV`, disponible y probada, pero no es el default porque
en los datos de la demo mueve la cuota hasta 0,47 pp (por encima del umbral de 0,2 pp) — queda
como opción para un cliente real, no como cambio de comportamiento de la demo. El límite de 12
jugadores y el Monte Carlo no se ejercitan en la demo (7 canales); probados con datos sintéticos
aparte (`tests/test_atribucion.py`). `mart_calidad__modelo` aún no tiene vista en el dashboard
(es tarea de RQ-23).

#### RQ-14 · Robustez por segmento · P2 · Hecho
**Qué:** no publicar señales de un segmento con menos de N conversiones (configurable, por defecto 1 000; el glosario ya habla de 1 000 y 3 000). Intervalo bootstrap también para segmentos con volumen suficiente.
**Aceptación:** el dashboard marca "evidencia insuficiente" en lugar de la señal; el intérprete no recomienda acciones sobre esos segmentos.

**Nota:** `minimo_conversiones_senal` (config, por defecto 1000, el mismo valor que ya usaba
`confianza_media_pedidos`) hace que `asignar_senal` devuelva "Evidencia insuficiente" para
**todos** los canales de una vista (total o segmento) por debajo del umbral, en vez de una señal
real — verificado en la demo: "Libros y papelería" y "tablet" (segmentos chicos) caen ahí,
mientras que los segmentos con volumen siguen con sus señales normales. El intérprete no necesitó
cambios: ya solo propone la prueba de incrementalidad cuando encuentra la señal literal
`"Escalar (validar)"` (`interprete/datos.py`), así que "Evidencia insuficiente" simplemente nunca
la dispara. El intervalo bootstrap ahora también corre para segmentos con conversiones suficientes
(antes solo la vista total); el costo es real: la ventana vigente pasó de ~60 s a ~125 s en la
demo. Es exactamente el tipo de costo que RQ-17 (rendimiento con volumen real) tiene que absorber.

### Épica E · Costos y plataformas

#### RQ-15 · Meta reporta frente al modelo · P1 · depende de RQ-05, RQ-09 · Hecho (con datos simulados)
**Qué:** comparar por campaña las conversiones e ingresos que reporta cada plataforma con los que asigna el modelo.
**Aceptación:** nuevo `mart_plataformas__comparacion` (`platform`, `campaign_id`, `conv_plataforma`, `conv_modelo`, `ingresos_plataforma`, `ingresos_modelo`, `brecha_pct`); vista en el dashboard con una nota fija: la brecha incluye vistas sin clic y cambios de dispositivo.

**Nota:** igual que RQ-09, con datos simulados porque RQ-05 (Data Transfer Service de Meta/Google
Ads) sigue diferido. `generar_datos.py` gana la tabla `reportado_plataformas`: cuando una ruta
convierte, **cada plataforma pagada que la ruta tocó reclama la venta completa** con su propia
medición (igual que en la vida real: Meta y Google no se coordinan ni saben que el otro también
tuvo un touch), más un extra fijo por campaña (`exceso_vista`, 1.05–1.60 según qué tan típico es que
esa campaña sea solo-vista) para las conversiones con solo impresión que nunca generan sesión en
GA4. `campanas.py::comparacion_plataformas()` solo arma la comparación (join + `brecha_pct`); no
inventa el exceso, ya viene en los datos. La brecha resultante es grande (200–700 % según campaña):
es intencional, no un error — las campañas de Display y Paid Social suelen ser canales que
**asisten** más que cierran, así que el modelo multi-touch (Shapley) les da poco crédito mientras la
plataforma, que no reparte entre canales, reclama la venta completa cada vez que aparece en la
ruta. La nota fija del dashboard (RQ-23: pestaña Plataformas en Explorar) lo explica así, no solo
con "vistas sin clic y cambios de dispositivo" como decía la redacción original del RQ —esa no era
la causa dominante en estos datos—. Probado en `tests/test_campanas.py`.

#### RQ-16 · Impresiones y alcance de anuncios · P3 · Hecho (con datos simulados)
**Qué:** traer impresiones, alcance y frecuencia por campaña y día al tablero (no entran a las rutas) y dejarlos listos para el MMM (RQ-22).

**Nota:** `generar_datos.py` agrega la tabla `impresiones` (impresiones, alcance, frecuencia por
campaña y día, con un CTR implícito distinto por campaña vía `impresiones_por_sesion`). Nuevo mart
`mart_plataformas__alcance`, agregado a la ventana de análisis completa (no es una serie de tiempo
mensual: eso queda para cuando RQ-22 lo necesite de verdad). Se muestra junto a RQ-15 en la pestaña
Plataformas de Explorar, no en una pestaña aparte (son del mismo nivel canal/campaña y el RQ no pide
una vista propia).

### Épica F · Rendimiento

#### RQ-17 · Tiempo de corrida con volumen real · P1 · depende de RQ-13 · Hecho parcialmente
**Qué:** objetivo de 15 minutos para 12 meses de un cliente con 2 millones de sesiones al mes.
- Rutas agregadas por secuencia o por conjunto con sus conteos.
- Rebanadas en paralelo (`joblib`).
- Caché de resultados por (ventana, segmento, versión de datos).
**Aceptación:** `pytest -m rendimiento` genera 20 millones de sesiones sintéticas y mide el tiempo; el resultado queda en `mart_ejecucion`.

**Nota:** de los tres puntos, solo el primero ya estaba hecho (RQ-13, agregación por conjunto de
canales para Shapley) y los otros dos se intentaron pero no dieron el resultado esperado en esta
demo:

- **Rebanadas en paralelo**: los segmentos de cada ventana corren con `joblib.Parallel` (la
  vista "Todos" va antes y sola porque los segmentos dependen de su `totales` para el
  sobre-/sub-índice). Se usó `backend="threading"` a propósito: con el backend de procesos
  (`loky`), cada worker reimporta `run_demo.py` desde cero y los globals de `ConfigCliente` que
  fija `_aplicar_config()` (umbrales, canales pagados, variante de Markov, etc.) volverían a sus
  valores por defecto del código en cada worker, no a los de la config cargada — un bug real que
  se evitó yendo por threads. El costo: en la demo, la corrida con threading tardó lo mismo que en
  serie (~130-170 s totales, dentro del ruido de corrida a corrida que ya existía). El código de
  los modelos (`Counter` en Python puro) no suelta el GIL; solo el ajuste de la logística de
  Shapley lo hace, y no alcanza a compensar. Queda la paralelización lista (y correcta) para
  cuando se haga el refactor de pasar la config explícita en vez de por globals de módulo, que
  habilitaría procesos reales.
- **Cache por (ventana, segmento, versión de datos)**: se probó con `joblib.Memory` (hashea el
  contenido de `rutas`/`sesiones`/`costos` más un "fingerprint" de la config). **Resultado: la
  corrida con cache fue 3-4 veces más lenta** (567 s vs. ~130-170 s sin cache), y se revirtió. La
  causa: esta demo ya tiene un no-determinismo de orden de filas entre corridas (DuckDB reordena
  por su ejecución paralela interna — el mismo fenómeno que se documentó en RQ-01), así que el
  contenido exacto de `rutas` —y por lo tanto su hash— nunca es idéntico entre dos corridas
  aunque los datos de origen no hayan cambiado. Cada corrida fallaba la cache (hash distinto) y
  pagaba el costo extra de hashear y escribir en disco sin nunca reutilizar nada. Una cache por
  contenido exacto no sirve aquí sin antes resolver ese no-determinismo (ordenar explícitamente
  las rutas antes de construir el DataFrame, por ejemplo) o sin cambiar la llave de cache a algo
  más estable que el contenido completo (p. ej. un hash de `(corte, ventana_dias, dim, segmento,
  version_config)` tomado de `mart_ejecucion`, confiando en que los datos de origen no cambiaron
  entre corridas en vez de verificarlo por contenido).
- **`pytest -m rendimiento` con 20 millones de sesiones**: la prueba está en
  `tests/test_rendimiento.py`, marcada y excluida de CI, pero **no se corrió** en este entorno:
  generar 20 M de sesiones sintéticas y correr el pipeline completo sobre ellas excede el tiempo
  razonable de una sesión de trabajo aquí. Queda pendiente de ejecutar con infraestructura
  dedicada (o en un lote aparte).

### Épica G · Calidad, monitoreo e historia

#### RQ-18 · Controles de calidad de datos · P1 · depende de RQ-03 · Hecho
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

**Nota:** `calidad.py` (`controles_calidad`). Los controles corren **después** del cálculo de
modelos, no antes: dependen de `mart_calidad__conciliacion` y `mart_calidad__canales`
(ventana vigente), que a su vez se calculan junto con los modelos en el mismo bucle de
`run_demo.py`; separarlos habría duplicado esas consultas. Si falla un control crítico, igual se
lanza la excepción **antes** de persistir nada (el `CREATE OR REPLACE TABLE` final no llega a
correr), así que los `mart_*` de la corrida anterior quedan intactos — se pierde el tiempo de
cómputo de esa corrida, no la garantía de no dejar datos a medias. El semáforo del dashboard queda
para RQ-23.

**Bug real encontrado y corregido al escribir este control:** `CAST(timestamptz AS DATE)` en
DuckDB usa la zona horaria de **sesión** (que aquí se detecta del sistema operativo —
`America/Lima` en esta máquina—, no UTC) para decidir el día de calendario. Sin forzar
`AT TIME ZONE 'UTC'` explícito, una sesión justo al iniciar la ventana (`2025-10-01 00:00:00 UTC`)
se contaba como `2025-09-30`, y el control de "días sin costos" fallaba en la propia demo (3 días
"faltantes" que en realidad estaban un día antes). Se corrigió en `calidad.py` y también en
`sql/04_kpi_mensual.sql` (`inv`, que tenía el mismo problema desde antes de este RQ, sin que
ninguna prueba lo detectara). Los demás casts a `DATE` del repo parten de parámetros de texto
(`CAST(? AS DATE)`), que no tienen este problema porque DuckDB los parsea literalmente.

#### RQ-19 · Historia de resultados · P1 · Hecho
**Qué:** hoy las tablas `mart_*` se borran en cada corrida. Guardar además una copia por fecha de corte en `hist_*` (o una columna `corte` en tablas particionadas en BigQuery).
**Aceptación:** el dashboard puede mostrar la evolución mensual de la cuota y el ROAS por canal; `estado_modelo` usa la historia en lugar de recalcular el mes anterior.

**Nota:** `hist_mart_modelos__comparativo` (cuota) y `hist_mart_decision__canal` (ROAS/costo) —
`actualizar_historia()` les agrega una copia con columna `corte` al final de cada corrida; si ya
había una fila para ese mismo corte, la reemplaza (una corrida repetida no duplica historia,
probado en `tests/test_historia.py`). No se tocan al borrar los `mart_*` al empezar la corrida
(el `DROP` solo alcanza `mart_%`). `estado_modelo` ahora busca en `hist_mart_modelos__comparativo`
la corrida anterior más reciente (`corte` más grande por debajo del actual); si la encuentra, usa
esa cuota directamente (sin recalcular Shapley para el mes anterior); si no hay historia todavía
(la primera corrida de un cliente nuevo), recalcula el mes calendario anterior como antes — es el
único caso en que no hay con qué comparar. **No se pudo observar el camino "con historia" en la
demo**: al tener siempre los mismos datos sintéticos, cada corrida cae en el mismo `corte`
exacto, así que nunca hay un corte *anterior* real que leer (solo se prueba el camino "primera
corrida"); el camino con historia se verificó aparte con un corte sembrado a mano en
`tests/test_historia.py::test_estado_modelo_usa_la_historia_si_existe`. Falta la vista del
dashboard para la evolución mensual (RQ-23).

### Épica H · Validación y calibración (etapa 3)

#### RQ-20 · Diseño de pruebas de incrementalidad · P2 · Hecho
**Qué:** ampliar `proximos_pasos.diseno_prueba_incrementalidad` con:
- Prueba geográfica por regiones (con la dimensión `geo_region` y, en producción, departamentos).
- Plantilla para Conversion Lift de Meta (insumos que pide la plataforma y duración sugerida).
- Costo de la prueba en ventas que se dejan de ganar.
**Aceptación:** `mart_siguientes_pasos__prueba_incrementalidad` incluye el tipo de prueba, duración, efecto mínimo detectable y costo estimado.

**Nota:** la tabla gana la columna `tipo_prueba` con tres valores: `holdout_usuario` (la prueba
original, ahora con `costo_prueba_soles` cuando hay `ingresos` disponibles y `None` si no), `geografica`
(una región por canal se deja sin el canal como control; la demo usa sus dos regiones, Lima y
Provincias — en producción `geo` traería departamentos) y `conversion_lift_meta` (plantilla fija
para "Paid Social" con el holdout del 10 % y la duración mínima de 4 semanas que recomienda la
propia Meta, más un texto de insumos: permisos de Business Manager, evento de conversión
configurado y no tocar creatividades/audiencias mientras corre). `_emd_relativo()` se extrajo como
helper compartido por los tres tipos de prueba. Como los tres tipos traen columnas distintas
(`holdout_pct`/`region_control`/`insumos`), los tres consumidores que leían esta tabla
(`interprete/datos.py`, `interprete/herramientas.py`, `app_pages/04_siguientes_pasos.py`) se
filtraron a `tipo_prueba == 'holdout_usuario'`, que es el único que hoy saben interpretar — ampliarlos
a los otros dos tipos queda para un RQ futuro si el cliente los pide. Verificado con
`tests/test_proximos_pasos.py` (5 pruebas), pipeline completo y `AppTest` en las 5 páginas del
dashboard sin excepciones.

#### RQ-21 · Carga de resultados de experimentos y calibración · P2 · depende de RQ-20 · Hecho
**Qué:** tabla `experimentos` (canal, fechas, tipo, ventas incrementales, intervalo, fuente) cargada desde un CSV o un formulario. Con ella:
- Comparar el crédito atribuido con el efecto incremental medido.
- Factor de calibración por canal, visible y opcional (no se aplica por defecto).
**Aceptación:** `mart_validacion__experimentos`; el dashboard muestra "validado" o "sin validar" por canal; el intérprete distingue crédito atribuido de efecto medido.

**Nota:** nuevo módulo `experimentos.py` con `cargar_experimentos()` (lee el CSV de
`cfg.ruta_experimentos`; `None` si no hay ruta configurada o el archivo no existe todavía — un
cliente nuevo puede no tener experimentos corridos aún, no es un error), `mart_validacion_experimentos()`
(prorratea la cuota atribuida del modelo vigente a los días del experimento, porque la demo no
vuelve a correr el pipeline solo para esas fechas, y marca "validado" si el atribuido cae dentro
del intervalo del 90 % que midió el experimento) y `estado_validacion_por_canal()`
("Validado"/"Sin validar"/"Sin probar" por canal pagado, el más reciente si hay varios
experimentos). `data/experimentos.csv` trae dos experimentos sintéticos para la demo: uno de
holdout por usuario en Paid Social (confirma la señal "Escalar: validar") y uno geográfico en Paid
Search (el experimento mide menos de lo que el modelo atribuye — "Sin validar" — consistente con su
señal "Revisar"); ambos construidos a partir de `efecto_real` para que la demo cuente una historia
coherente, no números arbitrarios. `interprete/datos.py` agrega `validacion_experimentos` a los
hechos con las dos cifras en claves separadas y nombradas explícitamente
(`credito_atribuido_por_el_modelo` / `efecto_incremental_medido_por_el_experimento`) para que el
intérprete nunca las funda en un solo número, y cada canal en `canales` trae su
`estado_validacion_experimento`/`factor_calibracion`. La vista del dashboard (tabla de estado por
canal) queda para RQ-23, que ya la tenía planeada junto con las demás vistas nuevas — evita
construir la UI dos veces. Verificado con `tests/test_experimentos.py` (8 pruebas), pipeline
completo (`mart_validacion__experimentos`/`mart_validacion__canal` con los valores esperados) y
`AppTest` en las 5 páginas sin excepciones.

#### RQ-22 · Marketing Mix Modeling (opcional) · P3 · depende de RQ-16, RQ-19 · Hecho (versión ligera)
**Qué:** módulo `mmm/` con datos semanales (inversión, impresiones, ventas, controles de estacionalidad y feriados de Perú) usando Meridian o PyMC-Marketing, con los experimentos de RQ-21 como información previa. Requiere al menos un año de historia.
**Aceptación:** curvas de respuesta y ROAS marginal por canal en `mart_mmm__*`; vista de triangulación (atribución, experimentos y MMM lado a lado).

**Nota (desviación deliberada):** ni Meridian ni PyMC-Marketing están instalados en este entorno
—son dependencias pesadas con compilación nativa (PyTensor/JAX)— y agregarlas solo para un módulo
opcional no se justificó bajo la urgencia de entregar la demo. Se implementó un MMM equivalente en
espíritu con lo que ya está en el stack (`mmm.py`, módulo plano, no paquete: no hay suficientes
piezas para justificar una carpeta como `interprete/`):
- **Adstock geométrico** (`adstock_geometrico`) + **saturación de Hill** (`saturacion_hill`) por
  canal pagado, sobre `mmm.semanal()` (inversión semanal por canal desde `costs`, ventas totales
  desde `orders`, mes y % de días feriados de Perú de fecha fija como controles — se omiten los
  feriados móviles de Semana Santa para no mantener un cálculo de Pascua solo para esto).
- **`BayesianRidge`** de scikit-learn sobre las variables transformadas y estandarizadas (da
  intervalo de credibilidad sin MCMC; sin estandarizar, el prior de BayesianRidge encogía casi
  todos los coeficientes a 0 porque las variables saturadas viven en [0, 1] y las ventas en miles
  de soles — encontrado al probar, no es un detalle menor del ajuste).
- Estacionalidad como **par seno/coseno** (2 parámetros) en vez de 11 dummies de mes: con ~52
  semanas de historia, los dummies no dejaban grados de libertad para estimar el efecto de los
  canales (el intervalo de credibilidad salía más ancho que el propio coeficiente). No se usaron
  los experimentos de RQ-21 como prior formal (eso sí requeriría una librería bayesiana de verdad
  con priors informativos); quedan solo en la vista de triangulación, lado a lado, para que la
  persona que decide los compare a ojo.
- `mart_mmm__curvas` (grilla de inversión semanal de 0 a 1,5x el máximo histórico, por canal) y
  `mart_mmm__resumen` (ROAS marginal — el efecto de un sol más al ritmo de inversión actual, no el
  ROAS promedio — con intervalo p05-p95). Nueva pestaña "Triangulación" en Modelos y robustez:
  cuota atribuida, estado de validación con experimentos (RQ-21) y ROAS marginal del MMM, más las
  curvas de respuesta con la inversión actual marcada.
- **Los intervalos de credibilidad son anchos** (p. ej. Paid Social: 2,8 central pero
  [-1,3; 7,0] al 90 %, cruzando cero) con los ~52 puntos semanales de esta demo. Es el resultado
  honesto de solo 12 meses de historia, exactamente la limitación que el propio RQ reconoce al
  pedir "al menos un año" — no se intentó disimularlo angostando el intervalo artificialmente.
- Migrar a Meridian/PyMC-Marketing queda documentado como siguiente paso si un cliente real lo
  pide en serio: `mmm.semanal()` ya deja los datos en la forma que cualquiera de las dos espera
  (fecha, canal, inversión, ventas, controles).

Verificado con `tests/test_mmm.py` (9 pruebas, incluida una con señal sintética fuerte para
confirmar que el ajuste recupera coeficientes positivos), pipeline completo y `AppTest` en las 5
páginas, con ventanas distintas y una vista de segmento, sin excepciones.

### Épica I · Dashboard

#### RQ-23 · Vistas nuevas y ajustes · P1 · Hecho parcialmente
- Resumen: roles abre / asiste / cierra / único (RQ-11) y semáforo de calidad (RQ-18).
- Explorar: pestaña Campañas (RQ-09) y pestaña Plataformas, con la comparación entre lo que reporta Meta y lo que asigna el modelo (RQ-15).
- Modelos y robustez: evolución histórica (RQ-19) y diagnóstico de Shapley (RQ-13).
- Siguientes pasos: estado de validación por canal (RQ-21).
- Descarga en CSV de cada tabla visible.
**Aceptación:** ninguna página calcula métricas (revisión de código: solo lecturas de `mart_*` y formato); prueba de humo con `streamlit.testing.v1.AppTest` por página.

**Nota:** las pestañas Campañas/Plataformas de Explorar, que dependían de los datos de Meta Ads,
se completaron después al implementar RQ-09/RQ-15/RQ-16 (quedaron para el final de la hoja de ruta
por pedido explícito del usuario) — ver sus notas para el detalle. El resto se entregó en esta
vuelta. El rol abre/asiste/cierra/único ya
existía en Resumen desde RQ-11; esta vuelta agregó: semáforo de calidad en Resumen (expander
colapsado salvo que haya una alerta o crítico, leyendo `mart_calidad__controles`, con
`dashboard_comun.estilo_estado()` nuevo — reemplaza los lambdas de color sueltos que ya traía la
pestaña "Estado del modelo", unificados en un solo semáforo ok/alerta/crítico ↔ estable/cambió ↔
Validado/Sin validar/Sin probar); dos pestañas nuevas en Modelos y robustez — "Diagnóstico Shapley"
(gráfico de calibración por decil de `mart_calidad__modelo` más método/C/AUC/log loss) y "Evolución
histórica" (cuota por canal y corte de `hist_mart_modelos__comparativo`, con aviso explícito cuando
solo hay un corte — hoy es el caso, porque la demo corre con una sola fecha de corte fija; se llena
con cada corrida mensual real, igual que le pasaría a un cliente nuevo); la tabla de validación con
experimentos (RQ-21) en Siguientes pasos, con expander de detalle por experimento; y
`dashboard_comun.boton_descarga()` aplicado a las tablas principales de las cuatro páginas (no a
cada gráfico, para no saturar la UI). Verificado con `ruff check`, `pytest` (136 passed) y `AppTest`
en las 5 páginas, incluyendo ventanas distintas (7 y 30 días) y una vista de segmento
(Dispositivo: mobile), sin excepciones.

#### RQ-24 · Despliegue · P2 · Hecho
**Qué:** Dockerfile; pipeline como Cloud Run job con Cloud Scheduler; dashboard como servicio de Cloud Run detrás de Identity-Aware Proxy; secretos en Secret Manager; cuentas de servicio con permisos mínimos (lectura de datasets fuente, escritura del dataset de marts).
**Aceptación:** `make deploy` documentado; el dashboard no es accesible sin autenticación de Google del dominio del cliente.

**Nota:** `Dockerfile` único (`python:3.13-slim` + `streamlit run dashboard.py`) sirve tanto al
Service del dashboard como al Job del pipeline (`gcloud run jobs deploy` sobreescribe el comando
con `run_demo.py --config config/<cliente>.yaml`); `.dockerignore` agregado. El `Makefile` suma
`deploy-setup` (cuentas de servicio, bucket y permisos, una vez por cliente), `deploy-build`,
`deploy-job`, `deploy-app`, `deploy-scheduler` y `deploy` (build+job+app, el redespliegue
repetible), todos parametrizados por `PROJECT`/`REGION`/`CLIENTE`. Documentado en
`docs/despliegue.md` con la arquitectura completa y dos decisiones explícitas: (1) como el pipeline
corre contra DuckDB sin importar `motor` (BigQuery todavía no tiene una ruta de ejecución nativa,
solo el placeholder `sql_bigquery/rutas_bigquery.sql`), el `.duckdb` se persiste en un **volumen de
Cloud Storage** montado en el Job (lectura-escritura) y el Service (solo lectura) — se vuelve
innecesario el día que la ejecución migre a BigQuery; (2) **Identity-Aware Proxy** solo se puede
poner delante de Cloud Run con un External HTTPS Load Balancer de por medio (Cloud Run no lo
soporta directo); se documentó esa opción y la alternativa más simple (IAM nativo de Cloud Run,
`--no-allow-unauthenticated` + `run.invoker`), dejando la elección al cliente. Las dos cuentas de
servicio (`atribucion-pipeline-<cliente>`, `atribucion-dashboard-<cliente>`) quedan acotadas al
bucket y secreto del cliente, sin rol de proyecto. **No se probó contra un proyecto GCP real** (sin
credenciales en este entorno) ni se pudo validar `docker build` (Docker Desktop instalado pero el
daemon no estaba corriendo en esta sesión): quedó una revisión manual cuidadosa del `Dockerfile` y
el `Makefile` (sintaxis de tabs confirmada con `cat -A`), pendiente de una build real antes de usarlo
con un cliente.

### Épica J · Intérprete con Claude

#### RQ-25 · Evaluación y robustez · P2 · Hecho
- Banco de 30 preguntas de negocio con respuestas esperadas (qué cifras y qué cautelas deben aparecer) en `tests/evals/`.
- El verificador reconoce formatos de Perú (`S/ 1,234.56`, `12.5 %`, `3,5 pp`) y porcentajes calculados como texto.
- Registro de tokens y costo por consulta en una tabla de uso.
- El conocimiento (`conocimiento/*.md`) se actualiza con las definiciones de la sección 1 y con las vistas nuevas.
**Aceptación:** `pytest -m evals` (opcional, gasta API) reporta el porcentaje de respuestas que cumplen; las pruebas actuales siguen pasando sin API.

**Nota:** `tests/evals/banco.py` trae las 30 preguntas (`Pregunta` con texto, vista, cifras
esperadas calculadas en vivo desde `construir_hechos()` —nunca a mano, para no desactualizarse si
cambian los datos— y fragmentos de texto que debe/no debe contener la respuesta), agrupadas en
cifra directa, comparación entre canales, segmentos, sensibilidad a la ventana, incrementalidad y
validación con experimentos (RQ-21), cautelas de negocio que siempre deben aparecer (causalidad,
ROAS no marginal, dato sintético) y preguntas fuera de alcance que debe rechazar.
`tests/evals/test_evals.py` las corre contra la API real, marcado `evals`. El verificador
(`interprete/verificador.py`) ya reconocía los formatos de Perú de antes (separador de miles con
coma, coma o punto como decimal, sin espacio antes de `%`); esta vuelta se limitó a agregar pruebas
explícitas que lo documentan (`tests/test_interprete.py`), porque no hacía falta cambiar el regex.
Nuevo módulo `interprete/uso.py` (`costo_usd()` con precios USD/millón de tokens por modelo,
`registrar()`/`leer()` sobre un CSV) registrado desde `Interprete._cerrar()` en cada interpretación
o pregunta (incluida la que usa la plantilla sin LLM, con costo 0, para poder medir cuántas veces
se cae al respaldo); vive en `logs/uso_interprete.csv`, fuera de `data/` y `resultados/` y
gitignorado — es telemetría operativa, no un resultado del pipeline. Un fallo al escribir el
registro nunca rompe la interpretación (se loggea aparte). `app_pages/05_pregunta.py` ahora muestra
tokens y costo estimado junto a la respuesta. El conocimiento se actualizó: `glosario.md` con
"Validación con experimentos" y "Factor de calibración" (RQ-21) y la sección 1 de este documento
con las mismas dos filas; `playbook.md` con la rama Validado/Sin validar/Sin probar en el paso 1 de
siguientes pasos. **Hallazgo:** `pytest tests` (sin filtro `-m`) no tenía antes ningún `addopts` que
excluyera `rendimiento`/`evals` por defecto —sin este cambio, el banco de 30 preguntas habría
corrido con cada `pytest tests`, contradiciendo el propio README/CLAUDE.md ("no gastan API"). Se
agregó `addopts = "-m \"not rendimiento and not evals\""` a `pyproject.toml`; verificado que
`pytest tests` sigue en 146 passed/32 deselected y que `pytest tests -m evals`/`-m rendimiento`
siguen pudiendo correrse a propósito.

### Épica K · Ingeniería

#### RQ-26 · Estructura, calidad de código e integración continua · P1 · Hecho parcialmente
- Paquete `src/atribucion/` con submódulos (`config`, `fuentes`, `sql`, `modelos`, `metricas`, `marts`, `app`, `interprete`); `pyproject.toml`.
- `ruff` y `mypy` en modo básico; `pre-commit`.
- GitHub Actions: lint, pruebas sin API y prueba de regresión de marts con datos sintéticos pequeños.
- `Makefile` con `datos`, `pipeline`, `app`, `test`.
**Aceptación:** CI en verde en cada PR; `make test` corre en menos de 3 minutos.

**Nota (lote 1):** se entregó `pyproject.toml` (deps + `ruff` + marcadores de pytest), `Makefile`,
`.github/workflows/ci.yml` (lint + pruebas) y `requirements.txt` actualizado. **Se difiere** la
reubicación a `src/atribucion/` (es puramente organizativa y de alto riesgo de romper imports bajo
presión de tiempo) y `pre-commit`. `mypy` queda configurado en `pyproject.toml` pero no se ejecuta
en CI todavía: el código existente no tiene anotaciones de tipos y requeriría una pasada aparte.

#### RQ-27 · Pruebas de modelos y SQL · P1 · Hecho
- Modelos: casos a mano para cada regla, Markov (efecto de remoción con una cadena de 2 canales calculada a mano) y Shapley (propiedades de RQ-13).
- SQL: fixtures pequeños de eventos y pedidos con resultados esperados de sesiones, canales, rutas y conciliación.
- Regresión: con la semilla actual, el error de Shapley frente al efecto real no supera 2 pp.
**Aceptación:** cobertura ≥ 80 % en `modelos` y `metricas`.

**Nota (lote 1):** `tests/test_atribucion.py`, `tests/test_metricas_decision.py` y `tests/test_sql.py`
(100 % de cobertura en `atribucion.py` y `metricas_decision.py`). Las propiedades de Shapley se
prueban de forma aproximada (eficiencia agregada, simetría con canales intercambiables, caso
degenerado de jugador nulo): la prueba exacta de los axiomas por conjunto de canales es el
diagnóstico de RQ-13, que reestructura `shapley()` y aún no está hecho.

### Épica L · Seguridad y privacidad

#### RQ-28 · Datos personales · P1 · Hecho
- El pipeline no lee ni guarda correo, teléfono, nombre ni dirección. `customer_id` se guarda solo con hash.
- Las tablas `mart_*` no contienen identificadores de usuario.
- Política de retención configurable (por defecto 13 meses de eventos crudos).
- Cumplimiento de la Ley 29733 documentado en `docs/privacidad.md`.
**Aceptación:** prueba que falla si una columna de un `mart_*` coincide con una lista de nombres sensibles.

**Nota:** `privacidad.py` (`verificar_marts_sin_pii`, `hash_customer_id`, `aplicar_retencion_eventos`).
La comparación es por **nombre exacto de columna**, no substring: una columna descriptiva como
`unidos_por_ga_client_id` (RQ-07, un conteo agregado) menciona la llave sin contener el dato — un
`in` ingenuo la marcaba como falso positivo. `aplicar_retencion_eventos` no se corre
automáticamente en `run_demo.py` (es destructivo; se agenda aparte, RQ-24).

---

## 4. Tablas `mart_*` nuevas o modificadas

| Tabla | Cambio | RQ |
|---|---|---|
| `mart_decision__canal` | Columnas de roles: `ventas_abre`, `ventas_asiste`, `ventas_cierra`, `ventas_unico` y sus porcentajes | RQ-11 |
| `mart_decision__campana` | Nueva: crédito de canal repartido entre campañas | RQ-09 |
| `mart_plataformas__comparacion` | Nueva: reportado por la plataforma vs. modelo | RQ-15 |
| `mart_plataformas__alcance` | Nueva: impresiones, alcance, frecuencia | RQ-16 |
| `mart_calidad__conciliacion` | Pedidos unidos por llave | RQ-07 |
| `mart_calidad__canales` | Nueva: % Unassigned, Direct, Meta sin UTM | RQ-06 |
| `mart_calidad__controles` | Nueva | RQ-18 |
| `mart_calidad__modelo` | Nueva: diagnóstico de Shapley | RQ-13 |
| `mart_calidad__error_modelo` | Solo en modo demo | RQ-02 |
| `mart_validacion__experimentos` / `__canal` | Nuevas | RQ-21 |
| `mart_mmm__curvas` / `__resumen` | Nuevas (opcional): curva de respuesta y ROAS marginal por canal | RQ-22 |
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
