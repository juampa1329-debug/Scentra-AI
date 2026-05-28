FROM python:3.11-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
COPY backend/requirements-ml.txt .
RUN pip install --no-cache-dir -r requirements-ml.txt

COPY backend/app_saas ./app_saas
COPY migrations ./migrations

ENV SAAS_ML_MODEL_DIR=/models
ENV BENTOML_HOME=/bentoml

EXPOSE 8090
CMD ["uvicorn", "app_saas.ml_service.main:app", "--host", "0.0.0.0", "--port", "8090"]
