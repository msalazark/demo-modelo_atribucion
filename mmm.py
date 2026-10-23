"""Marketing Mix Model ligero (RQ-22, opcional, de docs/RQ_mejoras.md).

Adstock geométrico + curva de saturación de Hill + regresión bayesiana (`BayesianRidge` de
scikit-learn, que da intervalo de credibilidad sin necesitar MCMC) sobre inversión semanal por
canal, con controles de estacionalidad (mes) y feriados peruanos.

**No es Meridian ni PyMC-Marketing** (lo que pedía el RQ): ninguno de los dos está instalado en
este entorno -son dependencias pesadas, con compilación nativa- y agregarlos solo para un módulo
opcional no se justificó. El enfoque es afín en espíritu (adstock + saturación + regresión con
incertidumbre) pero sin inferencia MCMC completa ni los priors jerárquicos de esas librerías.
Migrar a una de ellas queda como siguiente paso si un cliente real lo pide en serio: la función
`semanal()` ya deja los datos en la forma (`date`, canal, inversión, ventas, controles) que
cualquiera de las dos espera.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.linear_model import BayesianRidge

# Feriados de fecha fija (se omiten los móviles -Semana Santa- para no mantener un cálculo de
# Pascua solo para esto). Alcanza para la señal de estacionalidad que necesita el MMM.
FERIADOS_PERU = {
    "2025-01-01", "2025-05-01", "2025-06-29", "2025-07-28", "2025-07-29", "2025-08-30",
    "2025-10-08", "2025-11-01", "2025-12-08", "2025-12-25",
    "2026-01-01", "2026-05-01", "2026-06-29", "2026-07-28", "2026-07-29", "2026-08-30",
    "2026-10-08", "2026-11-01", "2026-12-08", "2026-12-25",
}


def semanal(con, inicio: pd.Timestamp, corte: pd.Timestamp, canales_pagados: list[str]) -> pd.DataFrame:
    """Una fila por semana: ventas totales, inversión por canal (columnas anchas) y controles
    (mes, % de días feriados de la semana). Base del MMM: no entra a las rutas de atribución."""
    ventas = con.execute(
        "SELECT CAST(date_trunc('week', created_at AT TIME ZONE 'UTC') AS DATE) AS semana, "
        "sum(revenue_pen) AS ventas FROM orders WHERE status = 'pagado' "
        "AND created_at BETWEEN CAST(? AS TIMESTAMPTZ) AND CAST(? AS TIMESTAMPTZ) GROUP BY 1",
        [inicio.isoformat(), corte.isoformat()],
    ).df()
    costos = con.execute(
        "SELECT date_trunc('week', date) AS semana, channel AS canal, sum(cost_pen) AS costo "
        "FROM costs WHERE date BETWEEN CAST(? AS DATE) AND CAST(? AS DATE) GROUP BY 1, 2",
        [inicio.date().isoformat(), corte.date().isoformat()],
    ).df()
    ventas["semana"] = pd.to_datetime(ventas.semana)
    costos["semana"] = pd.to_datetime(costos.semana)
    costos_anchos = costos.pivot(index="semana", columns="canal", values="costo").reindex(columns=canales_pagados).fillna(0.0)
    costos_anchos.columns = [f"costo_{c}" for c in costos_anchos.columns]

    out = ventas.set_index("semana").join(costos_anchos, how="left").fillna(0.0).reset_index()
    out["mes"] = out.semana.dt.month
    out["pct_feriados"] = out.semana.apply(
        lambda s: sum((s + pd.Timedelta(days=d)).date().isoformat() in FERIADOS_PERU for d in range(7)) / 7)
    return out.sort_values("semana").reset_index(drop=True)


def adstock_geometrico(x: np.ndarray, decaimiento: float) -> np.ndarray:
    """El efecto de la inversión de una semana se arrastra a las siguientes, decayendo
    geométricamente (`decaimiento` en [0, 1): 0 = sin arrastre, cerca de 1 = casi permanente)."""
    out = np.zeros_like(x, dtype=float)
    acumulado = 0.0
    for i, v in enumerate(x):
        acumulado = v + decaimiento * acumulado
        out[i] = acumulado
    return out


def saturacion_hill(x: np.ndarray, media_efectiva: float, pendiente: float = 2.0) -> np.ndarray:
    """Retornos decrecientes: cerca de 0 para inversión baja, se acerca a 1 para inversión muy
    por encima de `media_efectiva` (el punto donde el efecto llega a la mitad de su máximo)."""
    media_efectiva = max(media_efectiva, 1e-6)
    xp = np.clip(x, 0, None) ** pendiente
    return xp / (xp + media_efectiva**pendiente)


def _transformar(costo: np.ndarray, decaimiento: float) -> tuple[np.ndarray, float]:
    adstock = adstock_geometrico(costo, decaimiento)
    media_efectiva = np.median(adstock[adstock > 0]) if (adstock > 0).any() else 1.0
    return saturacion_hill(adstock, media_efectiva), media_efectiva


def ajustar(semanal_df: pd.DataFrame, canales_pagados: list[str], decaimiento: float = 0.4) -> dict:
    """Ajusta un `BayesianRidge` sobre las variables transformadas (adstock + saturación) de cada
    canal más mes y feriados como controles. Devuelve coeficientes, intervalo de credibilidad y
    los parámetros de transformación (para poder reconstruir la curva de respuesta)."""
    cols_canal = [f"costo_{c}" for c in canales_pagados]
    X_partes, medias_efectivas = {}, {}
    for c, col in zip(canales_pagados, cols_canal):
        transformada, media_efectiva = _transformar(semanal_df[col].to_numpy(), decaimiento)
        X_partes[c] = transformada
        medias_efectivas[c] = media_efectiva
    X = pd.DataFrame(X_partes, index=semanal_df.index)
    # Estacionalidad como par seno/coseno (2 parámetros) en vez de 11 dummies de mes: con ~52
    # semanas de historia, 11 dummies dejan muy pocos grados de libertad para estimar el efecto
    # de los canales (se probó, el intervalo de credibilidad quedaba más ancho que el coeficiente).
    semana_del_anio = semanal_df.semana.dt.isocalendar().week.astype(float)
    X["estacion_sin"] = np.sin(2 * np.pi * semana_del_anio / 52)
    X["estacion_cos"] = np.cos(2 * np.pi * semana_del_anio / 52)
    X["pct_feriados"] = semanal_df.pct_feriados.to_numpy()

    # Estandarizar X: las variables ya están en [0, 1] (saturación) pero `ventas` está en miles de
    # soles; sin escalar, el prior de BayesianRidge (pensado para variables de escala similar)
    # encoge casi todos los coeficientes a 0 (se probó: el ajuste "funcionaba" pero no estimaba
    # nada). Los coeficientes se des-escalan después para quedar en unidades de la variable cruda
    # (soles por unidad de saturación), que es lo que necesitan curvas_respuesta/resumen_canal.
    escala = X.std(ddof=0).replace(0, 1.0)
    modelo = BayesianRidge()
    modelo.fit((X / escala).to_numpy(), semanal_df.ventas.to_numpy())
    ic_coef_escalado = modelo.sigma_.diagonal() ** 0.5  # desviación estándar posterior, en X escalada
    coef = modelo.coef_ / escala.to_numpy()
    coef_sd = ic_coef_escalado / escala.to_numpy()

    return {
        "modelo": modelo, "X": X, "canales": canales_pagados, "decaimiento": decaimiento,
        "medias_efectivas": medias_efectivas, "coef": dict(zip(X.columns, coef, strict=True)),
        "coef_sd": dict(zip(X.columns, coef_sd, strict=True)),
    }


def curvas_respuesta(semanal_df: pd.DataFrame, ajuste: dict, n_puntos: int = 20) -> pd.DataFrame:
    """Para cada canal: inversión semanal (de 0 a 1,5x el máximo histórico) y ventas estimadas que
    aportaría esa inversión manteniendo todo lo demás en su promedio (`mart_mmm__curvas`)."""
    filas = []
    for c in ajuste["canales"]:
        col = f"costo_{c}"
        maximo = semanal_df[col].max()
        if maximo <= 0:
            continue
        grilla = np.linspace(0, maximo * 1.5, n_puntos)
        saturada = saturacion_hill(grilla, ajuste["medias_efectivas"][c])
        contribucion = ajuste["coef"][c] * saturada
        for inv, cont in zip(grilla, contribucion, strict=True):
            filas.append({"canal": c, "inversion_semanal": round(float(inv), 2), "ventas_estimadas": round(float(cont), 2)})
    return pd.DataFrame(filas)


def resumen_canal(semanal_df: pd.DataFrame, ajuste: dict) -> pd.DataFrame:
    """ROAS marginal en la inversión semanal actual (promedio de las últimas 4 semanas): cuánto
    sube la venta estimada por un sol más, no el ROAS promedio (`mart_mmm__resumen`)."""
    filas = []
    for c in ajuste["canales"]:
        col = f"costo_{c}"
        actual = semanal_df[col].tail(4).mean()
        if actual <= 0:
            filas.append({"canal": c, "inversion_semanal_actual": 0.0, "roas_marginal": None,
                         "roas_marginal_p05": None, "roas_marginal_p95": None,
                         "decaimiento_adstock": ajuste["decaimiento"], "media_efectiva": ajuste["medias_efectivas"][c]})
            continue
        delta = max(actual * 0.01, 1.0)
        media_efectiva = ajuste["medias_efectivas"][c]
        base = saturacion_hill(np.array([actual]), media_efectiva)[0]
        alto = saturacion_hill(np.array([actual + delta]), media_efectiva)[0]
        coef, sd = ajuste["coef"][c], ajuste["coef_sd"][c]
        marginal = (alto - base) / delta
        filas.append({
            "canal": c, "inversion_semanal_actual": round(float(actual), 2),
            "roas_marginal": round(float(coef * marginal), 3),
            "roas_marginal_p05": round(float((coef - 1.645 * sd) * marginal), 3),
            "roas_marginal_p95": round(float((coef + 1.645 * sd) * marginal), 3),
            "decaimiento_adstock": ajuste["decaimiento"], "media_efectiva": round(float(media_efectiva), 2),
        })
    return pd.DataFrame(filas)
