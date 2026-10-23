"""Resumen: KPIs con tendencia, quién gana cada pregunta, señal por canal e interpretación."""
import altair as alt
import streamlit as st

from dashboard_comun import (
    CANAL_COLORS,
    CONFIANZA_BADGE,
    NOMBRE_MODELO,
    SENAL_COLORS,
    boton_descarga,
    color_canal,
    contexto,
    estilo_canal,
    estilo_estado,
    estilo_senal,
    evidencia,
    panel_interpretacion,
    titulo_canal,
)

ctx = contexto()
v, rank, ejec = ctx.vista, ctx.rank, ctx.ejec

# ----------------------------------------------------------------- encabezado
cab, ev, est = st.columns([5, 1.2, 1.6], vertical_alignment="center")
with cab:
    seg = "Todo el negocio" if v.dim == "Todos" else f"{v.dim}: {v.segmento}"
    st.subheader(seg)
    st.caption(f"{ctx.pedidos:,} pedidos con ruta · ventana de atribución {v.ventana_dias} días · modelo {ctx.nombre_modelo}")
with ev:
    nivel = evidencia(ctx.pedidos)
    st.badge(f"Evidencia {nivel}", icon=":material/verified:", color=CONFIANZA_BADGE[nivel],
             help="Pedidos con ruta en esta vista. Más de 3,000: alta. De 1,000 a 3,000: media. Menos de 1,000: baja.")
with est:
    revisar = ejec.alertas > 0 or ejec.canales_cambiaron > 0
    st.badge("Modelo: revisar" if revisar else "Modelo estable", icon=":material/monitoring:",
             color="orange" if revisar else "green",
             help=f"{ejec.canales_cambiaron} canal(es) fuera de su intervalo frente al mes anterior y {ejec.alertas} alerta(s) "
                  "de reajuste. Detalle en Modelos y robustez.")

# ----------------------------------------------------------------- semáforo de calidad (RQ-18)
if not ctx.es_segmento:
    controles = ctx.datos["controles"]
    peor = "crítico" if (controles.estado == "crítico").any() else "alerta" if (controles.estado == "alerta").any() else "ok"
    icono = {"ok": ":material/check_circle:", "alerta": ":material/warning:", "crítico": ":material/error:"}[peor]
    with st.expander(f"{icono} Semáforo de calidad de datos", expanded=peor != "ok"):
        tabla_controles = controles.rename(columns={"control": "Control", "valor": "Valor", "umbral": "Umbral",
                                                     "unidad": "Unidad", "estado": "Estado"}).drop(columns="severidad")
        st.dataframe(tabla_controles.style.map(estilo_estado, subset=["Estado"]), hide_index=True,
                     alt="Controles de calidad de los datos de entrada, con su valor, umbral y estado")
        st.caption("Un control «crítico» detiene la corrida antes de publicar resultados; «alerta» no la detiene pero conviene revisarlo.")
        boton_descarga(controles, "calidad_controles")

# ----------------------------------------------------------------- KPIs
if not ctx.es_segmento:
    k = ctx.kpi
    ult, ant = k.iloc[-1], k.iloc[-2]

    def kpi(etiqueta, col, fmt, inverso=False, neutro=False, ayuda=None, tipo="line"):
        d = (ult[col] / ant[col] - 1) * 100
        st.metric(etiqueta, fmt(ult[col]), f"{d:+.1f} %", delta_color="off" if neutro else "inverse" if inverso else "normal",
                  delta_description="vs. mes anterior", chart_data=k[col].tolist(), chart_type=tipo, border=True, help=ayuda)

    st.caption(f"Último mes ({ult.periodo}) y tendencia de los {len(k)} meses de la ventana.")
    with st.container(horizontal=True):
        kpi("Pedidos", "pedidos", lambda x: f"{x:,.0f}", tipo="bar")
        kpi("Ingresos", "ingresos", lambda x: f"S/ {x:,.0f}")
        kpi("Inversión en medios", "inversion_medios", lambda x: f"S/ {x:,.0f}", neutro=True)
        kpi("Ingresos por sol invertido", "mer", lambda x: f"{x:.2f}", ayuda="Ingresos totales / inversión en medios pagados (MER).")
        kpi("Costo por pedido", "cpa_blended", lambda x: f"S/ {x:,.1f}", inverso=True,
            ayuda="Inversión en medios pagados / pedidos totales (CPA blended).")
        kpi("Conversión por sesión", "conv_sesion_pct", lambda x: f"{x:.2f} %")
