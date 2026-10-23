"""Banco de 30 preguntas de negocio para evaluar al intérprete (RQ-25 de docs/RQ_mejoras.md).

Cada pregunta define qué cifras debe citar la respuesta y qué cautelas de texto debe incluir (o
evitar). Las cifras esperadas se calculan en vivo desde `construir_hechos()` -- nunca a mano --
para que el banco no quede desactualizado si cambian los datos sintéticos o la demo se vuelve a
correr. `test_evals.py` ejecuta esto contra la API real (marcado `evals`; no corre en CI por
defecto porque gasta crédito).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from interprete.datos import Vista


@dataclass
class Pregunta:
    id: str
    texto: str
    vista: Vista = field(default_factory=Vista)
    cifras_esperadas: Callable[[dict], list[float]] = field(default=lambda h: [])
    debe_contener: list[str] = field(default_factory=list)  # subcadenas (minúsculas) esperadas en la respuesta
    no_debe_contener: list[str] = field(default_factory=list)


def _canal(h: dict, nombre: str) -> dict | None:
    return next((c for c in h["canales"] if c["canal"] == nombre), None)


def _cuota(nombre: str) -> Callable[[dict], list[float]]:
    def f(h):
        c = _canal(h, nombre)
        return [c["cuota_pct"]] if c else []
    return f


def _roas(nombre: str) -> Callable[[dict], list[float]]:
    def f(h):
        c = _canal(h, nombre)
        return [c["roas"]] if c and c["roas"] is not None else []
    return f


def _alcance(nombre: str) -> Callable[[dict], list[float]]:
    def f(h):
        c = _canal(h, nombre)
        return [float(c["usuarios_alcanzados"])] if c else []
    return f


VISTA_MOBILE = Vista(dim="Dispositivo", segmento="mobile")
VISTA_DESKTOP = Vista(dim="Dispositivo", segmento="desktop")

BANCO: list[Pregunta] = [
    # ---------------------------------------------------------- A. cifra directa
    Pregunta("cuota_paid_social", "¿Qué porcentaje de las ventas atribuye el modelo a Paid Social?",
             cifras_esperadas=_cuota("Paid Social")),
    Pregunta("cuota_paid_search", "¿Cuál es la cuota de ventas de Paid Search con el modelo elegido?",
             cifras_esperadas=_cuota("Paid Search")),
    Pregunta("cuota_email", "¿Qué cuota de ventas tiene Email?", cifras_esperadas=_cuota("Email")),
    Pregunta("roas_paid_social", "¿Cuál es el ROAS de Paid Social?", cifras_esperadas=_roas("Paid Social"),
             debe_contener=["roas"]),
    Pregunta("roas_display", "¿Cuál es el ROAS de Display?", cifras_esperadas=_roas("Display")),
    Pregunta("alcance_organic", "¿A cuántos usuarios alcanza Organic Search?",
             cifras_esperadas=_alcance("Organic Search")),
    Pregunta("senal_paid_social", "¿Qué señal tiene Paid Social: escalar, revisar, mantener o proteger?",
             debe_contener=["escalar"]),
    Pregunta("mediana_dias_compra", "¿Cuántos días tarda en mediana un usuario en comprar desde su primer contacto?",
             cifras_esperadas=lambda h: [h["tiempo_hasta_la_compra"]["mediana_dias"]]),

    # ---------------------------------------------------------- B. comparación entre canales
    Pregunta("mejor_alcance", "¿Qué canal tiene el mayor alcance de usuarios?",
             debe_contener=[], cifras_esperadas=lambda h: [h["mejores"]["alcance"]["valor"]]),
    Pregunta("mejor_asistidor", "¿Qué canal asiste más ventas en volumen?",
             cifras_esperadas=lambda h: [h["mejores"]["asistidor_por_volumen"]["valor"]]),
    Pregunta("mejor_conversion", "¿Qué canal convierte mejor por usuario?",
             cifras_esperadas=lambda h: [h["mejores"]["conversion_por_usuario"]["valor"]]),
    Pregunta("canal_numero_1", "¿Cuál es el canal número 1 en ventas atribuidas con la ventana vigente?",
             cifras_esperadas=lambda h: []),

    # ---------------------------------------------------------- C. segmentos (usa la herramienta comparar_segmentos)
    Pregunta("email_mobile_vs_desktop", "¿Cómo le va a Email en mobile frente a desktop? Usa la herramienta si hace falta.",
             debe_contener=["mobile", "desktop"]),
    Pregunta("paid_social_region", "Compara Paid Social entre Lima y Provincias.",
             debe_contener=["lima", "provincias"]),
    Pregunta("sin_roas_en_segmento", "Dentro del segmento mobile de Dispositivo, ¿cuál es el ROAS de Paid Social?",
             vista=VISTA_MOBILE, debe_contener=["no hay"], no_debe_contener=["roas de"]),
    Pregunta("conversion_tipo_cliente", "¿Convierten distinto los clientes nuevos y recurrentes?",
             debe_contener=["nuevo", "recurrente"]),

    # ---------------------------------------------------------- D. sensibilidad a la ventana (tool)
    Pregunta("sensibilidad_ventana", "¿El canal número 1 cambia si la ventana de atribución es de 7 o de 90 días?",
             debe_contener=["ventana"]),
    Pregunta("ventana_vigente", "¿Cuántos días dura la ventana de atribución vigente?",
             cifras_esperadas=lambda h: [float(h["vista"]["ventana_atribucion_dias"])]),

    # ---------------------------------------------------------- E. incrementalidad y validación con experimentos
    Pregunta("prueba_incrementalidad", "¿Cuántas semanas necesito para validar Paid Social con un 20 % de audiencia en control?",
             debe_contener=["semana"]),
    Pregunta("validacion_paid_social", "¿El experimento de Paid Social confirmó lo que le atribuye el modelo?",
             debe_contener=["atribu"]),
    Pregunta("validacion_paid_search", "¿Qué dice el experimento de Paid Search sobre el crédito que le da el modelo?",
             debe_contener=["atribu", "medi"]),
    Pregunta("canal_sin_experimento", "¿Hay algún experimento corrido para Display?",
             debe_contener=["no"]),

    # ---------------------------------------------------------- F. cautelas de negocio (siempre deben aparecer)
    Pregunta("causalidad_escalar", "¿Debo mover presupuesto a Paid Social ahora mismo porque la señal dice escalar?",
             debe_contener=["prueba de incrementalidad"]),
    Pregunta("roas_no_marginal", "Si duplico la inversión en Paid Search, ¿se duplican las ventas atribuidas?",
             debe_contener=["promedio"]),
    Pregunta("efecto_real_sintetico", "¿Qué tan cerca está Shapley del efecto real en estos datos?",
             debe_contener=["sintétic"]),
    Pregunta("markov_no_rompe_regla", "Explica qué mide Markov sin usar ningún dato que no esté en la vista actual.",
             no_debe_contener=["73.4", "inventad"]),

    # ---------------------------------------------------------- G. fuera de alcance / datos faltantes
    Pregunta("gasto_competencia", "¿Cuánto gastó la competencia en publicidad este mes?",
             debe_contener=["no"]),
    Pregunta("margen_por_producto", "¿Cuál es el margen por producto de las ventas de Paid Social?",
             debe_contener=["no"]),
    Pregunta("meta_impresiones", "¿Cuántas impresiones tuvo la campaña de Meta este mes?",
             debe_contener=["no"]),
    Pregunta("prediccion_proximo_mes", "¿Cuántas ventas va a tener Paid Social el próximo mes?",
             debe_contener=["no"]),
]

assert len(BANCO) == 30, f"El banco debe tener 30 preguntas, tiene {len(BANCO)}"
