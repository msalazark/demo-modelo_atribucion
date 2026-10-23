"""Evaluación del intérprete contra el banco de 30 preguntas de negocio (RQ-25).

Corre con `pytest -m evals` (gasta crédito de la API de Claude): no corre en CI ni en
`pytest tests` por defecto. El resto de la suite no depende de esto y sigue pasando sin
credenciales (ver tests/test_interprete.py, que usa un cliente falso).
"""
from __future__ import annotations

import pytest

from interprete.agente import Interprete
from interprete.datos import construir_hechos
from interprete.verificador import _numeros

from .banco import BANCO

pytestmark = pytest.mark.evals

_RESULTADOS: list[dict] = []


def _cifra_presente(valor: float, texto: str) -> bool:
    disponibles = [v for _, v in _numeros(texto)]
    tol = max(0.6, abs(valor) * 0.05)
    return any(abs(valor - d) <= tol for d in disponibles)


@pytest.mark.parametrize("p", BANCO, ids=[p.id for p in BANCO])
def test_pregunta_del_banco(p):
    hechos = construir_hechos(p.vista)
    r = Interprete().preguntar(p.vista, p.texto)
    texto = r.texto.lower()

    fallos = []
    if any("no aparecen en los datos" in a for a in r.advertencias):
        fallos.append("cifras sin respaldo: " + "; ".join(r.advertencias))
    for cifra in p.cifras_esperadas(hechos):
        if not _cifra_presente(cifra, r.texto):
            fallos.append(f"falta la cifra {cifra}")
    for frag in p.debe_contener:
        if frag.lower() not in texto:
            fallos.append(f"falta '{frag}'")
    for frag in p.no_debe_contener:
        if frag.lower() in texto:
            fallos.append(f"no debería mencionar '{frag}'")

    _RESULTADOS.append({"id": p.id, "ok": not fallos})
    assert not fallos, "; ".join(fallos) + f"\n\nRespuesta completa:\n{r.texto}"


def test_zzz_resumen_final():
    """Nombrada para correr al final (orden de definición) e imprimir el % de aciertos del banco.
    Si se filtra la corrida con -k, puede no ver todos los resultados: no es una prueba real."""
    if not _RESULTADOS:
        pytest.skip("No se registraron resultados (revisa si se filtró la corrida con -k).")
    ok = sum(1 for r in _RESULTADOS if r["ok"])
    total = len(_RESULTADOS)
    print(f"\nBanco de evaluación del intérprete: {ok}/{total} ({ok / total * 100:.0f} %) preguntas cumplen.")
