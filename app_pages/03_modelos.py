"""Modelos y robustez: comparación de modelos, roles, ventana de atribución y estado del modelo."""
import altair as alt
import pandas as pd
import streamlit as st

from dashboard_comun import MODELOS, NOMBRE_MODELO, barras, color_canal, contexto, estilo_canal

ctx = contexto()
v, rank = ctx.vista, ctx.rank
seg = "Todo el negocio" if v.dim == "Todos" else f"{v.dim}: {v.segmento}"
st.subheader(seg)
st.caption(f"Ventana de atribución {v.ventana_dias} días. Ningún modelo es «la verdad»: si todos coinciden la conclusión es firme; "
           "si no, depende del modelo.")

comp = ctx.comp[ctx.comp.canal.isin(rank.index)]
reglas = [k for k, (_, fam) in MODELOS.items() if fam == "Regla"]

tab_cmp, tab_ven, tab_rol, tab_est = st.tabs(
    [":material/compare: Comparar modelos", ":material/schedule: Ventana de atribución",
     ":material/swap_horiz: Roles", ":material/monitoring: Estado del modelo"])

# ----------------------------------------------------------------- comparar modelos
with tab_cmp:
    rango = comp[comp.modelo.isin(reglas)].groupby("canal").cuota_pct.agg(minimo="min", maximo="max").reset_index()
    rango["amplitud"] = rango.maximo - rango.minimo
    orden = comp[comp.modelo == "shapley"].sort_values("cuota_pct", ascending=False).canal.tolist()
    puntos = comp[comp.modelo.isin(["markov", "shapley", "efecto_real"])].assign(Modelo=lambda d: d.modelo.map(NOMBRE_MODELO))
    dominio = ["Markov", "Shapley", "Efecto real (sintético)"]
    y = alt.Y("canal:N", sort=orden, title=None)
    barra = alt.Chart(rango).mark_rule(strokeWidth=12, opacity=0.35, strokeCap="round").encode(
        y=y, x=alt.X("minimo:Q", title="% de las ventas atribuidas"), x2="maximo:Q", color=color_canal(),
        tooltip=["canal", alt.Tooltip("minimo:Q", format=".1f"), alt.Tooltip("maximo:Q", format=".1f")])
    marcas = alt.Chart(puntos).mark_point(filled=True, size=140, opacity=1).encode(
        y=y, x="cuota_pct:Q",
        shape=alt.Shape("Modelo:N", scale=alt.Scale(domain=dominio, range=["triangle-up", "circle", "diamond"]),
                        legend=alt.Legend(title="Modelo")),
        color=alt.Color("Modelo:N", scale=alt.Scale(domain=dominio, range=["#8A94A8", "#14213D", "#E03131"]), legend=None),
        tooltip=["canal", "Modelo", alt.Tooltip("cuota_pct:Q", title="Cuota %", format=".1f")])
    st.markdown("**Rango de crédito por canal** · la barra clara va del menor al mayor valor entre las seis reglas")
    st.altair_chart((barra + marcas).properties(height=max(240, 48 * len(rank))),
                    alt="Rango de crédito por canal entre las reglas, con Markov, Shapley y el efecto real")
    inest = rango[rango.amplitud >= 8].sort_values("amplitud", ascending=False)
    estable = rango[rango.amplitud < 4]
    if len(inest):
        st.info("**Dependen del modelo** (más de 8 pp entre reglas): "
                + ", ".join(f"{r.canal} ({r.minimo:.0f}–{r.maximo:.0f} %)" for r in inest.itertuples())
                + (". **Estables:** " + ", ".join(estable.canal) if len(estable) else "") + ".", icon=":material/straighten:")

    err = ctx.rebanada("error").assign(Modelo=lambda d: d.modelo.map(NOMBRE_MODELO),
                                       Familia=lambda d: d.modelo.map({k: f for k, (_, f) in MODELOS.items()})).sort_values("error_medio_pp")
    a, b = st.columns([3, 2], gap="large")
    with a:
        st.markdown("**¿Qué modelo se acerca más al efecto real?** (error medio, pp)")
        st.altair_chart(
            alt.Chart(err).mark_bar(cornerRadiusEnd=3).encode(
                y=alt.Y("Modelo:N", sort=err.Modelo.tolist(), title=None), x=alt.X("error_medio_pp:Q", title="Puntos porcentuales"),
                color=alt.Color("Familia:N", scale=alt.Scale(domain=["Data-driven", "Regla"], range=["#1940E2", "#A9B3C8"]),
                                legend=alt.Legend(title=None)), tooltip=["Modelo", "Familia", "error_medio_pp"],
            ).properties(height=max(220, 34 * len(err))), alt="Error medio de cada modelo frente al efecto real")
    with b:
        st.info("Solo se puede medir porque los datos son sintéticos y el generador conoce el efecto real. "
                "Con un cliente real se valida con pruebas de incrementalidad.", icon=":material/science:")
        with st.expander("Tabla de cuotas por modelo"):
            cols = [k for k in MODELOS if k in comp.modelo.unique()] + ["efecto_real"]
            piv = comp.pivot(index="canal", columns="modelo", values="cuota_pct").reindex(columns=cols).loc[orden]
            piv.columns = [NOMBRE_MODELO[c] for c in piv.columns]
            piv = piv.reset_index().rename(columns={"canal": "Canal"})
            st.dataframe(piv.style.map(estilo_canal, subset=["Canal"]), hide_index=True,
                         column_config={c: st.column_config.NumberColumn(format="%.1f %%") for c in piv.columns[1:]},
                         alt="Cuota de ventas por canal según cada modelo")

