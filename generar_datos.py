"""
Genera datos sintéticos de un ecommerce con la estructura del export de GA4
en BigQuery, más la tabla de pedidos del backend y los costos por canal.

Como los datos son sintéticos, la probabilidad real de conversión de cada
combinación de canales es conocida (PARAMS_REALES). Eso permite medir qué tan
cerca llega cada modelo de atribución al efecto real.

Salida: data/ecommerce.duckdb con las tablas
  events               -> imita analytics_XXXX.events_YYYYMMDD (una sola tabla con event_date)
  orders               -> pedidos del backend (fuente de verdad de la venta)
  costs                -> inversión diaria por canal y campaña pagada (RQ-09)
  impresiones          -> impresiones, alcance y frecuencia por campaña y día (RQ-16)
  reportado_plataformas -> conversiones e ingresos que cada plataforma (Meta/Google Ads) reclama
                           haber generado, por campaña y día (RQ-15; siempre por encima de lo
                           real: ver el comentario junto a CAMPANAS_PAGADAS)
  truth                -> parámetros reales del modelo generador (solo para validar)
"""
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

SEED = 20261014
N_USUARIOS = 150_000
INICIO = datetime(2025, 7, 1, tzinfo=UTC)
# 15 meses (2025-07 a 2026-09): los últimos 12 son la ventana de análisis y los 3 anteriores dan
# historia de lookback y una ventana previa para vigilar la estabilidad del modelo.
DIAS = 457
DOMINIO = "https://www.tiendademo.pe"

# Canal -> combinaciones fuente/medio tal como llegan en las UTMs
FUENTES = {
    "Paid Social": [("fb", "paid_social"), ("ig", "paid_social"), ("facebook", "paid")],
    "Paid Search": [("google", "cpc")],
    "Display": [("google", "display")],
    "Organic Search": [("google", "organic"), ("bing", "organic")],
    "Email": [("newsletter", "email")],
    "Referral": [("comparadorperu.com", "referral"), ("blogtecno.pe", "referral")],
    "Direct": [(None, None)],
}
CANALES = list(FUENTES)

# Primera sesión: canales que abren la demanda; siguientes: canales que cierran
P_PRIMERA = {"Paid Social": .26, "Display": .12, "Organic Search": .22, "Paid Search": .14,
             "Referral": .08, "Email": .03, "Direct": .15}
P_SIGUIENTE = {"Direct": .28, "Paid Search": .18, "Email": .14, "Organic Search": .18,
               "Paid Social": .12, "Display": .05, "Referral": .05}

# Atributos del usuario conocidos aun si no compra (sirven como filtros del dashboard).
# Influyen en el MIX de canales, no en la probabilidad de compra: así el efecto real por canal
# sigue siendo el mismo en todos los segmentos y se puede validar el modelo dentro de cada uno.
SEGMENTOS = {
    "device_category": {"mobile": .60, "desktop": .32, "tablet": .08},
    "geo_region": {"Lima": .62, "Provincias": .38},
    "customer_type": {"nuevo": .72, "recurrente": .28},
    "content_group": {"Tecnología": .30, "Hogar": .22, "Moda": .30, "Libros y papelería": .18},
}
SESGO_CANAL = {  # (atributo, valor) -> multiplicador sobre la probabilidad de entrar por cada canal
    ("device_category", "mobile"): {"Paid Social": 1.5, "Direct": .8, "Paid Search": .8, "Email": .7, "Organic Search": .9},
    ("device_category", "desktop"): {"Paid Search": 1.3, "Email": 1.5, "Organic Search": 1.1, "Paid Social": .6},
    ("geo_region", "Provincias"): {"Paid Social": 1.3, "Display": 1.4, "Referral": .8, "Email": .8},
    ("geo_region", "Lima"): {"Paid Search": 1.1, "Email": 1.1},
    ("customer_type", "recurrente"): {"Direct": 2.2, "Email": 2.2, "Paid Social": .5, "Display": .5, "Referral": .7},
    ("content_group", "Moda"): {"Paid Social": 1.4, "Display": 1.3, "Paid Search": .8},
    ("content_group", "Tecnología"): {"Paid Search": 1.4, "Organic Search": 1.2, "Paid Social": .8},
    ("content_group", "Hogar"): {"Referral": 1.5, "Email": 1.2},
    ("content_group", "Libros y papelería"): {"Organic Search": 1.3, "Display": .7},
}

