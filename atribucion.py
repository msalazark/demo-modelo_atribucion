"""
Modelos de atribución data-driven sobre la tabla `rutas`.

- markov():   cadena de Markov de primer orden con efecto de remoción.
- shapley():  valores de Shapley sobre la probabilidad de conversión, estimada
              con una regresión logística (efectos por canal + pares de canales).
- ultimo_no_directo(): referencia, la regla que se usa como comparación.
- efecto_real(): solo para datos sintéticos; usa los parámetros del generador.
"""
from __future__ import annotations

import itertools
import json
import math
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

INICIO, CONV, NULO = "(inicio)", "(conversion)", "(nulo)"


# ---------------------------------------------------------------- referencia
def ultimo_no_directo(rutas: pd.DataFrame) -> pd.DataFrame:
    """Crédito completo al último canal distinto de Direct (Direct si la ruta es solo directa)."""
    conv, ingreso = Counter(), Counter()
    for ruta, valor in rutas.loc[rutas.convirtio, ["ruta", "revenue_pen"]].itertuples(index=False):
        no_directos = [c for c in ruta if c != "Direct"]
        canal = no_directos[-1] if no_directos else "Direct"
        conv[canal] += 1
        ingreso[canal] += valor
    return pd.DataFrame({"conversiones": pd.Series(conv), "ingresos": pd.Series(ingreso)})


# ---------------------------------------------------------------- Markov
def _prob_conversion(Q: np.ndarray, R_conv: np.ndarray) -> float:
    """Probabilidad de absorción en (conversion) partiendo de (inicio), fila 0."""
    n = Q.shape[0]
    x = np.linalg.solve(np.eye(n) - Q, R_conv)
    return float(x[0])


