"""
Verificación de cifras: toda cifra de una interpretación debe estar en los hechos o en el
conocimiento que se le dio al modelo. Lo que no aparece se marca para que alguien lo revise.
"""
from __future__ import annotations

import re

_NUMERO = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
_MILES = re.compile(r"(?<=\d),(?=\d{3}\b)")
_COMA_DECIMAL = re.compile(r"(?<=\d),(?=\d{1,2}\b)")


def _numeros(texto: str) -> list[tuple[str, float]]:
    limpio = _MILES.sub("", texto)
    limpio = _COMA_DECIMAL.sub(".", limpio)
    return [(m.group(), float(m.group())) for m in _NUMERO.finditer(limpio)]


def cifras_no_respaldadas(texto: str, respaldo: str) -> list[str]:
    """Cifras del `texto` que no aparecen (con tolerancia de redondeo) en `respaldo`."""
    disponibles = [v for _, v in _numeros(respaldo)]
    faltan: list[str] = []
    for crudo, valor in _numeros(texto):
        if valor == int(valor) and valor <= 12 and "." not in crudo:
            continue  # numeración de listas, meses y conteos pequeños
        tol = 0.051 if "." in crudo else 0.5
        if not any(abs(valor - d) <= tol for d in disponibles) and crudo not in faltan:
            faltan.append(crudo)
    return faltan
