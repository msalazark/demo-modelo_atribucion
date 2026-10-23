"""Datos personales (RQ-28 de docs/RQ_mejoras.md). Ver docs/privacidad.md (Ley 29733).

- El pipeline no lee ni guarda correo, teléfono, nombre ni dirección.
- `customer_id` se guarda solo con hash (`hash_customer_id`).
- Las tablas `mart_*` no llevan identificadores de usuario (`verificar_marts_sin_pii`, que
  corre en `tests/test_privacidad.py` contra la base de datos de la demo).
- Política de retención configurable de eventos crudos (`aplicar_retencion_eventos`).
"""
from __future__ import annotations

import hashlib

import duckdb

# Nombres de columna (o fragmentos) que no deben aparecer en una tabla mart_*: identificadores de
# usuario y PII directa. No es una lista exhaustiva de todo el vocabulario posible, pero cubre los
# campos que hoy existen en events/orders (ver docs/contratos_datos.md) y los clásicos de PII.
COLUMNAS_SENSIBLES = [
    "user_pseudo_id", "ga_client_id", "ga_session_id", "customer_id", "user_id",
    "fbp", "fbc", "gclid",
    "email", "correo", "telefono", "phone", "celular",
    "nombre", "apellido", "name",
    "direccion", "address", "dni", "documento",
]


def verificar_marts_sin_pii(con: duckdb.DuckDBPyConnection) -> list[tuple[str, str]]:
    """Columnas de alguna tabla `mart_*` que coinciden con `COLUMNAS_SENSIBLES`.

    Devuelve una lista de (tabla, columna); vacía si todo está limpio. Se corre como prueba
    (`tests/test_privacidad.py`) contra la base de datos generada por `run_demo.py`.
    """
    cols = con.sql(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_name LIKE 'mart_%'"
    ).df()
    sensibles = set(COLUMNAS_SENSIBLES)
    violaciones = []
    for _, fila in cols.iterrows():
        # Coincidencia exacta (no substring): columnas descriptivas como "unidos_por_ga_client_id"
        # (un conteo agregado, RQ-07) mencionan la llave sin contener el dato en sí.
        if fila.column_name.lower() in sensibles:
            violaciones.append((fila.table_name, fila.column_name))
    return violaciones


def hash_customer_id(customer_id: str) -> str:
    """`customer_id` se guarda solo con este hash (sha256), nunca en texto plano."""
    return hashlib.sha256(customer_id.encode("utf-8")).hexdigest()


def aplicar_retencion_eventos(con: duckdb.DuckDBPyConnection, meses: int) -> int:
    """Borra de `events` las filas con más de `meses` de antigüedad (política de retención,
    por defecto 13 meses). No se corre automáticamente en `run_demo.py`: es una operación
    destructiva que se agenda aparte (p. ej. un job mensual), no en cada corrida del pipeline.

    Devuelve cuántas filas se borraron.
    """
    antes = con.sql("SELECT count(*) FROM events").fetchone()[0]
    con.execute(
        "DELETE FROM events WHERE to_timestamp(event_timestamp / 1e6) < "
        "current_timestamp - to_months(CAST(? AS INTEGER))",
        [meses],
    )
    despues = con.sql("SELECT count(*) FROM events").fetchone()[0]
    return antes - despues