def markov(rutas: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Cadena de Markov de primer orden. Devuelve crédito por canal y diagnóstico."""
    transiciones = Counter()
    for ruta, convirtio in rutas[["ruta", "convirtio"]].itertuples(index=False):
        estados = [INICIO, *ruta, CONV if convirtio else NULO]
        transiciones.update(zip(estados[:-1], estados[1:]))

    canales = sorted({c for ruta in rutas.ruta for c in ruta})
    transitorios = [INICIO, *canales]
    idx = {s: i for i, s in enumerate(transitorios)}
    n = len(transitorios)
    Q = np.zeros((n, n))
    R = np.zeros((n, 2))                                 # columnas: conversion, nulo
    salidas = Counter()
    for (a, b), k in transiciones.items():
        salidas[a] += k
    for (a, b), k in transiciones.items():
        p = k / salidas[a]
        if b == CONV:
            R[idx[a], 0] += p
        elif b == NULO:
            R[idx[a], 1] += p
        else:
            Q[idx[a], idx[b]] += p

    base = _prob_conversion(Q, R[:, 0])
    remocion = {}
    for c in canales:
        # Quitar el canal: toda transición que entraba a él termina en (nulo)
        Qr = Q.copy()
        Qr[:, idx[c]] = 0.0
        remocion[c] = 1 - _prob_conversion(Qr, R[:, 0]) / base

    total_re = sum(remocion.values())
    pesos = {c: remocion[c] / total_re for c in canales}
    convertidas = rutas[rutas.convirtio]
    n_conv, ingresos = len(convertidas), convertidas.revenue_pen.sum()
    df = pd.DataFrame({
        "conversiones": {c: pesos[c] * n_conv for c in canales},
        "ingresos": {c: pesos[c] * ingresos for c in canales},
        "efecto_remocion": remocion,
    })
    return df, {"prob_conversion_base": base}


# ---------------------------------------------------------------- Shapley
def _matriz(conjuntos: list[frozenset], canales: list[str]) -> np.ndarray:
    pares = list(itertools.combinations(canales, 2))
    X = np.zeros((len(conjuntos), len(canales) + len(pares)))
    for i, s in enumerate(conjuntos):
        for j, c in enumerate(canales):
            X[i, j] = c in s
        for j, (a, b) in enumerate(pares):
            X[i, len(canales) + j] = a in s and b in s
    return X


def shapley(rutas: pd.DataFrame, C: float = 1.0) -> tuple[pd.DataFrame, dict]:
    """
    v(S) = P(conversión | la ruta tocó exactamente los canales S) - P(conversión | ningún canal),
    estimada con una logística sobre indicadores de canal y de pares de canales.
    Cada venta reparte su crédito entre los canales de su ruta según sus valores de Shapley.
    """
    canales = sorted({c for ruta in rutas.ruta for c in ruta})
    conjuntos = [frozenset(r) for r in rutas.ruta]
    X = _matriz(conjuntos, canales)
    y = rutas.convirtio.to_numpy().astype(int)
    modelo = LogisticRegression(C=C, max_iter=5000).fit(X, y)

    cache: dict[frozenset, float] = {}

    def p(S: frozenset) -> float:
        if S not in cache:
            cache[S] = float(modelo.predict_proba(_matriz([S], canales))[0, 1])
        return cache[S]

    vacio = p(frozenset())

    def v(S: frozenset) -> float:
        return p(S) - vacio

    def valores_shapley(T: frozenset) -> dict[str, float]:
        jugadores = sorted(T)
        n = len(jugadores)
        phi = {}
        for i in jugadores:
            otros = [j for j in jugadores if j != i]
            total = 0.0
            for k in range(len(otros) + 1):
                peso = math.factorial(k) * math.factorial(n - k - 1) / math.factorial(n)
                for S in itertools.combinations(otros, k):
                    S = frozenset(S)
                    total += peso * (v(S | {i}) - v(S))
            phi[i] = total
        return phi

    conv, ingreso = defaultdict(float), defaultdict(float)
    reparto_por_conjunto = {}
    for ruta, valor in rutas.loc[rutas.convirtio, ["ruta", "revenue_pen"]].itertuples(index=False):
        T = frozenset(ruta)
        if T not in reparto_por_conjunto:
            phi = valores_shapley(T)
            suma = sum(max(x, 0.0) for x in phi.values())
            reparto_por_conjunto[T] = ({c: max(x, 0.0) / suma for c, x in phi.items()} if suma > 0
                                       else {c: 1 / len(T) for c in T})
        for c, w in reparto_por_conjunto[T].items():
            conv[c] += w
            ingreso[c] += w * valor

    df = pd.DataFrame({"conversiones": pd.Series(conv), "ingresos": pd.Series(ingreso)})
    return df, {"conjuntos_distintos": len(reparto_por_conjunto), "prob_sin_canales": vacio}


# ---------------------------------------------------------------- verdad (solo sintético)
def efecto_real(rutas: pd.DataFrame, params_json: str) -> pd.Series:
    """Conversiones incrementales reales por canal: p(T) - p(T sin el canal), sumado sobre todas las rutas."""
    P = json.loads(params_json)

    def p(S):
        z = P["b0"] + sum(P["beta"][c] for c in S)
        for par, g in P["sinergia"].items():
            a, b = par.split("|")
            if a in S and b in S:
                z += g
        return 1 / (1 + math.exp(-z))

    efecto = defaultdict(float)
    for ruta in rutas.ruta:
        T = set(ruta)
        pt = p(T)
        for c in T:
            efecto[c] += pt - p(T - {c})
    return pd.Series(efecto)


# ---------------------------------------------------------------- modelos de referencia (reglas)
MODELOS_REGLA = ["primer_clic", "ultimo_clic", "lineal", "posicion_u", "decaimiento_temporal"]


def _pesos(modelo: str, n: int, dias: list[float], vida_media: float) -> list[float]:
    """Reparto del crédito de una venta entre las n sesiones de su ruta (suma 1)."""
    if modelo == "primer_clic":
        return [1.0] + [0.0] * (n - 1)
    if modelo == "ultimo_clic":  # incluye Direct: es la regla ingenua de referencia
        return [0.0] * (n - 1) + [1.0]
    if modelo == "lineal":
        return [1.0 / n] * n
    if modelo == "posicion_u":  # 40 % primera, 40 % última, 20 % repartido en el medio
        if n == 1:
            return [1.0]
        if n == 2:
            return [0.5, 0.5]
        return [0.4] + [0.2 / (n - 2)] * (n - 2) + [0.4]
    if modelo == "decaimiento_temporal":  # cada `vida_media` días el crédito se reduce a la mitad
        crudo = [0.5 ** (d / vida_media) for d in dias]
        total = sum(crudo)
        return [c / total for c in crudo]
    raise ValueError(f"Modelo desconocido: {modelo}")


def modelos_regla(rutas: pd.DataFrame, vida_media: float = 7.0) -> dict[str, pd.DataFrame]:
    """Primer clic, último clic, lineal, posición U y decaimiento temporal."""
    conv = {m: defaultdict(float) for m in MODELOS_REGLA}
    ingreso = {m: defaultdict(float) for m in MODELOS_REGLA}
    for ruta, dias, valor in rutas.loc[rutas.convirtio, ["ruta", "dias_antes", "revenue_pen"]].itertuples(index=False):
        for m in MODELOS_REGLA:
            for canal, w in zip(ruta, _pesos(m, len(ruta), dias, vida_media)):
                conv[m][canal] += w
                ingreso[m][canal] += w * valor
    return {
        m: pd.DataFrame({"conversiones": pd.Series(conv[m]), "ingresos": pd.Series(ingreso[m])})
        for m in MODELOS_REGLA
    }


# ---------------------------------------------------------------- roles según Markov
def markov_roles(rutas: pd.DataFrame) -> pd.DataFrame:
    """
    Qué hace cada canal dentro de la cadena, a partir de las transiciones observadas:
      p_apertura_pct   % de las rutas que empiezan en el canal (abridor)
      p_continua_pct   % de las visitas al canal tras las cuales el usuario sigue a otro canal (asistente)
      p_cierre_pct     % de las visitas al canal que terminan en compra (conversor)
      p_abandono_pct   % de las visitas que terminan sin compra
    """
    salidas: dict[str, Counter] = defaultdict(Counter)
    aperturas = Counter()
    for ruta, convirtio in rutas[["ruta", "convirtio"]].itertuples(index=False):
        estados = [*ruta, CONV if convirtio else NULO]
        aperturas[ruta[0]] += 1
        for a, b in zip(estados[:-1], estados[1:]):
            salidas[a][b] += 1
    filas = {}
    for canal, s in salidas.items():
        n = sum(s.values())
        filas[canal] = {
            "p_apertura_pct": aperturas[canal] / len(rutas) * 100,
            "p_continua_pct": (n - s[CONV] - s[NULO]) / n * 100,
            "p_cierre_pct": s[CONV] / n * 100,
            "p_abandono_pct": s[NULO] / n * 100,
        }
    return pd.DataFrame(filas).T.round(2).rename_axis("canal")