# ----------------------------------------------------------------- ventana
with tab_ven:
    todas = ctx.datos["comp"]
    s = todas[(todas.dim == v.dim) & (todas.segmento == v.segmento) & (todas.modelo == v.modelo) & todas.canal.isin(rank.index)]
    st.markdown(f"**Cuota por canal según la ventana** · {ctx.nombre_modelo}")
    lineas = alt.Chart(s).mark_line(point=True).encode(
        x=alt.X("ventana_dias:Q", title="Ventana de atribución (días)", scale=alt.Scale(type="sqrt"),
                axis=alt.Axis(values=sorted(s.ventana_dias.unique()))),
        y=alt.Y("cuota_pct:Q", title="% de las ventas atribuidas"), color=color_canal(legend=True),
        tooltip=["canal", "ventana_dias", "cuota_pct", "ranking"])
    vigente = alt.Chart(pd.DataFrame({"x": [v.ventana_dias]})).mark_rule(strokeDash=[4, 4], color="#14213D").encode(x="x:Q")
    st.altair_chart((lineas + vigente).properties(height=320), alt="Cuota por canal según la ventana de atribución")

    top = (s.sort_values(["ventana_dias", "ranking"]).groupby("ventana_dias")
           .agg(primero=("canal", "first"), top3=("canal", lambda c: " > ".join(list(c)[:3]))).reset_index())
    errs = ctx.datos["error"]
    errs = errs[(errs.dim == v.dim) & (errs.segmento == v.segmento) & (errs.modelo == v.modelo)][["ventana_dias", "error_medio_pp"]]
    ped = ctx.datos["conciliacion"][["ventana_dias", "pedidos_con_ruta"]]
    tabla = top.merge(errs, on="ventana_dias").merge(ped, on="ventana_dias").rename(
        columns={"ventana_dias": "Ventana (días)", "top3": "Ranking (top 3)", "error_medio_pp": "Error vs. real (pp)",
                 "pedidos_con_ruta": "Pedidos con ruta"}).drop(columns="primero")
    st.dataframe(tabla, hide_index=True, column_config={
        "Pedidos con ruta": st.column_config.NumberColumn(format="%,d"),
        "Error vs. real (pp)": st.column_config.NumberColumn(format="%.2f")}, alt="Ranking de canales por ventana")
    if top.primero.nunique() == 1:
        st.success(f"**{top.primero.iloc[0]}** es el canal #1 en las {len(top)} ventanas probadas: la conclusión no depende de la ventana.",
                   icon=":material/check_circle:")
    else:
        lid = top.groupby("primero").ventana_dias.apply(lambda x: f"{x.min()} a {x.max()} días" if len(x) > 1 else f"{x.iloc[0]} días")
        st.warning("El canal #1 cambia según la ventana: " + "; ".join(f"**{c}** con {w}" for c, w in lid.items())
                   + ". La recomendación es sensible a esta decisión.", icon=":material/warning:")
    st.caption("Las plataformas (Meta, Google Ads) usan sus propias ventanas; por eso sus cifras no cuadran con las de este reporte.")

