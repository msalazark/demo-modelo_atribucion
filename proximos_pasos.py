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


def _emd_relativo(n_c: float, n_t: float, p: float, z: float) -> float:
    """Efecto mínimo detectable relativo (%) con grupos de tamaño n_c (control) y n_t (tratamiento)
    y tasa base p, para el z de confianza/poder ya combinado."""
    emd_abs = z * np.sqrt(p * (1 - p) * (1 / n_c + 1 / n_t))
    return round(emd_abs / p * 100, 1)


def diseno_prueba_incrementalidad(
    m: pd.DataFrame,
    dias_totales: int,
    geo: pd.DataFrame | None = None,
    semanas: tuple[int, ...] = (4, 8, 12),
    holdouts: tuple[float, ...] = (0.10, 0.20, 0.50),
    alfa: float = 0.05,
    poder: float = 0.80,
) -> pd.DataFrame:
    """
    Diseño de pruebas de incrementalidad por canal pagado (RQ-20): tipo de prueba, duración,
    efecto mínimo detectable (EMD) y costo estimado (ventas que se dejan de ganar en el grupo de
    control, asumiendo que el canal tiene el efecto que ya le atribuye el modelo).

    Tipos:
      holdout_usuario: un % de los usuarios no ve el canal (`m`: costo, shapley, usuarios_alcanzados,
        ingresos opcional para el costo en soles).
      geografica: una región se queda sin el canal (control) y el resto sigue expuesto (`geo`:
        canal, segmento (región), usuarios_alcanzados; se omite si no se pasa `geo`).
      conversion_lift_meta: plantilla con los insumos que pide Meta y la duración sugerida.

    Supuestos (estimación de planificación, no un cálculo de potencia definitivo):
      - Usuarios expuestos por semana = usuarios alcanzados / semanas de datos.
      - Tasa base = conversiones atribuidas (Shapley) por usuario alcanzado.
      - EMD = menor diferencia relativa entre grupos que la prueba detecta con la
        confianza y el poder indicados.
    """
    pagados = m.dropna(subset=["costo"])
    z = norm.ppf(1 - alfa / 2) + norm.ppf(poder)
    tiene_ingresos = "ingresos" in m.columns
    filas = []
    for canal, r in pagados.iterrows():
        usuarios_semana = r.usuarios_alcanzados / (dias_totales / 7)
        p = r.shapley / r.usuarios_alcanzados
        ticket = (r.ingresos / r.shapley) if tiene_ingresos and r.shapley else None
        for w in semanas:
            for h in holdouts:
                n = usuarios_semana * w
                n_c, n_t = n * h, n * (1 - h)
                pedidos_perdidos = n_c * p
                filas.append({
                    "canal": canal, "tipo_prueba": "holdout_usuario", "semanas": w, "holdout_pct": int(h * 100),
                    "usuarios_prueba": int(n), "usuarios_control": int(n_c),
                    "tasa_base_pct": round(p * 100, 2), "emd_relativo_pct": _emd_relativo(n_c, n_t, p, z),
                    "costo_prueba_pedidos": round(pedidos_perdidos, 1),
                    "costo_prueba_soles": round(pedidos_perdidos * ticket, 0) if ticket else None,
                })

    if geo is not None and len(geo):
        filas += _prueba_geografica(m, geo, dias_totales, semanas, z)
    filas += _plantilla_conversion_lift_meta(m, dias_totales, z)
    return pd.DataFrame(filas)


def _prueba_geografica(
    m: pd.DataFrame, geo: pd.DataFrame, dias_totales: int, semanas: tuple[int, ...], z: float,
) -> list[dict]:
    """Una región por canal se deja sin el canal (control); el resto de regiones sigue expuesto
    (tratamiento). En producción, `geo` trae departamentos en vez de las dos regiones de la demo."""
    filas = []
    pagados = m.dropna(subset=["costo"])
    for canal, r in pagados.iterrows():
        regiones = geo[geo.canal == canal].set_index("segmento").usuarios_alcanzados
        if len(regiones) < 2:
            continue
        total = regiones.sum()
        p = r.shapley / r.usuarios_alcanzados
        for region_control, usuarios_control in regiones.items():
            usuarios_tratamiento = total - usuarios_control
            for w in semanas:
                frac = w / (dias_totales / 7)
                n_c, n_t = usuarios_control * frac, usuarios_tratamiento * frac
                if n_c <= 0 or n_t <= 0:
                    continue
                filas.append({
                    "canal": canal, "tipo_prueba": "geografica", "semanas": w,
                    "region_control": region_control, "usuarios_prueba": int(n_c + n_t),
                    "usuarios_control": int(n_c), "tasa_base_pct": round(p * 100, 2),
                    "emd_relativo_pct": _emd_relativo(n_c, n_t, p, z),
                    "costo_prueba_pedidos": round(n_c * p, 1),
                })
    return filas


def _plantilla_conversion_lift_meta(m: pd.DataFrame, dias_totales: int, z: float, semanas: int = 4) -> list[dict]:
    """Insumos que pide Meta Conversion Lift (holdout aleatorizado por la propia plataforma,
    típicamente 10-20 % de la audiencia) y la duración mínima que recomienda Meta (4 semanas)."""
    filas = []
    pagados = m.dropna(subset=["costo"])
    holdout_meta = 0.10
    for canal, r in pagados.iterrows():
        if canal not in ("Paid Social",):  # Conversion Lift es específico de Meta
            continue
        usuarios_semana = r.usuarios_alcanzados / (dias_totales / 7)
        n = usuarios_semana * semanas
        n_c, n_t = n * holdout_meta, n * (1 - holdout_meta)
        p = r.shapley / r.usuarios_alcanzados
        filas.append({
            "canal": canal, "tipo_prueba": "conversion_lift_meta", "semanas": semanas,
            "holdout_pct": int(holdout_meta * 100), "usuarios_prueba": int(n), "usuarios_control": int(n_c),
            "tasa_base_pct": round(p * 100, 2), "emd_relativo_pct": _emd_relativo(n_c, n_t, p, z),
            "costo_prueba_pedidos": round(n_c * p, 1),
            "insumos": ("Business Manager con permiso de Conversion Lift; evento de conversión "
                       "configurado en el píxel/CAPI; presupuesto mínimo según Meta (suele pedir "
                       "spend diario estable durante toda la prueba); no pausar ni cambiar "
                       "creatividades/audiencias mientras corre."),
        })
    return filas
