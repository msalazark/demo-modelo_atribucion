"""Esquema de configuración por cliente (RQ-01 de docs/RQ_mejoras.md).

Reemplaza las constantes que hoy están repartidas en run_demo.py, dashboard_comun.py e
interprete/datos.py. Los valores de config/demo.yaml reproducen exactamente el comportamiento
actual de la demo; config/produccion.yaml es la plantilla para un cliente real.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from reglas_canal import META_SITE_SOURCE_NAME_DEFECTO, REGLAS_CANAL_UTM_DEFECTO, ReglaCanalUTM


class ConfigCliente(BaseModel):
    cliente: str
    modo: Literal["demo", "produccion"] = "demo"
    motor: Literal["duckdb", "bigquery"] = "duckdb"
    proyecto_gcp: str | None = None
    dataset_gcp: str | None = None

    zona_horaria: str = "America/Lima"
    moneda: str = "PEN"
    ruta_bd: str = "data/ecommerce.duckdb"

    ventana_analisis_meses: int = Field(12, gt=0)
    ventanas_atribucion_dias: list[int] = Field(default_factory=lambda: [7, 14, 30, 60, 90])
    ventana_vigente_dias: int = 30
    ventana_tiempo_dias: int = 90
    n_bootstrap: int = Field(30, gt=0)

    canales_pagados: list[str] = Field(default_factory=lambda: ["Paid Social", "Paid Search", "Display"])
    canales_no_invertibles: list[str] = Field(default_factory=lambda: ["Direct"])
    pasarelas: list[str] = Field(default_factory=list)
    # RQ-06: reglas de canal, evaluadas en orden; luego gclid -> Paid Search, fbclid en la URL sin
    # UTMs -> "Meta (sin UTM)", sin fuente -> Direct, el resto -> Unassigned.
    reglas_canal_utm: list[ReglaCanalUTM] = Field(default_factory=lambda: list(REGLAS_CANAL_UTM_DEFECTO))
    meta_site_source_name: list[str] = Field(default_factory=lambda: list(META_SITE_SOURCE_NAME_DEFECTO))
    estados_validos_pedido: list[str] = Field(default_factory=lambda: ["pagado"])
    campo_fecha_conversion: Literal["created_at", "paid_at"] = "created_at"
    dimensiones_segmentacion: dict[str, str] = Field(default_factory=dict)
    # RQ-11 / decisión abierta #3: quién "cierra" la venta. "ultima_sesion" es la definición
    # canónica de la sección 1; "ultimo_no_directo" ignora las sesiones Direct finales.
    variante_cierre: Literal["ultima_sesion", "ultimo_no_directo"] = "ultima_sesion"

    umbral_escalar: float = 1.2
    umbral_revisar: float = 0.8
    ratio_asistidor: float = 2.0
    brecha_modelos_pp: float = 3.0
    sobre_indice_pp: float = 3.0
    confianza_alta_ci: float = 2.0
    confianza_media_ci: float = 4.0
    confianza_alta_pedidos: int = 3000
    confianza_media_pedidos: int = 1000

    # RQ-13: escalabilidad y diagnóstico de Shapley. shapley_c=None activa la selección de la
    # regularización por validación cruzada; el valor fijo (1.0) es el que ya traía la demo y
    # garantiza no mover la cuota al adoptar la agregación por conjunto de canales.
    limite_jugadores_shapley: int = Field(12, gt=0)
    shapley_monte_carlo_permutaciones: int = Field(200, gt=0)
    shapley_c: float | None = 1.0

    # RQ-12: variante de Markov vigente
    markov_orden: Literal[1, 2] = 1
    markov_excluir_direct: bool = False
    markov_ingreso_por_valor: bool = False

    # RQ-28: retención de eventos crudos (se aplica con privacidad.aplicar_retencion_eventos,
    # no automáticamente en cada corrida: ver docs/privacidad.md).
    retencion_eventos_meses: int = Field(13, gt=0)

    # RQ-14: con menos conversiones que esto en el corte, no se publica señal (ni en la vista
    # total ni en un segmento): "Evidencia insuficiente" en vez de Escalar/Revisar/etc.
    minimo_conversiones_senal: int = Field(1000, gt=0)

    # RQ-17: hilos para procesar segmentos en paralelo dentro de cada ventana. -1 = todos los
    # núcleos disponibles; 1 desactiva el paralelismo (útil para depurar).
    n_jobs: int = -1

    # RQ-21: CSV con resultados de experimentos de incrementalidad (holdout, geográfica, Conversion
    # Lift, etc.) cargado por el cliente; None o archivo inexistente = sin experimentos todavía
    # (mart_validacion__experimentos sale vacío, no es un error).
    ruta_experimentos: str | None = None

    @model_validator(mode="after")
    def _bigquery_necesita_proyecto(self) -> ConfigCliente:
        if self.motor == "bigquery" and not (self.proyecto_gcp and self.dataset_gcp):
            raise ValueError("motor=bigquery requiere proyecto_gcp y dataset_gcp")
        if self.ventana_vigente_dias not in self.ventanas_atribucion_dias:
            raise ValueError("ventana_vigente_dias debe estar en ventanas_atribucion_dias")
        return self
