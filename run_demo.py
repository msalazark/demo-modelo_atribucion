"""
Corre la demo completa:
  1. SQL: sesiones -> rutas -> conciliación (DuckDB, misma lógica que en BigQuery)
  2. Modelos: último clic no directo (referencia), Markov y Shapley
  3. Validación contra el efecto real (solo posible con datos sintéticos)
  4. Exporta resultados/*.csv

Uso:
  python generar_datos.py   # una vez
  python run_demo.py
"""
from pathlib import Path

import duckdb
import pandas as pd

from atribucion import efecto_real, markov, shapley, ultimo_no_directo

BASE = Path(__file__).parent
CANALES_PAGADOS = ["Paid Social", "Paid Search", "Display"]


def main():
    con = duckdb.connect(str(BASE / "data" / "ecommerce.duckdb"))
    for f in ("01_sesiones.sql", "02_rutas.sql", "03_conciliacion.sql"):
        con.execute((BASE / "sql" / f).read_text())

    rutas = con.sql("SELECT user_pseudo_id, order_id, revenue_pen, convirtio, ruta FROM rutas").df()
    rutas["ruta"] = rutas.ruta.apply(list)
    conciliacion = con.sql("SELECT * FROM conciliacion").df()
    costos = con.sql("SELECT channel AS canal, sum(cost_pen) AS costo FROM costs GROUP BY 1").df().set_index("canal").costo
    params = con.sql("SELECT params FROM truth").fetchone()[0]

    ref = ultimo_no_directo(rutas)
    mk, diag_mk = markov(rutas)
    sh, diag_sh = shapley(rutas)
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

    # Estabilidad: intervalo del 90 % de la cuota Shapley con 50 remuestreos bootstrap
    muestras = []
    for b in range(50):
        s = rutas.sample(len(rutas), replace=True, random_state=b).reset_index(drop=True)
        sh_b, _ = shapley(s)
        muestras.append(sh_b.conversiones / sh_b.conversiones.sum() * 100)
    intervalos = pd.DataFrame(muestras).quantile([0.05, 0.95]).T.round(1)
    salida["shapley_pct_p05"] = intervalos[0.05]
    salida["shapley_pct_p95"] = intervalos[0.95]

    out = BASE / "resultados"
    out.mkdir(exist_ok=True)
    salida.to_csv(out / "atribucion_por_canal.csv")
    conciliacion.to_csv(out / "conciliacion.csv", index=False)
    pd.Series(error, name="error_medio_pp").round(2).to_csv(out / "error_vs_real.csv")

    pd.set_option("display.width", 200)
    print(conciliacion.T)
    print(salida)
    print("Error medio absoluto vs efecto real (puntos porcentuales):", {k: round(v, 2) for k, v in error.items()})
    print("Markov:", diag_mk, "| Shapley:", diag_sh)


if __name__ == "__main__":
    main()
