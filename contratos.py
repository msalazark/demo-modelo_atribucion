"""Contratos de datos de entrada (RQ-03 de docs/RQ_mejoras.md): esquema mínimo de cada fuente,
documentado en docs/contratos_datos.md.

`validar_fuente()` se corre antes de los SQL (run_demo.py): falla si faltan campos obligatorios e
informa el % de nulos de cada campo declarado. No valida *valores* (eso es RQ-18, controles de
calidad); aquí solo se confirma que la fuente tiene la forma esperada antes de procesarla.
"""
from __future__ import annotations

import pandas as pd

CONTRATOS: dict[str, dict[str, list[str]]] = {
    "eventos_ga4": {
        "obligatorios": ["event_date", "event_timestamp", "event_name", "user_pseudo_id",
                         "event_params.ga_session_id", "collected_traffic_source.*"],
        "opcionales": ["user_id", "device.category", "geo.region", "page_location",
                       "ecommerce.transaction_id"],
    },
    "pedidos": {
        "obligatorios": ["order_id", "created_at", "status", "revenue", "ga_client_id"],
        "opcionales": ["paid_at", "ga_session_id", "fbp", "fbc", "customer_id", "payment_method",
                       "customer_type", "margen"],
    },
    "costos": {
        "obligatorios": ["date", "platform", "campaign_id", "campaign_name", "cost"],
        "opcionales": ["impressions", "clicks", "reach", "platform_conversions",
                       "platform_conversion_value"],
    },
}


def _columna(campo: str, alias: dict[str, str]) -> str:
    """Nombre real de columna para un campo del contrato (puede venir anidado, p. ej.
    `event_params.ga_session_id`): el alias puede mapear el campo completo o solo su raíz."""
    raiz = campo.split(".")[0]
    return alias.get(campo, alias.get(raiz, raiz))


def validar_fuente(nombre: str, df: pd.DataFrame, alias: dict[str, str] | None = None) -> dict:
    """Valida que `df` cumpla el contrato de la fuente `nombre` (ver docs/contratos_datos.md).

    `alias` mapea un campo del contrato a la columna real de `df`, para fuentes cuyos nombres de
    columna no coinciden literalmente con el contrato (p. ej. esta demo usa `revenue_pen` en vez
    de `revenue`). Lanza `ValueError` si falta un campo obligatorio; si no, devuelve el número de
    filas y el % de nulos de cada campo presente (obligatorio u opcional).
    """
    if nombre not in CONTRATOS:
        raise ValueError(f"Fuente desconocida: '{nombre}'. Fuentes válidas: {sorted(CONTRATOS)}")
    alias = alias or {}
    contrato = CONTRATOS[nombre]

    faltantes = [campo for campo in contrato["obligatorios"] if _columna(campo, alias) not in df.columns]
    if faltantes:
        raise ValueError(f"Fuente '{nombre}': faltan campos obligatorios {faltantes} "
                         f"(columnas disponibles: {list(df.columns)})")

    pct_nulos = {}
    for campo in contrato["obligatorios"] + contrato["opcionales"]:
        col = _columna(campo, alias)
        if col in df.columns:
            pct_nulos[campo] = round(float(df[col].isna().mean() * 100), 2)
    return {"fuente": nombre, "filas": len(df), "pct_nulos": pct_nulos}
