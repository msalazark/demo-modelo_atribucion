"""Pruebas de proximos_pasos.py (RQ-20): diseño de pruebas de incrementalidad."""
import pandas as pd

from proximos_pasos import diseno_prueba_incrementalidad


def _m():
    return pd.DataFrame({
        "costo": {"Paid Social": 10_000.0, "Paid Search": 8_000.0, "Email": float("nan")},
        "shapley": {"Paid Social": 300.0, "Paid Search": 200.0, "Email": 150.0},
        "ingresos": {"Paid Social": 30_000.0, "Paid Search": 20_000.0, "Email": 15_000.0},
        "usuarios_alcanzados": {"Paid Social": 10_000, "Paid Search": 8_000, "Email": 5_000},
    })


def test_solo_canales_pagados_tienen_prueba_de_holdout():
    out = diseno_prueba_incrementalidad(_m(), dias_totales=365)
    holdout = out[out.tipo_prueba == "holdout_usuario"]
    assert set(holdout.canal) == {"Paid Social", "Paid Search"}  # Email no tiene costo


def test_holdout_trae_tipo_duracion_emd_y_costo():
    out = diseno_prueba_incrementalidad(_m(), dias_totales=365)
    fila = out[(out.tipo_prueba == "holdout_usuario") & (out.canal == "Paid Social")].iloc[0]
    assert fila.tipo_prueba == "holdout_usuario"
    assert fila.semanas > 0
    assert fila.emd_relativo_pct > 0
    assert fila.costo_prueba_pedidos > 0
    assert fila.costo_prueba_soles > 0  # hay ingresos -> se puede estimar en soles


def test_prueba_geografica_usa_una_region_como_control():
    geo = pd.DataFrame([
        {"canal": "Paid Social", "segmento": "Lima", "usuarios_alcanzados": 7000},
        {"canal": "Paid Social", "segmento": "Provincias", "usuarios_alcanzados": 3000},
    ])
    out = diseno_prueba_incrementalidad(_m(), dias_totales=365, geo=geo)
    geograficas = out[out.tipo_prueba == "geografica"]
    assert set(geograficas.region_control) == {"Lima", "Provincias"}
    assert (geograficas.emd_relativo_pct > 0).all()


def test_sin_geo_no_genera_filas_geograficas():
    out = diseno_prueba_incrementalidad(_m(), dias_totales=365, geo=None)
    assert (out.tipo_prueba != "geografica").all()


def test_plantilla_conversion_lift_meta_solo_para_paid_social():
    out = diseno_prueba_incrementalidad(_m(), dias_totales=365)
    meta = out[out.tipo_prueba == "conversion_lift_meta"]
    assert set(meta.canal) == {"Paid Social"}
    assert meta.iloc[0].insumos  # trae texto de insumos
    assert meta.iloc[0].semanas == 4  # duración mínima que recomienda Meta
