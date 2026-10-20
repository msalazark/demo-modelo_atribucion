"""
Análisis para los siguientes pasos de la solución, con la data que ya se tiene:

  - tiempo_hasta_compra(): cuántos días pasan entre el primer contacto y la compra
    (justifica la ventana de atribución).
  - diseno_prueba_incrementalidad(): qué tan pequeño es el efecto que una prueba de holdout
    podría detectar en cada canal pagado, según el tráfico real del canal.

Lógica pura (DataFrames in / DataFrames out); la orquesta run_demo.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm


def tiempo_hasta_compra(
    rutas: pd.DataFrame, ventana_dias: int = 30, ancho: int = 3
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (percentiles por canal de apertura, histograma con tramos de `ancho` días)."""
    conv = rutas[rutas.convirtio].copy()
    conv["dias"] = conv.dias_antes.apply(max)  # la sesión más antigua de la ruta
    conv["canal_apertura"] = conv.ruta.apply(lambda r: r[0])

    por_canal = (
        conv.groupby("canal_apertura").dias
        .agg(pedidos="count", dias_p50=lambda s: s.quantile(.5), dias_p90=lambda s: s.quantile(.9))
        .round(1).reset_index()
    )
    total = pd.DataFrame([{
        "canal_apertura": "(todos)", "pedidos": len(conv),
        "dias_p50": round(conv.dias.quantile(.5), 1), "dias_p90": round(conv.dias.quantile(.9), 1),
    }])
    por_canal = pd.concat([total, por_canal], ignore_index=True)

    bordes = list(range(0, ventana_dias + ancho, ancho))
    cortes = pd.cut(conv.dias, bordes, right=False, include_lowest=True)
    hist = cortes.value_counts(sort=False).rename("pedidos").reset_index()
    hist["dias_desde"] = [int(i.left) for i in hist.dias]
    hist["rango"] = [f"{int(i.left)}-{int(i.right)}" for i in hist.dias]
    hist["pct"] = (hist.pedidos / hist.pedidos.sum() * 100).round(1)
    return por_canal, hist[["dias_desde", "rango", "pedidos", "pct"]]


def diseno_prueba_incrementalidad(
    m: pd.DataFrame,
    dias_totales: int,
    semanas: tuple[int, ...] = (4, 8, 12),
    holdouts: tuple[float, ...] = (0.10, 0.20, 0.50),
    alfa: float = 0.05,
    poder: float = 0.80,
) -> pd.DataFrame:
    """
    Efecto mínimo detectable (EMD) de una prueba de holdout por canal pagado.

    Supuestos (estimación de planificación, no un cálculo de potencia definitivo):
      - Usuarios expuestos por semana = usuarios alcanzados / semanas de datos.
      - Tasa base = conversiones atribuidas (Shapley) por usuario alcanzado.
      - Un grupo de control (holdout) deja de ver el canal; el resto sigue expuesto.
      - EMD = menor diferencia relativa entre grupos que la prueba detecta con la
        confianza y el poder indicados.
    """
    pagados = m.dropna(subset=["costo"])
    z = norm.ppf(1 - alfa / 2) + norm.ppf(poder)
    filas = []
    for canal, r in pagados.iterrows():
        usuarios_semana = r.usuarios_alcanzados / (dias_totales / 7)
        p = r.shapley / r.usuarios_alcanzados
        for w in semanas:
            for h in holdouts:
                n = usuarios_semana * w
                n_c, n_t = n * h, n * (1 - h)
                emd_abs = z * np.sqrt(p * (1 - p) * (1 / n_c + 1 / n_t))
                filas.append({
                    "canal": canal, "semanas": w, "holdout_pct": int(h * 100),
                    "usuarios_prueba": int(n), "usuarios_control": int(n_c),
                    "tasa_base_pct": round(p * 100, 2), "emd_relativo_pct": round(emd_abs / p * 100, 1),
                })
    return pd.DataFrame(filas)
