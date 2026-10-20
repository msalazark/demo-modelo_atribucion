"""
Acceso de solo lectura a las tablas mart_* y armado de los "hechos" que el intérprete puede citar.

Todo número que aparece en una interpretación sale de aquí: el LLM no calcula ni inventa cifras.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import duckdb
import pandas as pd

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "ecommerce.duckdb"
VENTANA_VIGENTE = 30
CANALES_NO_INVERTIBLES = ("Direct",)
REGLAS = ["primer_clic", "ultimo_clic", "ultimo_no_directo", "lineal", "posicion_u", "decaimiento_temporal"]
TABLAS = {  # lista blanca: las herramientas del agente solo pueden leer estas
    "mart_decision__canal", "mart_modelos__comparativo", "mart_decision__senal", "mart_calidad__error_modelo",
    "mart_calidad__conciliacion", "mart_kpi__mensual", "mart_estado__modelo", "mart_estado__disparadores",
    "mart_tiempo__a_compra", "mart_tiempo__histograma", "mart_siguientes_pasos__prueba_incrementalidad",
    "mart_ejecucion", "mart_narrativa",
}


@dataclass(frozen=True)
class Vista:
    """Lo que el usuario está mirando en el dashboard: los filtros activos."""

    ventana_dias: int = VENTANA_VIGENTE
    dim: str = "Todos"
    segmento: str = "Todos"
    modelo: str = "shapley"
    canales: tuple[str, ...] | None = None  # None = todos
    excluir_directo: bool = True

    def clave(self) -> str:
        return hashlib.sha1(json.dumps(asdict(self), sort_keys=True, default=str).encode()).hexdigest()[:12]

    @property
    def es_por_defecto(self) -> bool:
        return self == Vista()

    def describir(self) -> str:
        seg = "todo el negocio" if self.dim == "Todos" else f"{self.dim.lower()}: {self.segmento}"
        return f"{seg}, ventana de {self.ventana_dias} días, modelo {self.modelo}"


class Lector:
    """Lee las tablas mart_* abriendo y cerrando la conexión en cada consulta (no bloquea run_demo.py)."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = str(db_path)

    def consulta(self, tabla: str, donde: str = "", params: list | None = None) -> pd.DataFrame:
        if tabla not in TABLAS:
            raise ValueError(f"Tabla no permitida: {tabla}")
        con = duckdb.connect(self.db_path, read_only=True)
        try:
            return con.execute(f"SELECT * FROM {tabla} {donde}", params or []).df()
        finally:
            con.close()

    def rebanada(self, tabla: str, v: Vista, **extra) -> pd.DataFrame:
        condiciones = ["ventana_dias = ?", "dim = ?", "segmento = ?"]
        params: list = [v.ventana_dias, v.dim, v.segmento]
        for col, valor in extra.items():
            condiciones.append(f"{col} = ?")
            params.append(valor)
        return self.consulta(tabla, "WHERE " + " AND ".join(condiciones), params)

    def opciones(self) -> dict[str, list[str]]:
        """Valores disponibles por dimensión de segmento."""
        df = self.consulta("mart_decision__canal", "WHERE ventana_dias = ?", [VENTANA_VIGENTE])[["dim", "segmento"]]
        return {d: sorted(g.segmento.unique()) for d, g in df.drop_duplicates().groupby("dim")}


def _r(x, n=1):
    return None if x is None or pd.isna(x) else round(float(x), n)


