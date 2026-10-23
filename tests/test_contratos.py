"""Pruebas de contratos.py (RQ-03): validación de esquema mínimo por fuente."""
import pandas as pd
import pytest

from contratos import validar_fuente


def test_valida_pedidos_con_alias_de_columna():
    df = pd.DataFrame({
        "order_id": ["O1", "O2"], "created_at": pd.to_datetime(["2025-01-01", "2025-01-02"]),
        "status": ["pagado", "pagado"], "revenue_pen": [100.0, None], "ga_client_id": ["u1", None],
    })
    reporte = validar_fuente("pedidos", df, alias={"revenue": "revenue_pen"})
    assert reporte["fuente"] == "pedidos" and reporte["filas"] == 2
    assert reporte["pct_nulos"]["revenue"] == 50.0
    assert reporte["pct_nulos"]["ga_client_id"] == 50.0


def test_falla_si_falta_un_campo_obligatorio():
    df = pd.DataFrame({"order_id": ["O1"], "created_at": [pd.Timestamp("2025-01-01")]})
    with pytest.raises(ValueError, match="faltan campos obligatorios"):
        validar_fuente("pedidos", df, alias={"revenue": "revenue_pen"})


def test_fuente_desconocida_falla():
    with pytest.raises(ValueError, match="Fuente desconocida"):
        validar_fuente("no_existe", pd.DataFrame())


def test_valida_eventos_ga4_sin_alias():
    """Los nombres de columna de esta demo ya coinciden con la raíz de los campos anidados del
    contrato (event_params, collected_traffic_source, ecommerce)."""
    df = pd.DataFrame({
        "event_date": ["20250101"], "event_timestamp": [1], "event_name": ["session_start"],
        "user_pseudo_id": ["u1"], "event_params": [[]], "collected_traffic_source": [None],
        "ecommerce": [None],
    })
    reporte = validar_fuente("eventos_ga4", df)
    assert "event_params.ga_session_id" in reporte["pct_nulos"]
    assert "collected_traffic_source.*" in reporte["pct_nulos"]


def test_opcionales_ausentes_no_fallan():
    df = pd.DataFrame({
        "date": ["2025-01-01"], "platform": ["meta"], "campaign_id": ["C1"],
        "campaign_name": ["verano"], "cost": [100.0],
    })
    reporte = validar_fuente("costos", df)
    assert "impressions" not in reporte["pct_nulos"]  # opcional y ausente: no aparece, no falla
