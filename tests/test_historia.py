"""Pruebas de historia de resultados (RQ-19): estado_modelo usa hist_* en vez de recalcular,
una vez que hay una corrida anterior; actualizar_historia es idempotente por corte."""
import duckdb
import pandas as pd
import pytest

import run_demo as r


@pytest.fixture
def con_vacio():
    con = duckdb.connect(":memory:")
    yield con
    con.close()


def _comparativo_shapley(canales_cuota: dict, ventana_dias=30) -> pd.DataFrame:
    filas = [{"canal": c, "modelo": "shapley", "cuota_pct": cuota, "ventana_dias": ventana_dias,
              "dim": "Todos", "segmento": "Todos"} for c, cuota in canales_cuota.items()]
    return pd.DataFrame(filas)


def test_estado_modelo_usa_la_historia_si_existe(con_vacio, monkeypatch):
    monkeypatch.setattr(r, "VENTANA_DIAS", 30)
    corte_anterior = pd.Timestamp("2026-08-31", tz="UTC")
    r.actualizar_historia(
        con_vacio, "mart_modelos__comparativo",
        _comparativo_shapley({"A": 60.0, "B": 40.0}), corte_anterior,
    )

    corte_actual = pd.Timestamp("2026-09-30", tz="UTC")
    actual = pd.DataFrame([
        {"canal": "A", "modelo": "shapley", "cuota_pct": 62.0, "cuota_p05": 58.0, "cuota_p95": 66.0},
        {"canal": "B", "modelo": "shapley", "cuota_pct": 38.0, "cuota_p05": 34.0, "cuota_p95": 42.0},
    ])
    out = r.estado_modelo(con_vacio, pd.Timestamp("2025-10-01", tz="UTC"), corte_actual, actual).set_index("canal")

    assert out.loc["A", "cuota_previa"] == 60.0  # vino de la historia, no de un recálculo
    assert out.loc["B", "cuota_previa"] == 40.0
    assert out.loc["A", "corte_previo"] == "2026-08-31"
    assert out.loc["A", "estado"] == "estable"  # 60 está dentro de [58, 66]


def test_actualizar_historia_es_idempotente_por_corte(con_vacio):
    corte = pd.Timestamp("2026-09-30", tz="UTC")
    r.actualizar_historia(con_vacio, "mart_modelos__comparativo", _comparativo_shapley({"A": 60.0}), corte)
    r.actualizar_historia(con_vacio, "mart_modelos__comparativo", _comparativo_shapley({"A": 61.0}), corte)
    hist = con_vacio.sql("SELECT * FROM hist_mart_modelos__comparativo").df()
    assert len(hist) == 1
    assert hist.iloc[0].cuota_pct == 61.0  # la corrida repetida reemplaza, no duplica


def test_cuota_previa_de_historia_retorna_none_sin_historia(con_vacio, monkeypatch):
    monkeypatch.setattr(r, "VENTANA_DIAS", 30)
    previa, corte_previo = r._cuota_previa_de_historia(con_vacio, pd.Timestamp("2026-09-30", tz="UTC"))
    assert previa is None and corte_previo is None