# Modelo real de conversión: logit(p) = b0 + suma(beta_canal) + sinergia social x search
PARAMS_REALES = {
    "b0": -5.3,
    "beta": {"Paid Social": 1.25, "Paid Search": 1.05, "Display": 0.55, "Organic Search": 0.95,
             "Email": 1.15, "Referral": 0.65, "Direct": 0.30},
    "sinergia": {"Paid Social|Paid Search": 0.60},
}

COSTO_POR_SESION = {"Paid Social": 0.95, "Paid Search": 1.70, "Display": 0.45}  # PEN
PASARELAS = ["niubiz.com.pe", "mercadopago.com.pe"]
METODOS_PAGO = ["tarjeta", "yape", "transferencia", "contraentrega"]
P_METODOS = [.55, .25, .12, .08]

# RQ-09/RQ-15/RQ-16: dos campañas por canal pagado, cada una con su costo y sus impresiones por
# sesión (CTR implícito = 1 / impresiones_por_sesion). `exceso_vista` es el extra que la propia
# plataforma reclama por conversiones con solo vista (sin clic, no generan sesión en GA4: no se
# pueden ver con esta metodología). El resto de la brecha plataforma-vs-modelo sale solo, sin
# ningún factor artificial: si una ruta convertida pasó por dos canales pagados, ambas plataformas
# reclaman la venta completa (igual que en la vida real, cada una mide con su propia ventana).
CAMPANAS_PAGADAS = {
    "Paid Social": [
        {"id": "paid_social_prospecting", "peso": .6, "mult_costo": .85, "exceso_vista": 1.35,
         "impresiones_por_sesion": 42},
        {"id": "paid_social_retargeting", "peso": .4, "mult_costo": 1.25, "exceso_vista": 1.15,
         "impresiones_por_sesion": 18},
    ],
    "Paid Search": [
        {"id": "paid_search_marca", "peso": .35, "mult_costo": .6, "exceso_vista": 1.05,
         "impresiones_por_sesion": 3},
        {"id": "paid_search_generica", "peso": .65, "mult_costo": 1.3, "exceso_vista": 1.20,
         "impresiones_por_sesion": 12},
    ],
    "Display": [
        {"id": "display_prospecting", "peso": .7, "mult_costo": .9, "exceso_vista": 1.60,
         "impresiones_por_sesion": 90},
        {"id": "display_remarketing", "peso": .3, "mult_costo": 1.1, "exceso_vista": 1.30,
         "impresiones_por_sesion": 35},
    ],
}
CAMPANA_CANAL = {info["id"]: canal for canal, lst in CAMPANAS_PAGADAS.items() for info in lst}
CAMPANA_INFO = {info["id"]: info for lst in CAMPANAS_PAGADAS.values() for info in lst}


def prob_conversion(canales: set) -> float:
    z = PARAMS_REALES["b0"] + sum(PARAMS_REALES["beta"][c] for c in canales)
    for par, g in PARAMS_REALES["sinergia"].items():
        a, b = par.split("|")
        if a in canales and b in canales:
            z += g
    return 1 / (1 + math.exp(-z))


def elegir(rng, dist):
    claves = list(dist)
    pesos = np.array([dist[k] for k in claves])
    return claves[rng.choice(len(claves), p=pesos / pesos.sum())]


def sesgar(dist: dict, atributos: dict) -> dict:
    """Ajusta la distribución de canales según el segmento del usuario."""
    ajustada = dict(dist)
    for par in atributos.items():
        for canal, f in SESGO_CANAL.get(par, {}).items():
            ajustada[canal] *= f
    return ajustada


def param(key, s=None, i=None, d=None):
    return {"key": key, "value": {"string_value": s, "int_value": i, "double_value": d}}