# ----------------------------------------------------------------- roles
with tab_rol:
    a, b = st.columns(2, border=True)
    with a:
        st.markdown("**Abridor** · % de las rutas que empiezan en el canal")
        st.altair_chart(barras(rank, "p_apertura_pct", "% de las rutas"), alt="Probabilidad de abrir la ruta por canal")
    with b:
        st.markdown("**Conversor** · % de las visitas al canal que terminan en compra")
        st.altair_chart(barras(rank, "p_cierre_pct", "% de las visitas"), alt="Probabilidad de cierre por canal")
    pc = rank.p_continua_pct
    st.caption(f"El % de visitas tras las que el usuario sigue a otro canal es casi igual en todos ({pc.min():.0f}–{pc.max():.0f} %): "
               "con Markov de primer orden la asistencia no se distingue; se mide con la brecha frente al último clic (Resumen) "
               "y con las asistencias por cierre (Explorar).")

# ----------------------------------------------------------------- estado del modelo
with tab_est:
    ej = ctx.ejec
    st.markdown(f"**¿Cambió el modelo respecto del mes anterior?** · Shapley, total, ventana de {int(ej.ventana_dias)} días")
    e = ctx.datos["estado"].rename(columns={"canal": "Canal", "cuota_actual": "Cuota actual %", "p05": "Piso 90 %", "p95": "Techo 90 %",
                                            "cuota_previa": "Cuota mes anterior %", "cambio_pp": "Cambio (pp)", "estado": "Estado"})
    st.dataframe(
        e.drop(columns="corte_previo").style.map(estilo_canal, subset=["Canal"]).map(
            lambda s: "background-color:#D3F9D8;color:#1B5E20;font-weight:600" if s == "estable"
            else "background-color:#FFE3E3;color:#9B1C1C;font-weight:600", subset=["Estado"]),
        hide_index=True, alt="Estado de la cuota de cada canal frente al mes anterior",
        column_config={c: st.column_config.NumberColumn(format="%.1f") for c in ["Cuota actual %", "Piso 90 %", "Techo 90 %",
                                                                                  "Cuota mes anterior %"]}
        | {"Cambio (pp)": st.column_config.NumberColumn(format="%+.1f")},
    )
    st.caption(f"«Cambió» = la cuota del mes anterior (corte {e.corte_previo.iloc[0]}) queda fuera del intervalo del 90 % de la cuota actual. "
               "Con una ventana de 12 meses que solo avanza uno, cambios grandes son una señal real.")
    st.markdown("**Disparadores de reajuste anticipado** · últimos 60 días frente a los 60 previos")
    d = ctx.datos["disparadores"].rename(columns={"regla": "Regla", "ultimos_60d": "Últimos 60 d", "60d_previos": "60 d previos",
                                                  "cambio": "Cambio", "umbral": "Umbral", "unidad": "Unidad", "estado": "Estado"})
    st.dataframe(
        d.style.map(lambda s: "background-color:#FFE3E3;color:#9B1C1C;font-weight:600" if s == "alerta"
                    else "background-color:#D3F9D8;color:#1B5E20;font-weight:600", subset=["Estado"]),
        hide_index=True, alt="Reglas que sugieren reajustar el modelo antes de tiempo",
        column_config={c: st.column_config.NumberColumn(format="%.1f") for c in ["Últimos 60 d", "60 d previos", "Cambio", "Umbral"]},
    )
    st.info("**Cadencia sugerida.** Datos y KPIs: diaria o semanal. Modelos de atribución: mensual (trimestral si el volumen es bajo). "
            "Pruebas de incrementalidad: trimestral por canal grande. Reajusta antes si hay una alerta arriba o canales «cambió».",
            icon=":material/event_repeat:")
