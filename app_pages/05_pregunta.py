"""Pregunta a los datos: chat con el intérprete, anclado en la vista actual y con herramientas de solo lectura."""
import streamlit as st

from dashboard_comun import api_key, contexto, interprete_disponible
from interprete.agente import Interprete

ctx = contexto()
v = ctx.vista

st.subheader("Pregunta a los datos")
st.caption(f"Responde con las cifras de la vista actual: {v.describir()}. Si cambias un filtro, la siguiente pregunta usa la nueva vista.")
if not interprete_disponible():
    st.info("No hay credenciales de Claude configuradas (ANTHROPIC_API_KEY como variable de entorno o en `st.secrets`). "
            "Sin ellas el chat devuelve la lectura automática de la vista.", icon=":material/key:")

SUGERENCIAS = [
    "¿Dónde pongo el próximo sol de marketing?",
    "¿Por qué este canal lidera y qué tan confiable es?",
    "¿Cambia la conclusión si cambio la ventana de atribución?",
    "¿Cómo rinde Paid Social por dispositivo?",
    "¿Qué prueba de incrementalidad haría primero?",
]
if "chat" not in st.session_state:
    st.session_state.chat = []

c1, c2 = st.columns([6, 1], vertical_alignment="center")
with c1:
    sugerida = st.pills("Sugerencias", SUGERENCIAS, key="sugerencia", label_visibility="collapsed")
with c2:
    if st.button("Limpiar", icon=":material/delete_sweep:", disabled=not st.session_state.chat):
        st.session_state.chat = []
        st.rerun()

for m in st.session_state.chat:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("meta"):
            st.caption(m["meta"])
        for a in m.get("advertencias", []):
            st.warning(a, icon=":material/fact_check:")

pregunta = st.chat_input("Pregunta sobre los resultados…")
if not pregunta and sugerida:
    pregunta = sugerida
    st.session_state.sugerencia = None

if pregunta:
    with st.chat_message("user"):
        st.markdown(pregunta)
    with st.chat_message("assistant"):
        with st.spinner("Consultando los datos…"):
            historial = [{"role": m["role"], "content": m["content"]} for m in st.session_state.chat]
            r = Interprete(api_key=api_key()).preguntar(v, pregunta, historial)
        st.markdown(r.texto)
        usos = f"Herramientas: {', '.join(r.herramientas)} · " if r.herramientas else ""
        meta = (f"{usos}{r.generado_con} · {r.segundos:.1f} s" if r.generado_con.startswith("llm:")
                else "Lectura automática por reglas (sin IA)")
        st.caption(meta)
        for a in r.advertencias:
            st.warning(a, icon=":material/fact_check:")
    st.session_state.chat += [{"role": "user", "content": pregunta},
                              {"role": "assistant", "content": r.texto, "meta": meta, "advertencias": r.advertencias}]
