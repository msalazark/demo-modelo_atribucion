"""Pruebas de atribucion.py (RQ-27): reglas, Markov, Shapley, último clic no directo y roles.

Los casos de Markov están calculados a mano (ver el comentario en test_markov_efecto_remocion).
"""
import json

import numpy as np
import pandas as pd
import pytest

from atribucion import (
    _pesos,
    comparar_variantes_markov,
    efecto_real,
    markov,
    markov_roles,
    modelos_regla,
    shapley,
    ultimo_no_directo,
)


def _rutas(filas: list[tuple[list[str], bool, float, list[float]]]) -> pd.DataFrame:
    """Arma un DataFrame `rutas` mínimo a partir de (ruta, convirtio, revenue_pen, dias_antes)."""
    return pd.DataFrame(filas, columns=["ruta", "convirtio", "revenue_pen", "dias_antes"])


# ----------------------------------------------------------------- reglas (_pesos)
@pytest.mark.parametrize("n,esperado", [(1, [1.0]), (2, [1.0, 0.0]), (3, [1.0, 0.0, 0.0])])
def test_pesos_primer_clic(n, esperado):
    assert _pesos("primer_clic", n, [0.0] * n, 7.0) == esperado


@pytest.mark.parametrize("n,esperado", [(1, [1.0]), (2, [0.0, 1.0]), (3, [0.0, 0.0, 1.0])])
def test_pesos_ultimo_clic(n, esperado):
    assert _pesos("ultimo_clic", n, [0.0] * n, 7.0) == esperado


def test_pesos_lineal_reparte_por_igual():
    assert _pesos("lineal", 4, [0.0] * 4, 7.0) == [0.25, 0.25, 0.25, 0.25]


@pytest.mark.parametrize("n,esperado", [
    (1, [1.0]), (2, [0.5, 0.5]), (3, [0.4, 0.2, 0.4]), (4, [0.4, 0.1, 0.1, 0.4]),
])
def test_pesos_posicion_u(n, esperado):
    assert _pesos("posicion_u", n, [0.0] * n, 7.0) == pytest.approx(esperado)


def test_pesos_decaimiento_temporal_a_mano():
    # vida_media=7: a 7 días de la compra el peso crudo es 0.5; a 0 días es 1.0.
    pesos = _pesos("decaimiento_temporal", 2, [7.0, 0.0], 7.0)
    assert pesos == pytest.approx([0.5 / 1.5, 1.0 / 1.5])


def test_pesos_modelo_desconocido_falla():
    with pytest.raises(ValueError):
        _pesos("no_existe", 2, [0.0, 0.0], 7.0)


def test_modelos_regla_corre_las_cinco():
    rutas = _rutas([(["A", "B"], True, 100.0, [7.0, 0.0])])
    out = modelos_regla(rutas)
    assert set(out) == {"primer_clic", "ultimo_clic", "lineal", "posicion_u", "decaimiento_temporal"}
    assert out["primer_clic"].loc["A", "conversiones"] == 1.0
    assert out["ultimo_clic"].loc["B", "conversiones"] == 1.0


# ----------------------------------------------------------------- último clic no directo
def test_ultimo_no_directo_ignora_direct_salvo_que_sea_la_unica():
    rutas = _rutas([
        (["Direct"], True, 10.0, [0.0]),
        (["A", "Direct"], True, 20.0, [1.0, 0.0]),
        (["A", "B"], True, 30.0, [2.0, 0.0]),
    ])
    out = ultimo_no_directo(rutas)
    assert out.conversiones.to_dict() == {"Direct": 1, "A": 1, "B": 1}
    assert out.ingresos.to_dict() == {"Direct": 10.0, "A": 20.0, "B": 30.0}


# ----------------------------------------------------------------- Markov
def test_markov_efecto_remocion_cadena_de_dos_canales():
    """Cálculo a mano (ver docs/RQ_mejoras.md RQ-27): rutas A, A->B (convertidas) y B (no convertida).

    Transiciones: (inicio)->A=2/3, (inicio)->B=1/3, A->conversion=1/2, A->B=1/2,
    B->conversion=1/2, B->nulo=1/2.
    base = P(conversión) = 2/3.
    Quitando A: la única vía a conversión es (inicio)->B->conversion = 1/3 * 1/2 = 1/6.
      remocion[A] = 1 - (1/6)/(2/3) = 0.75
    Quitando B: la única vía es (inicio)->A->conversion = 2/3 * 1/2 = 1/3.
      remocion[B] = 1 - (1/3)/(2/3) = 0.5
    peso_A = 0.75/1.25 = 0.6, peso_B = 0.5/1.25 = 0.4
    """
    rutas = _rutas([
        (["A"], True, 100.0, [0.0]),
        (["A", "B"], True, 200.0, [1.0, 0.0]),
        (["B"], False, 0.0, [0.0]),
    ])
    df, diag = markov(rutas)
    assert diag["prob_conversion_base"] == pytest.approx(2 / 3)
    assert df.efecto_remocion.to_dict() == pytest.approx({"A": 0.75, "B": 0.5})
    assert df.conversiones.to_dict() == pytest.approx({"A": 0.6 * 2, "B": 0.4 * 2})
    assert df.ingresos.to_dict() == pytest.approx({"A": 0.6 * 300, "B": 0.4 * 300})


