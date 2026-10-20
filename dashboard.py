"""
Dashboard de atribución: filtros, paneles interactivos e intérprete de resultados.

Solo lee las tablas mart_* de DuckDB que genera run_demo.py; no calcula datos.

Uso:
  python run_demo.py
  streamlit run dashboard.py
"""
import duckdb
import streamlit as st

from dashboard_comun import DIMENSIONES, MODELOS, PAGADOS, VENTANAS, cargar, db_mtime
from interprete.datos import Lector

st.set_page_config(page_title="Atribución de canales", page_icon=":material/insights:", layout="wide")

try:
    datos = cargar(db_mtime())
    opciones = Lector().opciones()
except (duckdb.Error, FileNotFoundError):
    st.error("No encuentro las tablas de resultados. Ejecuta `python run_demo.py` para generarlas.")
    st.stop()

canales = sorted(datos["canal"].canal.unique())
ejec = datos["ejecucion"].iloc[0]

# Filtros globales: viven aquí para que se conserven al cambiar de página.
with st.sidebar:
    st.header("Filtros")
    st.segmented_control(
        "Ventana de atribución", VENTANAS, default=30, key="ventana", required=True,
        format_func=lambda d: f"{d} d",
        help="Días hacia atrás desde la compra en que un contacto cuenta para la venta. "
        "Con una ventana corta se pierden los primeros contactos.",
    )
    st.selectbox(
        "Modelo de atribución", list(MODELOS), key="modelo", format_func=lambda k: MODELOS[k][0],
        help="Cambia la cuota, el ROAS y las señales. Shapley es el recomendado; las reglas sirven de referencia.",
    )
    st.selectbox(
        "Segmentar por", DIMENSIONES, key="dim", format_func=lambda d: "Sin segmento" if d == "Todos" else d,
        help="Recalcula el modelo solo con los usuarios del segmento. Dentro de un segmento no hay costo por canal.",
    )
    dim = st.session_state.get("dim", "Todos")
    if dim != "Todos":
        st.selectbox("Segmento", opciones[dim], key=f"segmento_{dim}")
    st.pills("Tipo de canal", ["Pagados", "No pagados"], selection_mode="multi", default=["Pagados", "No pagados"],
             key="tipo_canal", help=f"Pagados: {', '.join(PAGADOS)}.")
    st.multiselect("Canales", canales, default=canales, key="canales_sel")
    st.toggle(
        "Excluir Direct de los rankings", value=True, key="excluir_directo",
        help="Direct es el regreso de usuarios que ya conocían la marca; no es un canal en el que se invierta.",
    )
    st.divider()
    st.caption(f":material/update: Ventana de análisis móvil: {ejec.inicio} a {ejec.corte} ({ejec.ventana_meses} meses). "
               f"Actualizado {ejec.ejecutado_en[:10]}. Datos sintéticos con la estructura del export de GA4.")

pg = st.navigation(
    [
        st.Page("app_pages/01_resumen.py", title="Resumen", icon=":material/dashboard:", default=True),
        st.Page("app_pages/02_explorar.py", title="Explorar", icon=":material/bar_chart:"),
        st.Page("app_pages/03_modelos.py", title="Modelos y robustez", icon=":material/science:"),
        st.Page("app_pages/04_siguientes_pasos.py", title="Siguientes pasos", icon=":material/flag:"),
        st.Page("app_pages/05_pregunta.py", title="Pregunta a los datos", icon=":material/chat:"),
    ]
)
pg.run()
