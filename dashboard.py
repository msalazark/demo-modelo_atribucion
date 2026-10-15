"""
Dashboard de decisión de canales: resumen ejecutivo + alcance, asistencia y conversión.

Solo lee las tablas mart_* de DuckDB que genera run_demo.py; no calcula datos.
Las señales (Escalar / Revisar / Proteger...) y la confianza vienen ya calculadas en
mart_decision__canal.

Uso:
  python run_demo.py
  streamlit run dashboard.py
"""
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

DB_PATH = Path(__file__).parent / "data" / "ecommerce.duckdb"
NO_INVERTIBLES = ["Direct"]  # no es un canal sobre el que se decida presupuesto

# Un color por canal, el mismo en todo el reporte (gráficos, tarjetas y tablas).
CANAL_COLORS = {
    "Paid Social": "#1940E2",
    "Paid Search": "#F76707",
    "Display": "#9C36B5",
    "Organic Search": "#2F9E44",
    "Email": "#D6336C",
    "Referral": "#1098AD",
    "Direct": "#868E96",
}
SENAL_COLORS = {  # fondo de la celda de señal (tono suave) y texto
    "Escalar (validar)": ("#D3F9D8", "#1B5E20"),
    "Aprovechar": ("#D0EBFF", "#0B4F8A"),
    "Proteger": ("#E5DBFF", "#4A2A8C"),
    "Mantener": ("#F1F3F5", "#495057"),
    "Revisar": ("#FFE3E3", "#9B1C1C"),
    "No es palanca": ("#F1F3F5", "#868E96"),
}
CONFIANZA_BADGE = {"alta": "green", "media": "orange", "baja": "red"}

st.set_page_config(page_title="Decisión de canales", page_icon=":material/insights:", layout="wide")


def color_canal(legend: bool = False) -> alt.Color:
    """Escala de color fija: el canal conserva su color aunque se filtren otros."""
    return alt.Color(
        "canal:N",
        scale=alt.Scale(domain=list(CANAL_COLORS), range=list(CANAL_COLORS.values())),
        legend=alt.Legend(title=None) if legend else None,
    )


def canal_con_punto(canal: str) -> str:
    return f'<span style="color:{CANAL_COLORS.get(canal, "#868E96")}">●</span> {canal}'


@st.cache_data(ttl="1h")
def cargar() -> dict[str, pd.DataFrame]:
    """Lee las tablas mart_* de DuckDB. No calcula nada: la lógica vive en run_demo.py.

    La conexión se abre y se cierra en cada carga para no bloquear el archivo
    cuando se vuelve a correr run_demo.py con el dashboard abierto.
    """
    tablas = {
        "metricas": "mart_decision__canal",
        "pares": "mart_decision__pares_asistencia",
        "rutas": "mart_decision__rutas_top",
        "error": "mart_calidad__error_modelo",
        "conciliacion": "mart_calidad__conciliacion",
        "periodos": "mart_periodos",
        "kpi": "mart_kpi__mensual",
    }
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        datos = {k: con.sql(f"SELECT * FROM {t}").df() for k, t in tablas.items()}
    finally:
        con.close()
    return datos


try:
    datos = cargar()
except (duckdb.Error, FileNotFoundError):
    st.error("No encuentro las tablas de resultados. Ejecuta `python run_demo.py` para generarlas.")
    st.stop()

periodos: pd.DataFrame = datos["periodos"].sort_values("periodo")
metricas_hist: pd.DataFrame = datos["metricas"]  # todos los cortes, para la pestaña Evolución
kpi: pd.DataFrame = datos["kpi"].sort_values("periodo").reset_index(drop=True)

# El reporte es mensual acumulado: "2026-03" = desde el primer dato hasta el cierre de marzo.
periodo = st.sidebar.select_slider(
    "Acumulado hasta el cierre de",
    options=list(periodos.periodo),
    value=periodos.periodo.iloc[-1],
    help="Cada periodo recalcula los modelos con todas las rutas desde el inicio de los datos "
    "hasta esa fecha. Más meses acumulados = cuotas más estables.",
)
info_periodo = periodos.set_index("periodo").loc[periodo]


