# Despliegue (RQ-24)

Artefactos y comandos para desplegar esta app en GCP. No se probaron contra un proyecto real (el
entorno de desarrollo no tiene credenciales de GCP): son el punto de partida para la primera vez
que se despliegue con un cliente, a revisar con sus restricciones de organización (VPC-SC,
dominios permitidos, etc.) antes de correrlos.

## Arquitectura

```
Cloud Scheduler (mensual) --OIDC--> Cloud Run Job "atribucion-pipeline-<cliente>"
                                           |  escribe
                                           v
                              gs://<bucket>/data/ecommerce.duckdb   (volumen de Cloud Storage)
                                           ^  lee (read-only)
                                           |
         usuario --(IAP / IAM)--> Cloud Run Service "atribucion-dashboard-<cliente>"
```

Dos despliegues de Cloud Run a partir de la **misma imagen** (`Dockerfile`): un **Job** para
`run_demo.py` (se ejecuta y termina) y un **Service** para `streamlit run dashboard.py` (queda
escuchando). `gcloud run jobs deploy` sobreescribe el `CMD` de la imagen con `--command`/`--args`;
el Service usa el `CMD` tal cual.

### Por qué un volumen de Cloud Storage para el `.duckdb`

Hoy el pipeline corre contra DuckDB sin importar `motor` en la config (`motor: bigquery` es un
campo reservado: no hay todavía una ruta de ejecución nativa en BigQuery, ver `sql_bigquery/` y la
sección "Pasar a un cliente real" del README). Cloud Run no tiene disco persistente local, así que
sin un volumen externo cada corrida del Job empezaría desde una base de datos vacía y el Service
nunca vería los resultados del Job. La solución de menor esfuerzo hoy es montar un bucket de Cloud
Storage como volumen (`--add-volume=type=cloud-storage`, soportado nativamente por Cloud Run desde
2024) en la misma ruta (`/app/data`) en el Job (lectura-escritura) y en el Service (solo lectura).
**Cuando se implemente la ejecución nativa en BigQuery, este volumen deja de hacer falta**: BigQuery
ya es el almacenamiento persistente y el Service puede leer directo de ahí.

### Por qué Identity-Aware Proxy y no solo IAM de Cloud Run

Cloud Run ya soporta restringir el acceso a cuentas o grupos de Google con
`--no-allow-unauthenticated` + `gcloud run services add-iam-policy-binding` (rol
`roles/run.invoker`), sin pasos adicionales. **IAP**, en cambio, solo se puede poner delante de
Cloud Run a través de un **External HTTPS Load Balancer** (Cloud Run no expone IAP directamente):
se necesita un Serverless NEG apuntando al servicio, un backend service con IAP habilitado y un
certificado gestionado. Vale la pena si el cliente ya tiene una política de acceso de IAP
centralizada (p. ej. Context-Aware Access) o si quiere la pantalla de consentimiento de Google de
por medio; si no, el IAM directo de Cloud Run es más simple y ya cumple "no accesible sin
autenticación de Google del dominio del cliente". Decisión abierta por cliente: ver sección 8 de
`docs/RQ_mejoras.md`.

## Secret Manager

`ANTHROPIC_API_KEY` no va en el código ni en el YAML de config (regla del proyecto): se crea una
vez por cliente y se monta como variable de entorno:

```bash
printf '%s' "sk-ant-..." | gcloud secrets create anthropic-api-key-<cliente> --data-file=- --project=$PROJECT
```

`--set-secrets=ANTHROPIC_API_KEY=anthropic-api-key-<cliente>:latest` (ya incluido en los targets
del Makefile) la inyecta en el contenedor sin que quede en la definición del servicio/job en texto
plano.

## Cuentas de servicio (permisos mínimos)

| Cuenta | Para qué | Roles |
|---|---|---|
| `atribucion-pipeline-<cliente>` | Corre el Job | `roles/storage.objectAdmin` solo sobre el bucket del cliente; `roles/secretmanager.secretAccessor` solo sobre su secreto. Cuando exista la ruta BigQuery: añadir `roles/bigquery.dataViewer` sobre el dataset fuente (export de GA4 / pedidos) y `roles/bigquery.dataEditor` sobre el dataset de marts, ambos acotados por dataset, no a nivel de proyecto. |
| `atribucion-dashboard-<cliente>` | Corre el Service | `roles/storage.objectViewer` solo sobre el bucket del cliente (lectura); `roles/secretmanager.secretAccessor` solo sobre su secreto. Con BigQuery: `roles/bigquery.dataViewer` sobre el dataset de marts únicamente — nunca sobre el dataset fuente. |

Ninguna de las dos tiene rol a nivel de proyecto: todo está acotado al bucket/secreto/dataset del
cliente, siguiendo el principio de mínimo privilegio.

## Comandos

Todo en el `Makefile` (variables `PROJECT`, `REGION`, `CLIENTE`; ver comentarios ahí para el detalle
de cada flag):

```bash
# Una sola vez por cliente: cuentas de servicio, bucket y permisos. Antes: crear el secreto (arriba).
make deploy-setup PROJECT=mi-proyecto-gcp CLIENTE=la-positiva

# Build + despliegue del Job y el Service (repetible en cada entrega de código).
make deploy PROJECT=mi-proyecto-gcp CLIENTE=la-positiva REGION=us-central1

# Una sola vez por cliente: corrida mensual automática del Job (día 1, 6 a.m. hora de Lima).
make deploy-scheduler PROJECT=mi-proyecto-gcp CLIENTE=la-positiva
```

`deploy-job`/`deploy-app` usan `config/<cliente>.yaml` (`--args=run_demo.py,--config,config/<cliente>.yaml`):
crear ese archivo a partir de `config/produccion.yaml` antes del primer despliegue.

## Qué falta para producción real (fuera de este RQ)

- Ejecución nativa en BigQuery (`sql_bigquery/`): elimina el volumen de Cloud Storage.
- VPC Service Controls / Private Google Access si la organización del cliente lo exige.
- Alertas de Cloud Monitoring sobre fallos del Job (hoy solo hay logs vía `structlog`).
