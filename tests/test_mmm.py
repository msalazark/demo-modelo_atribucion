"""Pruebas de mmm.py (RQ-22, opcional): adstock, saturación y ajuste del MMM ligero."""
import numpy as np
import pandas as pd
import pytest

from mmm import adstock_geometrico, ajustar, curvas_respuesta, resumen_canal, saturacion_hill


def test_adstock_sin_decaimiento_no_arrastra():
    x = np.array([10.0, 0.0, 0.0])
    out = adstock_geometrico(x, decaimiento=0.0)
    assert out.tolist() == [10.0, 0.0, 0.0]


def test_adstock_con_decaimiento_arrastra():
    x = np.array([10.0, 0.0, 0.0])
    out = adstock_geometrico(x, decaimiento=0.5)
    assert out[1] == pytest.approx(5.0)
    assert out[2] == pytest.approx(2.5)


def test_saturacion_cero_en_cero():
    assert saturacion_hill(np.array([0.0]), media_efectiva=100.0)[0] == 0.0


def test_saturacion_es_mitad_en_la_media_efectiva():
    out = saturacion_hill(np.array([100.0]), media_efectiva=100.0)
    assert out[0] == pytest.approx(0.5, abs=0.01)


def test_saturacion_creciente_y_acotada_en_1():
    out = saturacion_hill(np.linspace(0, 1000, 20), media_efectiva=100.0)
    assert (np.diff(out) >= 0).all()
    assert out[-1] < 1.0


def _semanal_sintetica(n=60, seed=0):
    rng = np.random.default_rng(seed)
    semanas = pd.date_range("2025-01-06", periods=n, freq="W-MON")
    costo_a = rng.uniform(500, 1500, n)
    costo_b = rng.uniform(200, 800, n)
    ventas = 3 * costo_a + 5 * costo_b + rng.normal(0, 200, n) + 10_000
    return pd.DataFrame({
        "semana": semanas, "ventas": ventas, "costo_Canal A": costo_a, "costo_Canal B": costo_b,
        "mes": semanas.month, "pct_feriados": 0.0,
    })


def test_ajustar_devuelve_coeficientes_positivos_con_senal_fuerte():
    sem = _semanal_sintetica()
    ajuste = ajustar(sem, ["Canal A", "Canal B"])
    assert ajuste["coef"]["Canal A"] > 0
    assert ajuste["coef"]["Canal B"] > 0


def test_curvas_respuesta_son_crecientes():
    sem = _semanal_sintetica()
    ajuste = ajustar(sem, ["Canal A", "Canal B"])
    curvas = curvas_respuesta(sem, ajuste)
    for canal in ["Canal A", "Canal B"]:
        serie = curvas[curvas.canal == canal].sort_values("inversion_semanal")
        assert (serie.ventas_estimadas.diff().dropna() >= -1e-6).all()


def test_resumen_canal_trae_roas_marginal_e_intervalo():
    sem = _semanal_sintetica()
    ajuste = ajustar(sem, ["Canal A", "Canal B"])
    resumen = resumen_canal(sem, ajuste)
    assert set(resumen.canal) == {"Canal A", "Canal B"}
    fila = resumen[resumen.canal == "Canal A"].iloc[0]
    assert fila.roas_marginal_p05 <= fila.roas_marginal <= fila.roas_marginal_p95


def test_canal_sin_inversion_no_rompe():
    sem = _semanal_sintetica()
    sem["costo_Canal C"] = 0.0
    ajuste = ajustar(sem, ["Canal A", "Canal B", "Canal C"])
    resumen = resumen_canal(sem, ajuste)
    fila = resumen[resumen.canal == "Canal C"].iloc[0]
    assert pd.isna(fila.roas_marginal)