def del_periodo(df: pd.DataFrame) -> pd.DataFrame:
    return df[df.periodo == periodo].drop(columns="periodo")


metricas = del_periodo(datos["metricas"]).set_index("canal")
pares = del_periodo(datos["pares"])
err = del_periodo(datos["error"]).set_index("modelo").error_medio_pp
conc = del_periodo(datos["conciliacion"]).iloc[0]

# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Filtros")
    excluir_directo = st.toggle(
        "Excluir Direct de los rankings",
        value=True,
        help="Direct no es un canal en el que se pueda invertir: es la vuelta del usuario "
        "que ya conocía la marca. Aparece en casi todas las rutas y distorsiona el ranking.",
    )
    canales_sel = st.multiselect("Canales", options=list(metricas.index), default=list(metricas.index))
    st.caption("Datos sintéticos con la estructura del export de GA4 en BigQuery.")

m = metricas.loc[canales_sel]
rank = m.drop(index=NO_INVERTIBLES, errors="ignore") if excluir_directo else m
if rank.empty:
    st.warning("Selecciona al menos un canal invertible.")
    st.stop()

# ================================================================= RESUMEN EJECUTIVO
st.title("¿Dónde pongo el próximo sol de marketing?")
cab, conf = st.columns([4, 1], vertical_alignment="center")
with cab:
    st.caption(
        f":material/date_range: Acumulado del {info_periodo.desde} al {info_periodo.hasta} · "
        f"{info_periodo.pedidos:,} pedidos con ruta de compra"
    )
with conf:
    st.badge(
        f"Evidencia {info_periodo.confianza}",
        icon=":material/verified:",
        color=CONFIANZA_BADGE[info_periodo.confianza],
        help="Baja: menos de 1,000 pedidos acumulados. Media: de 1,000 a 3,000. Alta: más de 3,000.",
    )
if info_periodo.parcial:
    st.warning("El último mes está incompleto: las cifras pueden moverse al cerrar el periodo.")
if info_periodo.confianza == "baja":
    st.warning(
        f"Solo {info_periodo.pedidos:,} pedidos acumulados: las cuotas de Markov y Shapley aún son "
        "inestables. No muevas presupuesto con este corte; mira el intervalo en la pestaña Inversión.",
        icon=":material/info:",
    )

# --- KPIs del mes frente al mes anterior
idx = kpi.index[kpi.periodo == periodo]
if len(idx):
    cur = kpi.loc[idx[0]]
    prev = kpi.loc[idx[0] - 1] if idx[0] > 0 else None

    def delta(col: str) -> str | None:
        if prev is None or not prev[col]:
            return None
        return f"{(cur[col] / prev[col] - 1) * 100:+.1f} %"

    st.caption(f"Resultados del mes de {periodo} frente al mes anterior (el resto del reporte es acumulado).")
    with st.container(horizontal=True):
        st.metric("Pedidos", f"{cur.pedidos:,.0f}", delta("pedidos"), border=True)
        st.metric("Ingresos", f"S/ {cur.ingresos:,.0f}", delta("ingresos"), border=True)
        st.metric("Inversión en medios", f"S/ {cur.inversion_medios:,.0f}", delta("inversion_medios"),
                  delta_color="off", border=True)
        st.metric("Ingresos por sol invertido", f"{cur.mer:.2f}", delta("mer"), border=True,
                  help="Ingresos totales del mes / inversión en medios pagados (MER).")
        st.metric("Costo por pedido", f"S/ {cur.cpa_blended:,.1f}", delta("cpa_blended"),
                  delta_color="inverse", border=True,
                  help="Inversión en medios pagados / pedidos totales (CPA blended).")
        st.metric("Conversión por sesión", f"{cur.conv_sesion_pct:.2f} %", delta("conv_sesion_pct"), border=True)

# --- ganadores por pregunta
c1, c2, c3 = st.columns(3)
with c1:
    metrica_alcance = st.segmented_control(
        "Alcance medido en", ["Usuarios alcanzados", "Usuarios nuevos"], default="Usuarios alcanzados", key="m_alc"
    )
