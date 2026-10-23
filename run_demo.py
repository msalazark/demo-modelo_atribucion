"""
Corre la demo completa sobre una ventana móvil de 12 meses:
  1. SQL: sesiones -> rutas -> conciliación (DuckDB, misma lógica que en BigQuery)
  2. Modelos: reglas (primer clic, último clic, lineal, posición U, decaimiento temporal),
     último clic no directo, Markov y Shapley
  3. Validación contra el efecto real (solo en modo demo: datos sintéticos, RQ-02)
  4. Métricas de decisión por canal: alcance, asistencia y conversión
  5. Una "rebanada" por cada combinación de filtros del dashboard:
        ventana de atribución (7 a 90 días) x segmento (total, dispositivo, región,
        tipo de cliente, categoría). Los modelos no son aditivos: cada filtro exige recalcular.
  6. Estado del modelo: ¿cambió frente a la ventana del mes anterior? ¿hay disparadores de reajuste?
  7. Siguientes pasos: tiempo hasta la compra y diseño de una prueba de incrementalidad
  8. Persiste todo en DuckDB (tablas mart_*) y exporta resultados/*.csv
  9. Narrativa pregenerada para las vistas por defecto (con LLM si hay ANTHROPIC_API_KEY)

La ventana móvil termina en el último pedido y cubre los 12 meses anteriores. Se reajusta
con cada corrida (mensual); los meses previos a la ventana solo aportan historia de lookback.

El dashboard solo lee las tablas mart_*; no calcula nada.

Uso:
  python generar_datos.py   # una vez
  python run_demo.py                               # usa config/demo.yaml
  python run_demo.py --config config/produccion.yaml
"""
import argparse
import os
import time
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd
from joblib import Parallel, delayed

from atribucion import efecto_real, markov, markov_roles, modelos_regla, shapley, ultimo_no_directo
from calidad import controles_calidad
from campanas import comparacion_plataformas, credito_por_campana
from config import ConfigCliente, cargar_config
from contratos import validar_fuente
from experimentos import cargar_experimentos, estado_validacion_por_canal, mart_validacion_experimentos
from metricas_decision import asignar_senal, rutas_top
from metricas_decision import calcular as metricas_por_canal
from mmm import ajustar as ajustar_mmm
from mmm import curvas_respuesta as curvas_respuesta_mmm
from mmm import resumen_canal as resumen_canal_mmm
from mmm import semanal as semanal_mmm
from proximos_pasos import diseno_prueba_incrementalidad, tiempo_hasta_compra
from reglas_canal import META_SITE_SOURCE_NAME_DEFECTO, REGLAS_CANAL_UTM_DEFECTO, sql_case_canal, sql_es_pasarela

BASE = Path(__file__).parent
SQL_DIR = BASE / "sql"
MODELOS_SENAL = ["primer_clic", "ultimo_clic", "ultimo_no_directo", "lineal", "posicion_u",
                 "decaimiento_temporal", "markov", "shapley"]

# Los globals de abajo vienen de ConfigCliente (RQ-01): _aplicar_config() los fija al arrancar
# main(). Quedan con los valores de la demo para que importar este módulo sin pasar por main()
# (pruebas, notebooks) siga comportándose igual que antes de RQ-01.
VENTANA_MESES = 12
VENTANA_DIAS = 30  # ventana de atribución vigente; las demás se prueban como filtro y sensibilidad
VENTANAS = [7, 14, 30, 60, 90]
VENTANA_TIEMPO = 90  # el tiempo hasta la compra se mide con la ventana más ancha para no truncar la cola
N_BOOTSTRAP = 30  # remuestreos para el intervalo del 90 % de la cuota Shapley (vista por defecto)
DIMENSIONES = {  # nombre en el dashboard -> columna de la tabla usuarios
    "Dispositivo": "device_category",
    "Región": "geo_region",
    "Tipo de cliente": "customer_type",
    "Categoría": "content_group",
}
PAGADOS = ["Paid Social", "Paid Search", "Display"]
ESTADOS_VALIDOS_PEDIDO = ["pagado"]
VARIANTE_CIERRE = "ultima_sesion"  # RQ-11: quién "cierra" la venta (decisión abierta #3)
LIMITE_JUGADORES_SHAPLEY = 12  # RQ-13: por encima, Shapley por Monte Carlo
N_PERMUTACIONES_MONTE_CARLO = 200
SHAPLEY_C = 1.0  # None = elegir por validación cruzada
MARKOV_ORDEN = 1  # RQ-12: variante vigente
MARKOV_EXCLUIR_DIRECT = False
MARKOV_INGRESO_POR_VALOR = False
PASARELAS: list[str] = []  # RQ-06
REGLAS_CANAL_UTM = list(REGLAS_CANAL_UTM_DEFECTO)
META_SITE_SOURCE_NAME = list(META_SITE_SOURCE_NAME_DEFECTO)
ZONA_HORARIA = "UTC"  # RQ-10: cortes mensuales en la zona horaria del cliente
UMBRAL_ESCALAR, UMBRAL_REVISAR = 1.2, 0.8
RATIO_ASISTIDOR, BRECHA_MODELOS_PP, SOBRE_INDICE_PP = 2.0, 3.0, 3.0
CONFIANZA_ALTA_CI, CONFIANZA_MEDIA_CI = 2.0, 4.0
CONFIANZA_ALTA_PEDIDOS, CONFIANZA_MEDIA_PEDIDOS = 3000, 1000
MINIMO_CONVERSIONES_SENAL = 1000  # RQ-14: por debajo, no se publica señal
N_JOBS = -1  # RQ-17: hilos para procesar segmentos en paralelo


