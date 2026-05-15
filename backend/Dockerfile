FROM python:3.11-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app_saas ./app_saas
COPY migrations ./migrations

EXPOSE 8000
CMD ["uvicorn", "app_saas.main:app", "--host", "0.0.0.0", "--port", "8000"]
