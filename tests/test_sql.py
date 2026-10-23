"""Pruebas de SQL (RQ-27): sesiones -> rutas -> conciliación con fixtures pequeños.

No dependen de haber corrido run_demo.py ni generar_datos.py: construyen su propio
`events`/`orders` en memoria (ver tests/conftest.py).
"""
import duckdb
import pandas as pd

import run_demo
from run_demo import _sql
from tests.conftest import EVENTS_SCHEMA, SQL_DIR, fijar_parametros_test, param


def test_sesiones_asigna_canal_por_fuente_y_medio(con_sql):
    con_sql.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    sesiones = con_sql.sql("SELECT user_pseudo_id, canal, es_pasarela FROM sesiones ORDER BY user_pseudo_id").df()
    assert sesiones.set_index("user_pseudo_id").canal.to_dict() == {"u1": "Paid Social", "u2": "Direct"}
    assert not sesiones.es_pasarela.any()


def test_usuarios_trae_los_atributos_de_segmentacion(con_sql):
    con_sql.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    usuarios = con_sql.sql("SELECT * FROM usuarios ORDER BY user_pseudo_id").df().set_index("user_pseudo_id")
    assert usuarios.loc["u1", "content_group"] == "Hogar"
    assert usuarios.loc["u2", "device_category"] == "mobile"


def test_rutas_separa_convertidas_de_no_convertidas(con_sql):
    con_sql.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    fijar_parametros_test(con_sql)
    con_sql.execute(_sql(SQL_DIR / "02_rutas.sql"))
    rutas = con_sql.sql("SELECT * FROM rutas ORDER BY user_pseudo_id").df()
    assert len(rutas) == 2
    convertida = rutas[rutas.convirtio].iloc[0]
    assert convertida.user_pseudo_id == "u1" and list(convertida.ruta) == ["Paid Social"]
    assert convertida.revenue_pen == 100.0 and convertida.order_id == "O1"
    no_convertida = rutas[~rutas.convirtio].iloc[0]
    assert no_convertida.user_pseudo_id == "u2" and list(no_convertida.ruta) == ["Direct"]


def test_conciliacion_cuenta_pedidos_vistos_en_ga4(con_sql):
    con_sql.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    fijar_parametros_test(con_sql)
    con_sql.execute(_sql(SQL_DIR / "02_rutas.sql"))
    con_sql.execute(_sql(SQL_DIR / "03_conciliacion.sql"))
    c = con_sql.sql("SELECT * FROM conciliacion").df().iloc[0]
    assert c.pedidos_backend == 1
    assert c.pedidos_vistos_en_ga4 == 1  # el evento purchase con transaction_id = 'O1'
    assert c.pedidos_sin_client_id == 0
    assert c.pedidos_con_ruta == 1


