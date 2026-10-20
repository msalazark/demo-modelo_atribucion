"""
Corre la demo completa sobre una ventana móvil de 12 meses:
  1. SQL: sesiones -> rutas -> conciliación (DuckDB, misma lógica que en BigQuery)
  2. Modelos: reglas (primer clic, último clic, lineal, posición U, decaimiento temporal),
     último clic no directo, Markov y Shapley
  3. Validación contra el efecto real (solo posible con datos sintéticos)
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
  python run_demo.py
"""
import time
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from atribucion import efecto_real, markov, markov_roles, modelos_regla, shapley, ultimo_no_directo
from metricas_decision import asignar_senal
from metricas_decision import calcular as metricas_por_canal
from metricas_decision import rutas_top
from proximos_pasos import diseno_prueba_incrementalidad, tiempo_hasta_compra

BASE = Path(__file__).parent
SQL_DIR = BASE / "sql"
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
MODELOS_SENAL = ["primer_clic", "ultimo_clic", "ultimo_no_directo", "lineal", "posicion_u",
                 "decaimiento_temporal", "markov", "shapley"]


# ----------------------------------------------------------------- ventana y parámetros
def ventana_movil(con: duckdb.DuckDBPyConnection) -> tuple[pd.Timestamp, pd.Timestamp]:
    """(inicio, corte): los 12 meses que terminan en el último pedido."""
    # Se castea a texto en UTC para no depender de pytz al leer TIMESTAMPTZ
    ultimo = con.sql(
        "SELECT CAST(max(created_at) AT TIME ZONE 'UTC' AS VARCHAR) FROM orders WHERE status = 'pagado'"
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


def construir_rutas(con: duckdb.DuckDBPyConnection, inicio, corte, ventana: int) -> pd.DataFrame:
    fijar_parametros(con, inicio, corte, ventana)
    con.execute((SQL_DIR / "02_rutas.sql").read_text())
    rutas = con.sql(
        "SELECT user_pseudo_id, order_id, revenue_pen, convirtio, device_category, geo_region, "
        "customer_type, content_group, ruta, dias_antes FROM rutas"
    ).df()
    rutas["ruta"] = rutas.ruta.apply(list)
    rutas["dias_antes"] = rutas.dias_antes.apply(list)
    return rutas


def cargar_sesiones(con, inicio, corte) -> pd.DataFrame:
    return con.execute(
        "SELECT s.canal, s.es_pasarela, u.device_category, u.geo_region, u.customer_type, u.content_group "
        "FROM sesiones s JOIN usuarios u USING (user_pseudo_id) "
        "WHERE s.inicio_sesion BETWEEN CAST(? AS TIMESTAMPTZ) AND CAST(? AS TIMESTAMPTZ)",
        [inicio.isoformat(), corte.isoformat()],
    ).df()


def costos_ventana(con, inicio, corte) -> pd.Series:
    return con.execute(
        "SELECT channel AS canal, sum(cost_pen) AS costo FROM costs "
        "WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) GROUP BY 1",
        [inicio.date().isoformat(), corte.date().isoformat()],
    ).df().set_index("canal").costo


# ----------------------------------------------------------------- modelos
def comparar_modelos(
    modelos: dict[str, pd.DataFrame],
    real: pd.Series,
    costos: pd.Series | None = None,
    ci: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Tabla larga canal x modelo (más el efecto real) y error medio de cada modelo vs. el real, en pp."""
    canales = sorted(real.index)
    cuota_real = (real / real.sum() * 100).reindex(canales)
    n_conv = next(iter(modelos.values())).conversiones.sum()
    costo = costos.reindex(canales) if costos is not None else pd.Series(float("nan"), index=canales)
    filas, error = [], {}
    for nombre, df in modelos.items():
        conv = df.conversiones.reindex(canales).fillna(0.0)
        ing = df.ingresos.reindex(canales).fillna(0.0)
        cuota = conv / conv.sum() * 100
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
    filas += [{"canal": c, "modelo": "efecto_real", "conversiones": round(cuota_real[c] / 100 * n_conv, 1),
               "cuota_pct": round(cuota_real[c], 1), "ingresos": None, "costo": costo[c], "roas": None,
               "cpa": None, "cuota_p05": None, "cuota_p95": None} for c in canales]
    comp = pd.DataFrame(filas)
    comp["ranking"] = comp.groupby("modelo").cuota_pct.rank(ascending=False, method="min").astype(int)
    return comp, pd.Series(error, name="error_medio_pp").round(2)


def intervalo_shapley(rutas: pd.DataFrame) -> pd.DataFrame:
    """Intervalo del 90 % de la cuota Shapley con remuestreos bootstrap."""
    muestras = []
    for b in range(N_BOOTSTRAP):
        s = rutas.sample(len(rutas), replace=True, random_state=b).reset_index(drop=True)
        sh_b, _ = shapley(s)
        muestras.append(sh_b.conversiones / sh_b.conversiones.sum() * 100)
    q = pd.DataFrame(muestras).quantile([0.05, 0.95]).T.round(1)
    return q.rename(columns={0.05: "p05", 0.95: "p95"})


def correr_rebanada(
    rutas: pd.DataFrame,
    sesiones: pd.DataFrame,
    costos: pd.Series | None,
    params: str,
    totales: dict[str, pd.Series],
    con_ci: bool = False,
) -> dict[str, pd.DataFrame]:
    """Modelos + métricas + señales para un conjunto de rutas (la ventana, o un segmento de ella).

    `totales[modelo]` es la cuota de ese modelo en el total (se usa para el sobre-índice de un segmento).
    `costos` es None dentro de un segmento: el costo existe solo por canal, no por segmento.
    """
    es_segmento = costos is None
    ref = ultimo_no_directo(rutas)
    mk, _ = markov(rutas)
    sh, _ = shapley(rutas)
    real = efecto_real(rutas, params)
    modelos = {**modelos_regla(rutas), "ultimo_no_directo": ref, "markov": mk, "shapley": sh}
    ci = intervalo_shapley(rutas) if con_ci else None
    comparativo, error = comparar_modelos(modelos, real, costos, ci)

    metricas, pares = metricas_por_canal(rutas, sesiones)
    metricas = metricas.join(markov_roles(rutas), how="left")
    metricas["costo"] = costos.reindex(metricas.index) if costos is not None else float("nan")
    metricas["es_pagado"] = metricas.index.isin(["Paid Social", "Paid Search", "Display"])

    n_conv = int(rutas.convirtio.sum())
    senales = []
    cuota_unc = comparativo[comparativo.modelo == "ultimo_no_directo"].set_index("canal").cuota_pct
    for modelo in MODELOS_SENAL:
        c = comparativo[comparativo.modelo == modelo].set_index("canal")
        m = pd.DataFrame({
            "cuota_pct": c.cuota_pct, "cuota_ultimo_no_directo_pct": cuota_unc, "roas": c.roas, "cpa": c.cpa,
            "costo": c.costo, "ancho_ci": (c.cuota_p95 - c.cuota_p05) if modelo == "shapley" else float("nan"),
            "ratio_asistencia": metricas.ratio_asistencia, "tasa_conv_usuario_pct": metricas.tasa_conv_usuario_pct,
            "cuota_total_pct": totales[modelo].reindex(c.index) if es_segmento else float("nan"),
        })
        senales.append(asignar_senal(m, n_conv, es_segmento).assign(modelo=modelo).reset_index())

    cuotas_total = {m: comparativo[comparativo.modelo == m].set_index("canal").cuota_pct for m in MODELOS_SENAL}
    return {
        "mart_decision__canal": metricas.reset_index(),
        "mart_modelos__comparativo": comparativo,
        "mart_decision__senal": pd.concat(senales, ignore_index=True),
        "mart_decision__pares_asistencia": pares,
        "mart_decision__rutas_top": rutas_top(rutas),
        "mart_calidad__error_modelo": error.rename_axis("modelo").reset_index(),
        "_cuotas": cuotas_total,
        "_n_conv": n_conv,
    }


# ----------------------------------------------------------------- estado del modelo
def estado_modelo(con, inicio, corte, params, actual: pd.DataFrame) -> pd.DataFrame:
    """Compara la cuota Shapley actual (con su intervalo) con la de la ventana del mes anterior."""
    fin_prev = corte.normalize().replace(day=1) - pd.Timedelta(seconds=1)
    inicio_prev = inicio - pd.DateOffset(months=1)
    rutas_prev = construir_rutas(con, inicio_prev, fin_prev, VENTANA_DIAS)
    sh_prev, _ = shapley(rutas_prev)
    previa = (sh_prev.conversiones / sh_prev.conversiones.sum() * 100).round(1)
    a = actual[actual.modelo == "shapley"].set_index("canal")
    out = pd.DataFrame({
        "cuota_actual": a.cuota_pct, "p05": a.cuota_p05, "p95": a.cuota_p95, "cuota_previa": previa,
    }).dropna(subset=["cuota_actual"])
    out["cambio_pp"] = (out.cuota_actual - out.cuota_previa).round(1)
    out["estado"] = ((out.cuota_previa >= out.p05) & (out.cuota_previa <= out.p95)).map(
        {True: "estable", False: "cambió"})
    out["corte_previo"] = fin_prev.date().isoformat()
    return out.rename_axis("canal").reset_index()


def disparadores(con, corte: pd.Timestamp) -> pd.DataFrame:
    """Reglas que sugieren reajustar el modelo antes de tiempo: últimos 60 días vs. los 60 previos."""
    def rango(dias_ini: int, dias_fin: int) -> tuple[str, str]:
        return ((corte - pd.Timedelta(days=dias_ini)).isoformat(), (corte - pd.Timedelta(days=dias_fin)).isoformat())

    def ventana(desde: str, hasta: str) -> dict:
        ped = con.execute("SELECT count(*) FROM orders WHERE status='pagado' AND created_at >= CAST(? AS TIMESTAMPTZ) "
                          "AND created_at < CAST(? AS TIMESTAMPTZ)", [desde, hasta]).fetchone()[0]
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
def main():
    t0 = time.time()
    con = duckdb.connect(str(BASE / "data" / "ecommerce.duckdb"))
    for t in con.sql("SELECT table_name FROM information_schema.tables WHERE table_name LIKE 'mart_%'").df().table_name:
        con.execute(f"DROP TABLE IF EXISTS {t}")  # las mart_* se regeneran por completo en cada corrida
    con.execute((SQL_DIR / "01_sesiones.sql").read_text())
    params = con.sql("SELECT params FROM truth").fetchone()[0]
    inicio, corte = ventana_movil(con)
    print(f"Ventana móvil: {inicio.date()} a {corte.date()} ({VENTANA_MESES} meses)")

    fijar_parametros(con, inicio, corte, VENTANA_DIAS)
    con.execute((SQL_DIR / "04_kpi_mensual.sql").read_text())
    kpi = con.sql("SELECT * FROM kpi_mensual").df()
    sesiones = cargar_sesiones(con, inicio, corte)
    costos = costos_ventana(con, inicio, corte)

    acumulado: dict[str, list[pd.DataFrame]] = {}
    conciliaciones, pedidos_por_ventana = [], {}
    rutas_tiempo = None
    for v in VENTANAS:
        rutas = construir_rutas(con, inicio, corte, v)
        con.execute((SQL_DIR / "03_conciliacion.sql").read_text())
        conciliaciones.append(con.sql("SELECT * FROM conciliacion").df().assign(ventana_dias=v))
        if v == VENTANA_TIEMPO:
            rutas_tiempo = rutas
        totales: dict[str, pd.Series] = {}
        rebanadas = [("Todos", "Todos", rutas, sesiones, costos)]
        for dim, col in DIMENSIONES.items():
            for valor in sorted(rutas[col].dropna().unique()):
                rebanadas.append((dim, valor, rutas[rutas[col] == valor], sesiones[sesiones[col] == valor], None))
        for dim, valor, r, s, c in rebanadas:
            ci = v == VENTANA_DIAS and dim == "Todos"
            res = correr_rebanada(r, s, c, params, totales, con_ci=ci)
            if dim == "Todos":
                totales = res["_cuotas"]
                pedidos_por_ventana[v] = res["_n_conv"]
            for nombre, df in res.items():
                if not nombre.startswith("_"):
                    acumulado.setdefault(nombre, []).append(df.assign(ventana_dias=v, dim=dim, segmento=valor))
        print(f"  ventana {v:>2} días: {len(rebanadas)} rebanadas, {pedidos_por_ventana[v]:,} pedidos con ruta "
              f"({time.time() - t0:,.0f} s)")

    marts = {n: pd.concat(dfs, ignore_index=True) for n, dfs in acumulado.items()}
    marts["mart_calidad__conciliacion"] = pd.concat(conciliaciones, ignore_index=True)

    # Vista por defecto = ventana vigente x total
    base = marts["mart_modelos__comparativo"].query("ventana_dias == @VENTANA_DIAS and dim == 'Todos'")
    mdec = marts["mart_decision__canal"].query("ventana_dias == @VENTANA_DIAS and dim == 'Todos'").set_index("canal")

    # Estado del modelo y disparadores de reajuste
    marts["mart_estado__modelo"] = estado_modelo(con, inicio, corte, params, base)
    marts["mart_estado__disparadores"] = disparadores(con, corte)

    # Siguientes pasos
    t_canal, t_hist = tiempo_hasta_compra(rutas_tiempo, VENTANA_TIEMPO, ancho=7)
    marts["mart_tiempo__a_compra"] = t_canal.assign(ventana_dias=VENTANA_TIEMPO)
    marts["mart_tiempo__histograma"] = t_hist.assign(ventana_dias=VENTANA_TIEMPO)
    sh = base[base.modelo == "shapley"].set_index("canal")
    para_prueba = pd.DataFrame({"costo": mdec.costo, "shapley": sh.conversiones,
                                "usuarios_alcanzados": mdec.usuarios_alcanzados})
    marts["mart_siguientes_pasos__prueba_incrementalidad"] = diseno_prueba_incrementalidad(
        para_prueba, (corte.normalize() - inicio.normalize()).days + 1)

    marts["mart_kpi__mensual"] = kpi
    est = marts["mart_estado__modelo"]
    disp = marts["mart_estado__disparadores"]
    marts["mart_ejecucion"] = pd.DataFrame([{
        "ejecutado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
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
    generar_narrativas(BASE / "data" / "ecommerce.duckdb")

    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(f"\nError medio vs. efecto real, ventana {VENTANA_DIAS} días, total (pp):")
    print(marts["mart_calidad__error_modelo"].query("ventana_dias == @VENTANA_DIAS and dim == 'Todos'")
          .set_index("modelo").error_medio_pp.sort_values())
    print("\nEstado del modelo:\n", est[["canal", "cuota_actual", "cuota_previa", "estado"]].to_string(index=False))
    print("\nDisparadores:\n", disp.to_string(index=False))
    print(f"\nListo en {time.time() - t0:,.0f} s")


if __name__ == "__main__":
    main()
