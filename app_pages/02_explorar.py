"""Explorar: alcance, asistencia, conversión, inversión, segmentos y rutas, con los filtros globales."""
import altair as alt
import streamlit as st

from dashboard_comun import DIMENSIONES, barras, boton_descarga, color_canal, contexto, estilo_canal

ctx = contexto()
v, rank = ctx.vista, ctx.rank
seg = "Todo el negocio" if v.dim == "Todos" else f"{v.dim}: {v.segmento}"
st.subheader(seg)
st.caption(f"Ventana de atribución {v.ventana_dias} días · modelo {ctx.nombre_modelo}")

tab_alc, tab_asi, tab_conv, tab_inv, tab_camp, tab_plat, tab_seg, tab_rut = st.tabs(
    [":material/groups: Alcance", ":material/handshake: Asistencia", ":material/target: Conversión",
     ":material/payments: Inversión", ":material/campaign: Campañas", ":material/compare_arrows: Plataformas",
     ":material/segment: Segmentos", ":material/route: Rutas"]
)

with tab_alc:
    a, b = st.columns(2, border=True)
    with a:
        st.markdown("**Usuarios alcanzados** · pasaron por el canal")
        st.altair_chart(barras(rank, "usuarios_alcanzados", "Usuarios"), alt="Usuarios alcanzados por canal")
    with b:
        st.markdown("**Usuarios nuevos** · el canal fue su primer contacto")
        st.altair_chart(barras(rank, "usuarios_nuevos", "Usuarios"), alt="Usuarios nuevos por canal")

with tab_asi:
    roles = (
        rank[["ventas_abre", "ventas_asiste", "ventas_cierra", "ventas_unico"]]
        .rename(columns={"ventas_abre": "Abrió", "ventas_asiste": "Asistió", "ventas_cierra": "Cerró",
                         "ventas_unico": "Único"})
        .reset_index().melt(id_vars="canal", var_name="rol", value_name="conversiones")
    )
    st.markdown("**Rol de cada canal en las ventas** · abrió la ruta, ayudó a mitad de camino, la cerró o fue el único contacto")
    st.altair_chart(
        alt.Chart(roles).mark_bar(stroke="white", strokeWidth=1).encode(
            y=alt.Y("canal:N", title=None, sort=alt.EncodingSortField("conversiones", op="sum", order="descending")),
            x=alt.X("conversiones:Q", title="Ventas", stack="zero"),
            color=color_canal(),
            opacity=alt.Opacity("rol:N", scale=alt.Scale(domain=["Abrió", "Asistió", "Cerró", "Único"],
                                                          range=[0.3, 0.6, 1.0, 0.15]),
                                legend=alt.Legend(title="Rol (más oscuro = más cerca de la compra)")),
            order=alt.Order("rol_orden:Q"), tooltip=["canal", "rol", "conversiones"],
        ).transform_calculate(
            rol_orden="datum.rol == 'Abrió' ? 0 : datum.rol == 'Asistió' ? 1 : datum.rol == 'Cerró' ? 2 : 3"
        ).properties(height=max(200, 44 * len(rank))),
        alt="Ventas por rol del canal: abrió, asistió, cerró o fue el único contacto",
    )
    pares = ctx.rebanada("pares")
    pares = pares[pares.asistente.isin(rank.index) & pares.cierre.isin(rank.index)]
    st.markdown("**¿A quién ayuda cada canal?** El de la fila asistió y el de la columna cerró")
    st.altair_chart(
        alt.Chart(pares).mark_rect().encode(
            x=alt.X("cierre:N", title="Cerró la venta", axis=alt.Axis(labelAngle=0)), y=alt.Y("asistente:N", title="Asistió"),
            color=alt.Color("conversiones:Q", scale=alt.Scale(scheme="greys"), title="Ventas"),
            tooltip=["asistente", "cierre", "conversiones"],
        ).properties(height=max(220, 40 * len(rank))),
        alt="Mapa de calor de asistencias entre canales",
    )

