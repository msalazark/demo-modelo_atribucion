# Guía de lectura de los datos de prueba

Esta demo corre sobre datos **100 % sintéticos**, generados por `generar_datos.py` con una semilla
fija (`SEED = 20261014`): cualquiera que corra ese script obtiene exactamente los mismos números.
No hay información real de ningún cliente. Esta guía explica qué representa cada tabla, de dónde
salen los números y qué limitaciones hay que tener presentes al leerlos — importante antes de usar
esta demo para explicarle el modelo a alguien o para decidir si vale la pena construir algo
parecido con datos reales.

## 1. Qué simula el generador

`generar_datos.py` imita la estructura de:
- El **export de GA4 a BigQuery** (tabla `events`, con `event_params`, `collected_traffic_source`,
  `ecommerce`) — aquí vive en DuckDB con el mismo esquema.
- Los **pedidos del backend** (tabla `orders`) — la fuente de verdad de la venta, no el evento
  `purchase` de GA4 (regla 4 de `CLAUDE.md`).
- La **inversión en medios** por canal y campaña (`costs`), **impresiones/alcance** (`impresiones`)
  y lo que **cada plataforma de medios dice que generó** (`reportado_plataformas`).

Rango de datos: **2025-07-01 a 2026-09-30** (457 días, ~150.000 usuarios, ~1,15 millones de
eventos, 6.448 pedidos). De esos 15 meses, los últimos 12 (2025-10-01 a 2026-09-30) son la
"ventana de análisis" que usa el pipeline; los 3 primeros meses solo existen para que las primeras
sesiones de la ventana tengan historia de *lookback* (sin ellos, enero-2026 no tendría sesiones de
noviembre-2025 que contar).

## 2. La tabla `truth`: por qué esta demo puede medir "qué tan cerca está cada modelo"

Es la única tabla que **no existe con un cliente real**. Guarda `PARAMS_REALES`: la fórmula exacta
con la que el generador decide si una combinación de canales convierte —

```
logit(p) = b0 + Σ beta[canal] + sinergia (Paid Social Ɨ Paid Search)
b0 = -5.3
beta: Paid Social 1.25 · Email 1.15 · Paid Search 1.05 · Organic Search 0.95 ·
      Referral 0.65 · Display 0.55 · Direct 0.30
sinergia Paid Social + Paid Search: +0.60 (estar en ambos convierte más que la suma de los dos)
```

Como el generador conoce esta fórmula, `atribucion.efecto_real()` puede calcular la conversión
incremental *real* de cada canal (cuánto bajarían las ventas si ese canal no existiera) y
compararla contra lo que cada modelo (reglas, Markov, Shapley) le atribuye. Esa comparación vive en
`mart_calidad__error_modelo` y es la base del mensaje "Shapley es el modelo más cercano al efecto
real" que aparece en el dashboard y en el glosario del intérprete.

**Con un cliente real no existe esta tabla ni esta comparación**: ahí la única forma de validar un
modelo es con una prueba de incrementalidad real (ver `mart_validacion__experimentos`, sección 6).
`efecto_real`/`truth` solo existen en `modo: demo` (regla 7 de `CLAUDE.md`); en `modo: produccion`
esas columnas y esas tablas no se generan.

## 3. Canales y cómo se deciden

Cada sesión entra por un canal, elegido con una distribución distinta para la **primera** sesión de
la ruta (qué tan probable es que cada canal "abra la demanda") y para las **siguientes** (qué tan
probable es que "cierre"):

| Canal | Abre (1.ª sesión) | Cierra (siguientes) | Es pagado |
|---|---|---|---|
| Paid Social | 26 % | 12 % | Sí |
| Direct | 15 % | 28 % | No |
| Organic Search | 22 % | 18 % | No |
| Paid Search | 14 % | 18 % | Sí |
| Referral | 8 % | 5 % | No |
| Email | 3 % | 14 % | No |
| Display | 12 % | 5 % | Sí |

