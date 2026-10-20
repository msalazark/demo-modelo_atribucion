"""
Herramientas de solo lectura que el intérprete puede llamar para profundizar más allá de la vista actual.

Ninguna acepta SQL ni nombres de tabla: las entradas son valores de una lista cerrada y las consultas
están parametrizadas. Devuelven JSON con las mismas cifras que ve el dashboard.
"""
from __future__ import annotations

import json

import pandas as pd

from .datos import REGLAS, Lector, Vista

CANALES = ["Paid Social", "Paid Search", "Display", "Organic Search", "Email", "Referral", "Direct"]
DIMENSIONES = ["Dispositivo", "Región", "Tipo de cliente", "Categoría"]

HERRAMIENTAS = [
    {
        "name": "detalle_canal",
        "description": (
            "Devuelve, para un canal y la vista actual, su cuota según cada modelo de atribución (reglas, Markov, "
            "Shapley y efecto real), su señal, ROAS, CPA, alcance, asistencias y conversión. Úsala cuando la pregunta "
            "sea sobre un canal concreto o sobre cuánto cambia según el modelo."),
        "input_schema": {"type": "object", "properties": {"canal": {"type": "string", "enum": CANALES}},
                         "required": ["canal"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "comparar_segmentos",
        "description": (
            "Compara un canal entre los valores de una dimensión de segmento (por ejemplo, dispositivo: mobile, desktop, "
            "tablet), con el modelo y la ventana de la vista actual. Devuelve cuota, señal y confianza por segmento. "
            "Úsala para preguntas del tipo '¿cómo rinde el canal X en mobile frente a desktop?'."),
        "input_schema": {"type": "object", "properties": {"canal": {"type": "string", "enum": CANALES},
                                                         "dimension": {"type": "string", "enum": DIMENSIONES}},
                         "required": ["canal", "dimension"], "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "sensibilidad_ventana",
        "description": (
            "Devuelve la cuota de cada canal con ventanas de atribución de 7, 14, 30, 60 y 90 días, para el segmento y "
            "el modelo de la vista actual, y cuál canal queda número 1 en cada ventana. Úsala para saber si una "
            "conclusión depende de la ventana."),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "strict": True,
    },
    {
        "name": "prueba_incrementalidad",
        "description": (
            "Devuelve el efecto mínimo detectable (EMD, % relativo de las conversiones del canal) de una prueba de "
            "holdout para un canal pagado, según semanas de duración y % de audiencia en control. Úsala para diseñar "
            "o evaluar la viabilidad de una prueba."),
        "input_schema": {"type": "object", "properties": {"canal": {"type": "string",
                                                                    "enum": ["Paid Social", "Paid Search", "Display"]}},
                         "required": ["canal"], "additionalProperties": False},
        "strict": True,
    },
]


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def ejecutar(nombre: str, entrada: dict, v: Vista, lector: Lector | None = None) -> str:
    """Ejecuta una herramienta. Siempre devuelve texto JSON; los errores salen como {"error": ...}."""
    lector = lector or Lector()
    try:
        if nombre == "detalle_canal":
            return _detalle_canal(entrada["canal"], v, lector)
        if nombre == "comparar_segmentos":
            return _comparar_segmentos(entrada["canal"], entrada["dimension"], v, lector)
        if nombre == "sensibilidad_ventana":
            return _sensibilidad(v, lector)
        if nombre == "prueba_incrementalidad":
            return _prueba(entrada["canal"], lector)
        return _json({"error": f"Herramienta desconocida: {nombre}"})
    except (KeyError, ValueError, IndexError) as e:
        return _json({"error": f"No se pudo ejecutar {nombre}: {e}"})


def _detalle_canal(canal: str, v: Vista, lector: Lector) -> str:
    if canal not in CANALES:
        raise ValueError("canal no válido")
    comp = lector.rebanada("mart_modelos__comparativo", v)
    comp = comp[comp.canal == canal]
    m = lector.rebanada("mart_decision__canal", v).set_index("canal").loc[canal]
    s = lector.rebanada("mart_decision__senal", v, modelo=v.modelo).set_index("canal").loc[canal]
    return _json({
        "canal": canal, "vista": v.describir(),
        "cuota_por_modelo_pct": {r.modelo: r.cuota_pct for r in comp.itertuples()},
        "roas_por_modelo": {r.modelo: r.roas for r in comp.itertuples() if pd.notna(r.roas)},
        "senal": s.senal, "motivo": s.motivo, "confianza": s.confianza,
        "usuarios_alcanzados": int(m.usuarios_alcanzados), "usuarios_nuevos": int(m.usuarios_nuevos),
        "conversiones_asistidas": int(m.conv_asistidas), "conversiones_cerradas": int(m.conv_cerradas),
        "conversion_por_usuario_pct": round(float(m.tasa_conv_usuario_pct), 2),
    })


def _comparar_segmentos(canal: str, dimension: str, v: Vista, lector: Lector) -> str:
    if canal not in CANALES or dimension not in DIMENSIONES:
        raise ValueError("canal o dimensión no válidos")
    filas = []
    for seg in lector.opciones().get(dimension, []):
        vs = Vista(ventana_dias=v.ventana_dias, dim=dimension, segmento=seg, modelo=v.modelo)
        c = lector.rebanada("mart_modelos__comparativo", vs, modelo=v.modelo).set_index("canal")
        s = lector.rebanada("mart_decision__senal", vs, modelo=v.modelo).set_index("canal")
        filas.append({"segmento": seg, "cuota_pct": float(c.loc[canal, "cuota_pct"]), "senal": s.loc[canal, "senal"],
                      "confianza": s.loc[canal, "confianza"]})
    total = lector.rebanada("mart_modelos__comparativo", Vista(ventana_dias=v.ventana_dias, modelo=v.modelo),
                            modelo=v.modelo).set_index("canal")
    return _json({"canal": canal, "dimension": dimension, "modelo": v.modelo,
                  "cuota_total_pct": float(total.loc[canal, "cuota_pct"]), "segmentos": filas,
                  "nota": "Dentro de un segmento no hay costo por canal: no hay ROAS."})


def _sensibilidad(v: Vista, lector: Lector) -> str:
    comp = lector.consulta("mart_modelos__comparativo", "WHERE dim = ? AND segmento = ? AND modelo = ?",
                           [v.dim, v.segmento, v.modelo])
    salida = []
    for vent, g in comp.groupby("ventana_dias"):
        g = g.sort_values("ranking")
        salida.append({"ventana_dias": int(vent), "numero_1": g.iloc[0].canal,
                       "cuota_pct": {r.canal: r.cuota_pct for r in g.itertuples()}})
    return _json({"modelo": v.modelo, "segmento": f"{v.dim}: {v.segmento}", "por_ventana": salida})


def _prueba(canal: str, lector: Lector) -> str:
    inc = lector.consulta("mart_siguientes_pasos__prueba_incrementalidad", "WHERE canal = ?", [canal])
    if inc.empty:
        raise ValueError("el canal no es pagado")
    return _json({"canal": canal, "referencia_emd_pct": 30, "configuraciones": [
        {"semanas": int(r.semanas), "control_pct": int(r.holdout_pct), "usuarios_en_control": int(r.usuarios_control),
         "emd_relativo_pct": r.emd_relativo_pct} for r in inc.sort_values(["holdout_pct", "semanas"]).itertuples()]})


__all__ = ["HERRAMIENTAS", "ejecutar", "REGLAS"]