with tab_conv:
    a, b = st.columns(2, border=True)
    with a:
        st.markdown("**Conversión por usuario** · % de usuarios del canal que compran")
        st.altair_chart(barras(rank, "tasa_conv_usuario_pct", "% de usuarios"), alt="Conversión por usuario y canal")
    with b:
        st.markdown("**Cierre por sesión** · % de sesiones donde se cierra la venta")
        st.altair_chart(barras(rank, "tasa_cierre_sesion_pct", "% de sesiones"), alt="Cierre por sesión y canal")
    st.markdown("**Alcance vs. conversión** · el tamaño es el volumen de asistencias")
    st.altair_chart(
        alt.Chart(rank.reset_index()).mark_circle(opacity=0.85).encode(
            x=alt.X("alcance_pct:Q", title="Alcance (% de usuarios)"),
            y=alt.Y("tasa_conv_usuario_pct:Q", title="Conversión por usuario (%)"),
            color=color_canal(legend=True),
            size=alt.Size("ventas_asiste:Q", title="Asistencias", scale=alt.Scale(range=[200, 1800])),
            tooltip=["canal", "alcance_pct", "tasa_conv_usuario_pct", "ventas_asiste"],
        ).properties(height=340),
        alt="Dispersión de alcance contra conversión por canal",
    )
    st.caption("La conversión alta de Email o Search es en parte selección: llegan a gente con intención. No se escala con presupuesto.")

with tab_inv:
    pagados = rank.dropna(subset=["costo"])
    if ctx.es_segmento:
        st.info("Dentro de un segmento no hay costo por canal, así que no hay ROAS ni CPA. Elige «Sin segmento» en el menú lateral.",
                icon=":material/info:")
    elif pagados.empty:
        st.info("Ningún canal pagado en la selección.")
    else:
        st.markdown("**Canales pagados** · retorno por sol invertido")
        tabla = pagados[["costo", "conversiones", "cpa", "roas", "cuota_pct"]].rename(
            columns={"costo": "Costo (S/)", "conversiones": "Ventas", "cpa": "CPA (S/)", "roas": "ROAS", "cuota_pct": "Cuota %"})
        st.dataframe(
            tabla,
            column_config={
                "Costo (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
                "Ventas": st.column_config.NumberColumn(format="%,.0f"),
                "CPA (S/)": st.column_config.NumberColumn(format="S/ %.2f"),
                "ROAS": st.column_config.ProgressColumn(format="%.2f", min_value=0, max_value=float(tabla.ROAS.max() * 1.2)),
                "Cuota %": st.column_config.NumberColumn(format="%.1f %%"),
            },
            alt="Costo, ventas, CPA, ROAS y cuota de los canales pagados",
        )
        st.caption("Email, orgánico y referral no tienen costo en los datos. ROAS y CPA son promedios, no marginales.")
        boton_descarga(tabla, "inversion_canales_pagados")

