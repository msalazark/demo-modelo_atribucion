"""Validación del crédito atribuido con experimentos de incrementalidad (RQ-21 de docs/RQ_mejoras.md).

El cliente carga un CSV con los resultados de sus pruebas (holdout, geográfica, Conversion Lift de
Meta, etc.); este módulo compara esas ventas incrementales medidas con el crédito que le asignó el
modelo de atribución vigente y calcula, solo a título informativo, un factor de calibración por
canal. El factor nunca se aplica solo: `run_demo.py` lo deja en el mart para que el dashboard y el
intérprete lo muestren, pero las cuotas que ya calculan los modelos no cambian.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

COLUMNAS_REQUERIDAS = [
    "canal", "fecha_inicio", "fecha_fin", "tipo_prueba", "ventas_incrementales",
    "intervalo_90_bajo", "intervalo_90_alto", "fuente",
]


def cargar_experimentos(ruta: str | Path | None) -> pd.DataFrame | None:
    """Lee el CSV de experimentos. None si no hay ruta configurada o el archivo no existe todavía
    (no es un error: un cliente nuevo puede no tener experimentos corridos aún)."""
    if not ruta or not Path(ruta).exists():
        return None
    df = pd.read_csv(ruta)
    faltantes = set(COLUMNAS_REQUERIDAS) - set(df.columns)
    if faltantes:
        raise ValueError(f"experimentos.csv no tiene las columnas: {sorted(faltantes)}")
    df["fecha_inicio"] = pd.to_datetime(df.fecha_inicio)
    df["fecha_fin"] = pd.to_datetime(df.fecha_fin)
    return df


def mart_validacion_experimentos(
    experimentos: pd.DataFrame | None,
    atribucion: pd.Series,
    inicio_ventana: pd.Timestamp,
    corte_ventana: pd.Timestamp,
) -> pd.DataFrame:
    """Una fila por experimento: ventas atribuidas por el modelo (prorrateadas a los días del
    experimento), ventas incrementales medidas, si el atribuido cae dentro del intervalo medido
    ("validado") y el factor de calibración (medido / atribuido).

    `atribucion` es la cuota del modelo vigente (ventanas_atribucion_dias/ventana_vigente_dias) en
    conversiones, para la ventana de análisis completa (`inicio_ventana`-`corte_ventana`); se
    prorratea linealmente a la duración del experimento porque la demo no vuelve a correr el
    pipeline solo para esas fechas. En producción, con suficiente historia (RQ-19), conviene
    comparar contra la cuota medida en ese mismo periodo en vez de prorratear.
    """
    columnas = ["canal", "tipo_prueba", "fecha_inicio", "fecha_fin", "dias_prueba",
                "ventas_atribuidas_prorrateadas", "ventas_incrementales_medidas",
                "intervalo_90_bajo", "intervalo_90_alto", "validado", "factor_calibracion", "fuente"]
    if experimentos is None or experimentos.empty:
        return pd.DataFrame(columns=columnas)

    dias_totales = (corte_ventana.normalize() - inicio_ventana.normalize()).days + 1
    filas = []
    for r in experimentos.itertuples():
        if r.canal not in atribucion.index:
            continue
        dias_prueba = (r.fecha_fin - r.fecha_inicio).days + 1
        atribuido = atribucion[r.canal] * dias_prueba / dias_totales
        validado = r.intervalo_90_bajo <= atribuido <= r.intervalo_90_alto
        factor = round(r.ventas_incrementales / atribuido, 2) if atribuido else None
        filas.append({
            "canal": r.canal, "tipo_prueba": r.tipo_prueba,
            "fecha_inicio": r.fecha_inicio.date().isoformat(), "fecha_fin": r.fecha_fin.date().isoformat(),
            "dias_prueba": dias_prueba, "ventas_atribuidas_prorrateadas": round(atribuido, 1),
            "ventas_incrementales_medidas": r.ventas_incrementales,
            "intervalo_90_bajo": r.intervalo_90_bajo, "intervalo_90_alto": r.intervalo_90_alto,
            "validado": validado, "factor_calibracion": factor, "fuente": r.fuente,
        })
    return pd.DataFrame(filas, columns=columnas)


def estado_validacion_por_canal(canales_pagados: list[str], mart: pd.DataFrame) -> pd.DataFrame:
    """'Validado' / 'Sin validar' / 'Sin probar' por canal pagado, para el resumen del dashboard.
    Si un canal tiene más de un experimento, usa el más reciente (mayor fecha_fin)."""
    filas = []
    for canal in canales_pagados:
        exp_canal = mart[mart.canal == canal].sort_values("fecha_fin")
        if exp_canal.empty:
            filas.append({"canal": canal, "estado": "Sin probar", "factor_calibracion": None})
            continue
        ultimo = exp_canal.iloc[-1]
        filas.append({"canal": canal, "estado": "Validado" if ultimo.validado else "Sin validar",
                      "factor_calibracion": ultimo.factor_calibracion})
    return pd.DataFrame(filas)