# ----------------------------------------------------------------- Markov: variantes (RQ-12)
def _rutas_markov_variantes() -> pd.DataFrame:
    return _rutas([
        (["Direct", "A"], True, 100.0, [1.0, 0.0]),
        (["Direct", "A"], True, 10.0, [1.0, 0.0]),
        (["A", "B"], True, 300.0, [1.0, 0.0]),
        (["B"], False, 0.0, [0.0]),
        (["Direct"], False, 0.0, [0.0]),
    ])


def test_markov_orden_2_reparte_todo_el_credito():
    rutas = _rutas_markov_variantes()
    df, diag = markov(rutas, orden=2)
    assert diag["orden"] == 2
    assert df.conversiones.sum() == pytest.approx(rutas.convirtio.sum())


def test_markov_excluir_direct_le_quita_todo_el_credito():
    rutas = _rutas_markov_variantes()
    df, _ = markov(rutas, excluir_direct=True)
    assert df.loc["Direct", "conversiones"] == 0
    assert df.loc["Direct", "efecto_remocion"] == 0
    assert df.conversiones.sum() == pytest.approx(rutas.convirtio.sum())


def test_markov_ingreso_por_valor_reparte_distinto_que_por_conversiones():
    """La ruta A->B (revenue 300) pesa mucho más en ingresos que en conversiones; ponderar por
    valor debe darle a B más cuota de ingresos que la cuota de conversiones que ya tiene."""
    rutas = _rutas_markov_variantes()
    por_conversiones, _ = markov(rutas, ponderar_ingreso_por_valor=False)
    por_valor, _ = markov(rutas, ponderar_ingreso_por_valor=True)
    cuota_ingreso_conv = por_conversiones.ingresos / por_conversiones.ingresos.sum()
    cuota_ingreso_valor = por_valor.ingresos / por_valor.ingresos.sum()
    assert not np.isclose(cuota_ingreso_conv["B"], cuota_ingreso_valor["B"])
    assert por_valor.ingresos.sum() == pytest.approx(por_conversiones.ingresos.sum())  # mismo total


def test_comparar_variantes_markov_reporta_las_ocho_combinaciones():
    rutas = _rutas_markov_variantes()
    params = json.dumps({"b0": -1.0, "beta": {"A": 1.0, "B": 0.5, "Direct": -0.5}, "sinergia": {}})
    comp = comparar_variantes_markov(rutas, params)
    assert len(comp) == 8
    assert set(comp.columns) == {"orden", "excluir_direct", "ingreso_por_valor", "error_medio_pp"}
    assert (comp.error_medio_pp.diff().dropna() >= 0).all()  # ordenado de menor a mayor error


# ----------------------------------------------------------------- Shapley
def _rutas_shapley(n: int, seed: int = 0) -> pd.DataFrame:
    import numpy as np

    rng = np.random.default_rng(seed)
    canales = ["A", "B", "C"]
    filas = []
    for _ in range(n):
        largo = rng.integers(1, 4)
        ruta = list(rng.choice(canales, size=largo, replace=False))
        convirtio = bool(rng.random() < (0.2 + 0.1 * len(ruta)))
        filas.append((ruta, convirtio, 100.0 if convirtio else 0.0, [0.0] * largo))
    return _rutas(filas)


def test_shapley_reparte_todo_el_credito_de_cada_venta():
    """Eficiencia a nivel agregado: cada venta reparte exactamente 1 unidad de crédito entre
    los canales de su ruta (RQ-13 pide eficiencia exacta por conjunto; a este nivel del código,
    sin el refactor de RQ-13, se verifica la invariante que ya garantiza el reparto normalizado)."""
    rutas = _rutas_shapley(60, seed=1)
    df, _ = shapley(rutas)
    assert df.conversiones.sum() == pytest.approx(rutas.convirtio.sum())


def test_shapley_simetria_canales_intercambiables():
    """Si A y B aparecen en rutas con exactamente los mismos patrones de co-ocurrencia y
    conversión, deben recibir el mismo crédito (propiedad de simetría de Shapley)."""
    rutas = _rutas([
        (["A"], True, 100.0, [0.0]), (["B"], True, 100.0, [0.0]),
        (["A"], False, 0.0, [0.0]), (["B"], False, 0.0, [0.0]),
        (["A", "C"], True, 100.0, [0.0, 0.0]), (["B", "C"], True, 100.0, [0.0, 0.0]),
        (["A", "C"], False, 0.0, [0.0, 0.0]), (["B", "C"], False, 0.0, [0.0, 0.0]),
    ])
    df, _ = shapley(rutas)
    assert df.conversiones["A"] == pytest.approx(df.conversiones["B"])
    assert df.ingresos["A"] == pytest.approx(df.ingresos["B"])