with c2:
    metrica_asist = st.segmented_control(
        "Asistencia medida en", ["Volumen", "Ratio asistencia/cierre"], default="Volumen", key="m_asi"
    )
with c3:
    metrica_conv = st.segmented_control(
        "Conversión medida en", ["Por usuario", "Cierre por sesión"], default="Por usuario", key="m_con"
    )

COL_ALCANCE = {"Usuarios alcanzados": "usuarios_alcanzados", "Usuarios nuevos": "usuarios_nuevos"}
COL_ASIST = {"Volumen": "conv_asistidas", "Ratio asistencia/cierre": "ratio_asistencia"}
COL_CONV = {"Por usuario": "tasa_conv_usuario_pct", "Cierre por sesión": "tasa_cierre_sesion_pct"}

col_a = COL_ALCANCE[metrica_alcance or "Usuarios alcanzados"]
col_s = COL_ASIST[metrica_asist or "Volumen"]
col_c = COL_CONV[metrica_conv or "Por usuario"]


def ganador(col: str) -> tuple[str, float, str, float]:
    s = rank[col].dropna().sort_values(ascending=False)
    seg = (s.index[1], s.iloc[1]) if len(s) > 1 else ("—", 0.0)
    return s.index[0], s.iloc[0], seg[0], seg[1]


def titulo_canal(canal: str) -> None:
    st.html(f'<div style="font-size:1.75rem;font-weight:600;line-height:1.3">{canal_con_punto(canal)}</div>')


g_alc, g_asi, g_con = ganador(col_a), ganador(col_s), ganador(col_c)

k1, k2, k3 = st.columns(3, border=True)
with k1:
    st.caption(":material/groups: MEJOR ALCANCE · llena el embudo")
    titulo_canal(g_alc[0])
    st.write(f"{g_alc[1]:,.0f} usuarios  \nSegundo: {g_alc[2]} ({g_alc[3]:,.0f})")
with k2:
    st.caption(":material/handshake: MEJOR ASISTIDOR · empuja hacia la compra")
    titulo_canal(g_asi[0])
    fmt = "{:,.0f} conversiones asistidas" if col_s == "conv_asistidas" else "{:,.2f} asistencias por cierre"
    st.write(f"{fmt.format(g_asi[1])}  \nSegundo: {g_asi[2]} ({g_asi[3]:,.2f})")
with k3:
    st.caption(":material/target: MEJOR CONVERSIÓN · cierra la venta")
    titulo_canal(g_con[0])
    st.write(f"{g_con[1]:.2f} %  \nSegundo: {g_con[2]} ({g_con[3]:.2f} %)")

st.info(
    "Si los tres ganadores son distintos, no hay un canal “mejor”: cada uno cumple un rol, "
    "y recortar al asistidor suele bajar los cierres semanas después.",
    icon=":material/lightbulb:",
)

# --- qué hacer con cada canal
st.subheader("Qué hacer con cada canal")
izq, der = st.columns([3, 2], gap="large")

with izq:
    acc = m.reset_index()[["canal", "senal", "confianza", "brecha_vs_ultimo_clic_pp", "motivo"]].rename(
        columns={"canal": "Canal", "senal": "Señal", "confianza": "Confianza",
                 "brecha_vs_ultimo_clic_pp": "Vs. último clic", "motivo": "Por qué"}
    )
    orden = {s: i for i, s in enumerate(SENAL_COLORS)}
    acc = acc.sort_values("Señal", key=lambda c: c.map(orden)).reset_index(drop=True)

    def estilo_canal(v: str) -> str:
        return f"color:{CANAL_COLORS.get(v, '#868E96')};font-weight:700"

    def estilo_senal(v: str) -> str:
        bg, fg = SENAL_COLORS.get(v, ("#F1F3F5", "#495057"))
        return f"background-color:{bg};color:{fg};font-weight:600"

    st.dataframe(
        acc.style.map(estilo_canal, subset=["Canal"]).map(estilo_senal, subset=["Señal"]),
        hide_index=True,
        column_config={
            "Vs. último clic": st.column_config.NumberColumn(
                format="%+.1f pp", help="Cuota Shapley menos cuota de último clic no directo."
            ),
            "Por qué": st.column_config.TextColumn(width="large"),
        },
        row_height=56,
        alt="Señal recomendada por canal con su confianza y el motivo",
    )
    st.caption(
        "**Escalar (validar)** es una hipótesis, no una orden: el ROAS es promedio, no marginal. "
        "Confírmala con una prueba de incrementalidad antes de mover más del 10–15 % del presupuesto."
    )

