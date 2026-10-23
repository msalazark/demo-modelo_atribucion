"""Fixtures compartidos por las pruebas de RQ-27 (modelos, métricas y SQL)."""
from __future__ import annotations

from pathlib import Path

import duckdb
import pandas as pd
import pytest

BASE = Path(__file__).parent.parent
SQL_DIR = BASE / "sql"

EVENTS_SCHEMA = """
    CREATE TABLE events (
      event_date VARCHAR, event_timestamp BIGINT, event_name VARCHAR, user_pseudo_id VARCHAR,
      user_id VARCHAR,
      event_params STRUCT(key VARCHAR, value STRUCT(string_value VARCHAR, int_value BIGINT, double_value DOUBLE))[],
      collected_traffic_source STRUCT(manual_source VARCHAR, manual_medium VARCHAR, manual_campaign_name VARCHAR, gclid VARCHAR),
      ecommerce STRUCT(transaction_id VARCHAR, purchase_revenue DOUBLE),
      device_category VARCHAR, geo_region VARCHAR, customer_type VARCHAR, content_group VARCHAR)"""


def param(key: str, s: str | None = None, i: int | None = None, d: float | None = None) -> dict:
    return {"key": key, "value": {"string_value": s, "int_value": i, "double_value": d}}


@pytest.fixture
def con_sql() -> duckdb.DuckDBPyConnection:
    """Conexión DuckDB en memoria con `events` y `orders` de dos usuarios:

    - u1: una sesión de Paid Social (fbclid/cpc por Facebook) que convierte (pedido pagado, visto
      en GA4 con el evento `purchase`).
    - u2: una sesión Direct (sin fuente) que no convierte.

    Cubre, dentro de la ventana [2025-01-01, 2025-01-31], el flujo sesiones -> rutas -> conciliación.
    """
    con = duckdb.connect(":memory:")
    con.execute(EVENTS_SCHEMA)
    eventos = [
        {
            "event_date": "20250110", "event_timestamp": 1_736_500_000_000_000, "event_name": "session_start",
            "user_pseudo_id": "u1",
            "event_params": [param("ga_session_id", i=1001), param("page_location", s="https://sitio/x")],
            "collected_traffic_source": {"manual_source": "facebook", "manual_medium": "cpc",
                                          "manual_campaign_name": "verano", "gclid": None},
            "ecommerce": None,
            "device_category": "desktop", "geo_region": "Lima", "customer_type": "nuevo", "content_group": "Hogar",
        },
        {
            "event_date": "20250110", "event_timestamp": 1_736_500_060_000_000, "event_name": "purchase",
            "user_pseudo_id": "u1",
            "event_params": [param("ga_session_id", i=1001), param("page_location", s="https://sitio/gracias"),
                              param("value", d=100.0), param("currency", s="PEN")],
            "collected_traffic_source": None,
            "ecommerce": {"transaction_id": "O1", "purchase_revenue": 100.0},
            "device_category": "desktop", "geo_region": "Lima", "customer_type": "nuevo", "content_group": "Hogar",
        },
        {
            "event_date": "20250111", "event_timestamp": 1_736_586_000_000_000, "event_name": "session_start",
            "user_pseudo_id": "u2",
            "event_params": [param("ga_session_id", i=2001), param("page_location", s="https://sitio/y")],
            "collected_traffic_source": None,  # sin fuente -> Direct
            "ecommerce": None,
            "device_category": "mobile", "geo_region": "Arequipa", "customer_type": "recurrente",
            "content_group": "Tecnología",
        },
    ]
    con.register("_df_ev", pd.DataFrame(eventos))
    con.execute("INSERT INTO events BY NAME SELECT * FROM _df_ev")
    con.unregister("_df_ev")

    pedidos = [{
        # Un minuto después del evento `purchase` (09:06:40 UTC): la sesión debe terminar antes
        # del pedido para que el JOIN con `sesiones` en sql/02_rutas.sql la incluya en la ruta.
        "order_id": "O1", "customer_id": "C1", "created_at": pd.Timestamp("2025-01-10 09:07:40", tz="UTC"),
        "revenue_pen": 100.0, "payment_method": "tarjeta", "status": "pagado",
        "ga_client_id": "u1", "ga_session_id": 1001,
    }]
    con.register("_df_ped", pd.DataFrame(pedidos))
    con.execute("CREATE TABLE orders AS SELECT * FROM _df_ped")
    con.unregister("_df_ped")
    yield con
    con.close()


def fijar_parametros_test(con: duckdb.DuckDBPyConnection, ventana_dias: int = 30) -> None:
    con.execute(
        "CREATE OR REPLACE TABLE parametros AS SELECT CAST(? AS TIMESTAMPTZ) AS inicio, "
        "CAST(? AS TIMESTAMPTZ) AS corte, CAST(? AS INTEGER) AS ventana_dias",
        ["2025-01-01T00:00:00+00:00", "2025-01-31T00:00:00+00:00", ventana_dias],
    )
