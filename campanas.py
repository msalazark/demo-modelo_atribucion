"""Nivel campaña y comparación contra lo que reportan las plataformas de medios (RQ-09/RQ-15/RQ-16
de docs/RQ_mejoras.md).

RQ-09 no corre Shapley a nivel campaña (no escala: ver RQ-13 y su límite de jugadores). En cambio,
atribuye a nivel **canal** con los modelos actuales y reparte ese crédito entre las campañas del
canal en proporción a sus sesiones dentro de las rutas convertidas -- una aproximación declarada,
no una atribución de campaña independiente.
"""
from __future__ import annotations

import pandas as pd

PLATAFORMA_DEL_CANAL = {"Paid Social": "Meta Ads", "Paid Search": "Google Ads", "Display": "Google Ads"}


def _sesiones_por_campana(rutas: pd.DataFrame, canales_pagados: list[str]) -> pd.DataFrame:
    """Sesiones por (canal, campaña) dentro de rutas convertidas y su participación dentro del
    canal (suma 1 por canal). Cuenta apariciones de sesión, no pedidos: una campaña que aparece
    dos veces en la misma ruta pesa el doble, igual que cuentan los roles (RQ-11)."""
    filas = [(canal, campana) for ruta, ruta_campana in
             zip(rutas.loc[rutas.convirtio, "ruta"], rutas.loc[rutas.convirtio, "ruta_campana"])
             for canal, campana in zip(ruta, ruta_campana) if canal in canales_pagados]
    conteo = pd.DataFrame(filas, columns=["canal", "campana"]).value_counts().reset_index(name="sesiones")
    conteo["participacion_pct"] = (conteo.sesiones / conteo.groupby("canal").sesiones.transform("sum") * 100).round(2)
    return conteo


def credito_por_campana(rutas: pd.DataFrame, credito_canal: pd.DataFrame, costo_campana: pd.Series,
                        canales_pagados: list[str]) -> pd.DataFrame:
    """`credito_canal`: DataFrame indexado por canal con `conversiones`/`ingresos` del modelo
    vigente (p. ej. `mart_modelos__comparativo` filtrado a ese modelo). `costo_campana`: Series
    indexada por campaña con el costo de la ventana de análisis (no de atribución).

    La suma de `conversiones`/`ingresos` por canal coincide exactamente con `credito_canal`
    (la participación de las campañas de un canal suma 100 %): es la base de la prueba de paridad.
    """
    out = _sesiones_por_campana(rutas, canales_pagados)
    out = out.merge(credito_canal[["conversiones", "ingresos"]], left_on="canal", right_index=True)
    out["conversiones"] = (out.conversiones * out.participacion_pct / 100).round(2)
    out["ingresos"] = (out.ingresos * out.participacion_pct / 100).round(2)
    out["costo"] = out.campana.map(costo_campana).round(2)
    out["roas"] = (out.ingresos / out.costo).round(2)
    out["cpa"] = (out.costo / out.conversiones).round(2)
    return out[["canal", "campana", "sesiones", "participacion_pct", "conversiones", "ingresos", "costo", "roas", "cpa"]]


def comparacion_plataformas(campanas_modelo: pd.DataFrame, reportado: pd.DataFrame) -> pd.DataFrame:
    """`campanas_modelo`: salida de `credito_por_campana` (canal, campana, conversiones, ingresos).
    `reportado`: `platform_conversions`/`platform_revenue` de `reportado_plataformas`, ya agregado
    por campaña para la ventana de análisis.

    `brecha_pct` > 0: la plataforma reclama más de lo que el modelo le atribuye -- siempre va a
    pasar algo de esto por las vistas sin clic (no generan sesión en GA4, el modelo no las ve) y
    por rutas que pasaron por más de un canal pagado (cada plataforma reclama la venta completa
    con su propia medición). No es un error del modelo: es la brecha estructural entre "último
    clic de la plataforma" y una atribución multi-touch sobre todos los canales.
    """
    out = campanas_modelo[["canal", "campana", "conversiones", "ingresos"]].merge(
        reportado, left_on="campana", right_index=True, how="left"
    ).rename(columns={"canal": "plataforma_canal", "conversiones": "conv_modelo", "ingresos": "ingresos_modelo",
                      "platform_conversions": "conv_plataforma", "platform_revenue": "ingresos_plataforma"})
    out["plataforma"] = out.plataforma_canal.map(PLATAFORMA_DEL_CANAL)
    out["brecha_pct"] = ((out.conv_plataforma - out.conv_modelo) / out.conv_modelo * 100).round(1)
    return out.rename(columns={"campana": "campaign_id", "plataforma_canal": "canal"})[
        ["plataforma", "canal", "campaign_id", "conv_plataforma", "conv_modelo",
         "ingresos_plataforma", "ingresos_modelo", "brecha_pct"]]
