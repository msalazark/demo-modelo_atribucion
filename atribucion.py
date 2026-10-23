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
from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.metrics import log_loss, roc_auc_score

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
def _prob_conversion(Q: np.ndarray, R_conv: np.ndarray, desde: int = 0) -> float:
    """Probabilidad (o valor esperado) de absorción partiendo del estado `desde`."""
    n = Q.shape[0]
    x = np.linalg.solve(np.eye(n) - Q, R_conv)
    return float(x[desde])


def _estado(historial: list[str], orden: int) -> tuple:
    """Estado = tupla de los últimos `orden` canales visitados, rellenada con INICIO al empezar."""
    cola = historial[-orden:] if orden else []
    return tuple([INICIO] * (orden - len(cola)) + cola)


def _cadena_markov(rutas: pd.DataFrame, orden: int, excluir_direct: bool):
    """Matrices de transición (Q, conteo e ingreso hacia conversión) de una cadena de Markov de
    orden `orden`, opcionalmente sin Direct como eslabón (RQ-12). Con orden=1 y excluir_direct=False
    el estado es exactamente el canal (igual que la cadena de primer orden original)."""
    canales = sorted({c for ruta in rutas.ruta for c in ruta})
    canales_cadena = [c for c in canales if c != "Direct"] if excluir_direct else canales

    transiciones: Counter = Counter()
    valor_conv: Counter = Counter()
    for ruta, convirtio, valor in rutas[["ruta", "convirtio", "revenue_pen"]].itertuples(index=False):
        secuencia = [c for c in ruta if c != "Direct"] if excluir_direct else list(ruta)
        historial: list[str] = []
        estado_actual = _estado(historial, orden)
        for c in secuencia:
            historial.append(c)
            estado_siguiente = _estado(historial, orden)
            transiciones[(estado_actual, estado_siguiente)] += 1
            estado_actual = estado_siguiente
        transiciones[(estado_actual, CONV if convirtio else NULO)] += 1
        if convirtio:
            valor_conv[estado_actual] += valor

    estados = sorted({a for a, _ in transiciones} | {b for _, b in transiciones if b not in (CONV, NULO)})
    idx = {s: i for i, s in enumerate(estados)}
    n = len(estados)
    Q = np.zeros((n, n))
    R_conteo = np.zeros(n)
    R_valor = np.zeros(n)
    salidas: Counter = Counter()
    for (a, b), k in transiciones.items():
        salidas[a] += k
    for (a, b), k in transiciones.items():
        p = k / salidas[a]
        if b == CONV:
            R_conteo[idx[a]] += p
        elif b != NULO:
            Q[idx[a], idx[b]] += p
    for estado, valor in valor_conv.items():
        R_valor[idx[estado]] = valor / salidas[estado]  # ingreso esperado por visita desde ese estado

    estado_inicio = idx[_estado([], orden)]
    return Q, R_conteo, R_valor, idx, estado_inicio, canales, canales_cadena


def markov(
    rutas: pd.DataFrame,
    orden: int = 1,
    excluir_direct: bool = False,
    ponderar_ingreso_por_valor: bool = False,
) -> tuple[pd.DataFrame, dict]:
    """Cadena de Markov con efecto de remoción. Variantes de RQ-12:

      orden: 1 (de toda la vida) o 2 (el estado es el par de los dos últimos canales visitados).
      excluir_direct: Direct no cuenta como eslabón de la cadena (se observó que, si cuenta, se
        lleva demasiado crédito solo por su frecuencia); sus sesiones se saltan al construir la ruta.
      ponderar_ingreso_por_valor: si es True, los ingresos se reparten con un efecto de remoción
        calculado sobre el ingreso esperado por visita, no con la misma cuota de conversiones.

    Con los valores por defecto el resultado es idéntico al de la cadena de primer orden original.
    """
    Q, R_conteo, R_valor, idx, estado_inicio, canales, canales_cadena = _cadena_markov(rutas, orden, excluir_direct)

    base = _prob_conversion(Q, R_conteo, estado_inicio)
    base_valor = _prob_conversion(Q, R_valor, estado_inicio) if ponderar_ingreso_por_valor else None

    remocion, remocion_valor = {}, {}
    for c in canales_cadena:
        columnas_c = [i for s, i in idx.items() if s[-1] == c]
        Qr = Q.copy()
        Qr[:, columnas_c] = 0.0
        remocion[c] = 1 - _prob_conversion(Qr, R_conteo, estado_inicio) / base
        if ponderar_ingreso_por_valor:
            remocion_valor[c] = 1 - _prob_conversion(Qr, R_valor, estado_inicio) / base_valor

    total_re = sum(remocion.values())
    pesos = {c: remocion[c] / total_re for c in canales_cadena}
    if ponderar_ingreso_por_valor:
        total_re_valor = sum(remocion_valor.values())
        pesos_ingreso = {c: remocion_valor[c] / total_re_valor for c in canales_cadena}
    else:
        pesos_ingreso = pesos

    convertidas = rutas[rutas.convirtio]
    n_conv, ingresos = len(convertidas), convertidas.revenue_pen.sum()
    df = pd.DataFrame({
        "conversiones": {c: pesos[c] * n_conv for c in canales_cadena},
        "ingresos": {c: pesos_ingreso[c] * ingresos for c in canales_cadena},
        "efecto_remocion": remocion,
    }).reindex(canales).fillna(0.0)  # Direct, si se excluyó, queda en la tabla con crédito 0
    return df, {"prob_conversion_base": base, "orden": orden, "excluir_direct": excluir_direct,
                "ponderar_ingreso_por_valor": ponderar_ingreso_por_valor}