def test_shapley_canal_ausente_no_recibe_credito():
    """Jugador nulo (caso degenerado): un canal que no aparece en ninguna ruta no puede tener
    crédito asignado."""
    rutas = _rutas([(["A"], True, 100.0, [0.0]), (["A"], False, 0.0, [0.0])])
    df, _ = shapley(rutas)
    assert "Z" not in df.index


# ----------------------------------------------------------------- RQ-13: diagnóstico y escala
def test_shapley_diagnostico_trae_las_claves_esperadas():
    rutas = _rutas_shapley(80, seed=2)
    _, diag = shapley(rutas)
    assert diag["metodo"] == "exacto"  # 3 canales << límite de 12
    assert diag["phi_negativos_recortados"] >= 0
    assert 0.0 <= diag["auc"] <= 1.0 or diag["auc"] != diag["auc"]  # NaN si un solo valor de y
    assert diag["log_loss"] >= 0
    assert set(diag["calibracion"].columns) == {"decil", "prob_predicha_media", "tasa_real_pct", "n_rutas"}
    assert diag["calibracion"].n_rutas.sum() == len(rutas)


def test_shapley_usa_monte_carlo_sobre_el_limite_de_jugadores():
    rutas = _rutas_shapley(80, seed=2)  # usa los 3 canales A, B, C del generador de prueba
    _, diag = shapley(rutas, limite_jugadores=2)
    assert diag["metodo"] == "monte_carlo"


def test_shapley_monte_carlo_se_aproxima_al_exacto():
    """Con suficientes permutaciones, Monte Carlo debe acercarse a la cuota exacta (misma
    semilla y mismos datos, solo cambia el algoritmo de reparto)."""
    rutas = _rutas_shapley(150, seed=3)
    exacto, _ = shapley(rutas, limite_jugadores=12)
    aprox, diag = shapley(rutas, limite_jugadores=0, n_permutaciones_monte_carlo=300)
    assert diag["metodo"] == "monte_carlo"
    cuota_exacta = exacto.conversiones / exacto.conversiones.sum() * 100
    cuota_aprox = aprox.conversiones.reindex(cuota_exacta.index) / aprox.conversiones.sum() * 100
    assert (cuota_exacta - cuota_aprox).abs().max() < 3.0  # pp


def test_shapley_c_fijo_evita_la_validacion_cruzada():
    rutas = _rutas_shapley(60, seed=4)
    _, diag = shapley(rutas, C=2.5)
    assert diag["C_elegido"] == 2.5


# ----------------------------------------------------------------- efecto_real (solo demo)
def test_efecto_real_calculado_a_mano():
    """p(S) = sigmoid(b0 + sum(beta)); sin sinergia. Con b0=-1, beta={A:1, B:0.5}:
    p({})=0.26894, p({A})=0.5, p({B})=0.37754, p({A,B})=0.62246 (sigmoid a mano).
    Ruta {A,B}: efecto[A] += p({A,B})-p({B}); efecto[B] += p({A,B})-p({A}).
    Ruta {A}:   efecto[A] += p({A})-p({})."""
    params = json.dumps({"b0": -1.0, "beta": {"A": 1.0, "B": 0.5}, "sinergia": {}})
    rutas = _rutas([(["A", "B"], True, 100.0, [0.0, 0.0]), (["A"], True, 50.0, [0.0])])
    out = efecto_real(rutas, params)
    assert out["A"] == pytest.approx(0.2449187 + 0.2310586, abs=1e-5)
    assert out["B"] == pytest.approx(0.1224593, abs=1e-5)


def test_efecto_real_aplica_sinergia_entre_pares():
    """Con sinergia A|B=1.0: p({A,B}) sube frente al caso sin sinergia, así que el efecto
    incremental de cada canal dentro de esa ruta también sube."""
    sin_sinergia = json.dumps({"b0": -1.0, "beta": {"A": 1.0, "B": 0.5}, "sinergia": {}})
    con_sinergia = json.dumps({"b0": -1.0, "beta": {"A": 1.0, "B": 0.5}, "sinergia": {"A|B": 1.0}})
    rutas = _rutas([(["A", "B"], True, 100.0, [0.0, 0.0])])
    assert efecto_real(rutas, con_sinergia)["A"] > efecto_real(rutas, sin_sinergia)["A"]


# ----------------------------------------------------------------- roles (markov_roles)
def test_markov_roles_calculado_a_mano():
    """rutas: A->B (convierte) y A (no convierte). A abre el 100% de las rutas; de sus 2 salidas,
    1 sigue a B (continúa) y 1 termina en nulo (abandono): 50%/50%. B solo tiene 1 salida, a
    conversión: 100% cierre."""
    rutas = _rutas([(["A", "B"], True, 100.0, [1.0, 0.0]), (["A"], False, 0.0, [0.0])])
    roles = markov_roles(rutas)
    assert roles.loc["A", "p_apertura_pct"] == pytest.approx(100.0)
    assert roles.loc["A", "p_continua_pct"] == pytest.approx(50.0)
    assert roles.loc["A", "p_abandono_pct"] == pytest.approx(50.0)
    assert roles.loc["B", "p_apertura_pct"] == pytest.approx(0.0)
    assert roles.loc["B", "p_cierre_pct"] == pytest.approx(100.0)