def construir_hechos(v: Vista, lector: Lector | None = None) -> dict:
    """Todo lo que se puede afirmar sobre la vista actual, listo para citar."""
    lector = lector or Lector()
    canal = lector.rebanada("mart_decision__canal", v).set_index("canal")
    comp = lector.rebanada("mart_modelos__comparativo", v)
    sen = lector.rebanada("mart_decision__senal", v, modelo=v.modelo).set_index("canal")
    ejec = lector.consulta("mart_ejecucion").iloc[0]
    conc = lector.consulta("mart_calidad__conciliacion", "WHERE ventana_dias = ?", [v.ventana_dias]).iloc[0]

    por_modelo = comp[comp.modelo == v.modelo].set_index("canal")
    unc = comp[comp.modelo == "ultimo_no_directo"].set_index("canal").cuota_pct
    rango = comp[comp.modelo.isin(REGLAS)].groupby("canal").cuota_pct.agg(["min", "max"])

    canales = []
    for c in canal.index:
        if v.canales is not None and c not in v.canales:
            continue
        m, s, p = canal.loc[c], sen.loc[c], por_modelo.loc[c]
        canales.append({
            "canal": c, "es_pagado": bool(m.es_pagado), "es_palanca_de_inversion": c not in CANALES_NO_INVERTIBLES,
            "senal": s.senal, "motivo": s.motivo, "confianza": s.confianza,
            "cuota_pct": _r(p.cuota_pct), "cuota_ultimo_clic_no_directo_pct": _r(unc.get(c)),
            "brecha_vs_ultimo_clic_pp": _r(s.brecha_vs_ultimo_clic_pp),
            "rango_cuota_entre_reglas_pct": [_r(rango.loc[c, "min"]), _r(rango.loc[c, "max"])],
            "roas": _r(p.roas, 2), "cpa_soles": _r(p.cpa, 1), "costo_soles": _r(p.costo, 0),
            "usuarios_alcanzados": int(m.usuarios_alcanzados), "usuarios_nuevos": int(m.usuarios_nuevos),
            "conversiones_asistidas": int(m.conv_asistidas), "conversiones_cerradas": int(m.conv_cerradas),
            "asistencias_por_cierre": _r(m.ratio_asistencia, 2),
            "conversion_por_usuario_pct": _r(m.tasa_conv_usuario_pct, 2),
            "prob_abrir_ruta_pct": _r(m.p_apertura_pct), "prob_cerrar_en_visita_pct": _r(m.p_cierre_pct),
        })

    ranking = [c for c in canales if not (v.excluir_directo and not c["es_palanca_de_inversion"])]

    def mejor(clave: str) -> dict | None:
        cand = sorted((c for c in ranking if c[clave] is not None), key=lambda c: c[clave], reverse=True)
        if not cand:
            return None
        return {"canal": cand[0]["canal"], "valor": cand[0][clave],
                "segundo": cand[1]["canal"] if len(cand) > 1 else None}

    kpi = lector.consulta("mart_kpi__mensual").sort_values("periodo")
    ult, ant = kpi.iloc[-1], kpi.iloc[-2]
    cols = ["pedidos", "ingresos", "inversion_medios", "mer", "cpa_blended", "conv_sesion_pct"]
    err = lector.rebanada("mart_calidad__error_modelo", v)
    numero_1 = lector.consulta(
        "mart_modelos__comparativo", "WHERE dim = ? AND segmento = ? AND modelo = ? AND ranking = 1",
        [v.dim, v.segmento, v.modelo],
    ).sort_values("ventana_dias")

    estado = lector.consulta("mart_estado__modelo")
    disp = lector.consulta("mart_estado__disparadores")
    tcan = lector.consulta("mart_tiempo__a_compra").query("canal_apertura == '(todos)'").iloc[0]
    thist = lector.consulta("mart_tiempo__histograma").sort_values("dias_desde")
    inc = lector.consulta("mart_siguientes_pasos__prueba_incrementalidad")

    objetivo = next((c["canal"] for c in canales if c["senal"] == "Escalar (validar)"), None)
    prueba = None
    if objetivo is not None and (inc.canal == objetivo).any():
        del_canal = inc[inc.canal == objetivo].sort_values("emd_relativo_pct")
        viables = del_canal[del_canal.emd_relativo_pct <= 30]
        cfg = viables.sort_values(["holdout_pct", "semanas"]).iloc[0] if len(viables) else del_canal.iloc[0]
        d10 = del_canal[(del_canal.holdout_pct == 10) & (del_canal.semanas == del_canal.semanas.max())]
        prueba = {
            "canal_a_validar": objetivo, "referencia_emd_pct": 30,
            "mejor_configuracion": {"semanas": int(cfg.semanas), "control_pct": int(cfg.holdout_pct),
                                    "emd_relativo_pct": _r(cfg.emd_relativo_pct, 0)},
            "alcanza_la_referencia": bool(len(viables)),
            "emd_con_control_10_pct_y_maxima_duracion_pct": _r(d10.emd_relativo_pct.iloc[0], 0) if len(d10) else None,
        }

    return {
        "vista": {"ventana_atribucion_dias": v.ventana_dias, "segmento": f"{v.dim}: {v.segmento}", "modelo": v.modelo,
                  "en_segmento_no_hay_costo_por_canal": v.dim != "Todos"},
        "ventana_de_analisis": {"inicio": str(ejec.inicio), "corte": str(ejec.corte), "meses": int(ejec.ventana_meses),
                                "ejecutado_en": str(ejec.ejecutado_en), "pedidos_con_ruta": int(conc.pedidos_con_ruta),
                                "pedidos_backend": int(conc.pedidos_backend)},
        "canales": canales,
        "mejores": {"alcance": mejor("usuarios_alcanzados"), "usuarios_nuevos": mejor("usuarios_nuevos"),
                    "asistidor_por_volumen": mejor("conversiones_asistidas"),
                    "conversion_por_usuario": mejor("conversion_por_usuario_pct")},
        "kpi_ultimo_mes": {"mes": ult.periodo, **{k: _r(ult[k], 2) for k in cols}},
        "kpi_mes_anterior": {"mes": ant.periodo, **{k: _r(ant[k], 2) for k in cols}},
        "error_de_cada_modelo_vs_efecto_real_pp": {r.modelo: _r(r.error_medio_pp, 2) for r in err.itertuples()},
        "nota_error": "Solo medible porque los datos son sintéticos; con un cliente real no existe.",
        "canal_numero_1_segun_ventana": [{"ventana_dias": int(r.ventana_dias), "canal": r.canal}
                                         for r in numero_1.itertuples()],
        "estado_del_modelo": [
            {"canal": r.canal, "cuota_actual_pct": _r(r.cuota_actual), "intervalo_90_pct": [_r(r.p05), _r(r.p95)],
             "cuota_mes_anterior_pct": _r(r.cuota_previa), "estado": r.estado} for r in estado.itertuples()],
        "disparadores_de_reajuste": [
            {"regla": r.regla, "cambio": _r(r.cambio), "unidad": r.unidad, "umbral": r.umbral, "estado": r.estado}
            for r in disp.itertuples()],
        "tiempo_hasta_la_compra": {"mediana_dias": _r(tcan.dias_p50), "percentil_90_dias": _r(tcan.dias_p90),
                                   "pct_de_compras_en_el_ultimo_tramo": _r(thist.pct.iloc[-1]),
                                   "ventana_medida_dias": int(tcan.ventana_dias)},
        "prueba_de_incrementalidad": prueba,
    }