def comparar_variantes_markov(rutas: pd.DataFrame, params_json: str) -> pd.DataFrame:
    """Error de cuota de cada variante de Markov (orden, Direct, reparto de ingresos) frente al
    efecto real, en datos sintéticos (RQ-12): la configuración elige cuál queda vigente."""
    real = efecto_real(rutas, params_json)
    cuota_real = real / real.sum() * 100
    filas = []
    for orden in (1, 2):
        for excluir_direct in (False, True):
            for ponderar_valor in (False, True):
                df, _ = markov(rutas, orden=orden, excluir_direct=excluir_direct,
                               ponderar_ingreso_por_valor=ponderar_valor)
                cuota = df.conversiones / df.conversiones.sum() * 100
                error = (cuota.reindex(cuota_real.index).fillna(0.0) - cuota_real).abs().mean()
                filas.append({"orden": orden, "excluir_direct": excluir_direct,
                              "ingreso_por_valor": ponderar_valor, "error_medio_pp": round(error, 2)})
    return pd.DataFrame(filas).sort_values("error_medio_pp").reset_index(drop=True)


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


def _valores_shapley_exacto(T: frozenset, v) -> dict[str, float]:
    """Fórmula exacta de Shapley: exponencial en |T|, exacta para cualquier conjunto pequeño."""
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


def _valores_shapley_montecarlo(T: frozenset, v, n_permutaciones: int, rng: np.random.Generator) -> dict[str, float]:
    """Estimación por muestreo de permutaciones (RQ-13): para universos grandes de canales, la
    fórmula exacta es inviable; el promedio de contribuciones marginales sobre permutaciones
    aleatorias converge al valor de Shapley."""
    jugadores = list(T)
    n = len(jugadores)
    if n == 0:
        return {}
    acumulado = {j: 0.0 for j in jugadores}
    for _ in range(n_permutaciones):
        actual: frozenset = frozenset()
        v_prev = v(actual)
        for pos in rng.permutation(n):
            j = jugadores[pos]
            actual = actual | {j}
            v_actual = v(actual)
            acumulado[j] += v_actual - v_prev
            v_prev = v_actual
    return {j: acumulado[j] / n_permutaciones for j in jugadores}


def _calibracion_por_deciles(proba: np.ndarray, y: np.ndarray, pesos: np.ndarray) -> pd.DataFrame:
    """Probabilidad predicha media vs. tasa real de conversión en 10 grupos de igual peso
    (conteo de rutas), ordenados por probabilidad predicha (RQ-13)."""
    d = pd.DataFrame({"proba": proba, "y": y, "peso": pesos}).sort_values("proba")
    total = d.peso.sum()
    d["decil"] = np.ceil(d.peso.cumsum() / total * 10).clip(1, 10).astype(int)
    return d.groupby("decil").apply(
        lambda g: pd.Series({
            "prob_predicha_media": round(float(np.average(g.proba, weights=g.peso)), 4),
            "tasa_real_pct": round(float(np.average(g.y, weights=g.peso)) * 100, 2),
            "n_rutas": int(g.peso.sum()),
        }), include_groups=False,
    ).reset_index()


