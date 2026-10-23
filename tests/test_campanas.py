"""Pruebas de campanas.py (RQ-09/RQ-15/RQ-16): crédito por campaña y comparación con plataformas."""
import pandas as pd
import pytest

from campanas import comparacion_plataformas, credito_por_campana


def _rutas():
    return pd.DataFrame({
        "convirtio": [True, True, True, True, False],
        "ruta": [
            ["Paid Social", "Paid Search"],
            ["Paid Social"],
            ["Paid Social"],
            ["Paid Search"],
            ["Paid Social"],  # no convertida: no debe contar
        ],
        "ruta_campana": [
            ["paid_social_prospecting", "paid_search_marca"],
            ["paid_social_retargeting"],
            ["paid_social_prospecting"],
            ["paid_search_generica"],
            ["paid_social_prospecting"],
        ],
    })


def _credito_canal():
    return pd.DataFrame({"conversiones": [300.0, 200.0], "ingresos": [30_000.0, 20_000.0]},
                        index=["Paid Social", "Paid Search"])


def _costo_campana():
    return pd.Series({"paid_social_prospecting": 1000.0, "paid_social_retargeting": 500.0,
                      "paid_search_marca": 400.0, "paid_search_generica": 800.0})


def test_ignora_rutas_no_convertidas():
    out = credito_por_campana(_rutas(), _credito_canal(), _costo_campana(), ["Paid Social", "Paid Search"])
    # paid_social_prospecting aparece en 2 rutas convertidas de 3 de Paid Social -> 2/3
    fila = out[out.campana == "paid_social_prospecting"].iloc[0]
    assert fila.sesiones == 2
    assert fila.participacion_pct == pytest.approx(66.67, abs=0.1)


def test_la_suma_por_canal_coincide_con_el_credito_de_canal():
    out = credito_por_campana(_rutas(), _credito_canal(), _costo_campana(), ["Paid Social", "Paid Search"])
    suma = out.groupby("canal")[["conversiones", "ingresos"]].sum()
    assert suma.loc["Paid Social", "conversiones"] == pytest.approx(300.0, abs=0.1)
    assert suma.loc["Paid Search", "conversiones"] == pytest.approx(200.0, abs=0.1)
    assert suma.loc["Paid Social", "ingresos"] == pytest.approx(30_000.0, abs=1)


def test_roas_y_cpa_por_campana():
    out = credito_por_campana(_rutas(), _credito_canal(), _costo_campana(), ["Paid Social", "Paid Search"])
    fila = out[out.campana == "paid_search_marca"].iloc[0]
    assert fila.costo == 400.0
    assert fila.roas == pytest.approx(fila.ingresos / 400.0, abs=0.01)
    assert fila.cpa == pytest.approx(400.0 / fila.conversiones, abs=0.01)


def test_canal_sin_campanas_pagadas_no_aparece():
    out = credito_por_campana(_rutas(), _credito_canal(), _costo_campana(), ["Paid Social", "Paid Search"])
    assert set(out.canal) == {"Paid Social", "Paid Search"}


def test_comparacion_plataformas_calcula_brecha():
    campanas = credito_por_campana(_rutas(), _credito_canal(), _costo_campana(), ["Paid Social", "Paid Search"])
    reportado = pd.DataFrame({
        "platform_conversions": [250.0, 120.0, 90.0],
        "platform_revenue": [50_000.0, 24_000.0, 18_000.0],
    }, index=pd.Index(["paid_social_prospecting", "paid_social_retargeting", "paid_search_marca"], name="campana"))
    comp = comparacion_plataformas(campanas, reportado)
    assert set(comp.columns) == {"plataforma", "canal", "campaign_id", "conv_plataforma", "conv_modelo",
                                 "ingresos_plataforma", "ingresos_modelo", "brecha_pct"}
    fila = comp[comp.campaign_id == "paid_social_prospecting"].iloc[0]
    assert fila.plataforma == "Meta Ads"
    assert fila.brecha_pct > 0  # la plataforma reclama más de lo que el modelo le atribuye


def test_comparacion_plataformas_sin_reporte_da_nan():
    campanas = credito_por_campana(_rutas(), _credito_canal(), _costo_campana(), ["Paid Social", "Paid Search"])
    reportado = pd.DataFrame({"platform_conversions": [250.0], "platform_revenue": [50_000.0]},
                             index=pd.Index(["paid_social_prospecting"], name="campana"))
    comp = comparacion_plataformas(campanas, reportado)
    sin_dato = comp[comp.campaign_id == "paid_search_generica"].iloc[0]
    assert pd.isna(sin_dato.conv_plataforma)
