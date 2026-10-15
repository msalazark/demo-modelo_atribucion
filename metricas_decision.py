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


def calcular(rutas: pd.DataFrame, sesiones: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (métricas por canal, pares asistente→cierre)."""
    canales = sorted({c for r in rutas.ruta for c in r})
    total_usuarios = rutas.user_pseudo_id.nunique()
    conv = rutas[rutas.convirtio]

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

    # Roles dentro de cada pedido convertido
    cierres, asistidas, introducidas, solo_canal = Counter(), Counter(), Counter(), Counter()
    ingresos_cierre = Counter()
    pares = Counter()
    for ruta, ingreso in conv[["ruta", "revenue_pen"]].itertuples(index=False):
        cierre = cierre_ultimo_no_directo(ruta)
        cierres[cierre] += 1
        ingresos_cierre[cierre] += ingreso
        introducidas[ruta[0]] += 1
        for c in set(ruta) - {cierre}:
            asistidas[c] += 1
            pares[(c, cierre)] += 1
        if len(set(ruta)) == 1:
            solo_canal[ruta[0]] += 1

    ses = sesiones[~sesiones.es_pasarela].groupby("canal").size()

    filas = []
    for c in canales:
        participa = usuarios_alcanzados[c]
        filas.append({
            "canal": c,
            "sesiones": int(ses.get(c, 0)),
            "usuarios_alcanzados": participa,
            "alcance_pct": round(participa / total_usuarios * 100, 1),
            "usuarios_nuevos": primer_contacto_usuarios[c],
            "conv_introducidas": introducidas[c],
            "conv_asistidas": asistidas[c],
            "conv_cerradas": cierres[c],
            "ratio_asistencia": round(asistidas[c] / cierres[c], 2) if cierres[c] else None,
            "usuarios_convertidos": usuarios_convertidos[c],
            "tasa_conv_usuario_pct": round(usuarios_convertidos[c] / participa * 100, 2) if participa else None,
            "tasa_cierre_sesion_pct": round(cierres[c] / ses.get(c, 1) * 100, 2),
            "ingresos_cierre": round(ingresos_cierre[c], 0),
        })
    metricas = pd.DataFrame(filas).set_index("canal")
    pares_df = pd.DataFrame(
        [(a, b, n) for (a, b), n in pares.items()], columns=["asistente", "cierre", "conversiones"]
    )
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


def asignar_senal(m: pd.DataFrame) -> pd.DataFrame:
    """
    Agrega a la tabla por canal una señal accionable para gerencia:
      confianza  alta/media/baja según el ancho del intervalo del 90 % de la cuota Shapley
      brecha_vs_ultimo_clic_pp  cuánto crédito gana o pierde el canal frente al último clic
      senal / motivo  qué hacer y por qué

    OJO: el ROAS es promedio, no marginal. La señal "Escalar" es una hipótesis a validar
    con una prueba de incrementalidad antes de mover presupuesto, no una orden.
    """
    m = m.copy()
    pagados = m.dropna(subset=["costo"])
    roas_prom = pagados.ingresos_shapley.sum() / pagados.costo.sum() if len(pagados) else float("nan")
    mediana_conv = m.drop(index="Direct", errors="ignore").tasa_conv_usuario_pct.median()

    ancho = m.shapley_pct_p95 - m.shapley_pct_p05
    m["confianza"] = pd.cut(ancho, [-1, 2.0, 4.0, 1e9], labels=["alta", "media", "baja"]).astype(str)
    m["brecha_vs_ultimo_clic_pp"] = (m.shapley_pct - m.ultimo_no_directo_pct).round(1)

    senales, motivos = [], []
    for canal, r in m.iterrows():
        extra = ""
        if canal == "Direct":
            pass  # su crédito en último clic no directo no es comparable
        elif r.brecha_vs_ultimo_clic_pp >= BRECHA_MODELOS_PP:
            extra = f" El último clic le quita {r.brecha_vs_ultimo_clic_pp:.1f} pp de crédito."
        elif r.brecha_vs_ultimo_clic_pp <= -BRECHA_MODELOS_PP:
            extra = f" El último clic le regala {abs(r.brecha_vs_ultimo_clic_pp):.1f} pp de crédito."

        if canal == "Direct":
            senal, motivo = "No es palanca", "Es el regreso de usuarios que ya conocían la marca; no se invierte en él."
        elif pd.notna(r.costo):
            rel = r.roas_shapley / roas_prom
            base = f"ROAS {r.roas_shapley:.1f} frente a {roas_prom:.1f} del promedio pagado; CPA S/ {r.cpa_shapley:.0f}."
            if rel >= UMBRAL_ESCALAR:
                senal, motivo = "Escalar (validar)", base
            elif rel <= UMBRAL_REVISAR:
                senal, motivo = "Revisar", base
            else:
                senal, motivo = "Mantener", base
            if r.ratio_asistencia >= RATIO_ASISTIDOR:
                motivo += f" Además asiste {r.ratio_asistencia:.1f} ventas por cada cierre propio."
        elif r.ratio_asistencia >= RATIO_ASISTIDOR:
            senal = "Proteger"
            motivo = f"Asiste {r.ratio_asistencia:.1f} ventas por cada cierre propio; no recortar mirando solo el último clic."
        elif r.tasa_conv_usuario_pct >= 1.2 * mediana_conv:
            senal = "Aprovechar"
            motivo = (f"Convierte {r.tasa_conv_usuario_pct:.1f} % de sus usuarios; es canal de cierre, "
                      "no de alcance.")
        else:
            senal = "Mantener"
            motivo = f"Aporta {r.shapley_pct:.1f} % de las ventas sin una señal clara de cambio."
        senales.append(senal)
        motivos.append(motivo + extra)
    m["senal"], m["motivo"] = senales, motivos
    return m