def test_rq08_la_ruta_del_segundo_pedido_no_incluye_sesiones_del_primero():
    """Un usuario con dos pedidos en 10 días: las sesiones previas al primer pedido no deben
    aparecer en la ruta del segundo, aunque ambas caigan dentro de la ventana de atribución
    (30 días) medida desde el segundo pedido."""
    con = duckdb.connect(":memory:")
    con.execute(EVENTS_SCHEMA)
    eventos = [{
        # S0: 9 días antes de O1 -> entra en la ruta de O1, no debe entrar en la de O2
        "event_date": "20250101", "event_timestamp": int(pd.Timestamp("2025-01-01T10:00:00Z").timestamp() * 1e6),
        "event_name": "session_start", "user_pseudo_id": "u1",
        "event_params": [param("ga_session_id", i=1)],
        "collected_traffic_source": {"manual_source": "facebook", "manual_medium": "cpc",
                                      "manual_campaign_name": None, "gclid": None},
        "ecommerce": None, "device_category": "desktop", "geo_region": "Lima",
        "customer_type": "nuevo", "content_group": "Hogar",
    }, {
        # S1: 3 días después de O1 y 7 antes de O2 -> solo debe entrar en la ruta de O2
        "event_date": "20250113", "event_timestamp": int(pd.Timestamp("2025-01-13T10:00:00Z").timestamp() * 1e6),
        "event_name": "session_start", "user_pseudo_id": "u1",
        "event_params": [param("ga_session_id", i=2)],
        "collected_traffic_source": {"manual_source": "newsletter", "manual_medium": "email",
                                      "manual_campaign_name": None, "gclid": None},
        "ecommerce": None, "device_category": "desktop", "geo_region": "Lima",
        "customer_type": "nuevo", "content_group": "Hogar",
    }]
    con.register("_ev", pd.DataFrame(eventos))
    con.execute("INSERT INTO events BY NAME SELECT * FROM _ev")
    con.unregister("_ev")
    pedidos = pd.DataFrame([
        {"order_id": "O1", "customer_id": "C1", "created_at": pd.Timestamp("2025-01-10T10:05:00", tz="UTC"),
         "revenue_pen": 100.0, "payment_method": "tarjeta", "status": "pagado", "ga_client_id": "u1",
         "ga_session_id": 1},
        {"order_id": "O2", "customer_id": "C1", "created_at": pd.Timestamp("2025-01-20T10:05:00", tz="UTC"),
         "revenue_pen": 80.0, "payment_method": "tarjeta", "status": "pagado", "ga_client_id": "u1",
         "ga_session_id": 2},
    ])
    con.register("_ped", pedidos)
    con.execute("CREATE TABLE orders AS SELECT * FROM _ped")
    con.unregister("_ped")

    con.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    fijar_parametros_test(con, ventana_dias=30)
    con.execute(_sql(SQL_DIR / "02_rutas.sql"))
    rutas = con.sql("SELECT order_id, ruta FROM rutas WHERE convirtio ORDER BY order_id").df().set_index("order_id")

    assert list(rutas.loc["O1", "ruta"]) == ["Paid Social"]
    assert list(rutas.loc["O2", "ruta"]) == ["Email"]  # no arrastra la sesión de O1
    con.close()


