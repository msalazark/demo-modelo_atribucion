"""Pruebas de metricas_decision.py (RQ-27, RQ-11): alcance/conversión, roles canónicos, señales
y rutas top."""
import pandas as pd

from metricas_decision import asignar_senal, calcular, cierre_ultimo_no_directo, roles_por_canal, rutas_top


def _rutas(filas):
    return pd.DataFrame(filas, columns=["user_pseudo_id", "ruta", "convirtio", "revenue_pen", "order_id"])


def _sesiones(filas):
    return pd.DataFrame(filas, columns=["canal", "es_pasarela"])


# ----------------------------------------------------------------- roles_por_canal (RQ-11)
def test_roles_a_mano_abre_asiste_cierra():
    """A→B→C: A abre, B asiste, C cierra (ejemplo literal de RQ-11)."""
    rutas = _rutas([("u1", ["A", "B", "C"], True, 100.0, "O1")])
    roles, pares = roles_por_canal(rutas)
    assert roles.loc["A", "ventas_abre"] == 1 and roles.loc["A", "ventas_asiste"] == 0
    assert roles.loc["B", "ventas_asiste"] == 1 and roles.loc["B", "ventas_abre"] == 0
    assert roles.loc["C", "ventas_cierra"] == 1
    assert pares.set_index(["asistente", "cierre"]).conversiones.to_dict() == {("B", "C"): 1}


def test_roles_a_mano_ruta_unica():
    """A (única sesión): es único, no suma a abre ni a cierra."""
    rutas = _rutas([("u1", ["A"], True, 50.0, "O1")])
    roles, _ = roles_por_canal(rutas)
    assert roles.loc["A", "ventas_unico"] == 1
    assert roles.loc["A", "ventas_abre"] == 0 and roles.loc["A", "ventas_cierra"] == 0


def test_roles_a_mano_canal_repetido_abre_y_asiste():
    """A→A→B: A abre (primera sesión) Y asiste (también aparece en la posición media); B cierra."""
    rutas = _rutas([("u1", ["A", "A", "B"], True, 100.0, "O1")])
    roles, _ = roles_por_canal(rutas)
    assert roles.loc["A", "ventas_abre"] == 1
    assert roles.loc["A", "ventas_asiste"] == 1
    assert roles.loc["B", "ventas_cierra"] == 1


def test_roles_variante_ultimo_no_directo():
    """A→B→Direct: con 'ultima_sesion' cierra Direct; con 'ultimo_no_directo' cierra B."""
    rutas = _rutas([("u1", ["A", "B", "Direct"], True, 100.0, "O1")])
    canonico, _ = roles_por_canal(rutas, variante_cierre="ultima_sesion")
    no_directo, _ = roles_por_canal(rutas, variante_cierre="ultimo_no_directo")
    assert canonico.loc["Direct", "ventas_cierra"] == 1
    assert no_directo.loc["B", "ventas_cierra"] == 1


# ----------------------------------------------------------------- calcular
def test_calcular_alcance_y_roles_a_mano():
    """u1: A->B convierte (A abre, B cierra; ruta de 2 no tiene posición media -> sin asiste).
    u2: A no convierte. u3: B único, convierte."""
    rutas = _rutas([
        ("u1", ["A", "B"], True, 100.0, "O1"),
        ("u2", ["A"], False, 0.0, None),
        ("u3", ["B"], True, 50.0, "O2"),
    ])
    sesiones = _sesiones([("A", False), ("A", False), ("B", False), ("B", False)])
    metricas, pares = calcular(rutas, sesiones)

    assert metricas.loc["A", "usuarios_alcanzados"] == 2  # u1, u2
    assert metricas.loc["B", "usuarios_alcanzados"] == 2  # u1, u3
    assert metricas.loc["A", "ventas_abre"] == 1 and metricas.loc["A", "ventas_asiste"] == 0
    assert metricas.loc["B", "ventas_cierra"] == 1  # solo u1: u3 es único, no suma a cierra
    assert metricas.loc["B", "ventas_unico"] == 1
    assert len(pares) == 0  # ninguna ruta de 3+ sesiones: no hay posiciones medias


def test_cierre_ultimo_no_directo():
    assert cierre_ultimo_no_directo(["A", "Direct"]) == "A"
    assert cierre_ultimo_no_directo(["Direct"]) == "Direct"


def test_rutas_top_ordena_por_pedidos():
    rutas = _rutas([
        ("u1", ["A", "B"], True, 100.0, "O1"),
        ("u2", ["A", "B"], True, 50.0, "O2"),
        ("u3", ["B"], True, 10.0, "O3"),
    ])
    top = rutas_top(rutas, n=2)
    assert top.iloc[0].ruta_txt == "A → B" and top.iloc[0].pedidos == 2
    assert len(top) == 2


# ----------------------------------------------------------------- asignar_senal
def _fila(**kw):
    base = {"cuota_pct": 20.0, "cuota_ultimo_no_directo_pct": 20.0, "roas": float("nan"), "cpa": float("nan"),
             "costo": float("nan"), "ancho_ci": float("nan"), "ratio_asistencia": 0.0,
             "tasa_conv_usuario_pct": 1.0, "cuota_total_pct": float("nan")}
    base.update(kw)
    return base