Esas probabilidades además se ajustan por el segmento del usuario (p. ej. en `mobile` Paid Social
pesa 1,5x más y Paid Search 0,8x menos; un cliente `recurrente` entra 2,2x más por Direct o Email).
**El ajuste mueve el *mix* de canales por segmento, nunca la probabilidad de compra**: por diseño,
el efecto real de cada canal (sección 2) es el mismo en todos los segmentos, para poder validar que
el modelo lo recupera también segmento por segmento.

Solo **Paid Social, Paid Search y Display** tienen costo — son los "canales pagados"
(`canales_pagados` en `config/demo.yaml`). Email, Organic Search, Referral y Direct nunca tienen
fila en `costs`: por eso no tienen ROAS ni CPA en ningún mart ni en el dashboard.

## 4. Campañas (RQ-09): dos por canal pagado, no una

Antes cada canal pagado tenía una sola campaña "siempre activa". Ahora cada uno tiene dos, con su
propio costo y su propio nivel de impresiones por sesión (CTR implícito distinto):

| Canal | Campaña | % de las sesiones del canal | Costo relativo | Impr. por sesión |
|---|---|---|---|---|
| Paid Social | `paid_social_prospecting` | 60 % | 0.85x | 42 |
| Paid Social | `paid_social_retargeting` | 40 % | 1.25x | 18 |
| Paid Search | `paid_search_marca` | 35 % | 0.60x | 3 |
| Paid Search | `paid_search_generica` | 65 % | 1.30x | 12 |
| Display | `display_prospecting` | 70 % | 0.90x | 90 |
| Display | `display_remarketing` | 30 % | 1.10x | 35 |

"Prospecting"/"genérica" son campañas de alcance amplio (más impresiones por sesión, o sea menos
clic-through); "retargeting"/"marca"/"remarketing" son más dirigidas. `mart_decision__campana`
reparte el crédito de canal de Shapley entre sus dos campañas en proporción a estas sesiones
**dentro de rutas convertidas** — no es un modelo de atribución aparte a nivel campaña.

## 5. Por qué "lo que reporta la plataforma" es mucho más alto que lo que le atribuye el modelo

`reportado_plataformas` (RQ-15) simula lo que Meta Ads / Google Ads dirían que generaron, y **a
propósito** es consistentemente más alto que `mart_decision__campana`:

1. **Cada plataforma reclama la venta completa** si su campaña apareció en la ruta, sin importar
   cuántos otros canales también aparecieron (si una ruta pasó por Paid Social *y* Paid Search,
   ambas plataformas la reclaman — el modelo la reparte entre las dos). Esto pasa en la vida real:
   las plataformas no se coordinan entre sí.
2. Encima de eso, un **extra fijo por campaña** (`exceso_vista`, de 1.05x en Paid Search-marca a
   1.60x en Display-prospecting) representa las conversiones que la plataforma ve por **vista sin
   clic** — nunca generan una sesión en GA4, así que el modelo no las puede ver en absoluto.

La brecha resultante es grande (habitualmente 200-700 % según la campaña, ver
`mart_plataformas__comparacion`) — es intencional, no un error de los datos: Display y Paid Social
suelen ser canales que **asisten** más que cierran, así que Shapley les da poco crédito mientras la
plataforma reclama la venta completa cada vez que aparecen. La pestaña "Plataformas" de Explorar
trae esta explicación como nota fija.

## 6. Los dos experimentos cargados (RQ-21)

`data/experimentos.csv` trae dos pruebas de incrementalidad **de ejemplo** (no generadas por
`generar_datos.py`, sino escritas a mano a partir del `efecto_real` de cada canal para que la
demo cuente una historia coherente):

