"""Siguientes pasos: plan interpretado, tiempo hasta la compra y diseño de una prueba de incrementalidad."""
import altair as alt
import pandas as pd
import streamlit as st

from dashboard_comun import color_canal, contexto, estilo_canal, panel_interpretacion

ctx = contexto()
v = ctx.vista

st.subheader("De la demo a una decisión que se pueda defender")
panel_interpretacion(ctx, "siguientes_pasos", "Plan de siguientes pasos")

izq, der = st.columns(2, gap="large")

# ----------------------------------------------------------------- tiempo hasta la compra
with izq:
    st.markdown("**¿Cuánto tardan en comprar?** Base para elegir la ventana de atribución")
    hist, t_canal = ctx.datos["t_hist"], ctx.datos["t_canal"]
    tot = t_canal[t_canal.canal_apertura == "(todos)"].iloc[0]
    st.altair_chart(
        alt.Chart(hist).mark_bar(color="#5C6B8A", cornerRadiusEnd=3).encode(
            x=alt.X("rango:O", sort=hist.rango.tolist(), title="Días entre el primer contacto y la compra",
                    axis=alt.Axis(labelAngle=0)),
            y=alt.Y("pct:Q", title="% de las compras"), tooltip=["rango", "pedidos", "pct"],
        ).properties(height=260),
        alt="Distribución de los días entre el primer contacto y la compra",
    )
    with st.container(horizontal=True):
        st.metric("Mediana", f"{tot.dias_p50:.0f} días", border=True)
        st.metric("Percentil 90", f"{tot.dias_p90:.0f} días", border=True)
        st.metric("Ventana vigente", f"{int(ctx.ejec.ventana_dias)} días", border=True,
                  help=f"Medido con una ventana de {int(tot.ventana_dias)} días para no truncar la cola.")
    tc = t_canal.drop(columns="ventana_dias").rename(columns={
        "canal_apertura": "Canal de apertura", "pedidos": "Pedidos", "dias_p50": "Mediana (d)", "dias_p90": "Percentil 90 (d)"})
    st.dataframe(tc.style.map(estilo_canal, subset=["Canal de apertura"]), hide_index=True,
                 column_config={"Pedidos": st.column_config.NumberColumn(format="%,d")},
                 alt="Mediana y percentil 90 de días hasta la compra por canal de apertura")
    st.caption("Regla práctica: la ventana debe cubrir al menos el percentil 90. Compara ventanas en Modelos y robustez.")

# ----------------------------------------------------------------- incrementalidad
with der:
    st.markdown("**Diseño de una prueba de incrementalidad** · ¿qué efecto puede detectar?")
    inc = ctx.datos["incrementalidad"]
    inc = inc[inc.canal.isin(ctx.rank.index)]
    if inc.empty:
        st.info("Selecciona al menos un canal pagado.")
    else:
        holdout = st.segmented_control("Audiencia en control (sin ver el canal)", [10, 20, 50], default=20,
                                       format_func=lambda x: f"{x} %", key="m_hold") or 20
        d = inc[inc.holdout_pct == holdout]
        referencia = 30
        lineas = alt.Chart(d).mark_line(point=True).encode(
            x=alt.X("semanas:O", title="Duración (semanas)", axis=alt.Axis(labelAngle=0)),
            y=alt.Y("emd_relativo_pct:Q", title="Efecto mínimo detectable (% de las ventas del canal)"),
            color=color_canal(legend=True),
            tooltip=["canal", "semanas", "usuarios_prueba", "usuarios_control", "tasa_base_pct", "emd_relativo_pct"])
        regla = alt.Chart(pd.DataFrame({"y": [referencia]})).mark_rule(strokeDash=[4, 4], color="#14213D").encode(y="y:Q")
        st.altair_chart((lineas + regla).properties(height=260), alt="Efecto mínimo detectable según semanas y canal")
        st.caption(f"Bajo la línea punteada ({referencia} %) la prueba distingue el efecto del azar. Menos es mejor.")

        objetivo = next((c for c in ctx.m.index if ctx.m.loc[c, "senal"] == "Escalar (validar)" and c in inc.canal.values), None)
        if objetivo:
            del_canal = inc[inc.canal == objetivo]
            sel = d[(d.canal == objetivo) & (d.emd_relativo_pct <= referencia)]
            todas = del_canal[del_canal.emd_relativo_pct <= referencia].sort_values(["holdout_pct", "semanas"])
            if len(sel):
                x = sel.sort_values("semanas").iloc[0]
                st.success(f"**{objetivo}**: con {int(x.semanas)} semanas y {holdout} % de control se detectan efectos desde "
                           f"{x.emd_relativo_pct:.0f} % ({int(x.usuarios_control):,} usuarios en control).", icon=":material/science:")
            elif len(todas):
                x = todas.iloc[0]
                st.warning(f"**{objetivo}**: con {holdout} % de control ninguna duración llega a {referencia} %. Lo logra con "
                           f"{int(x.holdout_pct)} % durante {int(x.semanas)} semanas. Dejar sin anuncios a media audiencia cuesta "
                           "ventas: la alternativa es una prueba geográfica.", icon=":material/science:")
            else:
                st.warning(f"**{objetivo}**: ninguna configuración alcanza {referencia} %. Conviene una prueba geográfica.",
                           icon=":material/science:")
        with st.expander("Supuestos del cálculo"):
            st.markdown(
                "- Usuarios expuestos por semana = usuarios alcanzados / semanas de datos.\n"
                "- Tasa base = ventas atribuidas por Shapley / usuarios alcanzados.\n"
                "- Confianza del 95 % y poder del 80 %, con grupos de control y expuesto de distinto tamaño.\n"
                "- Es una estimación de planificación: la potencia final depende de la varianza real y del diseño del control.")

# ----------------------------------------------------------------- hoja de ruta
st.divider()
c1, c2, c3 = st.columns(3, border=True)
with c1:
    st.markdown("**:material/check_circle: Hecho en esta demo**")
    st.markdown("- Rutas de GA4 unidas a los pedidos del backend\n- Markov y Shapley con intervalo de confianza\n"
                "- Seis reglas como rango de referencia\n- Sensibilidad a la ventana (7 a 90 días)\n"
                "- Filtros por segmento, modelo y ventana\n- Estado del modelo y disparadores de reajuste")
with c2:
    st.markdown("**:material/arrow_circle_right: Siguiente, con los datos actuales**")
    st.markdown("- Prueba de incrementalidad en el canal a escalar\n- Calibrar el modelo con su resultado\n"
                "- Cargar las tablas `mart_*` a BigQuery y publicar en Looker Studio\n"
                "- Programar la corrida mensual y la carga diaria de KPIs")
with c3:
    st.markdown("**:material/database: Requiere datos nuevos o el cliente**")
    st.markdown("- client_id y session_id de GA4 en cada pedido\n- Costos de todos los canales y por campaña\n"
                "- Impresiones para medir el efecto de ver un anuncio\n- MMM con ROAS marginal (MMix Pilot)\n"
                "- Margen por producto")
