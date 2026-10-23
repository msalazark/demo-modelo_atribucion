"""
Métricas de decisión por canal: alcance, asistencia y conversión.

Complementa a run_demo.py (que calcula la atribución Markov/Shapley) con las tres
preguntas que se usan para repartir presupuesto:

  1. Alcance      ¿qué canal trae más gente y más gente NUEVA al embudo?
  2. Asistencia   ¿qué canal ayuda a mover al usuario hacia la compra sin cerrarla?
  3. Conversión   ¿qué canal cierra mejor la venta cuando entra en juego?

Lógica pura (DataFrames in / DataFrames out). La orquesta run_demo.py, que persiste
los resultados en DuckDB; el dashboard solo lee esas tablas.
"""
from __future__ import annotations

from collections import Counter

import pandas as pd


def cierre_ultimo_no_directo(ruta: list[str]) -> str:
    """Mismo criterio que atribucion.ultimo_no_directo: último canal distinto de Direct."""
    no_directos = [c for c in ruta if c != "Direct"]
    return no_directos[-1] if no_directos else "Direct"


def _canal_cierre(ruta: list[str], variante_cierre: str) -> str:
    return cierre_ultimo_no_directo(ruta) if variante_cierre == "ultimo_no_directo" else ruta[-1]


def roles_por_canal(rutas: pd.DataFrame, variante_cierre: str = "ultima_sesion") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Roles canónicos por canal (sección 1 de docs/RQ_mejoras.md, RQ-11):

      Abre   la primera sesión de una ruta convertida con 2+ sesiones.
      Asiste aparece en una posición que no es la primera ni la última (una vez por pedido,
             aunque el canal se repita en varias posiciones medias).
      Cierra la última sesión (o, con variante_cierre='ultimo_no_directo', el último canal
             distinto de Direct).
      Único  la ruta convertida tiene una sola sesión; no suma a abre ni cierra.

    Devuelve (roles por canal, pares asistente→cierre) con los porcentajes sobre las
    apariciones del canal y las asistencias por cada cierre propio.
    """
    abre, asiste, cierra, unico = Counter(), Counter(), Counter(), Counter()
    apariciones, ingresos_cierre, pares = Counter(), Counter(), Counter()
    conv = rutas[rutas.convirtio]
    for ruta, ingreso in conv[["ruta", "revenue_pen"]].itertuples(index=False):
        for c in set(ruta):
            apariciones[c] += 1
        if len(ruta) == 1:
            unico[ruta[0]] += 1
            continue
        canal_abre, canal_cierra = ruta[0], _canal_cierre(ruta, variante_cierre)
        abre[canal_abre] += 1
        cierra[canal_cierra] += 1
        ingresos_cierre[canal_cierra] += ingreso
        for c in set(ruta[1:-1]):  # posiciones medias: ni abre ni cierra, aunque se repitan
            asiste[c] += 1
            pares[(c, canal_cierra)] += 1

    canales = sorted(apariciones)
    filas = []
    for c in canales:
        n = apariciones[c]
        filas.append({
            "canal": c,
            "ventas_abre": abre[c], "ventas_asiste": asiste[c], "ventas_cierra": cierra[c], "ventas_unico": unico[c],
            "abre_pct": round(abre[c] / n * 100, 1), "asiste_pct": round(asiste[c] / n * 100, 1),
            "cierra_pct": round(cierra[c] / n * 100, 1), "unico_pct": round(unico[c] / n * 100, 1),
            "asistencias_por_cierre": round(asiste[c] / cierra[c], 2) if cierra[c] else None,
            "ingresos_cierre": round(ingresos_cierre[c], 0),
        })
    roles = pd.DataFrame(filas).set_index("canal")
    pares_df = pd.DataFrame(
        [(a, b, n) for (a, b), n in pares.items()], columns=["asistente", "cierre", "conversiones"]
    )
    return roles, pares_df


def calcular(
    rutas: pd.DataFrame, sesiones: pd.DataFrame, variante_cierre: str = "ultima_sesion",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (métricas por canal, pares asistente→cierre): alcance y conversión propios más
    los roles canónicos de `roles_por_canal` (RQ-11)."""
    canales = sorted({c for r in rutas.ruta for c in r})
    total_usuarios = rutas.user_pseudo_id.nunique()
    conv = rutas[rutas.convirtio]
    roles, pares_df = roles_por_canal(rutas, variante_cierre)

    # Alcance: usuarios distintos y sesiones por canal; "nuevos" = canal de la primera sesión del usuario
    usuarios_alcanzados = Counter()
    primer_contacto_usuarios = Counter()
    por_usuario = rutas.groupby("user_pseudo_id").ruta.first()
    # un usuario con varios pedidos aparece en varias filas; su ruta sirve igual para alcance
    for ruta in por_usuario:
        for c in set(ruta):
            usuarios_alcanzados[c] += 1
        primer_contacto_usuarios[ruta[0]] += 1

    # Conversión: usuarios que pasaron por el canal y compraron
    usuarios_convertidos = Counter()
    for ruta in conv.groupby("user_pseudo_id").ruta.first():
        for c in set(ruta):
            usuarios_convertidos[c] += 1

    ses = sesiones[~sesiones.es_pasarela].groupby("canal").size()

    filas = []
    for c in canales:
        participa = usuarios_alcanzados[c]
        cierres_c = int(roles.ventas_cierra.get(c, 0))
        filas.append({
            "canal": c,
            "sesiones": int(ses.get(c, 0)),
            "usuarios_alcanzados": participa,
            "alcance_pct": round(participa / total_usuarios * 100, 1),
            "usuarios_nuevos": primer_contacto_usuarios[c],
            "usuarios_convertidos": usuarios_convertidos[c],
            "tasa_conv_usuario_pct": round(usuarios_convertidos[c] / participa * 100, 2) if participa else None,
            "tasa_cierre_sesion_pct": round(cierres_c / ses.get(c, 1) * 100, 2),
        })
    metricas = pd.DataFrame(filas).set_index("canal").join(roles, how="left")
    cols_conteo = ["ventas_abre", "ventas_asiste", "ventas_cierra", "ventas_unico",
                   "abre_pct", "asiste_pct", "cierra_pct", "unico_pct", "ingresos_cierre"]
    metricas[cols_conteo] = metricas[cols_conteo].fillna(0.0)  # canal sin apariciones en rutas convertidas
    return metricas, pares_df