with der:
    st.markdown("**Dónde cambia la historia**: crédito que gana o pierde cada canal frente al último clic")
    brecha = rank.reset_index()[["canal", "brecha_vs_ultimo_clic_pp"]]
    st.altair_chart(
        alt.Chart(brecha)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("canal:N", sort=alt.EncodingSortField("brecha_vs_ultimo_clic_pp", order="descending"),
                    title=None),
            x=alt.X("brecha_vs_ultimo_clic_pp:Q", title="Puntos porcentuales de las ventas"),
            color=color_canal(),
            tooltip=["canal", alt.Tooltip("brecha_vs_ultimo_clic_pp:Q", format="+.1f")],
        )
        .properties(height=max(200, 40 * len(brecha))),
        alt="Diferencia de crédito entre Shapley y último clic por canal",
    )
    st.caption(
        "Positivo: el último clic lo subestima (suele ser el que abre o ayuda). "
        "Negativo: el último clic le regala crédito (suele ser el que cierra)."
    )

# ================================================================= DETALLE
st.divider()
st.subheader("Detalle")
tab_alc, tab_asi, tab_conv, tab_inv, tab_evo, tab_rut = st.tabs(
    [":material/groups: Alcance", ":material/handshake: Asistencia", ":material/target: Conversión",
     ":material/payments: Inversión", ":material/trending_up: Evolución", ":material/route: Rutas"]
)


def barras(df: pd.DataFrame, x: str, titulo_x: str) -> alt.Chart:
    d = df.reset_index()
    return (
        alt.Chart(d)
        .mark_bar(cornerRadiusEnd=3)
        .encode(
            y=alt.Y("canal:N", sort="-x", title=None),
            x=alt.X(f"{x}:Q", title=titulo_x),
            color=color_canal(),
            tooltip=["canal", alt.Tooltip(f"{x}:Q", format=",.2f")],
        )
        .properties(height=max(180, 38 * len(d)))
    )


with tab_alc:
    a, b = st.columns(2, border=True)
    with a:
        st.markdown("**Usuarios alcanzados** (pasaron al menos una vez por el canal)")
        st.altair_chart(barras(rank, "usuarios_alcanzados", "Usuarios"), alt="Usuarios alcanzados por canal")
    with b:
        st.markdown("**Usuarios nuevos** (el canal fue su primer contacto)")
        st.altair_chart(barras(rank, "usuarios_nuevos", "Usuarios"), alt="Usuarios nuevos por canal")
    st.caption(
        "Alcanzados mide presencia; nuevos mide quién abre puertas. Un canal con muchos alcanzados "
        "y pocos nuevos (Email, Direct) está hablando con gente que ya conocía la marca."
    )

