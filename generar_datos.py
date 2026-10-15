"""
Genera datos sintéticos de un ecommerce con la estructura del export de GA4
en BigQuery, más la tabla de pedidos del backend y los costos por canal.

Como los datos son sintéticos, la probabilidad real de conversión de cada
combinación de canales es conocida (PARAMS_REALES). Eso permite medir qué tan
cerca llega cada modelo de atribución al efecto real.

Salida: data/ecommerce.duckdb con las tablas
  events   -> imita analytics_XXXX.events_YYYYMMDD (una sola tabla con event_date)
  orders   -> pedidos del backend (fuente de verdad de la venta)
  costs    -> inversión diaria por canal pagado
  truth    -> parámetros reales del modelo generador (solo para validar)
"""
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

SEED = 20261014
N_USUARIOS = 120_000
INICIO = datetime(2025, 10, 1, tzinfo=timezone.utc)
DIAS = 365   # 12 meses: 2025-10 a 2026-09, base del reporte mensual acumulado
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


def param(key, s=None, i=None, d=None):
    return {"key": key, "value": {"string_value": s, "int_value": i, "double_value": d}}


def main():
    rng = np.random.default_rng(SEED)
    fin = INICIO + timedelta(days=DIAS)
    eventos, pedidos = [], []
    sesiones_pagadas = {c: {} for c in COSTO_POR_SESION}  # canal -> fecha -> sesiones
    n_pedido = 100_000

    for u in range(N_USUARIOS):
        user_pseudo_id = f"{rng.integers(10**9, 10**10)}.{int(INICIO.timestamp()) + u}"
        n_ses = min(int(rng.geometric(0.45)), 8)   # 1 a 8 sesiones, media ~2,2
        t = INICIO + timedelta(seconds=float(rng.uniform(0, DIAS * 86400)))
        ruta = []
        for k in range(n_ses):
            if k > 0:
                t = t + timedelta(days=float(rng.exponential(3.0)), minutes=float(rng.uniform(5, 600)))
            if t >= fin:
                break
            canal = elegir(rng, P_PRIMERA if k == 0 else P_SIGUIENTE)
            ruta.append((t, canal))

        if not ruta:
            continue
        canales_ruta = {c for _, c in ruta}
        convierte = rng.random() < prob_conversion(canales_ruta)

        for idx, (ts, canal) in enumerate(ruta):
            ga_session_id = int(ts.timestamp())
            source, medium = FUENTES[canal][rng.integers(len(FUENTES[canal]))]
            campana = None if source is None else f"{canal.lower().replace(' ', '_')}_always_on"
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

    costos = [{"date": d, "channel": c, "cost_pen": round(n * COSTO_POR_SESION[c] * float(rng.uniform(.9, 1.1)), 2)}
              for c, por_dia in sesiones_pagadas.items() for d, n in sorted(por_dia.items())]

    carpeta = Path(__file__).parent / "data"
    carpeta.mkdir(exist_ok=True)
    con = duckdb.connect(str(carpeta / "ecommerce.duckdb"))
    for tabla in ("events", "orders", "costs", "truth"):
        con.execute(f"DROP TABLE IF EXISTS {tabla}")
    con.execute("""
        CREATE TABLE events (
          event_date VARCHAR, event_timestamp BIGINT, event_name VARCHAR, user_pseudo_id VARCHAR,
          event_params STRUCT(key VARCHAR, value STRUCT(string_value VARCHAR, int_value BIGINT, double_value DOUBLE))[],
          collected_traffic_source STRUCT(manual_source VARCHAR, manual_medium VARCHAR, manual_campaign_name VARCHAR, gclid VARCHAR),
          ecommerce STRUCT(transaction_id VARCHAR, purchase_revenue DOUBLE))""")
    df_ev = pd.DataFrame(eventos)
    con.execute("INSERT INTO events SELECT * FROM df_ev")
    df_ped = pd.DataFrame(pedidos)
    con.execute("CREATE TABLE orders AS SELECT * FROM df_ped")
    df_cost = pd.DataFrame(costos)
    con.execute("CREATE TABLE costs AS SELECT CAST(date AS DATE) AS date, channel, cost_pen FROM df_cost")
    con.execute("CREATE TABLE truth AS SELECT ? AS params", [json.dumps(PARAMS_REALES)])
    print(f"eventos={len(df_ev):,} pedidos={len(df_ped):,} filas_costos={len(df_cost):,}")
    con.close()


if __name__ == "__main__":
    main()
