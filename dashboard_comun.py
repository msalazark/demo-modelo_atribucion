"""
Piezas compartidas por las páginas del dashboard: colores, carga de datos, filtros y contexto.

No calcula datos: solo lee las tablas mart_* de DuckDB que genera run_demo.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import altair as alt
import duckdb
import pandas as pd
import streamlit as st

from interprete.agente import Interprete, credenciales_probables
from interprete.datos import Vista

DB_PATH = Path(__file__).parent / "data" / "ecommerce.duckdb"
NO_INVERTIBLES = ["Direct"]  # no es un canal sobre el que se decida presupuesto
PAGADOS = ["Paid Social", "Paid Search", "Display"]
VENTANAS = [7, 14, 30, 60, 90]
DIMENSIONES = ["Todos", "Dispositivo", "Región", "Tipo de cliente", "Categoría"]

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
    "Sobre-índice": ("#D3F9D8", "#1B5E20"),
    "Sub-índice": ("#FFE3E3", "#9B1C1C"),
    "Igual al total": ("#F1F3F5", "#495057"),
    "No es palanca": ("#F1F3F5", "#868E96"),
}
CONFIANZA_BADGE = {"alta": "green", "media": "orange", "baja": "red"}

# Nombres legibles de los modelos y su familia (reglas fijas vs. aprendidos de los datos)
MODELOS = {
    "shapley": ("Shapley", "Data-driven"),
    "markov": ("Markov", "Data-driven"),
    "ultimo_no_directo": ("Último clic no directo", "Regla"),
    "ultimo_clic": ("Último clic", "Regla"),
    "primer_clic": ("Primer clic", "Regla"),
    "lineal": ("Lineal", "Regla"),
    "posicion_u": ("Posición (U)", "Regla"),
    "decaimiento_temporal": ("Decaimiento temporal", "Regla"),
}
NOMBRE_MODELO = {k: v[0] for k, v in MODELOS.items()} | {"efecto_real": "Efecto real (sintético)"}


# ----------------------------------------------------------------- estilo
def color_canal(legend: bool = False) -> alt.Color:
    """Escala de color fija: el canal conserva su color aunque se filtren otros."""
    return alt.Color(
        "canal:N",
        scale=alt.Scale(domain=list(CANAL_COLORS), range=list(CANAL_COLORS.values())),
        legend=alt.Legend(title=None) if legend else None,
    )


def canal_con_punto(canal: str) -> str:
    return f'<span style="color:{CANAL_COLORS.get(canal, "#868E96")}">●</span> {canal}'


def titulo_canal(canal: str, tam: str = "1.75rem") -> None:
    st.html(f'<div style="font-size:{tam};font-weight:600;line-height:1.3">{canal_con_punto(canal)}</div>')


def estilo_canal(v: str) -> str:
    """Para Styler.map sobre una columna de nombres de canal."""
    return f"color:{CANAL_COLORS.get(v, '#868E96')};font-weight:700"


def estilo_senal(v: str) -> str:
    bg, fg = SENAL_COLORS.get(v, ("#F1F3F5", "#495057"))
    return f"background-color:{bg};color:{fg};font-weight:600"


def barras(df: pd.DataFrame, x: str, titulo_x: str, alto: int | None = None) -> alt.Chart:
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
        .properties(height=alto or max(160, 34 * len(d)))
    )


# ----------------------------------------------------------------- datos
TABLAS = {
    "canal": "mart_decision__canal",
    "comp": "mart_modelos__comparativo",
    "senal": "mart_decision__senal",
    "pares": "mart_decision__pares_asistencia",
    "rutas": "mart_decision__rutas_top",
    "error": "mart_calidad__error_modelo",
    "conciliacion": "mart_calidad__conciliacion",
    "kpi": "mart_kpi__mensual",
    "estado": "mart_estado__modelo",
    "disparadores": "mart_estado__disparadores",
    "t_canal": "mart_tiempo__a_compra",
    "t_hist": "mart_tiempo__histograma",
    "incrementalidad": "mart_siguientes_pasos__prueba_incrementalidad",
    "ejecucion": "mart_ejecucion",
    "narrativa": "mart_narrativa",
}


def db_mtime() -> float:
    return DB_PATH.stat().st_mtime if DB_PATH.exists() else 0.0


@st.cache_data(ttl="1h")
def cargar(_mtime: float) -> dict[str, pd.DataFrame]:
    """Lee las tablas mart_* de DuckDB. No calcula nada: la lógica vive en run_demo.py.

    La conexión se abre y se cierra en cada carga para no bloquear el archivo cuando se vuelve a
    correr run_demo.py con el dashboard abierto. `_mtime` invalida la caché cuando el archivo cambia.
    """
    con = duckdb.connect(str(DB_PATH), read_only=True)
    try:
        return {k: con.sql(f"SELECT * FROM {t}").df() for k, t in TABLAS.items()}
    finally:
        con.close()


def api_key() -> str | None:
    """Credencial para el intérprete: st.secrets o variable de entorno; nunca va en el código."""
    try:
        return st.secrets.get("ANTHROPIC_API_KEY") or None
    except Exception:  # sin archivo de secretos
        return os.getenv("ANTHROPIC_API_KEY") or None


def interprete_disponible() -> bool:
    return credenciales_probables(api_key())


@st.cache_data(ttl="6h", show_spinner=False)
def interpretar(clave: str, tipo: str, _vista: Vista, _mtime: float) -> dict:
    """Interpretación en vivo (opción B), cacheada por vista: la misma vista no vuelve a gastar API."""
    r = Interprete(api_key=api_key()).interpretar(_vista, tipo)
    return {"texto": r.texto, "generado_con": r.generado_con, "advertencias": r.advertencias,
            "segundos": r.segundos, "tokens": r.tokens_entrada + r.tokens_salida}


# ----------------------------------------------------------------- contexto
@dataclass
class Ctx:
    """Todo lo que una página necesita, ya filtrado por los controles del menú lateral."""

    datos: dict[str, pd.DataFrame]
    vista: Vista
    ejec: pd.Series
    conc: pd.Series
    kpi: pd.DataFrame
    tabla: pd.DataFrame  # índice canal: métricas del canal + cuota/ROAS del modelo elegido + señal
    m: pd.DataFrame  # canales seleccionados
    rank: pd.DataFrame  # seleccionados, sin Direct si se pidió excluirlo
    comp: pd.DataFrame  # todos los modelos de la rebanada, filas largas
    pedidos: int
    es_segmento: bool

    def rebanada(self, nombre: str) -> pd.DataFrame:
        df = self.datos[nombre]
        v = self.vista
        return df[(df.ventana_dias == v.ventana_dias) & (df.dim == v.dim) & (df.segmento == v.segmento)]

    @property
    def nombre_modelo(self) -> str:
        return NOMBRE_MODELO[self.vista.modelo]


def contexto() -> Ctx:
    """Arma el contexto a partir de los filtros del menú lateral (definidos en dashboard.py)."""
    datos = cargar(db_mtime())
    s = st.session_state
    dim = s["dim"]
    v = Vista(ventana_dias=int(s["ventana"]), dim=dim, segmento="Todos" if dim == "Todos" else s[f"segmento_{dim}"],
              modelo=s["modelo"], canales=tuple(s["canales_sel"]), excluir_directo=s["excluir_directo"])
    ctx = Ctx(datos=datos, vista=v, ejec=datos["ejecucion"].iloc[0], conc=pd.Series(dtype=float),
              kpi=datos["kpi"].sort_values("periodo").reset_index(drop=True), tabla=pd.DataFrame(), m=pd.DataFrame(),
              rank=pd.DataFrame(), comp=pd.DataFrame(), pedidos=0, es_segmento=dim != "Todos")
    conc = datos["conciliacion"]
    ctx.conc = conc[conc.ventana_dias == v.ventana_dias].iloc[0]
    canal = ctx.rebanada("canal").set_index("canal")
    ctx.comp = ctx.rebanada("comp")
    cm = ctx.comp[ctx.comp.modelo == v.modelo].set_index("canal")
    sen = ctx.rebanada("senal")
    sen = sen[sen.modelo == v.modelo].set_index("canal")
    ctx.tabla = canal.join(cm[["conversiones", "cuota_pct", "ingresos", "roas", "cpa", "cuota_p05", "cuota_p95", "ranking"]]
                           .rename(columns={"ranking": "ranking_modelo"})).join(sen[["senal", "motivo", "confianza",
                                                                                      "brecha_vs_ultimo_clic_pp"]])
    ctx.pedidos = int(canal.conv_cerradas.sum())
    tipos = s["tipo_canal"] or ["Pagados", "No pagados"]
    permitidos = [c for c in ctx.tabla.index if ((c in PAGADOS) and "Pagados" in tipos) or
                  ((c not in PAGADOS) and "No pagados" in tipos)]
    sel = [c for c in s["canales_sel"] if c in permitidos]
    ctx.m = ctx.tabla.loc[sel]
    ctx.rank = ctx.m.drop(index=NO_INVERTIBLES, errors="ignore") if s["excluir_directo"] else ctx.m
    if ctx.rank.empty:
        st.warning("Selecciona al menos un canal (revisa «Tipo de canal» y «Canales» en el menú lateral).")
        st.stop()
    return ctx


# ----------------------------------------------------------------- piezas reutilizables
def evidencia(pedidos: int) -> str:
    return "alta" if pedidos >= 3000 else "media" if pedidos >= 1000 else "baja"


def panel_interpretacion(ctx: Ctx, tipo: str, titulo: str) -> None:
    """Interpretación de la vista: pregenerada (C) si es la vista por defecto, y bajo demanda con IA (B)."""
    from interprete import plantilla
    from interprete.datos import construir_hechos

    v = ctx.vista
    with st.container(border=True):
        st.markdown(f"**{titulo}**")
        nar = ctx.datos["narrativa"]
        previa = nar[(nar.tipo == tipo)] if v.es_por_defecto and len(nar) else nar.iloc[0:0]
        clave = f"ia_{tipo}_{v.clave()}"
        if clave in st.session_state:
            r = st.session_state[clave]
        elif len(previa) and previa.iloc[0].generado_con.startswith("llm:"):
            p = previa.iloc[0]
            r = {"texto": p.texto, "generado_con": p.generado_con,
                 "advertencias": [a for a in str(p.advertencias).split(" | ") if a and a != "nan"],
                 "pregenerado": p.generado_en}
        else:
            hechos = construir_hechos(v)
            texto = plantilla.resumen(hechos) if tipo == "resumen" else plantilla.siguientes_pasos(hechos)
            r = {"texto": texto, "generado_con": "plantilla", "advertencias": []}
        st.markdown(r["texto"])
        pie = []
        if r["generado_con"].startswith("llm:"):
            pie.append(f":material/auto_awesome: {r['generado_con'][4:]}"
                       + (f" · pregenerado {r['pregenerado'][:10]}" if r.get("pregenerado") else " · en vivo"))
        else:
            pie.append(":material/rule: Lectura automática por reglas (sin IA)")
        st.caption(" · ".join(pie))
        for a in r["advertencias"]:
            st.warning(a, icon=":material/fact_check:")
        if not r["generado_con"].startswith("llm:"):
            if interprete_disponible():
                if st.button("Interpretar con IA", key=f"btn_{clave}", icon=":material/auto_awesome",
                             help="Claude redacta la interpretación con las cifras de esta vista y las verifica."):
                    with st.spinner("Interpretando…"):
                        st.session_state[clave] = interpretar(v.clave(), tipo, v, db_mtime())
                    st.rerun()
            else:
                st.caption("Para una interpretación con IA configura ANTHROPIC_API_KEY (variable de entorno o st.secrets).")