with tab_asi:
    st.markdown("**Rol de cada canal en las conversiones**: abrió la ruta, ayudó a mitad de camino o la cerró")
    roles = (
        rank[["conv_introducidas", "conv_asistidas", "conv_cerradas"]]
        .rename(columns={"conv_introducidas": "Introdujo", "conv_asistidas": "Asistió", "conv_cerradas": "Cerró"})
        .reset_index()
        .melt(id_vars="canal", var_name="rol", value_name="conversiones")
    )
    st.altair_chart(
        alt.Chart(roles)
        .mark_bar(stroke="white", strokeWidth=1)
        .encode(
            y=alt.Y("canal:N", title=None, sort=alt.EncodingSortField("conversiones", op="sum", order="descending")),
            x=alt.X("conversiones:Q", title="Conversiones", stack="zero"),
            color=color_canal(),
            opacity=alt.Opacity(
                "rol:N",
                scale=alt.Scale(domain=["Introdujo", "Asistió", "Cerró"], range=[0.3, 0.6, 1.0]),
                legend=alt.Legend(title="Rol (más oscuro = más cerca de la compra)"),
            ),
            order=alt.Order("rol_orden:Q"),
            tooltip=["canal", "rol", "conversiones"],
        )
        .transform_calculate(
            rol_orden="datum.rol == 'Introdujo' ? 0 : datum.rol == 'Asistió' ? 1 : 2"
        )
        .properties(height=max(200, 44 * len(rank))),
        alt="Conversiones por rol del canal: introdujo, asistió o cerró",
    )
    st.markdown("**¿A quién ayuda cada canal?** Conversiones donde el canal de la fila asistió y el de la columna cerró")
    mp = pares[pares.asistente.isin(rank.index) & pares.cierre.isin(rank.index)]
    st.altair_chart(
        alt.Chart(mp)
        .mark_rect()
        .encode(
            x=alt.X("cierre:N", title="Cerró la venta", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("asistente:N", title="Asistió"),
            color=alt.Color("conversiones:Q", scale=alt.Scale(scheme="greys"), title="Conversiones"),
            tooltip=["asistente", "cierre", "conversiones"],
        )
        .properties(height=max(220, 40 * rank.shape[0])),
        alt="Mapa de calor de asistencias entre canales",
    )
    st.caption(
        "Asistir = aparecer en la ruta de una compra sin ser el último canal no directo. "
        "Direct aparece como gran asistidor solo porque es la puerta de regreso; no es una palanca de inversión."
    )

with tab_conv:
    a, b = st.columns(2, border=True)
    with a:
        st.markdown("**Conversión por usuario** (% de usuarios del canal que compran)")
        st.altair_chart(
            barras(rank, "tasa_conv_usuario_pct", "% de usuarios"), alt="Conversión por usuario y canal"
        )
    with b:
        st.markdown("**Cierre por sesión** (% de sesiones del canal donde se cierra la venta)")
        st.altair_chart(
            barras(rank, "tasa_cierre_sesion_pct", "% de sesiones"), alt="Cierre por sesión y canal"
        )
    st.warning(
        "Email y Paid Search convierten más porque llegan a gente con intención o que ya conoce la "
        "marca. Esa tasa alta es en parte **selección**, no solo mérito del canal: no se escala "
        "subiendo presupuesto. Para eso están Alcance y la atribución causal (pestaña Inversión).",
        icon=":material/warning:",
    )
    st.markdown("**Alcance vs. conversión** (el tamaño es el volumen de asistencias)")
    sc = rank.reset_index()
    st.altair_chart(
        alt.Chart(sc)
        .mark_circle(opacity=0.85)
        .encode(
            x=alt.X("alcance_pct:Q", title="Alcance (% de usuarios)"),
            y=alt.Y("tasa_conv_usuario_pct:Q", title="Conversión por usuario (%)"),
            color=color_canal(legend=True),
            size=alt.Size("conv_asistidas:Q", title="Asistencias", scale=alt.Scale(range=[200, 1800])),
            tooltip=["canal", "alcance_pct", "tasa_conv_usuario_pct", "conv_asistidas"],
        )
        .properties(height=360),
        alt="Dispersión de alcance contra conversión por canal",
    )

with tab_inv:
    st.markdown("**Cuota real de las ventas según Shapley**, con intervalo de confianza del 90 %")
    inv = rank.reset_index()
    base = alt.Chart(inv).encode(y=alt.Y("canal:N", sort="-x", title=None))
    st.altair_chart(
        (
            base.mark_bar(cornerRadiusEnd=3).encode(
                x=alt.X("shapley_pct:Q", title="% de las conversiones"),
                color=color_canal(),
                tooltip=["canal", "shapley_pct"],
            )
            + base.mark_rule(color="#14213D", strokeWidth=2).encode(x="shapley_pct_p05:Q", x2="shapley_pct_p95:Q")
        ).properties(height=max(200, 40 * len(inv))),
        alt="Cuota de conversiones por canal con intervalo de confianza",
    )
    pagados = rank.dropna(subset=["costo"])
    if pagados.empty:
        st.info("Ningún canal pagado seleccionado.")
    else:
        st.markdown("**Canales pagados: retorno por sol invertido**")
        tabla = pagados[["costo", "shapley", "cpa_shapley", "roas_shapley"]].rename(
            columns={"costo": "Costo (S/)", "shapley": "Conversiones", "cpa_shapley": "CPA (S/)",
                     "roas_shapley": "ROAS"}
        )
        st.dataframe(
            tabla,
            column_config={
                "Costo (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
                "Conversiones": st.column_config.NumberColumn(format="%,.0f"),
                "CPA (S/)": st.column_config.NumberColumn(format="S/ %.2f"),
                "ROAS": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=float(tabla.ROAS.max() * 1.2)),
            },
            alt="Costo, conversiones, CPA y ROAS de los canales pagados",
        )
        st.caption("Los canales orgánicos, Email y Referral no tienen costo en los datos, por eso no tienen ROAS.")

