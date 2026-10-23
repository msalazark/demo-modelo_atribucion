"""Pruebas de privacidad.py (RQ-28): sin PII en mart_*, hash de customer_id, retención."""
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from privacidad import aplicar_retencion_eventos, hash_customer_id, verificar_marts_sin_pii

DB_DEMO = Path(__file__).parent.parent / "data" / "ecommerce.duckdb"


def test_detecta_columna_sensible_en_un_mart():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE mart_prueba__canal AS SELECT 'A' AS canal, 'u1' AS user_pseudo_id")
    violaciones = verificar_marts_sin_pii(con)
    con.close()
    assert ("mart_prueba__canal", "user_pseudo_id") in violaciones


def test_no_detecta_nada_en_un_mart_limpio():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE mart_prueba__canal AS SELECT 'A' AS canal, 100 AS conversiones")
    assert verificar_marts_sin_pii(con) == []
    con.close()


def test_hash_customer_id_es_determinista_y_no_reversible():
    h1 = hash_customer_id("C-000123")
    h2 = hash_customer_id("C-000123")
    assert h1 == h2
    assert h1 != "C-000123"
    assert len(h1) == 64  # sha256 hex


@pytest.mark.skipif(not DB_DEMO.exists(), reason="corre python run_demo.py primero")
def test_marts_de_la_demo_no_tienen_pii():
    con = duckdb.connect(str(DB_DEMO), read_only=True)
    violaciones = verificar_marts_sin_pii(con)
    con.close()
    assert violaciones == []


def test_aplicar_retencion_eventos_borra_solo_filas_viejas():
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE events (event_timestamp BIGINT)")
    vieja = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=20)
    reciente = pd.Timestamp.now(tz="UTC") - pd.DateOffset(months=1)
    con.register("_ev", pd.DataFrame({
        "event_timestamp": [int(vieja.timestamp() * 1e6), int(reciente.timestamp() * 1e6)],
    }))
    con.execute("INSERT INTO events SELECT * FROM _ev")
    con.unregister("_ev")

    borradas = aplicar_retencion_eventos(con, meses=13)
    assert borradas == 1
    assert con.sql("SELECT count(*) FROM events").fetchone()[0] == 1
    con.close()
