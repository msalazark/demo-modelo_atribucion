"""
Pruebas del intérprete con un cliente falso (no gastan API ni necesitan credenciales).
Las que leen datos usan data/ecommerce.duckdb: corre `python run_demo.py` antes.
"""
import json
from types import SimpleNamespace

import pytest

from interprete import plantilla
from interprete.agente import Interprete, conocimiento
from interprete.datos import Lector, Vista, construir_hechos
from interprete.herramientas import ejecutar
from interprete.uso import leer as leer_uso
from interprete.verificador import cifras_no_respaldadas


# ----------------------------------------------------------------- cliente falso
def texto(t: str, stop="end_turn"):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=t)], stop_reason=stop,
                           usage=SimpleNamespace(input_tokens=100, output_tokens=50))


def llamada(nombre: str, entrada: dict):
    bloque = SimpleNamespace(type="tool_use", id="toolu_1", name=nombre, input=entrada)
    return SimpleNamespace(content=[bloque], stop_reason="tool_use",
                           usage=SimpleNamespace(input_tokens=100, output_tokens=20))


class ClienteFalso:
    def __init__(self, *respuestas):
        self._cola = list(respuestas)
        self.llamadas: list[dict] = []
        self.messages = self  # el agente usa cliente.beta.messages.create
        self.beta = SimpleNamespace(messages=self)

    def create(self, **kw):
        self.llamadas.append(kw)
        r = self._cola.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(scope="module")
def hechos():
    return construir_hechos(Vista())


# ----------------------------------------------------------------- verificador
def test_verificador_acepta_cifras_de_los_hechos(hechos):
    top = max(hechos["canales"], key=lambda c: c["cuota_pct"])
    assert cifras_no_respaldadas(f"{top['canal']} pesa {top['cuota_pct']} % de las ventas", json.dumps(hechos)) == []


def test_verificador_marca_cifras_inventadas(hechos):
    assert "73.4" in cifras_no_respaldadas("Paid Social aporta 73.4 % de las ventas", json.dumps(hechos))


# RQ-25: el verificador debe reconocer los formatos de número que usa Perú, no solo el inglés.
def test_verificador_reconoce_soles_con_separador_de_miles():
    assert cifras_no_respaldadas("Ingresos de S/ 1,234.56 este mes", "el valor es 1234.56") == []


def test_verificador_reconoce_porcentaje_con_coma_decimal():
    assert cifras_no_respaldadas("una brecha de 3,5 pp", "el valor es 3.5") == []


def test_verificador_reconoce_porcentaje_sin_espacio():
    assert cifras_no_respaldadas("creció 12,5% este mes", "el valor es 12.5") == []


def test_verificador_coma_decimal_fuera_de_tolerancia_se_marca():
    assert "9.9" in cifras_no_respaldadas("una brecha de 9,9 pp", "el valor es 3.5")


# ----------------------------------------------------------------- plantilla (lectura sin LLM)
def test_plantilla_resumen_y_pasos(hechos):
    assert "ventas atribuidas" in plantilla.resumen(hechos)
    pasos = plantilla.siguientes_pasos(hechos)
    assert pasos.startswith("1.") and "ventana de atribución" in pasos


def test_plantilla_usa_solo_cifras_de_los_hechos(hechos):
    respaldo = json.dumps(hechos) + conocimiento()  # igual que el agente: hechos + conocimiento fijo
    assert cifras_no_respaldadas(plantilla.resumen(hechos) + plantilla.siguientes_pasos(hechos), respaldo) == []


# ----------------------------------------------------------------- agente
def test_sin_credenciales_devuelve_plantilla(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = Interprete().interpretar(Vista(), "resumen")
    assert r.generado_con == "plantilla" and r.advertencias


def test_interpretar_con_llm_anclado_y_cacheado():
    cliente = ClienteFalso(texto("Paid Social lidera el reparto de ventas."))
    r = Interprete(cliente=cliente).interpretar(Vista(), "resumen")
    assert r.generado_con.startswith("llm:") and "Paid Social" in r.texto and r.advertencias == []
    kw = cliente.llamadas[0]
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["thinking"] == {"type": "adaptive"} and "tools" not in kw
    assert "<hechos>" in kw["messages"][0]["content"]


def test_cifra_inventada_genera_advertencia():
    r = Interprete(cliente=ClienteFalso(texto("Paid Social aporta 73.4 % de las ventas."))).interpretar(Vista(), "resumen")
    assert any("73.4" in a for a in r.advertencias)


def test_pregunta_con_herramienta():
    cliente = ClienteFalso(llamada("detalle_canal", {"canal": "Paid Social"}), texto("Paid Social es el canal #1."))
    r = Interprete(cliente=cliente).preguntar(Vista(), "¿Cómo está Paid Social?")
    assert r.herramientas == ["detalle_canal"] and "Paid Social" in r.texto
    segunda = cliente.llamadas[1]["messages"]
    resultados = segunda[-1]["content"]
    assert segunda[-1]["role"] == "user" and resultados[0]["type"] == "tool_result"
    assert json.loads(resultados[0]["content"])["canal"] == "Paid Social"
    assert "tools" in cliente.llamadas[0]


def test_error_del_api_degrada_a_plantilla():
    r = Interprete(cliente=ClienteFalso(RuntimeError("sin red"))).interpretar(Vista(), "resumen")
    assert r.generado_con == "plantilla" and "RuntimeError" in r.advertencias[0] and r.texto


def test_rechazo_degrada_a_plantilla():
    r = Interprete(cliente=ClienteFalso(texto("", stop="refusal"))).interpretar(Vista(), "resumen")
    assert r.generado_con == "plantilla" and r.texto


# ----------------------------------------------------------------- registro de uso (RQ-25)
def test_cada_interpretacion_registra_uso(tmp_path):
    ruta = tmp_path / "uso.csv"
    cliente = ClienteFalso(texto("Paid Social lidera."))
    Interprete(cliente=cliente, ruta_uso=ruta).interpretar(Vista(), "resumen")
    uso = leer_uso(ruta)
    assert len(uso) == 1
    assert uso.iloc[0].tipo == "resumen" and uso.iloc[0].tokens_entrada == 100 and uso.iloc[0].tokens_salida == 50
    assert uso.iloc[0].generado_con.startswith("llm:")


def test_uso_se_acumula_entre_llamadas(tmp_path):
    ruta = tmp_path / "uso.csv"
    Interprete(cliente=ClienteFalso(texto("A.")), ruta_uso=ruta).interpretar(Vista(), "resumen")
    Interprete(cliente=ClienteFalso(texto("B.")), ruta_uso=ruta).interpretar(Vista(), "siguientes_pasos")
    assert len(leer_uso(ruta)) == 2


# ----------------------------------------------------------------- herramientas
def test_herramienta_rechaza_entradas_invalidas():
    assert "error" in json.loads(ejecutar("detalle_canal", {"canal": "'; DROP TABLE x; --"}, Vista()))
    assert "error" in json.loads(ejecutar("no_existe", {}, Vista()))


def test_herramientas_devuelven_json():
    for nombre, entrada in (("detalle_canal", {"canal": "Email"}),
                            ("comparar_segmentos", {"canal": "Paid Social", "dimension": "Dispositivo"}),
                            ("sensibilidad_ventana", {}), ("prueba_incrementalidad", {"canal": "Paid Social"})):
        assert "error" not in json.loads(ejecutar(nombre, entrada, Vista())), nombre


def test_lector_rechaza_tablas_fuera_de_la_lista():
    with pytest.raises(ValueError):
        Lector().consulta("orders")
