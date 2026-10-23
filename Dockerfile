# Imagen única para los dos despliegues de Cloud Run (RQ-24 de docs/RQ_mejoras.md):
#   - Servicio del dashboard (ENTRYPOINT de abajo, puerto $PORT que exige Cloud Run).
#   - Job del pipeline: mismo contenedor, pero `gcloud run jobs deploy` sobreescribe el comando
#     con ["python", "run_demo.py", "--config", "config/produccion.yaml"] (ver docs/despliegue.md).
FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# data/ecommerce.duckdb no se copia desde el repo en el despliegue real: en producción vive en el
# volumen de Cloud Storage que monta Cloud Run (docs/despliegue.md). El Dockerfile la incluye solo
# porque hoy es parte del repo de la demo; `.dockerignore` no la excluye a propósito por eso mismo.
ENV PYTHONUNBUFFERED=1
EXPOSE 8080

CMD ["streamlit", "run", "dashboard.py", \
     "--server.port=8080", "--server.address=0.0.0.0", "--server.headless=true"]
