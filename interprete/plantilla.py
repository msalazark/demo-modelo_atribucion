"""
Lectura determinista de los hechos (sin LLM): se usa como respaldo cuando no hay API key y como
punto de partida visible en cualquier vista. Mismo contenido que pediría el intérprete, sin
lenguaje libre: cada frase sale de una regla sobre las cifras.
"""
from __future__ import annotations

from collections import defaultdict


def _pct(x) -> str:
    return f"{x:.1f} %"


def _por_senal(h: dict) -> dict[str, list[dict]]:
    grupos: dict[str, list[dict]] = defaultdict(list)
    for c in h["canales"]:
        grupos[c["senal"]].append(c)
    return grupos


def resumen(h: dict) -> str:
    v = h["vista"]
    canales = [c for c in h["canales"] if c["es_palanca_de_inversion"]]
    if not canales:
        return "No hay canales de inversión en la selección actual."
    top = max(canales, key=lambda c: c["cuota_pct"])
    mj = h["mejores"]
    L = [f"**{top['canal']} concentra {_pct(top['cuota_pct'])} de las ventas atribuidas** "
         f"({v['modelo']}, {v['segmento']}, ventana de {v['ventana_atribucion_dias']} días)."]

    if mj["alcance"] and mj["asistidor_por_volumen"] and mj["conversion_por_usuario"]:
        a, s, c = mj["alcance"], mj["asistidor_por_volumen"], mj["conversion_por_usuario"]
        roles = f"- **Roles:** llena el embudo {a['canal']} ({a['valor']:,.0f} usuarios alcanzados); " \
                f"empuja hacia la compra {s['canal']} ({s['valor']:,.0f} conversiones asistidas); " \
                f"cierra mejor {c['canal']} ({c['valor']:.1f} % de sus usuarios compran)."
        distintos = len({a["canal"], s["canal"], c["canal"]}) > 1
        L.append(roles + (" Cada canal cumple un rol distinto." if distintos else ""))

    grupos = _por_senal(h)
    for senal, texto in (("Escalar (validar)", "Candidato a escalar, a validar con una prueba"),
                         ("Revisar", "A revisar por retorno bajo"), ("Proteger", "No recortar")):
        if grupos.get(senal):
            L.append(f"- **{texto}:** " + "; ".join(
                f"{c['canal']}" + (f" (ROAS {c['roas']:.1f}, CPA S/ {c['cpa_soles']:.0f})" if c["roas"] else "")
                for c in grupos[senal]) + ".")
    if grupos.get("Sobre-índice"):
        L.append("- **Pesan más en este segmento que en el total:** " + ", ".join(
            c["canal"] for c in grupos["Sobre-índice"]) + ".")

    cautelas = []
    if v["en_segmento_no_hay_costo_por_canal"]:
        cautelas.append("dentro de un segmento no hay costo por canal, así que no hay ROAS ni señales de inversión")
    n1 = {r["canal"] for r in h["canal_numero_1_segun_ventana"]}
    if len(n1) > 1:
        cautelas.append("el canal número 1 cambia según la ventana de atribución (" + ", ".join(sorted(n1)) + ")")
    bajas = [c["canal"] for c in canales if c["confianza"] == "baja"]
    if bajas:
        cautelas.append("confianza baja en " + ", ".join(bajas))
    cambio = [e["canal"] for e in h["estado_del_modelo"] if e["estado"] == "cambió"]
    if cambio and not v["en_segmento_no_hay_costo_por_canal"]:
        cautelas.append("la cuota actual se movió fuera de su intervalo respecto del mes anterior en " + ", ".join(cambio))
    if cautelas:
        L.append("- **Cautela:** " + "; ".join(cautelas) + ".")
    return "\n".join(L)


def siguientes_pasos(h: dict) -> str:
    pasos: list[str] = []
    p = h["prueba_de_incrementalidad"]
    if p:
        cfg = p["mejor_configuracion"]
        if p["alcanza_la_referencia"]:
            pasos.append(
                f"**Validar {p['canal_a_validar']} con una prueba de incrementalidad.** Con {cfg['semanas']} semanas y "
                f"{cfg['control_pct']} % de control se detectan efectos desde {cfg['emd_relativo_pct']:.0f} % de sus "
                f"conversiones; con 10 % de control y la máxima duración solo desde {p['emd_con_control_10_pct_y_maxima_duracion_pct']:.0f} %. "
                "Una prueba geográfica evita dejar sin anuncios a la mitad de la audiencia.")
        else:
            pasos.append(
                f"**Validar {p['canal_a_validar']}:** con el tráfico actual ninguna prueba por usuario detecta efectos "
                f"menores a {p['referencia_emd_pct']} %; la mejor llega a {cfg['emd_relativo_pct']:.0f} %. Conviene una prueba geográfica.")
    t = h["tiempo_hasta_la_compra"]
    n1 = [r["canal"] for r in h["canal_numero_1_segun_ventana"]]
    sens = ("el canal número 1 cambia según la ventana (" + ", ".join(sorted(set(n1))) + ")" if len(set(n1)) > 1
            else "el canal número 1 no cambia entre ventanas")
    pasos.append(
        f"**Confirmar la ventana de atribución.** La mitad de las compras ocurre en {t['mediana_dias']:.0f} días y el 90 % en "
        f"{t['percentil_90_dias']:.0f}; el último tramo aún concentra {t['pct_de_compras_en_el_ultimo_tramo']:.1f} % de las compras. "
        f"Hoy {sens}.")
    cambio = [e["canal"] for e in h["estado_del_modelo"] if e["estado"] == "cambió"]
    alertas = [d["regla"] for d in h["disparadores_de_reajuste"] if d["estado"] == "alerta"]
    estado = ("Hay alertas de reajuste (" + ", ".join(alertas) + ")." if alertas else "No hay alertas de reajuste.")
    pasos.append(
        "**Mantener el modelo al día.** Reajustar cada mes y antes si cambia la inversión, el mix o el tracking. "
        + estado + (f" Cuota fuera de intervalo en: {', '.join(cambio)}." if cambio else ""))
    pasos.append("**Completar los datos.** Costos de Email, orgánico y referral; client_id en todos los pedidos "
                 f"({h['ventana_de_analisis']['pedidos_con_ruta']:,} de {h['ventana_de_analisis']['pedidos_backend']:,} pedidos "
                 "tienen ruta); impresiones para Display y Paid Social; margen por producto.")
    pasos.append("**Llevarlo a producción.** Cargar las tablas mart_* a BigQuery y publicar el tablero en Looker Studio.")
    return "\n".join(f"{i}. {p}" for i, p in enumerate(pasos, 1))
