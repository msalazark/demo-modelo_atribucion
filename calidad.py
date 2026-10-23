"""Controles de calidad de datos (RQ-18 de docs/RQ_mejoras.md): corren antes de los modelos y
detienen la corrida si falla un control crítico. Alimentan `mart_calidad__controles`.

Los controles 1-4 reutilizan los marts que ya calcula `run_demo.py` (conciliación y canales) para
no repetir consultas; los controles 5-6 (costos y caída de eventos) consultan directo.
"""
from __future__ import annotations

import duckdb
import pandas as pd

UMBRALES_DEFECTO = {
    "Pedidos con ruta": (85.0, "mayor_igual", "crítico"),
    "Pedidos vistos en GA4": (70.0, "mayor_igual", "alerta"),
    "Sesiones Unassigned": (5.0, "menor_igual", "alerta"),
    "Tráfico de Meta sin UTM": (10.0, "menor_igual", "alerta"),
    "Días sin costos de un canal pagado activo": (0, "menor_igual", "crítico"),
    "Caída de eventos vs. media de 28 días": (-30.0, "mayor_igual", "crítico"),
}


def _fila(control: str, valor: float, unidad: str) -> dict:
    umbral, comparador, severidad = UMBRALES_DEFECTO[control]
    ok = valor >= umbral if comparador == "mayor_igual" else valor <= umbral
    return {"control": control, "valor": round(valor, 2), "umbral": umbral, "unidad": unidad,
            "severidad": severidad, "estado": "ok" if ok else severidad}


def _dias_sin_costo(con: duckdb.DuckDBPyConnection, inicio: pd.Timestamp, corte: pd.Timestamp,
                     canales_pagados: list[str]) -> int:
    """Días en que un canal pagado tuvo sesiones (estuvo "activo") pero no hay fila de costo."""
    return con.execute(
        "WITH dias_activos AS ("
        # CAST(timestamptz AS DATE) usa la zona horaria de sesión de DuckDB, no UTC: sin el
        # AT TIME ZONE explícito, una sesión a medianoche UTC puede caer "un día antes".
        "  SELECT DISTINCT CAST(inicio_sesion AT TIME ZONE 'UTC' AS DATE) AS dia, canal FROM sesiones"
        "  WHERE NOT es_pasarela AND canal = ANY(?)"
        "    AND inicio_sesion BETWEEN CAST(? AS TIMESTAMPTZ) AND CAST(? AS TIMESTAMPTZ)"
        "), dias_con_costo AS ("
        "  SELECT DISTINCT date AS dia, channel AS canal FROM costs"
        "  WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE)"
        ")"
        "SELECT count(*) FROM dias_activos a LEFT JOIN dias_con_costo c USING (dia, canal) "
        "WHERE c.dia IS NULL",
        [canales_pagados, inicio.isoformat(), corte.isoformat(), inicio.date().isoformat(), corte.date().isoformat()],
    ).fetchone()[0]


def _caida_eventos_pct(con: duckdb.DuckDBPyConnection, corte: pd.Timestamp) -> float:
    """% de cambio del último día con eventos frente a la media de los 28 anteriores."""
    diarios = con.execute(
        "SELECT CAST(to_timestamp(event_timestamp / 1e6) AT TIME ZONE 'UTC' AS DATE) AS dia, count(*) AS n "
        "FROM events WHERE to_timestamp(event_timestamp / 1e6) BETWEEN "
        "CAST(? AS TIMESTAMPTZ) - INTERVAL 29 DAY AND CAST(? AS TIMESTAMPTZ) "
        "GROUP BY 1 ORDER BY 1",
        [corte.isoformat(), corte.isoformat()],
    ).df()
    if len(diarios) < 2:
        return 0.0
    ultimo = diarios.iloc[-1].n
    media_28 = diarios.iloc[:-1].n.mean()
    return (ultimo / media_28 - 1) * 100 if media_28 else 0.0


def controles_calidad(
    con: duckdb.DuckDBPyConnection,
    inicio: pd.Timestamp,
    corte: pd.Timestamp,
    canales_pagados: list[str],
    conciliacion_vigente: pd.Series,
    canales_calidad: pd.DataFrame,
) -> pd.DataFrame:
    """Un control por fila: valor medido, umbral, severidad y estado (ok/alerta/crítico).

    `conciliacion_vigente`: fila de `mart_calidad__conciliacion` de la ventana de atribución
    vigente. `canales_calidad`: `mart_calidad__canales` completa (filas Unassigned/Direct/
    Meta sin UTM).
    """
    pct_ruta = (conciliacion_vigente.pedidos_con_ruta / conciliacion_vigente.pedidos_backend * 100
                if conciliacion_vigente.pedidos_backend else 100.0)
    pct_ga4 = (conciliacion_vigente.pedidos_vistos_en_ga4 / conciliacion_vigente.pedidos_backend * 100
               if conciliacion_vigente.pedidos_backend else 100.0)
    cc = canales_calidad.set_index("canal")
    pct_unassigned = float(cc.loc["Unassigned", "pct"]) if "Unassigned" in cc.index else 0.0
    pct_meta_sin_utm = float(cc.loc["Meta (sin UTM)", "pct"]) if "Meta (sin UTM)" in cc.index else 0.0
    dias_sin_costo = _dias_sin_costo(con, inicio, corte, canales_pagados)
    caida_eventos = _caida_eventos_pct(con, corte)

    return pd.DataFrame([
        _fila("Pedidos con ruta", pct_ruta, "%"),
        _fila("Pedidos vistos en GA4", pct_ga4, "%"),
        _fila("Sesiones Unassigned", pct_unassigned, "%"),
        _fila("Tráfico de Meta sin UTM", pct_meta_sin_utm, "%"),
        _fila("Días sin costos de un canal pagado activo", dias_sin_costo, "días"),
        _fila("Caída de eventos vs. media de 28 días", caida_eventos, "%"),
    ])