def _con_base(roas_x: float) -> pd.DataFrame:
    """`Base` domina el costo (99 % del total pagado) para que el ROAS promedio quede ≈ 5.0,
    así `X` (con costo marginal) sirve para probar la señal sin que mueva el propio promedio."""
    return pd.DataFrame({
        "Base": _fila(roas=5.0, costo=100_000.0, cpa=5.0),
        "X": _fila(roas=roas_x, costo=100.0, cpa=5.0),
    }).T


def test_senal_escalar_cuando_roas_supera_el_umbral():
    out = asignar_senal(_con_base(roas_x=7.0), pedidos=5000, es_segmento=False)  # rel = 7/5 = 1.4
    assert out.loc["X", "senal"] == "Escalar (validar)"


def test_senal_revisar_cuando_roas_bajo_el_umbral():
    out = asignar_senal(_con_base(roas_x=3.0), pedidos=5000, es_segmento=False)  # rel = 3/5 = 0.6
    assert out.loc["X", "senal"] == "Revisar"


def test_senal_direct_no_es_palanca():
    m = pd.DataFrame({"Direct": _fila()}).T
    out = asignar_senal(m, pedidos=5000, es_segmento=False)
    assert out.loc["Direct", "senal"] == "No es palanca"


def test_senal_proteger_canal_sin_costo_que_asiste_mucho():
    m = pd.DataFrame({"Organic": _fila(ratio_asistencia=3.0)}).T
    out = asignar_senal(m, pedidos=5000, es_segmento=False)
    assert out.loc["Organic", "senal"] == "Proteger"


def test_senal_aprovechar_canal_sin_costo_que_convierte_mucho():
    m = pd.DataFrame({
        "Organic": _fila(ratio_asistencia=0.0, tasa_conv_usuario_pct=5.0),
        "Email": _fila(ratio_asistencia=0.0, tasa_conv_usuario_pct=1.0),
    }).T
    out = asignar_senal(m, pedidos=5000, es_segmento=False)
    assert out.loc["Organic", "senal"] == "Aprovechar"


def test_senal_sobre_y_sub_indice_en_segmento():
    m = pd.DataFrame({
        "A": _fila(cuota_pct=30.0, cuota_total_pct=20.0),
        "B": _fila(cuota_pct=10.0, cuota_total_pct=20.0),
    }).T
    out = asignar_senal(m, pedidos=500, es_segmento=True, minimo_conversiones_senal=0)
    assert out.loc["A", "senal"] == "Sobre-índice"
    assert out.loc["B", "senal"] == "Sub-índice"


def test_senal_usa_umbrales_configurables():
    """Con un umbral_escalar más laxo, un ROAS que antes caía en 'Mantener' pasa a 'Escalar'."""
    m = _con_base(roas_x=5.6)  # rel ~= 1.12: entre 0.8 y 1.2 -> Mantener por defecto
    por_defecto = asignar_senal(m, pedidos=5000, es_segmento=False)
    laxo = asignar_senal(m, pedidos=5000, es_segmento=False, umbral_escalar=1.1)
    assert por_defecto.loc["X", "senal"] == "Mantener"
    assert laxo.loc["X", "senal"] == "Escalar (validar)"


def test_confianza_usa_umbrales_configurables_de_pedidos():
    m = pd.DataFrame({"X": _fila()}).T
    out = asignar_senal(m, pedidos=1500, es_segmento=False, confianza_alta_pedidos=1000, confianza_media_pedidos=500)
    assert out.loc["X", "confianza"] == "alta"


def test_confianza_por_ancho_de_intervalo_bootstrap():
    m = pd.DataFrame({"X": _fila(ancho_ci=1.5), "Y": _fila(ancho_ci=3.0), "Z": _fila(ancho_ci=5.0)}).T
    out = asignar_senal(m, pedidos=0, es_segmento=False, minimo_conversiones_senal=0)
    assert out.loc["X", "confianza"] == "alta"
    assert out.loc["Y", "confianza"] == "media"
    assert out.loc["Z", "confianza"] == "baja"


def test_senal_segmento_igual_al_total():
    m = pd.DataFrame({"A": _fila(cuota_pct=20.0, cuota_total_pct=20.0)}).T
    out = asignar_senal(m, pedidos=500, es_segmento=True, minimo_conversiones_senal=0)
    assert out.loc["A", "senal"] == "Igual al total"


def test_senal_escalar_menciona_asistencia_alta():
    m = _con_base(roas_x=7.0)
    m.loc["X", "ratio_asistencia"] = 3.0
    out = asignar_senal(m, pedidos=5000, es_segmento=False)
    assert "asiste" in out.loc["X", "motivo"]


# ----------------------------------------------------------------- RQ-14: robustez por segmento
def test_bajo_el_minimo_de_conversiones_no_se_publica_senal():
    """Con menos conversiones que minimo_conversiones_senal, ningún canal recibe una señal
    accionable (ni Direct, ni uno con ROAS claramente alto): todos quedan en evidencia insuficiente."""
    m = _con_base(roas_x=7.0)  # con volumen normal, X sería "Escalar (validar)"
    out = asignar_senal(m, pedidos=5000, es_segmento=False, minimo_conversiones_senal=10_000)
    assert (out.senal == "Evidencia insuficiente").all()
    assert (out.confianza == "baja").all()


def test_en_o_sobre_el_minimo_si_se_publica_senal():
    m = _con_base(roas_x=7.0)
    out = asignar_senal(m, pedidos=1000, es_segmento=False, minimo_conversiones_senal=1000)
    assert out.loc["X", "senal"] == "Escalar (validar)"