# ----------------------------------------------------------------- campañas (RQ-09)
with tab_camp:
    camp = ctx.datos["campana"]
    camp = camp[camp.canal.isin(rank.index)]
    if camp.empty:
        st.info("Ningún canal pagado con campañas en la selección.")
    else:
        st.markdown("**Campañas por canal pagado** · la cuota del canal se reparte en proporción a las sesiones de "
                    "cada campaña en rutas convertidas")
        st.caption("Vista fija: ventana de atribución vigente, total del negocio (no cambia con el segmento ni la "
                   "ventana elegidos en el menú lateral).")
        orden = camp.sort_values("conversiones", ascending=False).campana.tolist()
        g1, g2 = st.columns(2, border=True)
        with g1:
            st.altair_chart(
                alt.Chart(camp).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("campana:N", sort=orden, title=None), x=alt.X("conversiones:Q", title="Ventas atribuidas"),
                    color=color_canal(legend=True), tooltip=["canal", "campana", "conversiones", "ingresos"],
                ).properties(height=max(160, 40 * len(camp))),
                alt="Ventas atribuidas por campaña")
        with g2:
            st.altair_chart(
                alt.Chart(camp).mark_bar(cornerRadiusEnd=3).encode(
                    y=alt.Y("campana:N", sort=orden, title=None), x=alt.X("roas:Q", title="ROAS"),
                    color=color_canal(legend=False), tooltip=["canal", "campana", "roas", "cpa", "costo"],
                ).properties(height=max(160, 40 * len(camp))),
                alt="ROAS por campaña")
        tabla_camp = camp.rename(columns={
            "canal": "Canal", "campana": "Campaña", "sesiones": "Sesiones", "participacion_pct": "Participación %",
            "conversiones": "Ventas", "ingresos": "Ingresos (S/)", "costo": "Costo (S/)", "roas": "ROAS", "cpa": "CPA (S/)"})
        st.dataframe(
            tabla_camp.style.map(estilo_canal, subset=["Canal"]), hide_index=True,
            column_config={
                "Participación %": st.column_config.NumberColumn(format="%.1f %%"),
                "Ventas": st.column_config.NumberColumn(format="%,.1f"),
                "Ingresos (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
                "Costo (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
                "ROAS": st.column_config.NumberColumn(format="%.2f"), "CPA (S/)": st.column_config.NumberColumn(format="S/ %.2f"),
            },
            alt="Campañas de los canales pagados seleccionados",
        )
        st.caption("El reparto es proporcional, no un modelo de atribución aparte a nivel campaña: Shapley no escala a "
                   "tantas combinaciones (ver el límite de jugadores en Modelos y robustez).")
        boton_descarga(camp, "campanas")

# ----------------------------------------------------------------- plataformas (RQ-15/RQ-16)
with tab_plat:
    plat = ctx.datos["plataformas"]
    plat = plat[plat.canal.isin(rank.index)]
    if plat.empty:
        st.info("Ningún canal pagado con datos de plataforma en la selección.")
    else:
        st.markdown("**Lo que reporta cada plataforma frente a lo que le asigna el modelo**")
        st.warning(
            "La brecha incluye vistas sin clic (no generan sesión en GA4: el modelo no las puede ver) y que cada "
            "plataforma reclama la venta completa cuando la ruta pasó por más de un canal pagado, mientras el modelo "
            "la reparte entre todos. No es un error del modelo ni de la plataforma: miden cosas distintas.",
            icon=":material/warning:")
        orden = plat.sort_values("conv_plataforma", ascending=False).campaign_id.tolist()
        largo = plat.melt(id_vars=["canal", "campaign_id", "plataforma"], value_vars=["conv_modelo", "conv_plataforma"],
                          var_name="fuente", value_name="conversiones")
        largo["fuente"] = largo.fuente.map({"conv_modelo": "Modelo (multi-touch)", "conv_plataforma": "Plataforma (reportado)"})
        st.altair_chart(
            alt.Chart(largo).mark_bar().encode(
                y=alt.Y("campaign_id:N", sort=orden, title=None), x=alt.X("conversiones:Q", title="Ventas"),
                color=alt.Color("fuente:N", scale=alt.Scale(range=["#14213D", "#ADB5BD"]), legend=alt.Legend(title=None)),
                yOffset="fuente:N", tooltip=["canal", "campaign_id", "fuente", "conversiones"],
            ).properties(height=max(200, 50 * len(plat))),
            alt="Ventas atribuidas por el modelo frente a lo reportado por cada plataforma")
        tabla_plat = plat.rename(columns={
            "plataforma": "Plataforma", "canal": "Canal", "campaign_id": "Campaña",
            "conv_plataforma": "Conv. plataforma", "conv_modelo": "Conv. modelo",
            "ingresos_plataforma": "Ingresos plataforma (S/)", "ingresos_modelo": "Ingresos modelo (S/)",
            "brecha_pct": "Brecha %"})
        st.dataframe(
            tabla_plat.style.map(estilo_canal, subset=["Canal"]), hide_index=True,
            column_config={
                "Conv. plataforma": st.column_config.NumberColumn(format="%,.1f"),
                "Conv. modelo": st.column_config.NumberColumn(format="%,.1f"),
                "Ingresos plataforma (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
                "Ingresos modelo (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
                "Brecha %": st.column_config.NumberColumn(format="%+.0f %%"),
            },
            alt="Conversiones e ingresos: plataforma vs. modelo, por campaña",
        )
        boton_descarga(plat, "plataformas_comparacion")

        st.divider()
        alc = ctx.datos["alcance"]
        alc = alc[alc.canal.isin(rank.index)]
        if not alc.empty:
            st.markdown("**Impresiones, alcance y frecuencia** · no entran a las rutas de conversión")
            tabla_alc = alc.rename(columns={"canal": "Canal", "campana": "Campaña", "impresiones": "Impresiones",
                                            "alcance": "Alcance", "frecuencia": "Frecuencia"})
            st.dataframe(
                tabla_alc.style.map(estilo_canal, subset=["Canal"]), hide_index=True,
                column_config={"Impresiones": st.column_config.NumberColumn(format="%,.0f"),
                              "Alcance": st.column_config.NumberColumn(format="%,.0f"),
                              "Frecuencia": st.column_config.NumberColumn(format="%.2f")},
                alt="Impresiones, alcance y frecuencia por campaña",
            )
            st.caption("Insumo para un futuro Marketing Mix Model (RQ-22, opcional); hoy no se usa en las rutas de conversión.")
            boton_descarga(alc, "alcance_campanas")