else:
    cn = ctx.tabla
    with st.container(horizontal=True):
        st.metric("Pedidos con ruta", f"{ctx.pedidos:,}", border=True)
        st.metric("Sesiones", f"{int(cn.sesiones.sum()):,}", border=True)
        st.metric("Usuarios", f"{int(cn.usuarios_nuevos.sum()):,}", border=True)
        st.metric("Conversión por usuario", f"{ctx.pedidos / cn.usuarios_nuevos.sum() * 100:.2f} %", border=True)
    st.caption("Los KPIs de negocio (inversión, MER) existen solo para el total: el costo no está por segmento.")

# ----------------------------------------------------------------- ganadores
def ganador(col: str) -> tuple[str, float, str, float]:
    s = rank[col].dropna().sort_values(ascending=False)
    seg2 = (s.index[1], s.iloc[1]) if len(s) > 1 else ("—", 0.0)
    return s.index[0], s.iloc[0], seg2[0], seg2[1]


g_alc, g_asi, g_con = ganador("usuarios_alcanzados"), ganador("ventas_asiste"), ganador("tasa_conv_usuario_pct")
c1, c2, c3 = st.columns(3, border=True)
with c1:
    st.caption(":material/groups: MEJOR ALCANCE")
    titulo_canal(g_alc[0], "1.5rem")
    st.write(f"{g_alc[1]:,.0f} usuarios · 2.º {g_alc[2]}")
with c2:
    st.caption(":material/handshake: MEJOR ASISTIDOR")
    titulo_canal(g_asi[0], "1.5rem")
    st.write(f"{g_asi[1]:,.0f} ventas asistidas · 2.º {g_asi[2]}")
with c3:
    st.caption(":material/target: MEJOR CONVERSIÓN")
    titulo_canal(g_con[0], "1.5rem")
    st.write(f"{g_con[1]:.1f} % de sus usuarios · 2.º {g_con[2]}")

# ----------------------------------------------------------------- roles (RQ-11)
st.markdown("**Rol de cada canal en las ventas** · abre, asiste, cierra o es el único contacto")
roles = (
    rank[["ventas_abre", "ventas_asiste", "ventas_cierra", "ventas_unico"]]
    .rename(columns={"ventas_abre": "Abre", "ventas_asiste": "Asiste", "ventas_cierra": "Cierra", "ventas_unico": "Único"})
    .reset_index().melt(id_vars="canal", var_name="rol", value_name="ventas")
)
st.altair_chart(
    alt.Chart(roles).mark_bar(stroke="white", strokeWidth=1).encode(
        y=alt.Y("canal:N", title=None, sort=alt.EncodingSortField("ventas", op="sum", order="descending")),
        x=alt.X("ventas:Q", title="Ventas", stack="zero"),
        color=color_canal(),
        opacity=alt.Opacity("rol:N", scale=alt.Scale(domain=["Abre", "Asiste", "Cierra", "Único"],
                                                      range=[0.3, 0.55, 1.0, 0.15]),
                            legend=alt.Legend(title="Rol")),
        order=alt.Order("rol_orden:Q"), tooltip=["canal", "rol", "ventas"],
    ).transform_calculate(
        rol_orden="datum.rol == 'Abre' ? 0 : datum.rol == 'Asiste' ? 1 : datum.rol == 'Cierra' ? 2 : 3"
    ).properties(height=max(160, 34 * len(rank))),
    alt="Ventas por rol del canal: abre, asiste, cierra o es el único contacto",
)

