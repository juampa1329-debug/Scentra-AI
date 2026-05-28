from __future__ import annotations

import importlib.util
import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response

from app_saas.ml_service.db_ops import (
    try_record_drift,
    try_record_inference,
    try_record_model_evaluation,
    try_record_model_artifact,
    try_record_training_job_complete,
    try_record_training_job_start,
)
from app_saas.ml_service.datasets import build_training_dataset
from app_saas.ml_service.pipeline import (
    evaluate_drift,
    list_local_models,
    model_predict,
    model_root,
    normalize_model_key,
    normalize_task,
    train_autolabel_model,
    train_synthetic_model,
)
from app_saas.ml_service.schemas import AutoLabelTrainRequest, DatasetBuildRequest, DriftRequest, PredictRequest, TrainRequest

app = FastAPI(title="Scentra ML Service", version="0.1.0")

try:
    from prometheus_client import Counter, Histogram, generate_latest

    REQUESTS = Counter("scentra_ml_requests_total", "Scentra ML service requests", ["endpoint", "status"])
    LATENCY = Histogram("scentra_ml_latency_seconds", "Scentra ML service latency", ["endpoint"])
except Exception:
    REQUESTS = None
    LATENCY = None
    generate_latest = None


def _dependency_status() -> dict[str, bool]:
    return {
        "numpy": importlib.util.find_spec("numpy") is not None,
        "pandas": importlib.util.find_spec("pandas") is not None,
        "sklearn": importlib.util.find_spec("sklearn") is not None,
        "xgboost": importlib.util.find_spec("xgboost") is not None,
        "lightgbm": importlib.util.find_spec("lightgbm") is not None,
        "mlflow": importlib.util.find_spec("mlflow") is not None,
        "bentoml": importlib.util.find_spec("bentoml") is not None,
        "prometheus_client": importlib.util.find_spec("prometheus_client") is not None,
    }


def _observe(endpoint: str, status: str, started: float) -> None:
    if REQUESTS:
        REQUESTS.labels(endpoint=endpoint, status=status).inc()
    if LATENCY:
        LATENCY.labels(endpoint=endpoint).observe(max(0.0, time.perf_counter() - started))


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "ok": True,
        "service": "scentra-ml-service",
        "enabled": str(os.getenv("SAAS_ML_ENABLED", "false")).lower() in {"1", "true", "yes", "on"},
        "model_dir": str(model_root()),
        "mlflow_tracking_uri": os.getenv("MLFLOW_TRACKING_URI") or os.getenv("SAAS_MLFLOW_TRACKING_URI") or "",
        "dependencies": _dependency_status(),
    }


@app.get("/models")
def models() -> dict[str, Any]:
    return {"ok": True, "models": list_local_models()}


@app.post("/train/synthetic")
def train_synthetic(payload: TrainRequest) -> dict[str, Any]:
    started = time.perf_counter()
    task = normalize_task(payload.task_type)
    model_key = normalize_model_key(payload.model_key, task)
    job_id = try_record_training_job_start(
        {
            "tenant_id": payload.tenant_id,
            "job_type": "synthetic_autolabel",
            "prediction_type": task,
            "model_key": model_key,
            "framework": payload.framework,
            "source": "ml_service",
            "dataset_summary_json": {"sample_size": payload.sample_size, "source": "synthetic_autolabel"},
            "params_json": payload.model_dump(),
        }
    )
    try:
        result = train_synthetic_model(
            task_type=task,
            model_key=model_key,
            framework=payload.framework,
            version=payload.version,
            sample_size=payload.sample_size,
            seed=payload.seed,
        )
        result["training_job_id"] = job_id
        if payload.register_artifact:
            try_record_model_artifact(
                {
                    **result,
                    "tenant_id": payload.tenant_id,
                    "prediction_type": task,
                    "local_path": result.get("artifact_uri") or "",
                    "training_job_id": job_id,
                    "status": "candidate",
                }
            )
        try_record_training_job_complete(job_id, result=result)
        _observe("train_synthetic", "ok", started)
        return {"ok": True, "job_id": job_id, "artifact": result}
    except Exception as exc:
        try_record_training_job_complete(job_id, result={}, error=str(exc))
        _observe("train_synthetic", "error", started)
        raise HTTPException(status_code=400, detail={"code": "ml_training_failed", "message": str(exc)[:500]}) from exc


@app.post("/datasets/build")
def datasets_build(payload: DatasetBuildRequest) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = build_training_dataset(
            tenant_id=payload.tenant_id,
            task_type=payload.task_type,
            dataset_key=payload.dataset_key,
            version=payload.version,
            window_key=payload.window_key,
            min_samples=payload.min_samples,
            include_global=payload.include_global,
            notes=payload.notes,
        )
        _observe("datasets_build", "ok", started)
        return {"ok": True, "dataset": result["summary"]}
    except Exception as exc:
        _observe("datasets_build", "error", started)
        raise HTTPException(status_code=400, detail={"code": "ml_dataset_build_failed", "message": str(exc)[:500]}) from exc


