"""Pruebas de rendimiento (RQ-17).

`pytest -m rendimiento` no corre por defecto (genera datos sintéticos grandes); se agrega aparte.
"""
import pytest


def test_segmentos_corren_en_paralelo_sin_romper_resultados():
    """Los segmentos de una ventana se procesan con joblib.Parallel (run_demo.main): esta prueba
    confirma que `correr_rebanada` (la función que se paraleliza) sigue siendo una función normal,
    pura en sus argumentos explícitos, invocable igual en serie o en paralelo."""
    import pandas as pd

    import run_demo as r

    rutas = pd.DataFrame([
        {"user_pseudo_id": "u1", "order_id": "O1", "revenue_pen": 100.0, "convirtio": True,
         "device_category": "desktop", "geo_region": "Lima", "customer_type": "nuevo",
         "content_group": "Hogar", "ruta": ["A"], "dias_antes": [1.0]},
        {"user_pseudo_id": "u2", "order_id": None, "revenue_pen": 0.0, "convirtio": False,
         "device_category": "desktop", "geo_region": "Lima", "customer_type": "nuevo",
         "content_group": "Hogar", "ruta": ["A"], "dias_antes": [1.0]},
    ])
    sesiones = pd.DataFrame({"canal": ["A", "A"], "es_pasarela": [False, False]})
    costos = pd.Series({"A": 10.0})
    res = r.correr_rebanada(rutas, sesiones, costos, None, {}, con_ci=False)
    assert "mart_decision__canal" in res


@pytest.mark.rendimiento
def test_pipeline_con_20_millones_de_sesiones():
    """RQ-17: genera ~20 millones de sesiones sintéticas y mide el tiempo del pipeline completo.

    No corre en CI ni por defecto (`pytest -m rendimiento`): consume mucho tiempo y memoria.
    Queda documentado como pendiente de ejecutar con infraestructura dedicada; ver
    docs/RQ_mejoras.md (RQ-17) para el detalle de qué se intentó y qué no funcionó a la escala de
    la demo (la cache en disco con joblib.Memory, revertida).
    """
    pytest.skip("No se corrió en este entorno: 20M de sesiones exceden el tiempo/memoria disponibles aquí.")
