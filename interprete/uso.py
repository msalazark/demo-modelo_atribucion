"""Registro de uso del intérprete (RQ-25): tokens y costo aproximado por consulta a Claude.

No es una tabla `mart_*`: es telemetría operativa de la aplicación (cuánto se gasta en
interpretaciones), no un resultado del pipeline de atribución. Por eso vive en un CSV aparte
(`logs/uso_interprete.csv`, fuera de `data/` y `resultados/`) y nunca se versiona.
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

# USD por millón de tokens (precios de lista). Un modelo que no está aquí no rompe el registro:
# el costo sale en None y el resto de la fila se guarda igual.
PRECIOS_USD_POR_MILLON: dict[str, tuple[float, float]] = {
    "claude-opus-5-5": (15.0, 75.0),
    "claude-sonnet-5-5": (3.0, 15.0),
    "claude-haiku-5-5": (0.80, 4.0),
}

COLUMNAS = ["ejecutado_en", "vista", "tipo", "modelo", "generado_con", "tokens_entrada",
            "tokens_salida", "costo_usd", "segundos", "herramientas"]


def costo_usd(modelo: str, tokens_entrada: int, tokens_salida: int) -> float | None:
    precios = PRECIOS_USD_POR_MILLON.get(modelo)
    if precios is None:
        return None
    entrada, salida = precios
    return round(tokens_entrada / 1e6 * entrada + tokens_salida / 1e6 * salida, 4)


def registrar(
    ruta: str | Path,
    vista_clave: str,
    tipo: str,
    modelo: str,
    generado_con: str,
    tokens_entrada: int,
    tokens_salida: int,
    segundos: float,
    herramientas: list[str],
) -> None:
    """Agrega una fila a `ruta` (CSV; se crea con encabezado si no existe)."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fila = pd.DataFrame([{
        "ejecutado_en": datetime.now(UTC).isoformat(timespec="seconds"),
        "vista": vista_clave, "tipo": tipo, "modelo": modelo, "generado_con": generado_con,
        "tokens_entrada": tokens_entrada, "tokens_salida": tokens_salida,
        "costo_usd": costo_usd(modelo, tokens_entrada, tokens_salida),
        "segundos": segundos, "herramientas": ",".join(herramientas),
    }], columns=COLUMNAS)
    fila.to_csv(ruta, mode="a", header=not ruta.exists(), index=False)


def leer(ruta: str | Path) -> pd.DataFrame:
    ruta = Path(ruta)
    if not ruta.exists():
        return pd.DataFrame(columns=COLUMNAS)
    return pd.read_csv(ruta)