with tab_evo:
    st.markdown("**Resultados por mes** (no acumulado)")
    k_hist = kpi[kpi.periodo <= periodo]
    e1, e2 = st.columns(2, border=True)
    with e1:
        st.markdown("Pedidos")
        st.altair_chart(
            alt.Chart(k_hist).mark_bar(color="#5C6B8A", cornerRadiusEnd=3).encode(
                x=alt.X("periodo:O", title=None, axis=alt.Axis(labelAngle=-45)),
                y=alt.Y("pedidos:Q", title="Pedidos"),
                tooltip=["periodo", "pedidos", "ingresos"],
            ).properties(height=220),
            alt="Pedidos por mes",
        )
    with e2:
        st.markdown("Ingresos por sol invertido")
        st.altair_chart(
            alt.Chart(k_hist).mark_line(point=True, color="#5C6B8A").encode(
                x=alt.X("periodo:O", title=None, axis=alt.Axis(labelAngle=-45)),
                y=alt.Y("mer:Q", title="Ingresos / inversión", scale=alt.Scale(zero=False)),
                tooltip=["periodo", "mer", "cpa_blended"],
            ).properties(height=220),
            alt="Ingresos por sol invertido por mes",
        )

    hist = metricas_hist[metricas_hist.canal.isin(rank.index) & (metricas_hist.periodo <= periodo)]
    st.markdown("**Cuota Shapley acumulada por canal** (% de las conversiones al cierre de cada mes)")
    st.altair_chart(
        alt.Chart(hist)
        .mark_line(point=True)
        .encode(
            x=alt.X("periodo:O", title="Acumulado hasta", axis=alt.Axis(labelAngle=-45)),
            y=alt.Y("shapley_pct:Q", title="% de las conversiones"),
            color=color_canal(legend=True),
            tooltip=["periodo", "canal", "shapley_pct", "shapley_pct_p05", "shapley_pct_p95"],
        )
        .properties(height=340),
        alt="Evolución de la cuota Shapley acumulada por canal",
    )
    pag = hist.dropna(subset=["roas_shapley"])
    if not pag.empty:
        st.markdown("**ROAS acumulado de los canales pagados**")
        st.altair_chart(
            alt.Chart(pag)
            .mark_line(point=True)
            .encode(
                x=alt.X("periodo:O", title="Acumulado hasta", axis=alt.Axis(labelAngle=-45)),
                y=alt.Y("roas_shapley:Q", title="ROAS (Shapley)"),
                color=color_canal(legend=True),
                tooltip=["periodo", "canal", "roas_shapley", "cpa_shapley"],
            )
            .properties(height=300),
            alt="Evolución del ROAS acumulado de los canales pagados",
        )
    st.caption(
        "Es un acumulado: cada punto incluye todos los meses anteriores, así que la línea se "
        "estabiliza con el volumen. Un canal que sigue moviéndose en los últimos meses "
        "todavía no tiene suficiente evidencia para mover presupuesto."
    )

with tab_rut:
    st.markdown("**Rutas que más venden**")
    rt = del_periodo(datos["rutas"]).rename(columns={"ruta_txt": "Ruta", "pedidos": "Pedidos", "ingresos": "Ingresos (S/)"})
    st.dataframe(
        rt,
        hide_index=True,
        column_config={
            "Pedidos": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=int(rt.Pedidos.max())),
            "Ingresos (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
        },
        alt="Rutas de conversión más frecuentes",
    )

