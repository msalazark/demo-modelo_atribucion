"""Pruebas de experimentos.py (RQ-21): validación con experimentos y factor de calibración."""
import pandas as pd
import pytest

from experimentos import cargar_experimentos, estado_validacion_por_canal, mart_validacion_experimentos


def test_cargar_experimentos_none_si_no_hay_ruta():
    assert cargar_experimentos(None) is None


def test_cargar_experimentos_none_si_el_archivo_no_existe():
    assert cargar_experimentos("no/existe/experimentos.csv") is None


def test_cargar_experimentos_valida_columnas(tmp_path):
    ruta = tmp_path / "experimentos.csv"
    ruta.write_text("canal,fecha_inicio\nPaid Social,2026-06-01\n")
    with pytest.raises(ValueError, match="columnas"):
        cargar_experimentos(ruta)


def _experimentos():
    return pd.DataFrame({
        "canal": ["Paid Social", "Paid Search"],
        "fecha_inicio": pd.to_datetime(["2026-06-01", "2026-03-03"]),
        "fecha_fin": pd.to_datetime(["2026-07-26", "2026-03-30"]),
        "tipo_prueba": ["holdout_usuario", "geografica"],
        "ventas_incrementales": [250, 58],
        "intervalo_90_bajo": [210, 42],
        "intervalo_90_alto": [290, 74],
        "fuente": ["Holdout interno", "Prueba geográfica"],
    })


def test_mart_vacio_sin_experimentos():
    atribucion = pd.Series({"Paid Social": 1000.0})
    out = mart_validacion_experimentos(None, atribucion, pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-30"))
    assert out.empty


def test_mart_prorratea_y_valida_dentro_del_intervalo():
    # 365 días totales; Paid Social tiene 1529.8 conversiones -> prorrateado a 56 días = 234.6,
    # dentro de [210, 290] del experimento -> validado.
    atribucion = pd.Series({"Paid Social": 1529.8, "Paid Search": 1221.9})
    out = mart_validacion_experimentos(_experimentos(), atribucion, pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-30"))
    fila = out[out.canal == "Paid Social"].iloc[0]
    assert fila.dias_prueba == 56
    assert fila.ventas_atribuidas_prorrateadas == pytest.approx(234.6, abs=0.5)
    assert fila.validado
    assert fila.factor_calibracion == pytest.approx(250 / 234.6, abs=0.01)


def test_mart_detecta_sobreestimacion_fuera_del_intervalo():
    # Paid Search prorrateado (~93.7) queda por encima de [42, 74] -> sin validar.
    atribucion = pd.Series({"Paid Social": 1529.8, "Paid Search": 1221.9})
    out = mart_validacion_experimentos(_experimentos(), atribucion, pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-30"))
    fila = out[out.canal == "Paid Search"].iloc[0]
    assert not fila.validado
    assert fila.factor_calibracion < 1  # el experimento mide menos de lo que el modelo atribuye


def test_mart_ignora_canal_sin_cuota_atribuida():
    atribucion = pd.Series({"Paid Social": 1529.8})  # sin Paid Search
    out = mart_validacion_experimentos(_experimentos(), atribucion, pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-30"))
    assert set(out.canal) == {"Paid Social"}


def test_estado_validacion_por_canal():
    atribucion = pd.Series({"Paid Social": 1529.8, "Paid Search": 1221.9})
    mart = mart_validacion_experimentos(_experimentos(), atribucion, pd.Timestamp("2025-10-01"), pd.Timestamp("2026-09-30"))
    out = estado_validacion_por_canal(["Paid Social", "Paid Search", "Display"], mart).set_index("canal")
    assert out.loc["Paid Social", "estado"] == "Validado"
    assert out.loc["Paid Search", "estado"] == "Sin validar"
    assert out.loc["Display", "estado"] == "Sin probar"
    assert pd.isna(out.loc["Display", "factor_calibracion"])
