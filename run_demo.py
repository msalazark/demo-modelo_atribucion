"""
Corre la demo completa, por periodo mensual acumulado:
  1. SQL: sesiones -> rutas -> conciliación (DuckDB, misma lógica que en BigQuery)
  2. Modelos: último clic no directo (referencia), Markov y Shapley
  3. Validación contra el efecto real (solo posible con datos sintéticos)
  4. Métricas de decision por canal: alcance, asistencia y conversión
  5. Persiste todo en DuckDB (tablas mart_*) y exporta resultados/*.csv

Reporte mensual acumulado: el periodo "2026-03" significa "desde el primer dato hasta
el cierre de marzo". Los modelos se recalculan con las rutas de ese corte; las cuotas de
cada mes NO se pueden sumar ni promediar entre sí.

El dashboard (dashboard.py) solo lee las tablas mart_*; no calcula nada.

Uso:
  python generar_datos.py   # una vez
  python run_demo.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from atribucion import efecto_real, markov, shapley, ultimo_no_directo
from metricas_decision import asignar_senal
from metricas_decision import calcular as metricas_por_canal
from metricas_decision import rutas_top

BASE = Path(__file__).parent
SQL_DIR = BASE / "sql"
CANALES_PAGADOS = ["Paid Social", "Paid Search", "Display"]
N_BOOTSTRAP = 30  # remuestreos por periodo para el intervalo del 90 % de la cuota Shapley


def periodos(con: duckdb.DuckDBPyConnection) -> list[tuple[str, pd.Timestamp, pd.Timestamp, bool]]:
    """Meses con pedidos: (etiqueta, inicio de los datos, corte, es_parcial)."""
    # Se castea a texto en UTC para no depender de pytz al leer TIMESTAMPTZ
    r = con.sql(
        "SELECT CAST(min(created_at) AT TIME ZONE 'UTC' AS VARCHAR), "
        "CAST(max(created_at) AT TIME ZONE 'UTC' AS VARCHAR) FROM orders WHERE status = 'pagado'"
    ).fetchone()
    desde, ultimo_pedido = pd.Timestamp(r[0], tz="UTC"), pd.Timestamp(r[1], tz="UTC")
    salida = []
    for p in pd.period_range(desde, ultimo_pedido, freq="M"):
        fin_mes = p.end_time.tz_localize("UTC")
        parcial = ultimo_pedido < fin_mes - pd.Timedelta(days=2)
        salida.append((str(p), desde.normalize(), min(fin_mes, ultimo_pedido), parcial))
    return salida


def correr_periodo(con: duckdb.DuckDBPyConnection, corte: pd.Timestamp, params: str) -> dict[str, pd.DataFrame]:
    """Corre SQL + modelos + métricas con las rutas hasta `corte`."""
    con.execute("CREATE OR REPLACE TABLE parametros AS SELECT CAST(? AS TIMESTAMPTZ) AS corte", [corte.isoformat()])
    for f in ("02_rutas.sql", "03_conciliacion.sql"):
        con.execute((SQL_DIR / f).read_text())

    rutas = con.sql("SELECT user_pseudo_id, order_id, revenue_pen, convirtio, ruta FROM rutas").df()
    rutas["ruta"] = rutas.ruta.apply(list)
    conciliacion = con.sql("SELECT * FROM conciliacion").df()
    costos = con.execute(
        "SELECT channel AS canal, sum(cost_pen) AS costo FROM costs WHERE date <= CAST(? AS DATE) GROUP BY 1",
        [corte.date().isoformat()],
    ).df().set_index("canal").costo
    sesiones = con.execute(
        "SELECT canal, es_pasarela FROM sesiones WHERE inicio_sesion <= CAST(? AS TIMESTAMPTZ)", [corte.isoformat()]
    ).df()

    ref = ultimo_no_directo(rutas)
    mk, _ = markov(rutas)
    sh, _ = shapley(rutas)
    real = efecto_real(rutas, params)

    n_conv = int(rutas.convirtio.sum())
    tabla = pd.DataFrame({
        "ultimo_no_directo": ref.conversiones,
        "markov": mk.conversiones,
        "shapley": sh.conversiones,
        "efecto_real": real / real.sum() * n_conv,
    }).fillna(0.0)
    cuota = (tabla / n_conv * 100).round(1).add_suffix("_pct")
    ingresos = pd.DataFrame({
        "ingresos_ultimo_no_directo": ref.ingresos,
        "ingresos_markov": mk.ingresos,
        "ingresos_shapley": sh.ingresos,
    }).fillna(0.0)
    salida = pd.concat([tabla.round(1), cuota, ingresos.round(0)], axis=1)
    salida["costo"] = costos.reindex(salida.index)
    for m in ("ultimo_no_directo", "markov", "shapley"):
        salida[f"roas_{m}"] = (salida[f"ingresos_{m}"] / salida.costo).round(2)
    salida = salida.sort_values("efecto_real", ascending=False)
    salida.index.name = "canal"

    error = {m: (cuota[f"{m}_pct"] - cuota["efecto_real_pct"]).abs().mean()
             for m in ("ultimo_no_directo", "markov", "shapley")}

    # Estabilidad: intervalo del 90 % de la cuota Shapley con remuestreos bootstrap
    muestras = []
    for b in range(N_BOOTSTRAP):
        s = rutas.sample(len(rutas), replace=True, random_state=b).reset_index(drop=True)
        sh_b, _ = shapley(s)
        muestras.append(sh_b.conversiones / sh_b.conversiones.sum() * 100)
    intervalos = pd.DataFrame(muestras).quantile([0.05, 0.95]).T.round(1)
    salida["shapley_pct_p05"] = intervalos[0.05]
    salida["shapley_pct_p95"] = intervalos[0.95]

    # Métricas de decisión (alcance / asistencia / conversión) + atribución en una sola tabla
    metricas, pares = metricas_por_canal(rutas, sesiones)
    cols = ["markov", "shapley", "shapley_pct", "shapley_pct_p05", "shapley_pct_p95",
            "ultimo_no_directo_pct", "ingresos_shapley", "costo", "roas_shapley"]
    metricas = metricas.join(salida[cols], how="left")
    metricas["cpa_shapley"] = (metricas.costo / metricas.shapley).round(2)
    metricas = asignar_senal(metricas)  # señal accionable + confianza por canal

    return {
        "mart_atribucion__canal": salida.reset_index(),
        "mart_decision__canal": metricas.reset_index(),
        "mart_decision__pares_asistencia": pares,
        "mart_decision__rutas_top": rutas_top(rutas),
        "mart_calidad__conciliacion": conciliacion,
        "mart_calidad__error_modelo": pd.Series(error, name="error_medio_pp").round(2)
        .rename_axis("modelo").reset_index(),
    }


def main():
    con = duckdb.connect(str(BASE / "data" / "ecommerce.duckdb"))
    con.execute((SQL_DIR / "01_sesiones.sql").read_text())
    con.execute((SQL_DIR / "04_kpi_mensual.sql").read_text())
    kpi_mensual = con.sql("SELECT * FROM kpi_mensual").df()
    params = con.sql("SELECT params FROM truth").fetchone()[0]

    acumulado: dict[str, list[pd.DataFrame]] = {}
    meta = []
    for etiqueta, desde, corte, parcial in periodos(con):
        res = correr_periodo(con, corte, params)
        for nombre, df in res.items():
            acumulado.setdefault(nombre, []).append(df.assign(periodo=etiqueta))
        pedidos = int(res["mart_calidad__conciliacion"].pedidos_con_ruta.iloc[0])
        meta.append({"periodo": etiqueta, "desde": desde.date().isoformat(),
                     "hasta": corte.date().isoformat(), "pedidos": pedidos, "parcial": parcial})
        err = res["mart_calidad__error_modelo"].set_index("modelo").error_medio_pp
        print(f"{etiqueta}: pedidos={pedidos:,} error_shapley={err['shapley']:.2f}pp"
              f"{' (parcial)' if parcial else ''}")

    # Capa mart: lo único que consume el dashboard (y luego BigQuery / Looker)
    marts = {n: pd.concat(dfs, ignore_index=True) for n, dfs in acumulado.items()}
    periodos_df = pd.DataFrame(meta)
    # Semáforo de evidencia: cuántos pedidos sostienen los modelos en ese corte
    periodos_df["confianza"] = pd.cut(
        periodos_df.pedidos, [-1, 1000, 3000, 10**9], labels=["baja", "media", "alta"]
    ).astype(str)
    marts["mart_periodos"] = periodos_df
    marts["mart_kpi__mensual"] = kpi_mensual
    out = BASE / "resultados"
    out.mkdir(exist_ok=True)
    for nombre, df in marts.items():
        con.register("_df", df)
        con.execute(f"CREATE OR REPLACE TABLE {nombre} AS SELECT * FROM _df")
        con.unregister("_df")
        df.to_csv(out / f"{nombre}.csv", index=False)  # mismo contenido, listo para cargar a BQ
    con.close()

    ultimo = meta[-1]["periodo"]
    pd.set_option("display.width", 200, "display.max_columns", 30)
    print(f"\nAcumulado al cierre de {ultimo}:")
    print(marts["mart_decision__canal"].query("periodo == @ultimo")
          .drop(columns=["ingresos_cierre", "ingresos_shapley", "periodo"]).set_index("canal"))


if __name__ == "__main__":
    main()