def rutas_top(rutas: pd.DataFrame, n: int = 15) -> pd.DataFrame:
    conv = rutas[rutas.convirtio].copy()
    conv["ruta_txt"] = conv.ruta.apply(lambda r: " → ".join(r))
    g = conv.groupby("ruta_txt").agg(pedidos=("order_id", "count"), ingresos=("revenue_pen", "sum"))
    return g.sort_values("pedidos", ascending=False).head(n).reset_index()


# ---------------------------------------------------------------- señales para gerencia
UMBRAL_ESCALAR = 1.2   # ROAS del canal / ROAS promedio de los pagados
UMBRAL_REVISAR = 0.8
RATIO_ASISTIDOR = 2.0  # asistencias por cierre propio
BRECHA_MODELOS_PP = 3.0
SOBRE_INDICE_PP = 3.0  # en un segmento: diferencia de cuota frente al total


def _confianza(ancho_ci: float, pedidos: int, alta_ci: float, media_ci: float, alta_pedidos: int, media_pedidos: int) -> str:
    """Con intervalo bootstrap, por su ancho; sin él, por el volumen de pedidos del corte."""
    if pd.notna(ancho_ci):
        return "alta" if ancho_ci <= alta_ci else "media" if ancho_ci <= media_ci else "baja"
    return "alta" if pedidos >= alta_pedidos else "media" if pedidos >= media_pedidos else "baja"