| Canal | Tipo | Duración | Medido | Intervalo 90 % | Resultado |
|---|---|---|---|---|---|
| Paid Social | Holdout por usuario (20 % control) | 8 semanas | 250 ventas | [210, 290] | **Validado** — confirma la señal "Escalar (validar)" |
| Paid Search | Geográfica (Lima vs. Provincias) | 4 semanas | 58 ventas | [42, 74] | **Sin validar** — el experimento mide menos de lo que el modelo atribuye, consistente con su señal "Revisar" |

`Display` no tiene experimento cargado: aparece como "Sin probar" en `mart_validacion__canal`. El
`factor_calibracion` (medido / atribuido) es puramente informativo — nunca se aplica solo a ninguna
cuota (ver `interprete/conocimiento/glosario.md`).

## 7. El MMM (RQ-22, opcional): por qué sus intervalos son tan anchos

`mart_mmm__resumen` ajusta un modelo de inversión semanal (adstock + saturación + `BayesianRidge`,
ver `mmm.py`) sobre solo **~52 semanas** de historia. Con tan pocos puntos, el intervalo de
credibilidad del ROAS marginal suele cruzar cero (p. ej. Paid Social: 2,8 central pero
[-1,3; 7,0] al 90 %). **Es el resultado honesto de un año de datos**, no un error del ajuste — el
propio RQ-22 pide "al menos un año de historia" reconociendo esta limitación. Con un cliente real,
cuantas más semanas de historia se acumulen (vía `hist_*`, RQ-19), más se angostaría el intervalo.

## 8. Controles de calidad: cómo leer que todo salga "ok"

`mart_calidad__controles` siempre debería salir con las 6 filas en `ok` en esta demo (si falla un
control crítico, `run_demo.py` detiene la corrida antes de publicar nada — ver `calidad.py`). Los
valores típicos:

| Control | Valor típico | Umbral |
|---|---|---|
| Pedidos con ruta | ~99 % | ≥ 85 % (crítico) |
| Pedidos vistos en GA4 | ~70 % | ≥ 70 % (alerta) |
| Sesiones Unassigned | 0 % | ≤ 5 % (alerta) |
| Tráfico de Meta sin UTM | 0 % | ≤ 10 % (alerta) |
| Días sin costos de un canal pagado activo | 0 días | ≤ 0 (crítico) |
| Caída de eventos vs. media de 28 días | cerca de 0 % | ≥ -30 % (crítico) |

El "Pedidos vistos en GA4" ronda el umbral a propósito: el generador simula que el evento
`purchase` de GA4 se pierde ~12 % de las veces (thank-you page no cargada) y que ~4 % de los
pedidos llegan sin cookie de GA4 en absoluto — para que la demo muestre un caso real de
conciliación imperfecta entre backend y analítica, no un 100 % artificial.

## 9. Cómo regenerar (y qué cambia si lo haces)

```bash
python generar_datos.py   # recrea data/ecommerce.duckdb desde cero (misma semilla, mismos números)
python run_demo.py        # corre el pipeline completo sobre esos datos
```

La semilla es fija, así que **volver a correr `generar_datos.py` sin tocar el código da exactamente
los mismos datos**. Si en algún momento se edita la lógica del generador (nuevas campañas,
distribuciones, parámetros), toda la secuencia aleatoria posterior al cambio se recalcula distinta
— cambian casi todas las cifras de la demo, no solo lo que se tocó. Por eso cualquier cambio en
`generar_datos.py` debe ir seguido de volver a correr `run_demo.py` completo y revisar las señales
y marts de nuevo antes de confiar en los números (ver la nota de RQ-09 en `docs/RQ_mejoras.md` sobre
un bug real que este efecto hizo aparecer).

## 10. Dónde seguir leyendo

- **Qué significa cada cifra del dashboard:** `interprete/conocimiento/glosario.md`.
- **Qué RQ generó cada tabla y por qué:** `docs/RQ_mejoras.md`, sección 4 (tablas `mart_*`) y la
  nota de cada RQ.
- **Qué pasa al pasar a un cliente real** (qué tabla deja de existir, qué cambia): sección
  "Pasar a un cliente real" del `README.md`.