def shapley(
    rutas: pd.DataFrame,
    C: float | None = None,
    limite_jugadores: int = 12,
    n_permutaciones_monte_carlo: int = 200,
    seed: int = 0,
) -> tuple[pd.DataFrame, dict]:
    """
    v(S) = P(conversión | la ruta tocó exactamente los canales S) - P(conversión | ningún canal),
    estimada con una logística sobre indicadores de canal y de pares de canales.
    Cada venta reparte su crédito entre los canales de su ruta según sus valores de Shapley.

    RQ-13:
    - La logística se ajusta sobre las rutas **agregadas por conjunto de canales** (conteo de
      convertidas y no convertidas por conjunto, vía `sample_weight`), no una fila por ruta: mismo
      resultado, mucho más rápido con volumen real.
    - `C=None` (por defecto) elige la regularización por validación cruzada
      (`LogisticRegressionCV`); si no converge por falta de datos (ventanas chicas), usa `C=1.0`.
    - Con más de `limite_jugadores` canales en total, los valores de Shapley se estiman por Monte
      Carlo (muestreo de permutaciones) en vez de la fórmula exacta, exponencial en el tamaño de
      cada conjunto.
    - El diagnóstico devuelto (AUC, log-loss, calibración por deciles, phi negativos recortados a
      0) alimenta `mart_calidad__modelo`.
    """
    canales = sorted({c for ruta in rutas.ruta for c in ruta})
    rng = np.random.default_rng(seed)

    conteo = Counter((frozenset(r), bool(conv)) for r, conv in rutas[["ruta", "convirtio"]].itertuples(index=False))
    conjuntos_unicos = sorted({s for s, _ in conteo}, key=lambda s: (len(s), sorted(s)))
    Xg = _matriz(conjuntos_unicos, canales)
    filas_X, filas_y, pesos = [], [], []
    for i, s in enumerate(conjuntos_unicos):
        for resultado in (True, False):
            n = conteo.get((s, resultado), 0)
            if n:
                filas_X.append(Xg[i])
                filas_y.append(int(resultado))
                pesos.append(n)
    X, y, pesos = np.array(filas_X), np.array(filas_y), np.array(pesos, dtype=float)

    if C is None:
        try:
            modelo = LogisticRegressionCV(
                Cs=[0.01, 0.1, 1.0, 10.0, 100.0], cv=5, max_iter=5000, scoring="neg_log_loss",
            ).fit(X, y, sample_weight=pesos)
            C_elegido = float(modelo.C_[0])
        except ValueError:  # muy pocos datos para 5 folds (ventana o segmento chico)
            modelo = LogisticRegression(C=1.0, max_iter=5000).fit(X, y, sample_weight=pesos)
            C_elegido = 1.0
    else:
        modelo = LogisticRegression(C=C, max_iter=5000).fit(X, y, sample_weight=pesos)
        C_elegido = C

    proba_ajuste = modelo.predict_proba(X)[:, 1]
    try:
        auc = float(roc_auc_score(y, proba_ajuste, sample_weight=pesos))
    except ValueError:  # un solo valor de y en toda la ventana/segmento: AUC no está definida
        auc = float("nan")
    logloss = float(log_loss(y, proba_ajuste, sample_weight=pesos, labels=[0, 1]))
    calibracion = _calibracion_por_deciles(proba_ajuste, y, pesos)

    cache: dict[frozenset, float] = {}

    def p(S: frozenset) -> float:
        if S not in cache:
            cache[S] = float(modelo.predict_proba(_matriz([S], canales))[0, 1])
        return cache[S]

    vacio = p(frozenset())

    def v(S: frozenset) -> float:
        return p(S) - vacio

    usar_monte_carlo = len(canales) > limite_jugadores

    def valores_shapley(T: frozenset) -> dict[str, float]:
        if usar_monte_carlo:
            return _valores_shapley_montecarlo(T, v, n_permutaciones_monte_carlo, rng)
        return _valores_shapley_exacto(T, v)

    conv, ingreso = defaultdict(float), defaultdict(float)
    reparto_por_conjunto = {}
    phi_negativos_recortados = 0
    for ruta, valor in rutas.loc[rutas.convirtio, ["ruta", "revenue_pen"]].itertuples(index=False):
        T = frozenset(ruta)
        if T not in reparto_por_conjunto:
            phi = valores_shapley(T)
            phi_negativos_recortados += sum(1 for x in phi.values() if x < 0)
            suma = sum(max(x, 0.0) for x in phi.values())
            reparto_por_conjunto[T] = ({c: max(x, 0.0) / suma for c, x in phi.items()} if suma > 0
                                       else {c: 1 / len(T) for c in T})
        for c, w in reparto_por_conjunto[T].items():
            conv[c] += w
            ingreso[c] += w * valor

    df = pd.DataFrame({"conversiones": pd.Series(conv), "ingresos": pd.Series(ingreso)})
    diagnostico = {
        "conjuntos_distintos": len(reparto_por_conjunto), "prob_sin_canales": vacio,
        "metodo": "monte_carlo" if usar_monte_carlo else "exacto", "C_elegido": C_elegido,
        "auc": auc, "log_loss": logloss, "phi_negativos_recortados": phi_negativos_recortados,
        "calibracion": calibracion,
    }
    return df, diagnostico


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