def main():
    rng = np.random.default_rng(SEED)
    fin = INICIO + timedelta(days=DIAS)
    # Una sesión que arranca justo antes de `fin` puede todavía generar un pedido hasta 25 minutos
    # después (más el evento de purchase de la pasarela): sin este margen, el pedido puede caer
    # después de `fin`, dejando el último día del rango de eventos casi vacío y disparando la
    # alerta de "caída de eventos" en `calidad.py` por una razón que no tiene nada que ver con la
    # calidad real de los datos. Encontrado al variar la secuencia aleatoria para RQ-09/15/16.
    fin_sesiones = fin - timedelta(hours=2)
    eventos, pedidos = [], []
    atributos_usuario: dict[str, dict] = {}
    sesiones_pagadas = {c: {} for c in COSTO_POR_SESION}  # canal -> fecha -> sesiones
    sesiones_por_campana: dict[str, dict[str, int]] = {}  # campaña -> fecha -> sesiones
    conv_reportadas: dict[str, dict[str, int]] = {}       # campaña -> fecha -> conversiones (reclamadas por la plataforma)
    ingresos_reportados: dict[str, dict[str, float]] = {}
    n_pedido = 100_000

    for u in range(N_USUARIOS):
        user_pseudo_id = f"{rng.integers(10**9, 10**10)}.{int(INICIO.timestamp()) + u}"
        n_ses = min(int(rng.geometric(0.45)), 8)   # 1 a 8 sesiones, media ~2,2
        t = INICIO + timedelta(seconds=float(rng.uniform(0, DIAS * 86400)))
        atributos = {a: elegir(rng, d) for a, d in SEGMENTOS.items()}
        atributos_usuario[user_pseudo_id] = atributos
        p_primera, p_siguiente = sesgar(P_PRIMERA, atributos), sesgar(P_SIGUIENTE, atributos)
        ruta = []
        for k in range(n_ses):
            if k > 0:
                t = t + timedelta(days=float(rng.exponential(3.0)), minutes=float(rng.uniform(5, 600)))
            if t >= fin_sesiones:
                break
            canal = elegir(rng, p_primera if k == 0 else p_siguiente)
            ruta.append((t, canal))

        if not ruta:
            continue
        canales_ruta = {c for _, c in ruta}
        convierte = rng.random() < prob_conversion(canales_ruta)

        campanas_pagadas_ruta: set[str] = set()  # campañas pagadas tocadas en la ruta, para RQ-15
        for idx, (ts, canal) in enumerate(ruta):
            ga_session_id = int(ts.timestamp())
            source, medium = FUENTES[canal][rng.integers(len(FUENTES[canal]))]
            if source is None:
                campana = None
            elif canal in CAMPANAS_PAGADAS:
                opciones = CAMPANAS_PAGADAS[canal]
                campana = opciones[rng.choice(len(opciones), p=[o["peso"] for o in opciones])]["id"]
            else:
                campana = f"{canal.lower().replace(' ', '_')}_always_on"
            url = DOMINIO + "/"
            cts = None
            if source is not None:
                url += f"?utm_source={source}&utm_medium={medium}&utm_campaign={campana}"
                if canal == "Paid Social":
                    url += "&fbclid=IwAR" + str(rng.integers(10**8, 10**9))
                cts = {"manual_source": source, "manual_medium": medium,
                       "manual_campaign_name": campana,
                       "gclid": ("Cj0K" + str(rng.integers(10**8, 10**9))) if canal == "Paid Search" else None}
            if canal in COSTO_POR_SESION:
                dia = ts.date().isoformat()
                sesiones_pagadas[canal][dia] = sesiones_pagadas[canal].get(dia, 0) + 1
                sesiones_por_campana.setdefault(campana, {})
                sesiones_por_campana[campana][dia] = sesiones_por_campana[campana].get(dia, 0) + 1
                campanas_pagadas_ruta.add(campana)

            n_pv = int(rng.integers(1, 5))
            for j in range(n_pv + 1):
                ets = ts + timedelta(seconds=30 * j)
                nombre = "session_start" if j == 0 else "page_view"
                eventos.append({
                    "event_date": ets.strftime("%Y%m%d"),
                    "event_timestamp": int(ets.timestamp() * 1e6),
                    "event_name": nombre,
                    "user_pseudo_id": user_pseudo_id,
                    "event_params": [param("ga_session_id", i=ga_session_id),
                                     param("page_location", s=url if j == 0 else DOMINIO + "/producto")],
                    "collected_traffic_source": cts if j == 0 else None,
                    "ecommerce": None,
                })

            es_ultima = idx == len(ruta) - 1
            if convierte and es_ultima:
                n_pedido += 1
                order_id = f"ORD-{n_pedido}"
                valor = round(float(rng.lognormal(math.log(170), 0.45)), 2)
                t_pedido = ts + timedelta(minutes=float(rng.uniform(4, 25)))
                metodo = METODOS_PAGO[rng.choice(4, p=P_METODOS)]
                sin_cookie = rng.random() < 0.04          # pedido por link de pago o cambio de dispositivo
                pedidos.append({
                    "order_id": order_id,
                    "customer_id": f"C-{u:06d}",
                    "created_at": t_pedido,
                    "revenue_pen": valor,
                    "payment_method": metodo,
                    "status": "pagado",
                    "ga_client_id": None if sin_cookie else user_pseudo_id,
                    "ga_session_id": None if sin_cookie else ga_session_id,
                })
                # RQ-15: cada plataforma presente en la ruta reclama la venta completa con su
                # propia medición (de ahí que la suma de lo reportado por todas las campañas sea
                # mayor que las ventas reales cuando una ruta pasó por más de un canal pagado), en
                # la fecha del pedido (una plataforma reporta por fecha de conversión, no por cada
                # día en que hubo un toque previo).
                dia_pagada = t_pedido.date().isoformat()
                for campana_pagada in campanas_pagadas_ruta:
                    conv_reportadas.setdefault(campana_pagada, {})
                    ingresos_reportados.setdefault(campana_pagada, {})
                    conv_reportadas[campana_pagada][dia_pagada] = conv_reportadas[campana_pagada].get(dia_pagada, 0) + 1
                    ingresos_reportados[campana_pagada][dia_pagada] = (
                        ingresos_reportados[campana_pagada].get(dia_pagada, 0.0) + valor)
                # El evento purchase en GA4 se pierde en ~12 % de los casos (thank you page)
                # y en ~10 % de los que llegan, la pasarela abre una sesión nueva.
                if rng.random() < 0.12 or metodo in ("transferencia", "contraentrega"):
                    continue
                purchase_session = ga_session_id
                cts_compra = None
                url_compra = DOMINIO + "/checkout/gracias"
                if rng.random() < 0.10:
                    pas = PASARELAS[rng.integers(2)]
                    purchase_session = int(t_pedido.timestamp())
                    cts_compra = {"manual_source": pas, "manual_medium": "referral",
                                  "manual_campaign_name": None, "gclid": None}
                    eventos.append({
                        "event_date": t_pedido.strftime("%Y%m%d"),
                        "event_timestamp": int(t_pedido.timestamp() * 1e6) - 1,
                        "event_name": "session_start",
                        "user_pseudo_id": user_pseudo_id,
                        "event_params": [param("ga_session_id", i=purchase_session),
                                         param("page_location", s=url_compra)],
                        "collected_traffic_source": cts_compra,
                        "ecommerce": None,
                    })
                eventos.append({
                    "event_date": t_pedido.strftime("%Y%m%d"),
                    "event_timestamp": int(t_pedido.timestamp() * 1e6),
                    "event_name": "purchase",
                    "user_pseudo_id": user_pseudo_id,
                    "event_params": [param("ga_session_id", i=purchase_session),
                                     param("page_location", s=url_compra),
                                     param("value", d=valor), param("currency", s="PEN")],
                    "collected_traffic_source": None,
                    "ecommerce": {"transaction_id": order_id, "purchase_revenue": valor},
                })

    # RQ-09: costo por campaña (no solo por canal); RQ-16: impresiones/alcance/frecuencia por
    # campaña y día; RQ-15: lo que cada plataforma reclama haber generado (siempre >= lo real:
    # ver el comentario junto a `campanas_pagadas_ruta` sobre por qué).
    costos = [{"date": d, "channel": CAMPANA_CANAL[camp], "campaign": camp,
               "cost_pen": round(n * COSTO_POR_SESION[CAMPANA_CANAL[camp]] * CAMPANA_INFO[camp]["mult_costo"]
                                  * float(rng.uniform(.9, 1.1)), 2)}
              for camp, por_dia in sesiones_por_campana.items() for d, n in sorted(por_dia.items())]

    impresiones = []
    for camp, por_dia in sesiones_por_campana.items():
        info = CAMPANA_INFO[camp]
        for d, n in sorted(por_dia.items()):
            imp = max(1, int(n * info["impresiones_por_sesion"] * float(rng.uniform(.85, 1.15))))
            frecuencia = round(float(rng.uniform(1.6, 3.2)), 2)
            impresiones.append({"date": d, "channel": CAMPANA_CANAL[camp], "campaign": camp,
                                "impressions": imp, "reach": max(1, int(imp / frecuencia)), "frequency": frecuencia})

    reportado = []
    for camp, por_dia in conv_reportadas.items():
        info = CAMPANA_INFO[camp]
        for d, n in sorted(por_dia.items()):
            exceso = info["exceso_vista"] * float(rng.uniform(.95, 1.05))
            reportado.append({"date": d, "channel": CAMPANA_CANAL[camp], "campaign": camp,
                              "platform_conversions": round(n * exceso, 1),
                              "platform_revenue": round(ingresos_reportados[camp][d] * exceso, 2)})

    carpeta = Path(__file__).parent / "data"
    carpeta.mkdir(exist_ok=True)
    con = duckdb.connect(str(carpeta / "ecommerce.duckdb"))
    for tabla in ("events", "orders", "costs", "truth", "impresiones", "reportado_plataformas"):
        con.execute(f"DROP TABLE IF EXISTS {tabla}")
    con.execute("""
        CREATE TABLE events (
          event_date VARCHAR, event_timestamp BIGINT, event_name VARCHAR, user_pseudo_id VARCHAR,
          user_id VARCHAR,
          event_params STRUCT(key VARCHAR, value STRUCT(string_value VARCHAR, int_value BIGINT, double_value DOUBLE))[],
          collected_traffic_source STRUCT(manual_source VARCHAR, manual_medium VARCHAR, manual_campaign_name VARCHAR, gclid VARCHAR),
          ecommerce STRUCT(transaction_id VARCHAR, purchase_revenue DOUBLE),
          device_category VARCHAR, geo_region VARCHAR, customer_type VARCHAR, content_group VARCHAR)""")
    df_ev = pd.DataFrame(eventos)
    for atributo in SEGMENTOS:  # atributos del usuario repetidos en cada evento (columnas planas)
        df_ev[atributo] = df_ev.user_pseudo_id.map(lambda u, a=atributo: atributos_usuario[u][a])
    # `user_id` (RQ-07, llave de unión #3) no existe en este generador: esta demo no simula
    # usuarios logueados entre dispositivos. `BY NAME` lo deja en NULL sin tocar `eventos`.
    con.execute("INSERT INTO events BY NAME SELECT * FROM df_ev")
    df_ped = pd.DataFrame(pedidos)
    con.execute("CREATE TABLE orders AS SELECT * FROM df_ped")
    df_cost = pd.DataFrame(costos)
    con.execute("CREATE TABLE costs AS SELECT CAST(date AS DATE) AS date, channel, campaign, cost_pen FROM df_cost")
    df_imp = pd.DataFrame(impresiones)
    con.execute("CREATE TABLE impresiones AS SELECT CAST(date AS DATE) AS date, channel, campaign, "
                "impressions, reach, frequency FROM df_imp")
    df_rep = pd.DataFrame(reportado)
    con.execute("CREATE TABLE reportado_plataformas AS SELECT CAST(date AS DATE) AS date, channel, campaign, "
                "platform_conversions, platform_revenue FROM df_rep")
    con.execute("CREATE TABLE truth AS SELECT ? AS params", [json.dumps(PARAMS_REALES)])
    print(f"eventos={len(df_ev):,} pedidos={len(df_ped):,} filas_costos={len(df_cost):,} "
          f"filas_impresiones={len(df_imp):,} filas_reportado={len(df_rep):,}")
    con.close()


if __name__ == "__main__":
    main()
