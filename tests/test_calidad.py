"""Pruebas de calidad.py (RQ-18): controles de calidad de datos."""
import duckdb
import pandas as pd
import pytest

from calidad import controles_calidad


@pytest.fixture
def con_calidad():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE sesiones (inicio_sesion TIMESTAMPTZ, canal VARCHAR, es_pasarela BOOLEAN)")
    con.execute("CREATE TABLE costs (date DATE, channel VARCHAR, cost_pen DOUBLE)")
    con.execute("CREATE TABLE events (event_timestamp BIGINT)")
    yield con
    con.close()


def _conciliacion(backend=100, vistos=80, con_ruta=90):
    return pd.Series({"pedidos_backend": backend, "pedidos_vistos_en_ga4": vistos, "pedidos_con_ruta": con_ruta})


def _canales(unassigned_pct=2.0, meta_sin_utm_pct=1.0):
    return pd.DataFrame([
        {"canal": "Unassigned", "sesiones": 0, "pct": unassigned_pct},
        {"canal": "Direct", "sesiones": 0, "pct": 10.0},
        {"canal": "Meta (sin UTM)", "sesiones": 0, "pct": meta_sin_utm_pct},
    ])


def test_todo_ok_cuando_los_valores_estan_dentro_de_umbral(con_calidad):
    inicio, corte = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-01-31", tz="UTC")
    df = controles_calidad(con_calidad, inicio, corte, ["Paid Social"], _conciliacion(), _canales())
    assert (df.estado == "ok").all()


def test_pedidos_con_ruta_bajo_umbral_es_critico(con_calidad):
    inicio, corte = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-01-31", tz="UTC")
    conc = _conciliacion(backend=100, con_ruta=50)  # 50% < 85%
    df = controles_calidad(con_calidad, inicio, corte, ["Paid Social"], conc, _canales())
    fila = df.set_index("control").loc["Pedidos con ruta"]
    assert fila.estado == "crítico"


def test_unassigned_alto_es_alerta(con_calidad):
    inicio, corte = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-01-31", tz="UTC")
    df = controles_calidad(con_calidad, inicio, corte, ["Paid Social"], _conciliacion(),
                           _canales(unassigned_pct=12.0))
    fila = df.set_index("control").loc["Sesiones Unassigned"]
    assert fila.estado == "alerta"


def test_dias_sin_costo_de_canal_activo_es_critico(con_calidad):
    inicio, corte = pd.Timestamp("2025-01-01", tz="UTC"), pd.Timestamp("2025-01-03", tz="UTC")
    # Paid Social tuvo sesiones el 1 y 2 de enero, pero solo hay costo el día 1
    con_calidad.execute(
        "INSERT INTO sesiones VALUES "
        "('2025-01-01 10:00:00+00', 'Paid Social', FALSE), ('2025-01-02 10:00:00+00', 'Paid Social', FALSE)"
    )
    con_calidad.execute("INSERT INTO costs VALUES ('2025-01-01', 'Paid Social', 100.0)")
    df = controles_calidad(con_calidad, inicio, corte, ["Paid Social"], _conciliacion(), _canales())
    fila = df.set_index("control").loc["Días sin costos de un canal pagado activo"]
    assert fila.valor == 1 and fila.estado == "crítico"


def test_caida_de_eventos_fuerte_es_critica(con_calidad):
    corte = pd.Timestamp("2025-01-29", tz="UTC")
    eventos = [int(pd.Timestamp("2025-01-01", tz="UTC").timestamp() * 1e6) + i * 86_400_000_000
               for i in range(28) for _ in range(100)]
    eventos += [int(corte.timestamp() * 1e6)] * 10  # el último día cae a 10 (-90%)
    con_calidad.execute("INSERT INTO events SELECT * FROM (SELECT UNNEST(?) AS event_timestamp)", [eventos])
    inicio = pd.Timestamp("2025-01-01", tz="UTC")
    df = controles_calidad(con_calidad, inicio, corte, ["Paid Social"], _conciliacion(), _canales())
    fila = df.set_index("control").loc["Caída de eventos vs. media de 28 días"]
    assert fila.estado == "crítico" and fila.valor < -30