with tab_seg:
    dims = [d for d in DIMENSIONES if d != "Todos"]
    dim = st.segmented_control("Comparar canales entre", dims, default=dims[0], key="seg_dim") or dims[0]
    c = ctx.datos["comp"]
    c = c[(c.ventana_dias == v.ventana_dias) & (c.modelo == v.modelo) & (c.dim.isin(["Todos", dim])) & c.canal.isin(rank.index)]
    c = c.assign(segmento=c.segmento.where(c.dim != "Todos", "Total"))
    orden = ["Total"] + sorted(c[c.dim == dim].segmento.unique())
    st.markdown(f"**Cuota de las ventas por {dim.lower()}** · {ctx.nombre_modelo}")
    base = alt.Chart(c).encode(
        x=alt.X("segmento:N", sort=orden, title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("canal:N", sort=list(rank.sort_values("cuota_pct", ascending=False).index), title=None))
    st.altair_chart(
        (base.mark_rect().encode(color=alt.Color("cuota_pct:Q", scale=alt.Scale(scheme="blues"), title="Cuota %"))
         + base.mark_text(fontSize=12).encode(text=alt.Text("cuota_pct:Q", format=".1f"),
                                              color=alt.condition("datum.cuota_pct > 22", alt.value("white"), alt.value("#14213D")))
         ).properties(height=max(200, 44 * len(rank))),
        alt=f"Cuota de las ventas por canal y {dim.lower()}",
    )
    st.caption("Cada columna es un modelo recalculado solo con los usuarios del segmento. Un canal que pesa mucho más "
               "en un segmento que en el total es un candidato a campañas dirigidas.")

with tab_rut:
    rt = ctx.rebanada("rutas").drop(columns=["ventana_dias", "dim", "segmento"]).rename(
        columns={"ruta_txt": "Ruta", "pedidos": "Pedidos", "ingresos": "Ingresos (S/)"})
    st.markdown("**Rutas que más venden**")
    st.dataframe(
        rt, hide_index=True,
        column_config={
            "Pedidos": st.column_config.ProgressColumn(format="%d", min_value=0, max_value=int(rt.Pedidos.max())),
            "Ingresos (S/)": st.column_config.NumberColumn(format="S/ %,.0f"),
        },
        alt="Rutas de conversión más frecuentes",
    )
    boton_descarga(rt, "rutas_top")