def _aplicar_config(cfg: ConfigCliente) -> None:
    """Fija los globals de este módulo desde la configuración del cliente: reemplaza las
    constantes que antes estaban repetidas en dashboard_comun.py e interprete/datos.py (RQ-01)."""
    global VENTANA_MESES, VENTANA_DIAS, VENTANAS, VENTANA_TIEMPO, N_BOOTSTRAP, DIMENSIONES
    global PAGADOS, ESTADOS_VALIDOS_PEDIDO, VARIANTE_CIERRE, UMBRAL_ESCALAR, UMBRAL_REVISAR
    global RATIO_ASISTIDOR, BRECHA_MODELOS_PP, SOBRE_INDICE_PP, CONFIANZA_ALTA_CI, CONFIANZA_MEDIA_CI
    global CONFIANZA_ALTA_PEDIDOS, CONFIANZA_MEDIA_PEDIDOS, LIMITE_JUGADORES_SHAPLEY, N_PERMUTACIONES_MONTE_CARLO
    global MINIMO_CONVERSIONES_SENAL, N_JOBS
    global SHAPLEY_C, MARKOV_ORDEN, MARKOV_EXCLUIR_DIRECT, MARKOV_INGRESO_POR_VALOR
    global PASARELAS, REGLAS_CANAL_UTM, META_SITE_SOURCE_NAME, ZONA_HORARIA, RUTA_EXPERIMENTOS
    VENTANA_MESES = cfg.ventana_analisis_meses
    VENTANA_DIAS = cfg.ventana_vigente_dias
    VENTANAS = cfg.ventanas_atribucion_dias
    VENTANA_TIEMPO = cfg.ventana_tiempo_dias
    N_BOOTSTRAP = cfg.n_bootstrap
    DIMENSIONES = cfg.dimensiones_segmentacion
    PAGADOS = cfg.canales_pagados
    ESTADOS_VALIDOS_PEDIDO = cfg.estados_validos_pedido
    VARIANTE_CIERRE = cfg.variante_cierre
    UMBRAL_ESCALAR, UMBRAL_REVISAR = cfg.umbral_escalar, cfg.umbral_revisar
    RATIO_ASISTIDOR, BRECHA_MODELOS_PP, SOBRE_INDICE_PP = cfg.ratio_asistidor, cfg.brecha_modelos_pp, cfg.sobre_indice_pp
    CONFIANZA_ALTA_CI, CONFIANZA_MEDIA_CI = cfg.confianza_alta_ci, cfg.confianza_media_ci
    CONFIANZA_ALTA_PEDIDOS, CONFIANZA_MEDIA_PEDIDOS = cfg.confianza_alta_pedidos, cfg.confianza_media_pedidos
    MINIMO_CONVERSIONES_SENAL = cfg.minimo_conversiones_senal
    N_JOBS = cfg.n_jobs
    LIMITE_JUGADORES_SHAPLEY = cfg.limite_jugadores_shapley
    N_PERMUTACIONES_MONTE_CARLO = cfg.shapley_monte_carlo_permutaciones
    SHAPLEY_C = cfg.shapley_c
    MARKOV_ORDEN = cfg.markov_orden
    MARKOV_EXCLUIR_DIRECT = cfg.markov_excluir_direct
    MARKOV_INGRESO_POR_VALOR = cfg.markov_ingreso_por_valor
    PASARELAS = cfg.pasarelas
    REGLAS_CANAL_UTM = cfg.reglas_canal_utm
    META_SITE_SOURCE_NAME = cfg.meta_site_source_name
    ZONA_HORARIA = cfg.zona_horaria
    RUTA_EXPERIMENTOS = cfg.ruta_experimentos


