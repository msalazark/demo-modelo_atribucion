"""Pruebas de reglas_canal.py (RQ-06): orden 1) UTMs, 2) gclid -> Paid Search, 3) fbclid en la
URL sin UTMs -> "Meta (sin UTM)", 4) sin fuente -> Direct, 5) el resto -> Unassigned."""
import pytest

from reglas_canal import asignar_canal, sql_case_canal, sql_es_pasarela

# (source, medium, gclid, fbclid_en_url) -> canal esperado
CASOS = [
    (None, None, None, False, "Direct"),
    ("fb", "cpc", None, False, "Paid Social"),
    ("facebook", "paid", None, False, "Paid Social"),
    ("instagram", "ppc", None, False, "Paid Social"),
    ("tiktok", "retargeting", None, False, "Paid Social"),
    ("linkedin", "cpc", None, False, "Paid Social"),
    ("m.facebook.com", "cpc", None, False, "Paid Social"),
    ("l.facebook.com", "ppc", None, False, "Paid Social"),
    ("msg", "cpc", None, False, "Paid Social"),       # site_source_name de Meta
    ("an", "paid", None, False, "Paid Social"),       # site_source_name de Meta (Audience Network)
    ("google", "cpc", None, False, "Paid Search"),
    ("bing", "ppc", None, False, "Paid Search"),
    ("yahoo", "paid_search", None, False, "Paid Search"),
    ("google", "display", None, False, "Display"),     # medium gana: no matchea el regex de pago
    (None, "banner", None, False, "Display"),          # UTM antes que "sin fuente" (orden RQ-06)
    (None, "organic", None, False, "Organic Search"),
    ("google", "organic", None, False, "Organic Search"),
    (None, "email", None, False, "Email"),
    ("newsletter", "e-mail", None, False, "Email"),
    ("newsletter", "e_mail", None, False, "Email"),
    ("newsletter", "e mail", None, False, "Email"),
    ("someblog.com", "referral", None, False, "Referral"),
    (None, None, "Cj0abc123", False, "Paid Search"),          # gclid, sin UTMs
    ("google", "cpc", "Cj0abc123", False, "Paid Search"),     # UTM ya resuelve: gclid no se mira
    (None, None, None, True, "Meta (sin UTM)"),               # fbclid en la URL, sin UTMs ni gclid
    (None, None, "Cj0abc123", True, "Paid Search"),           # gclid antes que fbclid (orden RQ-06)
    ("google", None, None, False, "Unassigned"),              # source sin medium: ninguna regla calza
    ("unknownsource", "unknownmedium", None, False, "Unassigned"),
]


@pytest.mark.parametrize("source,medium,gclid,fbclid,esperado", CASOS)
def test_asignar_canal_tabla_de_casos(source, medium, gclid, fbclid, esperado):
    assert asignar_canal(source, medium, gclid, fbclid) == esperado


def test_al_menos_25_casos_cubiertos():
    assert len(CASOS) >= 25


def test_sql_case_canal_tiene_el_mismo_orden_que_asignar_canal():
    """El SQL generado debe traer, en el mismo orden, todas las reglas UTM más los 4 WHEN finales."""
    from reglas_canal import META_SITE_SOURCE_NAME_DEFECTO, REGLAS_CANAL_UTM_DEFECTO

    sql = sql_case_canal(REGLAS_CANAL_UTM_DEFECTO, META_SITE_SOURCE_NAME_DEFECTO)
    assert sql.index("Paid Social") < sql.index("Paid Search") < sql.index("Display")
    assert sql.index("Display") < sql.index("gclid IS NOT NULL")
    assert sql.index("gclid IS NOT NULL") < sql.index("fbclid=")
    assert sql.index("fbclid=") < sql.index("source IS NULL")
    assert sql.rstrip().endswith("END")


def test_sql_es_pasarela_vacio_es_false():
    assert sql_es_pasarela([]) == "FALSE"


def test_sql_es_pasarela_genera_in_list():
    assert "niubiz.com.pe" in sql_es_pasarela(["niubiz.com.pe"])