# ----------------------------------------------------------------- señales + interpretación
izq, der = st.columns([3, 2], gap="large")
with izq:
    st.markdown(f"**Qué hacer con cada canal** · {ctx.nombre_modelo}")
    acc = ctx.m.reset_index()[["canal", "senal", "confianza", "cuota_pct", "brecha_vs_ultimo_clic_pp", "roas", "motivo"]]
    orden = {s: i for i, s in enumerate(SENAL_COLORS)}
    acc = acc.sort_values("senal", key=lambda c: c.map(orden)).reset_index(drop=True)
    tabla = acc.rename(columns={"canal": "Canal", "senal": "Señal", "confianza": "Confianza", "cuota_pct": "Cuota",
                                "brecha_vs_ultimo_clic_pp": "Vs. último clic", "roas": "ROAS", "motivo": "Por qué"})
    if ctx.es_segmento:
        tabla = tabla.drop(columns="ROAS")
    evento = st.dataframe(
        tabla.style.map(estilo_canal, subset=["Canal"]).map(estilo_senal, subset=["Señal"]),
        hide_index=True, on_select="rerun", selection_mode="single-row", key="tabla_senales", row_height=52,
        column_config={
            "Cuota": st.column_config.NumberColumn(format="%.1f %%", help="% de las ventas atribuidas con el modelo elegido."),
            "Vs. último clic": st.column_config.NumberColumn(format="%+.1f pp",
                                                             help="Cuota del modelo menos cuota de último clic no directo."),
            "ROAS": st.column_config.NumberColumn(format="%.2f"),
            "Por qué": st.column_config.TextColumn(width="large"),
        },
        alt="Señal recomendada por canal, con su cuota, confianza y motivo. Selecciona una fila para ver el canal.",
    )
    if not ctx.es_segmento:
        st.caption("«Escalar (validar)» es una hipótesis: el ROAS es promedio, no marginal. Valídala con una prueba de incrementalidad.")
    boton_descarga(acc, "senales_por_canal")
    foco = acc.canal.iloc[evento.selection.rows[0]] if evento.selection.rows else None
with der:
    panel_interpretacion(ctx, "resumen", "Interpretación")

# ----------------------------------------------------------------- gráficos
g1, g2 = st.columns(2, border=True)
with g1:
    st.markdown("**Cuota de las ventas** (intervalo del 90 % en Shapley)")
    inv = rank.reset_index()
    base = alt.Chart(inv).encode(y=alt.Y("canal:N", sort="-x", title=None))
    capas = base.mark_bar(cornerRadiusEnd=3).encode(
        x=alt.X("cuota_pct:Q", title="% de las ventas"), color=color_canal(), tooltip=["canal", "cuota_pct"])
    if v.modelo == "shapley" and inv.cuota_p05.notna().any():
        capas += base.mark_rule(color="#14213D", strokeWidth=2).encode(x="cuota_p05:Q", x2="cuota_p95:Q")
    st.altair_chart(capas.properties(height=max(180, 36 * len(inv))), alt="Cuota de las ventas por canal")
with g2:
    st.markdown("**Dónde cambia la historia** frente al último clic (pp)")
    st.altair_chart(
        alt.Chart(rank.reset_index()).mark_bar(cornerRadiusEnd=3).encode(
            y=alt.Y("canal:N", sort=alt.EncodingSortField("brecha_vs_ultimo_clic_pp", order="descending"), title=None),
            x=alt.X("brecha_vs_ultimo_clic_pp:Q", title="Puntos porcentuales"), color=color_canal(),
            tooltip=["canal", alt.Tooltip("brecha_vs_ultimo_clic_pp:Q", format="+.1f")],
        ).properties(height=max(180, 36 * len(rank))),
        alt="Diferencia de crédito entre el modelo elegido y el último clic por canal",
    )

# ----------------------------------------------------------------- canal en foco
if foco:
    r = ctx.tabla.loc[foco]
    comp = ctx.comp[ctx.comp.canal == foco].assign(Modelo=lambda d: d.modelo.map(NOMBRE_MODELO))
    with st.container(border=True):
        a, b = st.columns([2, 3], gap="large")
        with a:
            titulo_canal(foco)
            st.badge(r.senal, color="gray")
            st.write(r.motivo)
            with st.container(horizontal=True):
                st.metric("Cuota", f"{r.cuota_pct:.1f} %")
                if not ctx.es_segmento and r.roas == r.roas:
                    st.metric("ROAS", f"{r.roas:.2f}")
                    st.metric("CPA", f"S/ {r.cpa:.0f}")
            with st.container(horizontal=True):
                st.metric("Alcance", f"{r.usuarios_alcanzados:,.0f}")
                st.metric("Asistencias por cierre", f"{r.asistencias_por_cierre:.1f}")
                st.metric("Conversión", f"{r.tasa_conv_usuario_pct:.1f} %")
        with b:
            st.markdown("**Su cuota según cada modelo**")
            st.altair_chart(
                alt.Chart(comp).mark_bar(cornerRadiusEnd=3, color=CANAL_COLORS[foco]).encode(
                    y=alt.Y("Modelo:N", sort="-x", title=None), x=alt.X("cuota_pct:Q", title="% de las ventas"),
                    tooltip=["Modelo", "cuota_pct"]).properties(height=240),
                alt=f"Cuota de {foco} según cada modelo de atribución",
            )
else:
    st.caption(":material/touch_app: Selecciona un canal en la tabla para ver su detalle.")