# ----------------------------------------------------------------- ventana y parámetros
def ventana_movil(con: duckdb.DuckDBPyConnection) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(inicio, corte): los VENTANA_MESES meses que terminan en el último pedido."""
    # Se castea a texto en UTC para no depender de pytz al leer TIMESTAMPTZ
    ultimo = con.execute(
        "SELECT CAST(max(created_at) AT TIME ZONE 'UTC' AS VARCHAR) FROM orders WHERE status = ANY(?)",
        [ESTADOS_VALIDOS_PEDIDO],
    ).fetchone()[0]
    corte = pd.Timestamp(ultimo, tz="UTC")
    inicio = corte.normalize() + pd.Timedelta(days=1) - pd.DateOffset(months=VENTANA_MESES)
    return inicio, corte


def fijar_parametros(con: duckdb.DuckDBPyConnection, inicio: pd.Timestamp, corte: pd.Timestamp, ventana: int) -> None:
    con.execute(
        "CREATE OR REPLACE TABLE parametros AS SELECT CAST(? AS TIMESTAMPTZ) AS inicio, "
        "CAST(? AS TIMESTAMPTZ) AS corte, CAST(? AS INTEGER) AS ventana_dias",
        [inicio.isoformat(), corte.isoformat(), ventana],
    )


def _sql(ruta: Path) -> str:
    """Lee un .sql y sustituye los placeholders que dependen de la configuración del cliente:

    `{{ESTADOS_VALIDOS_PEDIDO}}` (RQ-01): con un solo estado (el caso de la demo) genera
    `= 'pagado'`, igual que el código fijo que reemplaza: con DuckDB, aunque `IN ('pagado')` es
    equivalente, cambia el plan de consulta y con él el orden de filas —que afecta al redondeo y
    al muestreo bootstrap— frente al `=` original.
    `{{CASE_CANAL}}` / `{{ES_PASARELA}}` (RQ-06): reglas de canal y pasarelas configurables.
    `{{ZONA_HORARIA}}` (RQ-10): cortes mensuales en la zona horaria del cliente, no UTC.
    """
    valores = ["'" + e.replace("'", "''") + "'" for e in ESTADOS_VALIDOS_PEDIDO]
    filtro = f"= {valores[0]}" if len(valores) == 1 else f"IN ({', '.join(valores)})"
    texto = ruta.read_text().replace("{{ESTADOS_VALIDOS_PEDIDO}}", filtro)
    texto = texto.replace("{{CASE_CANAL}}", sql_case_canal(REGLAS_CANAL_UTM, META_SITE_SOURCE_NAME))
    texto = texto.replace("{{ES_PASARELA}}", sql_es_pasarela(PASARELAS))
    return texto.replace("{{ZONA_HORARIA}}", ZONA_HORARIA)


def construir_rutas(con: duckdb.DuckDBPyConnection, inicio, corte, ventana: int) -> pd.DataFrame:
    fijar_parametros(con, inicio, corte, ventana)
    con.execute(_sql(SQL_DIR / "02_rutas.sql"))
    rutas = con.sql(
        "SELECT user_pseudo_id, order_id, revenue_pen, convirtio, device_category, geo_region, "
        "customer_type, content_group, ruta, ruta_campana, dias_antes FROM rutas"
    ).df()
    rutas["ruta"] = rutas.ruta.apply(list)
    rutas["ruta_campana"] = rutas.ruta_campana.apply(list)
    rutas["dias_antes"] = rutas.dias_antes.apply(list)
    return rutas


def cargar_sesiones(con, inicio, corte) -> pd.DataFrame:
    return con.execute(
        "SELECT s.canal, s.es_pasarela, u.device_category, u.geo_region, u.customer_type, u.content_group "
        "FROM sesiones s JOIN usuarios u USING (user_pseudo_id) "
        "WHERE s.inicio_sesion BETWEEN CAST(? AS TIMESTAMPTZ) AND CAST(? AS TIMESTAMPTZ)",
        [inicio.isoformat(), corte.isoformat()],
    ).df()


def calidad_canales(sesiones: pd.DataFrame) -> pd.DataFrame:
    """% de sesiones en Unassigned, Direct y "Meta (sin UTM)" (RQ-06): calidad del etiquetado.
    Excluye sesiones de pasarela: no son tráfico de marketing, no hablan de calidad de etiquetado."""
    s = sesiones[~sesiones.es_pasarela]
    total = len(s)
    filas = [{"canal": c, "sesiones": int((s.canal == c).sum()),
              "pct": round(float((s.canal == c).mean() * 100), 2) if total else 0.0}
             for c in ("Unassigned", "Direct", "Meta (sin UTM)")]
    return pd.DataFrame(filas)


def costos_ventana(con, inicio, corte) -> pd.Series:
    return con.execute(
        "SELECT channel AS canal, sum(cost_pen) AS costo FROM costs "
        "WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) GROUP BY 1",
        [inicio.date().isoformat(), corte.date().isoformat()],
    ).df().set_index("canal").costo


def costos_por_campana(con, inicio, corte) -> pd.Series:
    """RQ-09: igual que `costos_ventana` pero por campaña, no por canal."""
    return con.execute(
        "SELECT campaign AS campana, sum(cost_pen) AS costo FROM costs "
        "WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) GROUP BY 1",
        [inicio.date().isoformat(), corte.date().isoformat()],
    ).df().set_index("campana").costo


def reportado_por_campana(con, inicio, corte) -> pd.DataFrame:
    """RQ-15: lo que cada plataforma reclama haber generado, agregado a la ventana de análisis."""
    return con.execute(
        "SELECT campaign AS campana, sum(platform_conversions) AS platform_conversions, "
        "sum(platform_revenue) AS platform_revenue FROM reportado_plataformas "
        "WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) GROUP BY 1",
        [inicio.date().isoformat(), corte.date().isoformat()],
    ).df().set_index("campana")


def alcance_por_campana(con, inicio, corte) -> pd.DataFrame:
    """RQ-16: impresiones, alcance y frecuencia por campaña (no entran a las rutas; insumo para
    un futuro MMM, RQ-22)."""
    return con.execute(
        "SELECT channel AS canal, campaign AS campana, sum(impressions) AS impresiones, "
        "sum(reach) AS alcance, sum(impressions) / sum(reach) AS frecuencia FROM impresiones "
        "WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) GROUP BY 1, 2",
        [inicio.date().isoformat(), corte.date().isoformat()],
    ).df()


# ----------------------------------------------------------------- modelos
def comparar_modelos(
    modelos: dict[str, pd.DataFrame],
    real: pd.Series | None,
    costos: pd.Series | None = None,
    ci: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.Series | None]:
    """Tabla larga canal x modelo y, solo en modo demo (`real` no es None), la fila `efecto_real`
    y el error medio de cada modelo frente a ella, en pp (RQ-02: en producción no existe)."""
    primero = next(iter(modelos.values()))
    canales = sorted(real.index) if real is not None else sorted(primero.index)
    cuota_real = (real / real.sum() * 100).reindex(canales) if real is not None else None
    n_conv = primero.conversiones.sum()
    costo = costos.reindex(canales) if costos is not None else pd.Series(float("nan"), index=canales)
    filas, error = [], {}
    for nombre, df in modelos.items():
        conv = df.conversiones.reindex(canales).fillna(0.0)
        ing = df.ingresos.reindex(canales).fillna(0.0)
        cuota = conv / conv.sum() * 100
        if cuota_real is not None:
            error[nombre] = (cuota - cuota_real).abs().mean()
        roas = (ing / costo).where(costo > 0)
        cpa = (costo / conv).where(costo > 0)
        for c in canales:
            filas.append({
                "canal": c, "modelo": nombre, "conversiones": round(conv[c], 1), "cuota_pct": round(cuota[c], 1),
                "ingresos": round(ing[c], 0), "costo": costo[c], "roas": round(roas[c], 2), "cpa": round(cpa[c], 2),
                "cuota_p05": ci.p05.get(c) if ci is not None and nombre == "shapley" else None,
                "cuota_p95": ci.p95.get(c) if ci is not None and nombre == "shapley" else None,
            })
    if cuota_real is not None:
        filas += [{"canal": c, "modelo": "efecto_real", "conversiones": round(cuota_real[c] / 100 * n_conv, 1),
                   "cuota_pct": round(cuota_real[c], 1), "ingresos": None, "costo": costo[c], "roas": None,
                   "cpa": None, "cuota_p05": None, "cuota_p95": None} for c in canales]
    comp = pd.DataFrame(filas)
    comp["ranking"] = comp.groupby("modelo").cuota_pct.rank(ascending=False, method="min").astype(int)
    error_medio = pd.Series(error, name="error_medio_pp").round(2) if cuota_real is not None else None
    return comp, error_medio


def intervalo_shapley(rutas: pd.DataFrame) -> pd.DataFrame:
    """Intervalo del 90 % de la cuota Shapley con remuestreos bootstrap."""
    muestras = []
    for b in range(N_BOOTSTRAP):
        s = rutas.sample(len(rutas), replace=True, random_state=b).reset_index(drop=True)
        sh_b, _ = shapley(s, C=SHAPLEY_C, limite_jugadores=LIMITE_JUGADORES_SHAPLEY,
                          n_permutaciones_monte_carlo=N_PERMUTACIONES_MONTE_CARLO, seed=b)
        muestras.append(sh_b.conversiones / sh_b.conversiones.sum() * 100)
    q = pd.DataFrame(muestras).quantile([0.05, 0.95]).T.round(1)
    return q.rename(columns={0.05: "p05", 0.95: "p95"})


def correr_rebanada(
    rutas: pd.DataFrame,
    sesiones: pd.DataFrame,
    costos: pd.Series | None,
    params: str | None,
    totales: dict[str, pd.Series],
    con_ci: bool = False,
) -> dict[str, pd.DataFrame]:
    """Modelos + métricas + señales para un conjunto de rutas (la ventana, o un segmento de ella).

    `totales[modelo]` es la cuota de ese modelo en el total (se usa para el sobre-índice de un segmento).
    `costos` es None dentro de un segmento: el costo existe solo por canal, no por segmento.
    `params` es None en modo producción (RQ-02): no hay tabla `truth` y no se calcula `efecto_real`.
    """
    es_segmento = costos is None
    ref = ultimo_no_directo(rutas)
    mk, _ = markov(rutas, orden=MARKOV_ORDEN, excluir_direct=MARKOV_EXCLUIR_DIRECT,
                   ponderar_ingreso_por_valor=MARKOV_INGRESO_POR_VALOR)
    sh, diag_shapley = shapley(rutas, C=SHAPLEY_C, limite_jugadores=LIMITE_JUGADORES_SHAPLEY,
                               n_permutaciones_monte_carlo=N_PERMUTACIONES_MONTE_CARLO)
    real = efecto_real(rutas, params) if params is not None else None
    modelos = {**modelos_regla(rutas), "ultimo_no_directo": ref, "markov": mk, "shapley": sh}
    ci = intervalo_shapley(rutas) if con_ci else None
    comparativo, error = comparar_modelos(modelos, real, costos, ci)

    metricas, pares = metricas_por_canal(rutas, sesiones, VARIANTE_CIERRE)
    metricas = metricas.join(markov_roles(rutas), how="left")
    metricas["costo"] = costos.reindex(metricas.index) if costos is not None else float("nan")
    metricas["es_pagado"] = metricas.index.isin(PAGADOS)

    n_conv = int(rutas.convirtio.sum())
    senales = []
    cuota_unc = comparativo[comparativo.modelo == "ultimo_no_directo"].set_index("canal").cuota_pct
    for modelo in MODELOS_SENAL:
        c = comparativo[comparativo.modelo == modelo].set_index("canal")
        m = pd.DataFrame({
            "cuota_pct": c.cuota_pct, "cuota_ultimo_no_directo_pct": cuota_unc, "roas": c.roas, "cpa": c.cpa,
            "costo": c.costo, "ancho_ci": (c.cuota_p95 - c.cuota_p05) if modelo == "shapley" else float("nan"),
            "ratio_asistencia": metricas.asistencias_por_cierre, "tasa_conv_usuario_pct": metricas.tasa_conv_usuario_pct,
            "cuota_total_pct": totales[modelo].reindex(c.index) if es_segmento else float("nan"),
        })
        senales.append(asignar_senal(
            m, n_conv, es_segmento,
            umbral_escalar=UMBRAL_ESCALAR, umbral_revisar=UMBRAL_REVISAR, ratio_asistidor=RATIO_ASISTIDOR,
            brecha_modelos_pp=BRECHA_MODELOS_PP, sobre_indice_pp=SOBRE_INDICE_PP,
            confianza_alta_ci=CONFIANZA_ALTA_CI, confianza_media_ci=CONFIANZA_MEDIA_CI,
            confianza_alta_pedidos=CONFIANZA_ALTA_PEDIDOS, confianza_media_pedidos=CONFIANZA_MEDIA_PEDIDOS,
            minimo_conversiones_senal=MINIMO_CONVERSIONES_SENAL,
        ).assign(modelo=modelo).reset_index())

    cuotas_total = {m: comparativo[comparativo.modelo == m].set_index("canal").cuota_pct for m in MODELOS_SENAL}
    return {
        "mart_decision__canal": metricas.reset_index(),
        "mart_modelos__comparativo": comparativo,
        "mart_decision__senal": pd.concat(senales, ignore_index=True),
        "mart_decision__pares_asistencia": pares,
        "mart_decision__rutas_top": rutas_top(rutas),
        **({"mart_calidad__error_modelo": error.rename_axis("modelo").reset_index()} if error is not None else {}),
        "mart_calidad__modelo": diag_shapley["calibracion"].assign(
            metodo=diag_shapley["metodo"], C_elegido=diag_shapley["C_elegido"], auc=diag_shapley["auc"],
            log_loss=diag_shapley["log_loss"], conjuntos_distintos=diag_shapley["conjuntos_distintos"],
            phi_negativos_recortados=diag_shapley["phi_negativos_recortados"],
        ),
        "_cuotas": cuotas_total,
        "_n_conv": n_conv,
    }


# ----------------------------------------------------------------- historia (RQ-19)
TABLAS_CON_HISTORIA = ["mart_modelos__comparativo", "mart_decision__canal"]


def actualizar_historia(con: duckdb.DuckDBPyConnection, tabla: str, df: pd.DataFrame, corte: pd.Timestamp) -> None:
    """Agrega una copia de `df` (con columna `corte`) a `hist_<tabla>`. Una corrida repetida con
    el mismo corte reemplaza su propia historia en vez de duplicarla."""
    hist = f"hist_{tabla}"
    con.register("_hist_nuevo", df.assign(corte=corte.date()))
    existe = con.execute(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = ?", [hist]
    ).fetchone()[0]
    if existe:
        con.execute(f"DELETE FROM {hist} WHERE corte = ?", [corte.date()])
        con.execute(f"INSERT INTO {hist} SELECT * FROM _hist_nuevo")
    else:
        con.execute(f"CREATE TABLE {hist} AS SELECT * FROM _hist_nuevo")
    con.unregister("_hist_nuevo")


def _cuota_previa_de_historia(con: duckdb.DuckDBPyConnection, corte: pd.Timestamp) -> tuple[pd.Series | None, str | None]:
    """Cuota Shapley de la corrida anterior más reciente (vista total, ventana vigente), si hay
    historia; None si esta es la primera corrida (no hay con qué comparar)."""
    existe = con.sql(
        "SELECT count(*) FROM information_schema.tables WHERE table_name = 'hist_mart_modelos__comparativo'"
    ).fetchone()[0]
    if not existe:
        return None, None
    previas = con.execute(
        "SELECT corte, canal, cuota_pct FROM hist_mart_modelos__comparativo "
        "WHERE ventana_dias = ? AND dim = 'Todos' AND segmento = 'Todos' AND modelo = 'shapley' "
        "AND corte < ? ORDER BY corte DESC",
        [VENTANA_DIAS, corte.date()],
    ).df()
    if previas.empty:
        return None, None
    ultimo_corte = previas.corte.iloc[0]
    fila = previas[previas.corte == ultimo_corte].set_index("canal").cuota_pct
    return fila, pd.Timestamp(ultimo_corte).date().isoformat()


# ----------------------------------------------------------------- estado del modelo
def estado_modelo(con, inicio, corte, actual: pd.DataFrame) -> pd.DataFrame:
    """Compara la cuota Shapley actual (con su intervalo) con la de la corrida anterior: usa la
    historia (RQ-19) si ya existe; si esta es la primera corrida, recalcula el mes calendario
    anterior (único caso en que no hay con qué comparar todavía)."""
    previa, corte_previo = _cuota_previa_de_historia(con, corte)
    if previa is None:
        fin_prev = corte.normalize().replace(day=1) - pd.Timedelta(seconds=1)
        inicio_prev = inicio - pd.DateOffset(months=1)
        rutas_prev = construir_rutas(con, inicio_prev, fin_prev, VENTANA_DIAS)
        sh_prev, _ = shapley(rutas_prev, C=SHAPLEY_C, limite_jugadores=LIMITE_JUGADORES_SHAPLEY,
                             n_permutaciones_monte_carlo=N_PERMUTACIONES_MONTE_CARLO)
        previa = (sh_prev.conversiones / sh_prev.conversiones.sum() * 100).round(1)
        corte_previo = fin_prev.date().isoformat()
    a = actual[actual.modelo == "shapley"].set_index("canal")
    out = pd.DataFrame({
        "cuota_actual": a.cuota_pct, "p05": a.cuota_p05, "p95": a.cuota_p95,
        "cuota_previa": previa.reindex(a.index),
    }).dropna(subset=["cuota_actual"])
    out["cambio_pp"] = (out.cuota_actual - out.cuota_previa).round(1)
    out["estado"] = ((out.cuota_previa >= out.p05) & (out.cuota_previa <= out.p95)).map(
        {True: "estable", False: "cambió"})
    out["corte_previo"] = corte_previo
    return out.rename_axis("canal").reset_index()


def disparadores(con, corte: pd.Timestamp) -> pd.DataFrame:
    """Reglas que sugieren reajustar el modelo antes de tiempo: últimos 60 días vs. los 60 previos."""
    def rango(dias_ini: int, dias_fin: int) -> tuple[str, str]:
        return ((corte - pd.Timedelta(days=dias_ini)).isoformat(), (corte - pd.Timedelta(days=dias_fin)).isoformat())

    def ventana(desde: str, hasta: str) -> dict:
        ped = con.execute("SELECT count(*) FROM orders WHERE status = ANY(?) AND created_at >= CAST(? AS TIMESTAMPTZ) "
                          "AND created_at < CAST(? AS TIMESTAMPTZ)", [ESTADOS_VALIDOS_PEDIDO, desde, hasta]).fetchone()[0]
        ses = con.execute("SELECT count(*) FROM sesiones WHERE NOT es_pasarela AND inicio_sesion >= CAST(? AS TIMESTAMPTZ) "
                          "AND inicio_sesion < CAST(? AS TIMESTAMPTZ)", [desde, hasta]).fetchone()[0]
        inv = con.execute("SELECT channel, sum(cost_pen) FROM costs WHERE date >= CAST(? AS DATE) AND date < CAST(? AS DATE) "
                          "GROUP BY 1", [desde[:10], hasta[:10]]).df().set_index("channel").iloc[:, 0]
        canales = set(con.execute("SELECT DISTINCT canal FROM sesiones WHERE inicio_sesion >= CAST(? AS TIMESTAMPTZ) "
                                  "AND inicio_sesion < CAST(? AS TIMESTAMPTZ)", [desde, hasta]).df().canal)
        return {"pedidos": ped, "conv": ped / ses * 100, "inv": inv.sum(), "mix": inv / inv.sum() * 100, "canales": canales}

    r, p = ventana(*rango(60, -1)), ventana(*rango(120, 60))
    mix_pp = float((r["mix"].reindex(p["mix"].index).fillna(0) - p["mix"]).abs().max())
    nuevos = sorted(r["canales"] - p["canales"])
    filas = [
        ("Inversión en medios", r["inv"], p["inv"], (r["inv"] / p["inv"] - 1) * 100, 25, "%"),
        ("Mix de inversión (mayor cambio de un canal)", mix_pp, 0.0, mix_pp, 10, "pp"),
        ("Pedidos", r["pedidos"], p["pedidos"], (r["pedidos"] / p["pedidos"] - 1) * 100, 25, "%"),
        ("Conversión por sesión", r["conv"], p["conv"], (r["conv"] / p["conv"] - 1) * 100, 15, "%"),
    ]
    out = pd.DataFrame(filas, columns=["regla", "ultimos_60d", "60d_previos", "cambio", "umbral", "unidad"])
    out["estado"] = (out.cambio.abs() > out.umbral).map({True: "alerta", False: "ok"})
    out = pd.concat([out, pd.DataFrame([{
        "regla": "Canales nuevos", "ultimos_60d": len(nuevos), "60d_previos": 0, "cambio": len(nuevos),
        "umbral": 0, "unidad": "canales", "estado": "alerta" if nuevos else "ok"}])], ignore_index=True)
    return out


# ----------------------------------------------------------------- orquestación
def main(ruta_config: str = "config/demo.yaml"):
    # Fuente única de verdad: dashboard_comun.py e interprete/datos.py leen el mismo YAML a través
    # de esta variable de entorno (streamlit run no acepta --config). Se fija antes de cualquier
    # import de interprete.* para que su config de módulo quede sincronizada con la de main().
    os.environ["ATRIBUCION_CONFIG"] = ruta_config
    cfg = cargar_config(ruta_config)
    _aplicar_config(cfg)
    t0 = time.time()
    con = duckdb.connect(str(BASE / cfg.ruta_bd))
    for t in con.sql("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'mart_%'").df().table_name:
        con.execute(f"DROP TABLE IF EXISTS {t}")  # las mart_* se regeneran por completo en cada corrida

    # Contratos de datos (RQ-03): se corren antes de los SQL. "costos" no se valida todavía: esta
    # demo trae costo por canal, no por campaña (campaign_id/campaign_name llegan con RQ-09).
    validar_fuente("eventos_ga4", con.sql("SELECT * FROM events").df(),
                   alias={"device.category": "device_category", "geo.region": "geo_region"})
    validar_fuente("pedidos", con.sql("SELECT * FROM orders").df(), alias={"revenue": "revenue_pen"})

    con.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    # `truth`/efecto_real solo existen en modo demo (RQ-02): en producción no hay verdad sintética
    # contra la que comparar los modelos, así que `params` queda en None y el resto del pipeline
    # se salta ese cálculo sin romperse.
    params = con.sql("SELECT params FROM truth").fetchone()[0] if cfg.modo == "demo" else None
    inicio, corte = ventana_movil(con)
    print(f"Ventana móvil: {inicio.date()} a {corte.date()} ({VENTANA_MESES} meses)")

    fijar_parametros(con, inicio, corte, VENTANA_DIAS)
    con.execute(_sql(SQL_DIR / "04_kpi_mensual.sql"))
    kpi = con.sql("SELECT * FROM kpi_mensual").df()
    sesiones = cargar_sesiones(con, inicio, corte)
    costos = costos_ventana(con, inicio, corte)

    acumulado: dict[str, list[pd.DataFrame]] = {}
    conciliaciones, pedidos_por_ventana = [], {}
    rutas_tiempo = None
    rutas_campana = None
    for v in VENTANAS:
        rutas = construir_rutas(con, inicio, corte, v)
        con.execute(_sql(SQL_DIR / "03_conciliacion.sql"))
        conciliaciones.append(con.sql("SELECT * FROM conciliacion").df().assign(ventana_dias=v))
        if v == VENTANA_TIEMPO:
            rutas_tiempo = rutas
        if v == VENTANA_DIAS:
            rutas_campana = rutas
        segmentos = []
        for dim, col in DIMENSIONES.items():
            for valor in sorted(rutas[col].dropna().unique()):
                segmentos.append((dim, valor, rutas[rutas[col] == valor], sesiones[sesiones[col] == valor], None))

        # "Todos" va primero y sola: los segmentos necesitan su `totales` (cuota del segmento
        # frente al total, para el sobre-/sub-índice) antes de poder correr.
        ci_total = v == VENTANA_DIAS and int(rutas.convirtio.sum()) >= MINIMO_CONVERSIONES_SENAL
        res_total = correr_rebanada(rutas, sesiones, costos, params, {}, con_ci=ci_total)
        totales = res_total["_cuotas"]
        pedidos_por_ventana[v] = res_total["_n_conv"]
        resultados = [("Todos", "Todos", res_total)]

        # RQ-17: los segmentos no dependen entre sí (solo de `totales`, ya fijo): corren en
        # paralelo. `threading` evita que cada worker reciba su propia copia de los globals de
        # configuración de este módulo (un problema real con workers de proceso: ver nota en
        # docs/RQ_mejoras.md), a costa de no escalar más allá del GIL en el código Python puro
        # (el ajuste de la logística de Shapley sí lo libera).
        def _segmento(dim, valor, r, s, c):
            ci = v == VENTANA_DIAS and int(r.convirtio.sum()) >= MINIMO_CONVERSIONES_SENAL
            return dim, valor, correr_rebanada(r, s, c, params, totales, con_ci=ci)

        resultados += Parallel(n_jobs=N_JOBS, backend="threading")(
            delayed(_segmento)(dim, valor, r, s, c) for dim, valor, r, s, c in segmentos
        )

        for dim, valor, res in resultados:
            for nombre, df in res.items():
                if not nombre.startswith("_"):
                    acumulado.setdefault(nombre, []).append(df.assign(ventana_dias=v, dim=dim, segmento=valor))
        print(f"  ventana {v:>2} días: {len(resultados)} rebanadas, {pedidos_por_ventana[v]:,} pedidos con ruta "
              f"({time.time() - t0:,.0f} s)")

    marts = {n: pd.concat(dfs, ignore_index=True) for n, dfs in acumulado.items()}
    marts["mart_calidad__conciliacion"] = pd.concat(conciliaciones, ignore_index=True)
    marts["mart_calidad__canales"] = calidad_canales(sesiones)

    # Controles de calidad (RQ-18): si falla uno crítico, la corrida se detiene aquí, antes de
    # persistir nada, y los mart_* de la corrida anterior quedan intactos.
    conciliacion_vigente = marts["mart_calidad__conciliacion"].query("ventana_dias == @VENTANA_DIAS").iloc[0]
    marts["mart_calidad__controles"] = controles_calidad(
        con, inicio, corte, PAGADOS, conciliacion_vigente, marts["mart_calidad__canales"])
    criticos = marts["mart_calidad__controles"].query("estado == 'crítico'")
    if len(criticos):
        detalle = "; ".join(f"{r.control}: {r.valor} {r.unidad} (umbral {r.umbral})" for r in criticos.itertuples())
        raise RuntimeError(f"Controles de calidad críticos fallidos, corrida detenida: {detalle}")

    # Vista por defecto = ventana vigente x total
    base = marts["mart_modelos__comparativo"].query("ventana_dias == @VENTANA_DIAS and dim == 'Todos'")
    mdec = marts["mart_decision__canal"].query("ventana_dias == @VENTANA_DIAS and dim == 'Todos'").set_index("canal")

    # Estado del modelo y disparadores de reajuste. estado_modelo lee hist_* (RQ-19) antes de
    # que se actualice con los datos de esta corrida.
    marts["mart_estado__modelo"] = estado_modelo(con, inicio, corte, base)
    marts["mart_estado__disparadores"] = disparadores(con, corte)
    for nombre in TABLAS_CON_HISTORIA:
        actualizar_historia(con, nombre, marts[nombre], corte)

    # Siguientes pasos
    t_canal, t_hist = tiempo_hasta_compra(rutas_tiempo, VENTANA_TIEMPO, ancho=7)
    marts["mart_tiempo__a_compra"] = t_canal.assign(ventana_dias=VENTANA_TIEMPO)
    marts["mart_tiempo__histograma"] = t_hist.assign(ventana_dias=VENTANA_TIEMPO)
    sh = base[base.modelo == "shapley"].set_index("canal")
    para_prueba = pd.DataFrame({"costo": mdec.costo, "shapley": sh.conversiones, "ingresos": sh.ingresos,
                                "usuarios_alcanzados": mdec.usuarios_alcanzados})
    # RQ-20: alcance por canal y región (una región se deja sin el canal en la prueba geográfica).
    geo_prueba = marts["mart_decision__canal"].query("ventana_dias == @VENTANA_DIAS and dim == 'Región'")[
        ["canal", "segmento", "usuarios_alcanzados"]]
    marts["mart_siguientes_pasos__prueba_incrementalidad"] = diseno_prueba_incrementalidad(
        para_prueba, (corte.normalize() - inicio.normalize()).days + 1, geo=geo_prueba)

    # RQ-21: validación con experimentos (si el cliente ya cargó resultados) y factor de
    # calibración por canal, informativo, no aplicado a ninguna cuota.
    experimentos = cargar_experimentos(BASE / RUTA_EXPERIMENTOS if RUTA_EXPERIMENTOS else None)
    marts["mart_validacion__experimentos"] = mart_validacion_experimentos(experimentos, sh.conversiones, inicio, corte)
    marts["mart_validacion__canal"] = estado_validacion_por_canal(PAGADOS, marts["mart_validacion__experimentos"])

    # RQ-09/RQ-15/RQ-16: nivel campaña y comparación con lo que reportan las plataformas de medios.
    # Reparte el crédito de canal del modelo vigente (shapley, ventana vigente, "Todos") entre sus
    # campañas; no corre un modelo de atribución aparte a nivel campaña (ver campanas.py).
    costo_campana = costos_por_campana(con, inicio, corte)
    marts["mart_decision__campana"] = credito_por_campana(rutas_campana, sh, costo_campana, PAGADOS)
    marts["mart_plataformas__comparacion"] = comparacion_plataformas(
        marts["mart_decision__campana"], reportado_por_campana(con, inicio, corte))
    marts["mart_plataformas__alcance"] = alcance_por_campana(con, inicio, corte)

    # RQ-22 (opcional): Marketing Mix Model ligero sobre inversión semanal (ver mmm.py; no es
    # Meridian ni PyMC-Marketing, no están instalados en este entorno). Con ~52 semanas de
    # historia los intervalos de credibilidad son anchos a propósito: es lo esperable con un año
    # de datos, no un error del ajuste.
    semanal_mmm_df = semanal_mmm(con, inicio, corte, PAGADOS)
    ajuste_mmm = ajustar_mmm(semanal_mmm_df, PAGADOS)
    marts["mart_mmm__curvas"] = curvas_respuesta_mmm(semanal_mmm_df, ajuste_mmm)
    marts["mart_mmm__resumen"] = resumen_canal_mmm(semanal_mmm_df, ajuste_mmm)

    marts["mart_kpi__mensual"] = kpi
    est = marts["mart_estado__modelo"]
    disp = marts["mart_estado__disparadores"]
    marts["mart_ejecucion"] = pd.DataFrame([{
        "ejecutado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "cliente": cfg.cliente, "modo": cfg.modo,
        "inicio": inicio.date().isoformat(), "corte": corte.date().isoformat(),
        "ventana_meses": VENTANA_MESES, "ventana_dias": VENTANA_DIAS, "ventanas_probadas": ",".join(map(str, VENTANAS)),
        "pedidos": pedidos_por_ventana[VENTANA_DIAS],
        "canales_cambiaron": int((est.estado == "cambió").sum()), "alertas": int((disp.estado == "alerta").sum()),
        "segundos": round(time.time() - t0),
    }])

    # Capa mart: lo único que consume el dashboard (y luego BigQuery / Looker)
    out = BASE / "resultados"
    out.mkdir(exist_ok=True)
    for nombre, df in marts.items():
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {nombre} AS SELECT * FROM _df")
        con.unregister("_df")
        df.to_csv(out / f"{nombre}.csv", index=False)  # mismo contenido, listo para cargar a BQ
    con.close()

    from interprete.narrativa import generar_narrativas  # después de cerrar: abre su propia conexión
    generar_narrativas(BASE / cfg.ruta_bd)

    pd.set_option("display.width", 200, "display.max_columns", 30)
    if "mart_calidad__error_modelo" in marts:  # solo existe en modo demo (RQ-02)
        print(f"\nError medio vs. efecto real, ventana {VENTANA_DIAS} días, total (pp):")
        print(marts["mart_calidad__error_modelo"].query("ventana_dias == @VENTANA_DIAS and dim == 'Todos'")
              .set_index("modelo").error_medio_pp.sort_values())
    print("\nEstado del modelo:\n", est[["canal", "cuota_actual", "cuota_previa", "estado"]].to_string(index=False))
    print("\nDisparadores:\n", disp.to_string(index=False))
    print(f"\nListo en {time.time() - t0:,.0f} s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default="config/demo.yaml", help="Ruta al YAML de configuración del cliente (RQ-01).")
    main(ap.parse_args().config)
