"""Reglas de canal configurables (RQ-06 de docs/RQ_mejoras.md).

El canal de una sesión se decide, en orden:
  1. UTMs (`utm_source`/`utm_medium`, aquí `source`/`medium`) con listas y expresiones regulares.
  2. Identificadores de clic: `gclid` -> Paid Search; `fbclid` en la URL sin UTMs -> "Meta (sin UTM)"
     (canal propio, para medir cuánto tráfico de Meta llega sin etiquetar).
  3. Sin fuente -> Direct.
  4. Lo que no calce -> Unassigned.

`asignar_canal()` es la misma lógica en Python puro (para pruebas con muchos casos a mano);
`sql_case_canal()`/`sql_es_pasarela()` generan el SQL equivalente a partir de la config, que
`run_demo._sql()` sustituye en `sql/01_sesiones.sql`.
"""
from __future__ import annotations

import re

from pydantic import BaseModel, Field


class ReglaCanalUTM(BaseModel):
    canal: str
    medio_regex: str | None = None  # si se da, se usa en vez de `medios`
    medios: list[str] = Field(default_factory=list)
    fuentes: list[str] = Field(default_factory=list)  # vacío = no filtra por fuente


REGLAS_CANAL_UTM_DEFECTO = [
    ReglaCanalUTM(canal="Paid Social", medio_regex=r"^(.*cp.*|ppc|retargeting|paid.*)$",
                 fuentes=["fb", "ig", "facebook", "instagram", "m.facebook.com", "l.facebook.com",
                          "tiktok", "linkedin"]),
    ReglaCanalUTM(canal="Paid Search", medio_regex=r"^(.*cp.*|ppc|retargeting|paid.*)$",
                 fuentes=["google", "bing", "yahoo"]),
    ReglaCanalUTM(canal="Display", medios=["display", "banner", "cpm", "interstitial", "expandable"]),
    ReglaCanalUTM(canal="Organic Search", medios=["organic"]),
    ReglaCanalUTM(canal="Email", medios=["email", "e-mail", "e_mail", "e mail"]),
    ReglaCanalUTM(canal="Referral", medios=["referral"]),
]
META_SITE_SOURCE_NAME_DEFECTO = ["fb", "ig", "msg", "an"]


def _coincide_utm(source: str | None, medium: str | None, regla: ReglaCanalUTM,
                   meta_site_source_name: list[str]) -> bool:
    fuentes = regla.fuentes
    if regla.canal == "Paid Social" and fuentes:
        fuentes = [*fuentes, *meta_site_source_name]
    if regla.medio_regex is not None:
        if medium is None or not re.match(regla.medio_regex, medium.lower()):
            return False
    elif medium is None or medium.lower() not in regla.medios:
        return False
    if fuentes and (source is None or source.lower() not in fuentes):
        return False
    return True


def asignar_canal(
    source: str | None,
    medium: str | None,
    gclid: str | None = None,
    fbclid_en_url: bool = False,
    reglas_utm: list[ReglaCanalUTM] = REGLAS_CANAL_UTM_DEFECTO,
    meta_site_source_name: list[str] = META_SITE_SOURCE_NAME_DEFECTO,
) -> str:
    """Canal de una sesión según las reglas de RQ-06, en el mismo orden que `sql_case_canal()`."""
    for regla in reglas_utm:
        if _coincide_utm(source, medium, regla, meta_site_source_name):
            return regla.canal
    if gclid is not None:
        return "Paid Search"
    if fbclid_en_url:
        return "Meta (sin UTM)"
    if source is None:
        return "Direct"
    return "Unassigned"


def _lista_sql(valores: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in valores)


def sql_case_canal(reglas_utm: list[ReglaCanalUTM], meta_site_source_name: list[str]) -> str:
    """SQL `CASE` equivalente a `asignar_canal()`, para sustituir en sql/01_sesiones.sql."""
    lineas = ["CASE"]
    for regla in reglas_utm:
        fuentes = regla.fuentes
        if regla.canal == "Paid Social" and fuentes:
            fuentes = [*fuentes, *meta_site_source_name]
        condiciones = []
        if regla.medio_regex is not None:
            condiciones.append(f"regexp_matches(lower(medium), '{regla.medio_regex}')")
        elif regla.medios:
            condiciones.append(f"lower(medium) IN ({_lista_sql(regla.medios)})")
        if fuentes:
            condiciones.append(f"lower(source) IN ({_lista_sql(fuentes)})")
        lineas.append(f"  WHEN {' AND '.join(condiciones)} THEN '{regla.canal}'")
    lineas += [
        "  WHEN gclid IS NOT NULL THEN 'Paid Search'",
        "  WHEN page_location IS NOT NULL AND regexp_matches(page_location, 'fbclid=') THEN 'Meta (sin UTM)'",
        "  WHEN source IS NULL THEN 'Direct'",
        "  ELSE 'Unassigned'",
        "END",
    ]
    return "\n".join(lineas)


def sql_es_pasarela(pasarelas: list[str]) -> str:
    if not pasarelas:
        return "FALSE"
    return f"coalesce(lower(source) IN ({_lista_sql(pasarelas)}), FALSE)"