def test_rq07_pedidos_con_una_sola_llave_cada_uno():
    """Tres pedidos, cada uno con una sola llave de unión a GA4 (RQ-07):
      OA: solo ga_client_id.
      OB: solo transaction_id (el evento `purchase` de u_b lo liga a OB).
      OC: solo user_id (u_c1 se loguea con user_id='LOGIN_C', igual que orders.customer_id)."""
    con = duckdb.connect(":memory:")
    con.execute(EVENTS_SCHEMA)
    def ts(s):
        return int(pd.Timestamp(s).timestamp() * 1e6)

    eventos = [
        {   # u_a: sesión Paid Search, se liga por ga_client_id
            "event_date": "20250105", "event_timestamp": ts("2025-01-05T10:00:00Z"),
            "event_name": "session_start", "user_pseudo_id": "u_a", "user_id": None,
            "event_params": [param("ga_session_id", i=1)],
            "collected_traffic_source": {"manual_source": "google", "manual_medium": "cpc",
                                          "manual_campaign_name": None, "gclid": None},
            "ecommerce": None, "device_category": "desktop", "geo_region": "Lima",
            "customer_type": "nuevo", "content_group": "Hogar",
        },
        {   # u_b: sesión Email + compra vista en GA4 con transaction_id = OB
            "event_date": "20250105", "event_timestamp": ts("2025-01-05T11:00:00Z"),
            "event_name": "session_start", "user_pseudo_id": "u_b", "user_id": None,
            "event_params": [param("ga_session_id", i=2)],
            "collected_traffic_source": {"manual_source": "newsletter", "manual_medium": "email",
                                          "manual_campaign_name": None, "gclid": None},
            "ecommerce": None, "device_category": "desktop", "geo_region": "Lima",
            "customer_type": "nuevo", "content_group": "Hogar",
        },
        {
            "event_date": "20250105", "event_timestamp": ts("2025-01-05T11:05:00Z"),
            "event_name": "purchase", "user_pseudo_id": "u_b", "user_id": None,
            "event_params": [param("ga_session_id", i=2)],
            "collected_traffic_source": None, "ecommerce": {"transaction_id": "OB", "purchase_revenue": 60.0},
            "device_category": "desktop", "geo_region": "Lima", "customer_type": "nuevo", "content_group": "Hogar",
        },
        {   # u_c1: sesión Referral, logueado con user_id = LOGIN_C (igual que customer_id de OC)
            "event_date": "20250105", "event_timestamp": ts("2025-01-05T12:00:00Z"),
            "event_name": "session_start", "user_pseudo_id": "u_c1", "user_id": "LOGIN_C",
            "event_params": [param("ga_session_id", i=3)],
            "collected_traffic_source": {"manual_source": "blog.pe", "manual_medium": "referral",
                                          "manual_campaign_name": None, "gclid": None},
            "ecommerce": None, "device_category": "desktop", "geo_region": "Lima",
            "customer_type": "nuevo", "content_group": "Hogar",
        },
    ]
    con.register("_ev", pd.DataFrame(eventos))
    con.execute("INSERT INTO events BY NAME SELECT * FROM _ev")
    con.unregister("_ev")
    pedidos = pd.DataFrame([
        {"order_id": "OA", "customer_id": "CA", "created_at": pd.Timestamp("2025-01-06", tz="UTC"),
         "revenue_pen": 100.0, "payment_method": "tarjeta", "status": "pagado", "ga_client_id": "u_a",
         "ga_session_id": 1},
        {"order_id": "OB", "customer_id": "CB", "created_at": pd.Timestamp("2025-01-06", tz="UTC"),
         "revenue_pen": 60.0, "payment_method": "tarjeta", "status": "pagado", "ga_client_id": None,
         "ga_session_id": 2},
        {"order_id": "OC", "customer_id": "LOGIN_C", "created_at": pd.Timestamp("2025-01-06", tz="UTC"),
         "revenue_pen": 80.0, "payment_method": "tarjeta", "status": "pagado", "ga_client_id": None,
         "ga_session_id": 3},
    ])
    con.register("_ped", pedidos)
    con.execute("CREATE TABLE orders AS SELECT * FROM _ped")
    con.unregister("_ped")

    con.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    fijar_parametros_test(con, ventana_dias=30)
    con.execute(_sql(SQL_DIR / "02_rutas.sql"))
    con.execute(_sql(SQL_DIR / "03_conciliacion.sql"))

    resueltos = con.sql("SELECT order_id, user_pseudo_id, llave_union FROM pedidos_resueltos ORDER BY order_id").df()
    resueltos = resueltos.set_index("order_id")
    assert resueltos.loc["OA", "llave_union"] == "ga_client_id" and resueltos.loc["OA", "user_pseudo_id"] == "u_a"
    assert resueltos.loc["OB", "llave_union"] == "transaction_id" and resueltos.loc["OB", "user_pseudo_id"] == "u_b"
    assert resueltos.loc["OC", "llave_union"] == "user_id" and resueltos.loc["OC", "user_pseudo_id"] == "u_c1"

    c = con.sql("SELECT * FROM conciliacion").df().iloc[0]
    assert c.unidos_por_ga_client_id == 1 and c.unidos_por_transaction_id == 1 and c.unidos_por_user_id == 1
    assert c.pedidos_sin_union == 0 and c.pedidos_con_ruta == 3

    rutas = con.sql("SELECT order_id, ruta FROM rutas WHERE convirtio ORDER BY order_id").df().set_index("order_id")
    assert list(rutas.loc["OA", "ruta"]) == ["Paid Search"]
    assert list(rutas.loc["OB", "ruta"]) == ["Email"]
    assert list(rutas.loc["OC", "ruta"]) == ["Referral"]
    con.close()