# ================================================================= MATRIZ Y CONFIANZA
st.divider()
st.subheader("Matriz de decisión")
matriz = rank[
    ["usuarios_alcanzados", "usuarios_nuevos", "conv_asistidas", "ratio_asistencia",
     "tasa_conv_usuario_pct", "tasa_cierre_sesion_pct", "shapley_pct", "roas_shapley"]
].rename(columns={
    "usuarios_alcanzados": "Alcanzados", "usuarios_nuevos": "Nuevos", "conv_asistidas": "Asistidas",
    "ratio_asistencia": "Asist./cierre", "tasa_conv_usuario_pct": "Conv. usuario %",
    "tasa_cierre_sesion_pct": "Cierre sesión %", "shapley_pct": "Cuota Shapley %", "roas_shapley": "ROAS",
})
st.dataframe(
    matriz,
    column_config={
        c: st.column_config.ProgressColumn(
            format="%.2f" if (matriz[c].max() or 0) < 100 else "%,.0f",
            min_value=0,
            max_value=float(matriz[c].max()) if matriz[c].notna().any() else 1.0,
        )
        for c in matriz.columns
    },
    alt="Matriz de decisión con alcance, asistencia, conversión e inversión por canal",
)

st.subheader("Qué tan confiable es este reporte")
cobertura = conc.pedidos_con_ruta / conc.pedidos_backend * 100
q1, q2, q3 = st.columns(3, border=True)
with q1:
    st.metric("Pedidos del backend con ruta", f"{cobertura:.1f} %",
              help="Pedidos pagados que se pudieron vincular a sesiones de GA4 por client_id.")
    st.caption(f"{conc.pedidos_con_ruta:,.0f} de {conc.pedidos_backend:,.0f}. "
               f"Sin client_id: {conc.pedidos_sin_client_id:,.0f}.")
with q2:
    st.metric("Ventas que GA4 vio", f"{conc.pedidos_vistos_en_ga4 / conc.pedidos_backend * 100:.1f} %",
              help="Compras del backend que tienen evento purchase en GA4.")
    st.caption("El resto se recupera desde el backend; por eso la venta no sale del evento de GA4.")
with q3:
    st.metric("Error del modelo vs. efecto real", f"{err['shapley']:.1f} pp",
              help="Solo se puede medir con datos sintéticos; en un cliente real no existe.")
    st.caption(f"Markov {err['markov']:.1f} pp · Último clic no directo {err['ultimo_no_directo']:.1f} pp.")

with st.expander("Cómo leer este reporte", icon=":material/menu_book:"):
    st.markdown(
        """
**Acumulado.** El periodo `2026-03` es todo lo ocurrido desde el primer dato hasta el cierre de marzo.
Cada corte recalcula los modelos; las cuotas de dos meses no se suman ni se promedian.

**Alcance, asistencia, conversión.** Alcance = usuarios que pasaron por el canal. Asistencia = veces que el
canal estuvo en la ruta de una compra sin ser el último. Conversión = % de usuarios del canal que compran.

**Cuota Shapley.** Reparte cada venta entre los canales de su ruta según lo que cada uno aporta a la
probabilidad de compra. Es la medida más cercana al efecto real que tenemos; el intervalo muestra su estabilidad.

**ROAS y CPA.** Son promedios sobre toda la inversión del periodo. No dicen qué pasa con el próximo sol
(ROAS marginal). Para escalar un canal hace falta una prueba de incrementalidad.

**Señales.** *Escalar (validar)*: ROAS ≥ 1.2× el promedio pagado. *Revisar*: ROAS ≤ 0.8×.
*Proteger*: canal sin costo que asiste 2 o más ventas por cada cierre propio. *Aprovechar*: convierte 1.2× la
mediana. Son reglas de lectura, no una decisión automática.

**Límites.** Los datos observacionales no prueban causalidad, no hay costo para canales orgánicos, y el
cruce depende de que el pedido guarde el client_id de GA4.
"""
    )
