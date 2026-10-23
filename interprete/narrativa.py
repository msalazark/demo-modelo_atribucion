"""
Narrativa pregenerada (opción C): run_demo.py llama a generar_narrativas() al terminar y guarda el texto
de las vistas por defecto en la tabla mart_narrativa. El dashboard solo la lee.

Con ANTHROPIC_API_KEY el texto lo escribe Claude (anclado en los hechos y verificado); sin credenciales,
se guarda la lectura determinista (plantilla) y queda marcada como tal.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from .agente import Interprete
from .datos import DB_PATH, Lector, Vista, construir_hechos

TIPOS = ("resumen", "siguientes_pasos")


def generar_narrativas(db_path: Path | str = DB_PATH) -> pd.DataFrame:
    lector = Lector(db_path)
    interprete = Interprete(lector)
    v = Vista()
    hechos = construir_hechos(v, lector)
    filas = []
    for tipo in TIPOS:
        r = interprete.interpretar(v, tipo, hechos=hechos)
        filas.append({
            "tipo": tipo, "ventana_dias": v.ventana_dias, "dim": v.dim, "segmento": v.segmento, "modelo": v.modelo,
            "texto": r.texto, "generado_con": r.generado_con, "advertencias": " | ".join(r.advertencias),
            "generado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        })
    df = pd.DataFrame(filas)
    con = duckdb.connect(str(db_path))
    try:
        con.register("_df", df)
        con.execute("CREATE OR REPLACE TABLE mart_narrativa AS SELECT * FROM _df")
    finally:
        con.close()
    df.to_csv(Path(db_path).resolve().parent.parent / "resultados" / "mart_narrativa.csv", index=False)
    print("Narrativa:", ", ".join(f"{r['tipo']} ({r['generado_con']})" for r in filas))
    return df