def test_rq10_corte_mensual_en_la_zona_horaria_del_cliente(monkeypatch):
    """Un pedido a las 22:00 del 31 de agosto en America/Lima (UTC-5, sin horario de verano) cae
    en agosto, no en septiembre (03:00 UTC del 1 de setiembre). Prueba directa de la expresión SQL
    que usa sql/04_kpi_mensual.sql: con zona UTC (la que trae la demo) cae en 2025-09; con la del
    cliente, en 2025-08."""
    con = duckdb.connect(":memory:")
    con.execute("CREATE TABLE _t AS SELECT TIMESTAMPTZ '2025-09-01 03:00:00+00' AS created_at")

    monkeypatch.setattr(run_demo, "ZONA_HORARIA", "UTC")
    sql_utc = run_demo._sql(SQL_DIR / "04_kpi_mensual.sql")
    assert "created_at AT TIME ZONE 'UTC'" in sql_utc

    monkeypatch.setattr(run_demo, "ZONA_HORARIA", "America/Lima")
    sql_lima = run_demo._sql(SQL_DIR / "04_kpi_mensual.sql")
    assert "created_at AT TIME ZONE 'America/Lima'" in sql_lima

    periodo_utc = con.sql("SELECT strftime(created_at AT TIME ZONE 'UTC', '%Y-%m') FROM _t").fetchone()[0]
    periodo_lima = con.sql("SELECT strftime(created_at AT TIME ZONE 'America/Lima', '%Y-%m') FROM _t").fetchone()[0]
    assert periodo_utc == "2025-09"
    assert periodo_lima == "2025-08"
    con.close()


def test_rq18_kpi_mensual_no_pierde_el_primer_dia_de_la_ventana(con_sql):
    """CAST(timestamptz AS DATE) usa la zona de sesión de DuckDB (America/Lima en esta máquina),
    no UTC: sin AT TIME ZONE 'UTC' explícito en el filtro de costos, el primer día de la ventana
    (medianoche UTC) se perdía por caer "un día antes" (RQ-18)."""
    con_sql.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    con_sql.execute(
        "CREATE OR REPLACE TABLE parametros AS SELECT CAST(? AS TIMESTAMPTZ) AS inicio, "
        "CAST(? AS TIMESTAMPTZ) AS corte, CAST(30 AS INTEGER) AS ventana_dias",
        ["2025-01-01T00:00:00+00:00", "2025-01-31T00:00:00+00:00"],
    )
    con_sql.execute("CREATE TABLE costs (date DATE, channel VARCHAR, cost_pen DOUBLE)")
    con_sql.execute("INSERT INTO costs VALUES ('2025-01-01', 'Paid Social', 50.0)")
    con_sql.execute(_sql(SQL_DIR / "02_rutas.sql"))
    con_sql.execute(_sql(SQL_DIR / "04_kpi_mensual.sql"))
    kpi = con_sql.sql("SELECT * FROM kpi_mensual").df()
    assert kpi.inversion_medios.sum() == 50.0  # el costo del 1 de enero no se pierde


def test_solo_cuentan_los_estados_validos_del_pedido(con_sql):
    """Con estados_validos_pedido=['pagado'] un pedido 'cancelado' no debe contar (RQ-01)."""
    extra = pd.DataFrame([{
        "order_id": "O2", "customer_id": "C2", "created_at": pd.Timestamp("2025-01-12", tz="UTC"),
        "revenue_pen": 50.0, "payment_method": "tarjeta", "status": "cancelado",
        "ga_client_id": "u1", "ga_session_id": 1001,
    }])
    con_sql.register("_extra", extra)
    con_sql.execute("INSERT INTO orders SELECT * FROM _extra")
    con_sql.unregister("_extra")
    con_sql.execute(_sql(SQL_DIR / "01_sesiones.sql"))
    fijar_parametros_test(con_sql)
    con_sql.execute(_sql(SQL_DIR / "02_rutas.sql"))
    con_sql.execute(_sql(SQL_DIR / "03_conciliacion.sql"))
    c = con_sql.sql("SELECT * FROM conciliacion").df().iloc[0]
    assert c.pedidos_backend == 1  # solo 'pagado' cuenta; 'cancelado' queda fuera