def asignar_senal(
    m: pd.DataFrame,
    pedidos: int,
    es_segmento: bool,
    umbral_escalar: float = UMBRAL_ESCALAR,
    umbral_revisar: float = UMBRAL_REVISAR,
    ratio_asistidor: float = RATIO_ASISTIDOR,
    brecha_modelos_pp: float = BRECHA_MODELOS_PP,
    sobre_indice_pp: float = SOBRE_INDICE_PP,
    confianza_alta_ci: float = 2.0,
    confianza_media_ci: float = 4.0,
    confianza_alta_pedidos: int = 3000,
    confianza_media_pedidos: int = 1000,
    minimo_conversiones_senal: int = 1000,
) -> pd.DataFrame:
    """
    Agrega a la tabla por canal una señal accionable para gerencia, para UN modelo de atribución.

    Columnas requeridas en `m` (índice = canal):
      cuota_pct, cuota_ultimo_no_directo_pct, roas, cpa, costo, ancho_ci (puede ser NaN),
      ratio_asistencia, tasa_conv_usuario_pct y, si es_segmento, cuota_total_pct.
    Devuelve las mismas filas con: confianza, brecha_vs_ultimo_clic_pp, senal, motivo.

    Los umbrales tienen por defecto los valores históricos de la demo; `run_demo.py` los pasa
    explícitos desde `ConfigCliente` (RQ-01).

    RQ-14: con menos de `minimo_conversiones_senal` conversiones en el corte, no se publica una
    señal — todos los canales quedan en "Evidencia insuficiente" en vez de Escalar/Revisar/etc.,
    sea la vista total o un segmento.

    OJO: el ROAS es promedio, no marginal. "Escalar" es una hipótesis a validar con una prueba
    de incrementalidad antes de mover presupuesto, no una orden. Dentro de un segmento no hay
    costo por canal, así que la señal solo compara el peso del canal frente al total.
    """
    m = m.copy()
    pagados = m[m.costo.notna() & m.roas.notna()]
    roas_prom = (pagados.roas * pagados.costo).sum() / pagados.costo.sum() if len(pagados) else float("nan")
    mediana_conv = m.drop(index="Direct", errors="ignore").tasa_conv_usuario_pct.median()

    m["confianza"] = [_confianza(a, pedidos, confianza_alta_ci, confianza_media_ci, confianza_alta_pedidos,
                                  confianza_media_pedidos) for a in m.ancho_ci]
    m["brecha_vs_ultimo_clic_pp"] = (m.cuota_pct - m.cuota_ultimo_no_directo_pct).round(1)

    senales, motivos = [], []
    for canal, r in m.iterrows():
        if pedidos < minimo_conversiones_senal:  # RQ-14: robustez por volumen
            senales.append("Evidencia insuficiente")
            motivos.append(f"Menos de {minimo_conversiones_senal:,} conversiones en el corte: "
                           "no hay evidencia suficiente para una señal confiable.")
            continue
        extra = ""
        if canal == "Direct":
            pass  # su crédito en último clic no directo no es comparable
        elif r.brecha_vs_ultimo_clic_pp >= brecha_modelos_pp:
            extra = f" El último clic le quita {r.brecha_vs_ultimo_clic_pp:.1f} pp de crédito."
        elif r.brecha_vs_ultimo_clic_pp <= -brecha_modelos_pp:
            extra = f" El último clic le regala {abs(r.brecha_vs_ultimo_clic_pp):.1f} pp de crédito."

        if canal == "Direct":
            senal, motivo = "No es palanca", "Es el regreso de usuarios que ya conocían la marca; no se invierte en él."
        elif es_segmento:
            dif = r.cuota_pct - r.cuota_total_pct
            base = f"Aporta {r.cuota_pct:.1f} % en este segmento frente a {r.cuota_total_pct:.1f} % del total."
            if dif >= sobre_indice_pp:
                senal, motivo = "Sobre-índice", base + " Pesa más aquí que en el total."
            elif dif <= -sobre_indice_pp:
                senal, motivo = "Sub-índice", base + " Pesa menos aquí que en el total."
            else:
                senal, motivo = "Igual al total", base
            extra = ""
        elif pd.notna(r.costo) and pd.notna(r.roas):
            rel = r.roas / roas_prom
            base = f"ROAS {r.roas:.1f} frente a {roas_prom:.1f} del promedio pagado; CPA S/ {r.cpa:.0f}."
            senal = "Escalar (validar)" if rel >= umbral_escalar else "Revisar" if rel <= umbral_revisar else "Mantener"
            motivo = base
            if r.ratio_asistencia >= ratio_asistidor:
                motivo += f" Además asiste {r.ratio_asistencia:.1f} ventas por cada cierre propio."
        elif r.ratio_asistencia >= ratio_asistidor:
            senal = "Proteger"
            motivo = f"Asiste {r.ratio_asistencia:.1f} ventas por cada cierre propio; no recortar mirando solo el último clic."
        elif r.tasa_conv_usuario_pct >= 1.2 * mediana_conv:
            senal = "Aprovechar"
            motivo = (f"Convierte {r.tasa_conv_usuario_pct:.1f} % de sus usuarios; es canal de cierre, "
                      "no de alcance.")
        else:
            senal = "Mantener"
            motivo = f"Aporta {r.cuota_pct:.1f} % de las ventas sin una señal clara de cambio."
        senales.append(senal)
        motivos.append(motivo + extra)
    m["senal"], m["motivo"] = senales, motivos
    m.loc[m.senal == "Evidencia insuficiente", "confianza"] = "baja"  # consistente con la señal
    return m[["confianza", "brecha_vs_ultimo_clic_pp", "senal", "motivo"]]