@app.post("/train/autolabel")
def train_autolabel(payload: AutoLabelTrainRequest) -> dict[str, Any]:
    started = time.perf_counter()
    task = normalize_task(payload.task_type)
    model_key = normalize_model_key(payload.model_key, task)
    job_id = try_record_training_job_start(
        {
            "tenant_id": payload.tenant_id,
            "job_type": "postgres_auto_label",
            "prediction_type": task,
            "model_key": model_key,
            "framework": payload.framework,
            "source": "ml_service",
            "dataset_summary_json": {
                "dataset_key": payload.dataset_key,
                "window_key": payload.window_key,
                "min_samples": payload.min_samples,
                "include_global": payload.include_global,
                "source": "postgres_feature_store",
            },
            "params_json": payload.model_dump(),
        }
    )
    try:
        result = train_autolabel_model(
            tenant_id=payload.tenant_id,
            task_type=task,
            model_key=model_key,
            framework=payload.framework,
            version=payload.version,
            dataset_key=payload.dataset_key,
            window_key=payload.window_key,
            min_samples=payload.min_samples,
            include_global=payload.include_global,
            seed=payload.seed,
            notes=payload.notes,
        )
        result["training_job_id"] = job_id
        if payload.register_artifact:
            try_record_model_artifact(
                {
                    **result,
                    "tenant_id": payload.tenant_id,
                    "prediction_type": task,
                    "local_path": result.get("artifact_uri") or "",
                    "training_job_id": job_id,
                    "status": "candidate",
                }
            )
        try_record_model_evaluation(
            {
                "tenant_id": payload.tenant_id,
                "model_key": result.get("model_key") or model_key,
                "model_version": result.get("version") or payload.version,
                "prediction_type": task,
                "evaluation_type": "offline_holdout",
                "dataset_id": (result.get("dataset") or {}).get("dataset_id") or "",
                "status": "completed",
                "metrics": result.get("metrics") or {},
                "slices_json": {
                    "tenant_scope": "tenant" if payload.tenant_id and not payload.include_global else "shared_global_anonymized",
                    "raw_content_used": False,
                },
                "notes": payload.notes,
            }
        )
        try_record_training_job_complete(job_id, result=result)
        _observe("train_autolabel", "ok", started)
        return {"ok": True, "job_id": job_id, "artifact": result}
    except Exception as exc:
        try_record_training_job_complete(job_id, result={}, error=str(exc))
        _observe("train_autolabel", "error", started)
        raise HTTPException(status_code=400, detail={"code": "ml_autolabel_training_failed", "message": str(exc)[:500]}) from exc


@app.post("/predict")
def predict(payload: PredictRequest) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = model_predict(
            model_key=payload.model_key,
            version=payload.version,
            task_type=payload.task_type,
            features=payload.features,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        result["latency_ms"] = latency_ms
        if payload.tenant_id:
            try_record_inference(
                {
                    "tenant_id": payload.tenant_id,
                    "prediction_id": payload.prediction_id,
                    "model_key": result.get("model_key") or payload.model_key,
                    "version": result.get("version") or payload.version,
                    "task_type": result.get("task_type") or payload.task_type,
                    "subject_type": payload.subject_type,
                    "subject_id": payload.subject_id,
                    "mode": payload.mode,
                    "status": "ok",
                    "score": result.get("score"),
                    "label": result.get("label"),
                    "confidence": result.get("confidence"),
                    "latency_ms": latency_ms,
                    "input_json": payload.features,
                    "output_json": result,
                }
            )
        _observe("predict", "ok", started)
        return {"ok": True, "prediction": result}
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        if payload.tenant_id:
            try_record_inference(
                {
                    "tenant_id": payload.tenant_id,
                    "prediction_id": payload.prediction_id,
                    "model_key": payload.model_key,
                    "version": payload.version,
                    "task_type": payload.task_type,
                    "subject_type": payload.subject_type,
                    "subject_id": payload.subject_id,
                    "mode": payload.mode,
                    "status": "error",
                    "latency_ms": latency_ms,
                    "fallback_used": True,
                    "input_json": payload.features,
                    "output_json": {},
                    "error_text": str(exc),
                }
            )
        _observe("predict", "error", started)
        raise HTTPException(status_code=404, detail={"code": "ml_prediction_failed", "message": str(exc)[:500]}) from exc


@app.post("/drift/evaluate")
def drift(payload: DriftRequest) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        result = evaluate_drift(
            model_key=payload.model_key,
            version=payload.version,
            task_type=payload.task_type,
            current_features=payload.current_features,
        )
        try_record_drift({**result, "tenant_id": payload.tenant_id, "prediction_type": payload.task_type, "window_key": payload.window_key})
        _observe("drift", "ok", started)
        return {"ok": True, "drift": result}
    except Exception as exc:
        _observe("drift", "error", started)
        raise HTTPException(status_code=404, detail={"code": "ml_drift_failed", "message": str(exc)[:500]}) from exc


@app.get("/metrics")
def metrics() -> Response:
    if not generate_latest:
        return Response("# prometheus_client unavailable\n", media_type="text/plain")
    return Response(generate_latest(), media_type="text/plain")
