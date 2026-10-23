"""Pruebas de interprete/uso.py (RQ-25): registro de tokens y costo por consulta."""
from interprete.uso import costo_usd, leer, registrar


def test_costo_usd_modelo_conocido():
    c = costo_usd("claude-sonnet-5-5", tokens_entrada=1_000_000, tokens_salida=1_000_000)
    assert c == 3.0 + 15.0


def test_costo_usd_modelo_desconocido_no_falla():
    assert costo_usd("modelo-que-no-existe", 100, 50) is None


def test_leer_sin_archivo_devuelve_vacio(tmp_path):
    out = leer(tmp_path / "no_existe.csv")
    assert out.empty


def test_registrar_crea_y_agrega_filas(tmp_path):
    ruta = tmp_path / "uso_interprete.csv"
    registrar(ruta, "clave1", "resumen", "claude-sonnet-5-5", "llm:claude-sonnet-5-5", 100, 50, 1.2, ["detalle_canal"])
    registrar(ruta, "clave2", "pregunta", "claude-sonnet-5-5", "plantilla", 0, 0, 0.0, [])
    out = leer(ruta)
    assert len(out) == 2
    assert out.iloc[0].vista == "clave1" and out.iloc[0].herramientas == "detalle_canal"
    assert out.iloc[0].costo_usd == costo_usd("claude-sonnet-5-5", 100, 50)
    assert out.iloc[1].costo_usd == 0.0
