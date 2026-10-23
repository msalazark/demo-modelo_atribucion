.PHONY: datos pipeline app test lint deploy-setup deploy-build deploy-job deploy-app deploy

datos:
	python generar_datos.py

pipeline:
	python run_demo.py

app:
	streamlit run dashboard.py

test:
	python -m pytest tests -m "not rendimiento and not evals"

lint:
	ruff check .

# ---------------------------------------------------------------- despliegue (RQ-24)
# Variables de cada cliente: `make deploy PROJECT=mi-proyecto-gcp CLIENTE=la-positiva`.
# Detalle y justificación de cada comando en docs/despliegue.md.
PROJECT ?=
REGION ?= us-central1
CLIENTE ?= demo
IMAGEN = $(REGION)-docker.pkg.dev/$(PROJECT)/atribucion/$(CLIENTE):latest
BUCKET = $(PROJECT)-atribucion-$(CLIENTE)
SECRET = anthropic-api-key-$(CLIENTE)
SA_PIPELINE = atribucion-pipeline-$(CLIENTE)@$(PROJECT).iam.gserviceaccount.com
SA_DASHBOARD = atribucion-dashboard-$(CLIENTE)@$(PROJECT).iam.gserviceaccount.com

# Una sola vez por cliente: cuentas de servicio, bucket para data/*.duckdb y el secreto de Claude.
# Requiere haber creado antes el secreto con `gcloud secrets create $(SECRET) --data-file=-`.
deploy-setup:
	test -n "$(PROJECT)"  # usa PROJECT=tu-proyecto-gcp
	gcloud iam service-accounts create atribucion-pipeline-$(CLIENTE) --project=$(PROJECT) \
		--display-name="Atribución ($(CLIENTE)): pipeline"
	gcloud iam service-accounts create atribucion-dashboard-$(CLIENTE) --project=$(PROJECT) \
		--display-name="Atribución ($(CLIENTE)): dashboard"
	gcloud storage buckets create gs://$(BUCKET) --project=$(PROJECT) --location=$(REGION) --uniform-bucket-level-access
	gcloud storage buckets add-iam-policy-binding gs://$(BUCKET) \
		--member=serviceAccount:$(SA_PIPELINE) --role=roles/storage.objectAdmin
	gcloud storage buckets add-iam-policy-binding gs://$(BUCKET) \
		--member=serviceAccount:$(SA_DASHBOARD) --role=roles/storage.objectViewer
	gcloud secrets add-iam-policy-binding $(SECRET) --project=$(PROJECT) \
		--member=serviceAccount:$(SA_PIPELINE) --role=roles/secretmanager.secretAccessor
	gcloud secrets add-iam-policy-binding $(SECRET) --project=$(PROJECT) \
		--member=serviceAccount:$(SA_DASHBOARD) --role=roles/secretmanager.secretAccessor

deploy-build:
	test -n "$(PROJECT)"
	gcloud builds submit --tag $(IMAGEN) --project=$(PROJECT)

deploy-job:
	test -n "$(PROJECT)"
	gcloud run jobs deploy atribucion-pipeline-$(CLIENTE) --image=$(IMAGEN) --project=$(PROJECT) --region=$(REGION) \
		--service-account=$(SA_PIPELINE) --set-secrets=ANTHROPIC_API_KEY=$(SECRET):latest \
		--add-volume=name=datos,type=cloud-storage,bucket=$(BUCKET) \
		--add-volume-mount=volume=datos,mount-path=/app/data \
		--command=python --args=run_demo.py,--config,config/$(CLIENTE).yaml \
		--max-retries=0 --task-timeout=30m

deploy-scheduler:
	test -n "$(PROJECT)"
	gcloud scheduler jobs create http atribucion-pipeline-$(CLIENTE)-mensual --project=$(PROJECT) --location=$(REGION) \
		--schedule="0 6 1 * *" --time-zone="America/Lima" \
		--uri="https://$(REGION)-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/$(PROJECT)/jobs/atribucion-pipeline-$(CLIENTE):run" \
		--http-method=POST --oauth-service-account-email=$(SA_PIPELINE)

deploy-app:
	test -n "$(PROJECT)"
	gcloud run deploy atribucion-dashboard-$(CLIENTE) --image=$(IMAGEN) --project=$(PROJECT) --region=$(REGION) \
		--service-account=$(SA_DASHBOARD) --set-secrets=ANTHROPIC_API_KEY=$(SECRET):latest \
		--add-volume=name=datos,type=cloud-storage,bucket=$(BUCKET),read-only=true \
		--add-volume-mount=volume=datos,mount-path=/app/data \
		--no-allow-unauthenticated --min-instances=0 --max-instances=2

# Redespliegue de cada corrida (no incluye deploy-setup ni deploy-scheduler: son de una sola vez).
deploy: deploy-build deploy-job deploy-app
