from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import train_test_split

SUPPORTED_TASKS = {
    "lead_scoring",
    "churn_prediction",
    "smart_remarketing",
    "operational_anomaly",
}

FEATURE_KEYS = [
    "conversations",
    "messages_received_7d",
    "messages_sent_7d",
    "hot_leads",
    "avg_lead_score",
    "inactive_14d",
    "inactivity_days",
    "avg_response_time_minutes",
    "webhook_errors_24h",
    "ai_failed_24h",
    "outbound_failed_24h",
    "dead_letters_open",
    "campaign_response_rate",
    "trigger_conversion_rate",
    "sentiment_score",
    "engagement_score",
]

LABELS = {
    "lead_scoring": ("cold", "warm", "hot"),
    "churn_prediction": ("low_risk", "medium_risk", "high_risk"),
    "smart_remarketing": ("low_opportunity", "watchlist", "high_opportunity"),
    "operational_anomaly": ("normal", "watch", "degraded"),
}


def normalize_task(value: str) -> str:
    task = str(value or "lead_scoring").strip().lower().replace("-", "_")
    if task not in SUPPORTED_TASKS:
        raise ValueError(f"unsupported_task:{task}")
    return task


def normalize_model_key(value: str, task_type: str) -> str:
    clean = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return clean or f"ml_{normalize_task(task_type)}_v1"


def model_root() -> Path:
    root = Path(os.getenv("SAAS_ML_MODEL_DIR") or "/models")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-value))


def _synthetic_features(sample_size: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = int(sample_size)
    conversations = rng.poisson(80, n) + 1
    inbound = rng.poisson(180, n)
    outbound = rng.poisson(150, n)
    avg_lead_score = rng.beta(2.3, 2.1, n) * 100
    hot_rate = np.clip(avg_lead_score / 140 + rng.normal(0, 0.08, n), 0.01, 0.85)
    hot_leads = rng.binomial(conversations, hot_rate)
    inactivity_days = np.clip(rng.gamma(2.4, 6.5, n), 0, 90)
    inactive_rate = np.clip((inactivity_days / 70) + rng.normal(0.08, 0.07, n), 0.0, 0.95)
    inactive_14d = rng.binomial(conversations, inactive_rate)
    response = np.clip(rng.lognormal(2.8, 0.9, n), 1, 360)
    campaign_rate = rng.beta(2.1, 4.3, n) * 100
    trigger_rate = rng.beta(2.4, 3.8, n) * 100
    sentiment = np.clip(rng.normal(0.08, 0.45, n), -1, 1)
    engagement = np.clip(
        (inbound + outbound) / np.maximum(conversations, 1) * 8
        + campaign_rate * 0.32
        + trigger_rate * 0.2
        + sentiment * 12
        - inactivity_days * 0.45,
        0,
        100,
    )
    webhook_errors = rng.poisson(0.4, n)
    ai_failed = rng.poisson(0.35, n)
    outbound_failed = rng.poisson(0.45, n)
    dead_letters = rng.poisson(0.2, n)
    anomaly_mask = rng.random(n) < 0.08
    webhook_errors[anomaly_mask] += rng.poisson(5, int(anomaly_mask.sum()))
    ai_failed[anomaly_mask] += rng.poisson(3, int(anomaly_mask.sum()))
    outbound_failed[anomaly_mask] += rng.poisson(4, int(anomaly_mask.sum()))
    dead_letters[anomaly_mask] += rng.poisson(2, int(anomaly_mask.sum()))
    return pd.DataFrame(
        {
            "conversations": conversations,
            "messages_received_7d": inbound,
            "messages_sent_7d": outbound,
            "hot_leads": hot_leads,
            "avg_lead_score": avg_lead_score,
            "inactive_14d": inactive_14d,
            "inactivity_days": inactivity_days,
            "avg_response_time_minutes": response,
            "webhook_errors_24h": webhook_errors,
            "ai_failed_24h": ai_failed,
            "outbound_failed_24h": outbound_failed,
            "dead_letters_open": dead_letters,
            "campaign_response_rate": campaign_rate,
            "trigger_conversion_rate": trigger_rate,
            "sentiment_score": sentiment,
            "engagement_score": engagement,
        }
    )


def synthetic_dataset(task_type: str, sample_size: int, seed: int) -> tuple[pd.DataFrame, np.ndarray]:
    task = normalize_task(task_type)
    frame = _synthetic_features(sample_size, seed)
    conversations = np.maximum(frame["conversations"].to_numpy(dtype=float), 1.0)
    hot_ratio = frame["hot_leads"].to_numpy(dtype=float) / conversations
    inactive_ratio = frame["inactive_14d"].to_numpy(dtype=float) / conversations
    errors = (
        frame["webhook_errors_24h"].to_numpy(dtype=float)
        + frame["ai_failed_24h"].to_numpy(dtype=float)
        + frame["outbound_failed_24h"].to_numpy(dtype=float)
        + frame["dead_letters_open"].to_numpy(dtype=float)
    )
    if task == "lead_scoring":
        probability = _sigmoid(
            (frame["avg_lead_score"].to_numpy(dtype=float) - 52) / 14
            + hot_ratio * 2.0
            + (frame["engagement_score"].to_numpy(dtype=float) - 45) / 28
            + frame["sentiment_score"].to_numpy(dtype=float) * 0.6
        )
    elif task == "churn_prediction":
        probability = _sigmoid(
            (frame["inactivity_days"].to_numpy(dtype=float) - 18) / 7
            + inactive_ratio * 2.8
            - (frame["engagement_score"].to_numpy(dtype=float) - 45) / 24
            + (frame["avg_response_time_minutes"].to_numpy(dtype=float) - 80) / 130
        )
    elif task == "smart_remarketing":
        probability = _sigmoid(
            (frame["avg_lead_score"].to_numpy(dtype=float) - 48) / 17
            + inactive_ratio * 1.6
            + (frame["campaign_response_rate"].to_numpy(dtype=float) - 30) / 35
            - (frame["avg_response_time_minutes"].to_numpy(dtype=float) - 80) / 160
        )
    else:
        probability = _sigmoid(errors * 0.72 + frame["dead_letters_open"].to_numpy(dtype=float) * 0.8 - 2.1)
    rng = np.random.default_rng(seed + 17)
    target = rng.binomial(1, np.clip(probability, 0.02, 0.98))
    if len(np.unique(target)) < 2:
        target[-1] = 1 - target[0]
    return frame[FEATURE_KEYS], target


def _estimator(framework: str, seed: int):
    clean = str(framework or "lightgbm").strip().lower()
    if clean == "lightgbm":
        try:
            from lightgbm import LGBMClassifier

            return LGBMClassifier(
                n_estimators=120,
                learning_rate=0.07,
                num_leaves=31,
                random_state=seed,
                verbose=-1,
            ), "lightgbm"
        except Exception:
            pass
    if clean == "xgboost":
        try:
            from xgboost import XGBClassifier

            return XGBClassifier(
                n_estimators=120,
                max_depth=4,
                learning_rate=0.07,
                subsample=0.9,
                colsample_bytree=0.9,
                eval_metric="logloss",
                random_state=seed,
            ), "xgboost"
        except Exception:
            pass
    return HistGradientBoostingClassifier(max_iter=120, learning_rate=0.07, random_state=seed), "sklearn_hist_gradient_boosting"


def _positive_probability(model: Any, frame: pd.DataFrame) -> np.ndarray:
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(frame)
        if proba.ndim == 2 and proba.shape[1] > 1:
            return proba[:, 1]
        return proba.reshape(-1)
    if hasattr(model, "decision_function"):
        return _sigmoid(np.asarray(model.decision_function(frame), dtype=float))
    return np.asarray(model.predict(frame), dtype=float)


def _label_for_score(task_type: str, score: float) -> str:
    low, medium, high = LABELS[normalize_task(task_type)]
    if score >= 70:
        return high
    if score >= 40:
        return medium
    return low


def train_synthetic_model(
    *,
    task_type: str,
    model_key: str,
    framework: str,
    version: str,
    sample_size: int,
    seed: int,
) -> dict[str, Any]:
    task = normalize_task(task_type)
    key = normalize_model_key(model_key, task)
    model_version = str(version or datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")).strip()
    frame, target = synthetic_dataset(task, sample_size, seed)
    x_train, x_test, y_train, y_test = train_test_split(
        frame,
        target,
        test_size=0.25,
        random_state=seed,
        stratify=target if len(np.unique(target)) > 1 else None,
    )
    model, resolved_framework = _estimator(framework, seed)
    model.fit(x_train, y_train)
    scores = _positive_probability(model, x_test)
    predictions = (scores >= 0.5).astype(int)
    metrics = {
        "accuracy": float(accuracy_score(y_test, predictions) * 100),
        "precision": float(precision_score(y_test, predictions, zero_division=0) * 100),
        "recall": float(recall_score(y_test, predictions, zero_division=0) * 100),
        "roc_auc": float(roc_auc_score(y_test, scores) * 100) if len(np.unique(y_test)) > 1 else None,
        "sample_size": int(sample_size),
        "train_size": int(len(x_train)),
        "test_size": int(len(x_test)),
        "positive_rate": float(np.mean(target) * 100),
    }
    feature_stats = {
        column: {
            "mean": float(frame[column].mean()),
            "std": float(frame[column].std() or 0),
            "min": float(frame[column].min()),
            "max": float(frame[column].max()),
        }
        for column in FEATURE_KEYS
    }
    metadata = {
        "model_key": key,
        "version": model_version,
        "task_type": task,
        "framework": resolved_framework,
        "feature_keys": FEATURE_KEYS,
        "labels": LABELS[task],
        "metrics": metrics,
        "feature_stats": feature_stats,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_source": "synthetic_autolabel",
    }
    artifact_dir = model_root() / key / model_version
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "model.joblib"
    metadata_path = artifact_dir / "metadata.json"
    joblib.dump({"model": model, "metadata": metadata}, model_path)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    mlflow_run_id = ""
    try:
        import mlflow

        tracking_uri = os.getenv("MLFLOW_TRACKING_URI") or os.getenv("SAAS_MLFLOW_TRACKING_URI")
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment("scentra_phase11_ml")
        with mlflow.start_run(run_name=key) as run:
            mlflow_run_id = run.info.run_id
            mlflow.log_params({"task_type": task, "framework": resolved_framework, "version": model_version, "sample_size": sample_size})
            for metric_key, metric_value in metrics.items():
                if metric_value is not None:
                    mlflow.log_metric(metric_key, float(metric_value))
            mlflow.log_artifact(str(metadata_path))
            mlflow.log_artifact(str(model_path))
    except Exception as exc:
        metadata["mlflow_error"] = str(exc)[:500]
    bentoml_tag = ""
    try:
        import bentoml

        saved = bentoml.sklearn.save_model(f"scentra_{key}", model, labels={"task_type": task, "version": model_version})
        bentoml_tag = str(saved.tag)
    except Exception as exc:
        metadata["bentoml_error"] = str(exc)[:500]
    if mlflow_run_id or bentoml_tag:
        metadata["mlflow_run_id"] = mlflow_run_id
        metadata["bentoml_tag"] = bentoml_tag
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "model_key": key,
        "version": model_version,
        "task_type": task,
        "framework": resolved_framework,
        "artifact_uri": str(model_path),
        "metadata_uri": str(metadata_path),
        "metrics": metrics,
        "feature_keys": FEATURE_KEYS,
        "mlflow_run_id": mlflow_run_id,
        "bentoml_tag": bentoml_tag,
        "metadata": metadata,
    }


def train_autolabel_model(
    *,
    tenant_id: str,
    task_type: str,
    model_key: str,
    framework: str,
    version: str,
    dataset_key: str,
    window_key: str,
    min_samples: int,
    include_global: bool,
    seed: int,
    notes: str = "",
) -> dict[str, Any]:
    from app_saas.ml_service.datasets import build_training_dataset

    task = normalize_task(task_type)
    key = normalize_model_key(model_key, task)
    model_version = str(version or datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")).strip()
    dataset = build_training_dataset(
        tenant_id=tenant_id,
        task_type=task,
        dataset_key=dataset_key,
        version=model_version,
        window_key=window_key,
        min_samples=min_samples,
        include_global=include_global,
        notes=notes,
    )
    frame = dataset["frame"]
    target = np.asarray(dataset["target"], dtype=int)
    feature_keys = list(frame.columns)
    stratify = target if len(np.unique(target)) > 1 and min(np.bincount(target)) >= 2 else None
    test_size = 0.25 if len(target) >= 20 else 0.33
    x_train, x_test, y_train, y_test = train_test_split(
        frame,
        target,
        test_size=test_size,
        random_state=seed,
        stratify=stratify,
    )
    model, resolved_framework = _estimator(framework, seed)
    model.fit(x_train, y_train)
    scores = _positive_probability(model, x_test)
    predictions = (scores >= 0.5).astype(int)
    metrics = {
        "accuracy": float(accuracy_score(y_test, predictions) * 100),
        "precision": float(precision_score(y_test, predictions, zero_division=0) * 100),
        "recall": float(recall_score(y_test, predictions, zero_division=0) * 100),
        "roc_auc": float(roc_auc_score(y_test, scores) * 100) if len(np.unique(y_test)) > 1 else None,
        "sample_size": int(len(target)),
        "train_size": int(len(x_train)),
        "test_size": int(len(x_test)),
        "positive_rate": float(np.mean(target) * 100),
    }
    feature_stats = {
        column: {
            "mean": float(frame[column].mean()),
            "std": float(frame[column].std() or 0),
            "min": float(frame[column].min()),
            "max": float(frame[column].max()),
        }
        for column in feature_keys
    }
    metadata = {
        "model_key": key,
        "version": model_version,
        "task_type": task,
        "framework": resolved_framework,
        "feature_keys": feature_keys,
        "labels": LABELS[task],
        "metrics": metrics,
        "feature_stats": feature_stats,
        "dataset": dataset["summary"],
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "training_source": "postgres_auto_labels",
        "tenant_id": tenant_id,
        "include_global": bool(include_global),
        "raw_content_used": False,
    }
    artifact_dir = model_root() / key / model_version
    artifact_dir.mkdir(parents=True, exist_ok=True)
    model_path = artifact_dir / "model.joblib"
    metadata_path = artifact_dir / "metadata.json"
    joblib.dump({"model": model, "metadata": metadata}, model_path)
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    mlflow_run_id = ""
    try:
        import mlflow

        tracking_uri = os.getenv("MLFLOW_TRACKING_URI") or os.getenv("SAAS_MLFLOW_TRACKING_URI")
        if tracking_uri:
            mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment("scentra_phase11_autolabel")
        with mlflow.start_run(run_name=key) as run:
            mlflow_run_id = run.info.run_id
            mlflow.log_params(
                {
                    "task_type": task,
                    "framework": resolved_framework,
                    "version": model_version,
                    "dataset_key": dataset["summary"].get("dataset_key") or "",
                    "dataset_id": dataset["summary"].get("dataset_id") or "",
                    "window_key": window_key,
                    "include_global": bool(include_global),
                }
            )
            for metric_key, metric_value in metrics.items():
                if metric_value is not None:
                    mlflow.log_metric(metric_key, float(metric_value))
            mlflow.log_artifact(str(metadata_path))
            mlflow.log_artifact(str(model_path))
            mlflow.log_artifact(str(dataset["summary"].get("dataset_uri") or ""))
    except Exception as exc:
        metadata["mlflow_error"] = str(exc)[:500]
    bentoml_tag = ""
    try:
        import bentoml

        saved = bentoml.sklearn.save_model(f"scentra_{key}", model, labels={"task_type": task, "version": model_version, "source": "postgres_auto_labels"})
        bentoml_tag = str(saved.tag)
    except Exception as exc:
        metadata["bentoml_error"] = str(exc)[:500]
    if mlflow_run_id or bentoml_tag:
        metadata["mlflow_run_id"] = mlflow_run_id
        metadata["bentoml_tag"] = bentoml_tag
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "model_key": key,
        "version": model_version,
        "task_type": task,
        "framework": resolved_framework,
        "artifact_uri": str(model_path),
        "metadata_uri": str(metadata_path),
        "metrics": metrics,
        "feature_keys": feature_keys,
        "dataset": dataset["summary"],
        "mlflow_run_id": mlflow_run_id,
        "bentoml_tag": bentoml_tag,
        "metadata": metadata,
    }


def _latest_version(model_key: str) -> str:
    key = normalize_model_key(model_key, "lead_scoring")
    root = model_root() / key
    if not root.exists():
        raise FileNotFoundError(f"model_not_found:{key}")
    versions = sorted([path.name for path in root.iterdir() if path.is_dir()])
    if not versions:
        raise FileNotFoundError(f"model_version_not_found:{key}")
    return versions[-1]


def load_model_package(model_key: str, version: str = "") -> dict[str, Any]:
    key = normalize_model_key(model_key, "lead_scoring")
    resolved_version = str(version or _latest_version(key)).strip()
    path = model_root() / key / resolved_version / "model.joblib"
    if not path.exists():
        raise FileNotFoundError(f"model_artifact_not_found:{key}:{resolved_version}")
    package = joblib.load(path)
    if not isinstance(package, dict) or "model" not in package:
        raise ValueError("invalid_model_package")
    return package


def model_predict(
    *,
    model_key: str,
    version: str,
    task_type: str,
    features: dict[str, Any],
) -> dict[str, Any]:
    task = normalize_task(task_type)
    package = load_model_package(model_key, version)
    metadata = package.get("metadata") or {}
    feature_keys = list(metadata.get("feature_keys") or FEATURE_KEYS)
    row = {key: float(features.get(key) or 0) for key in feature_keys}
    frame = pd.DataFrame([row], columns=feature_keys)
    probability = float(_positive_probability(package["model"], frame)[0])
    score = max(0.0, min(probability * 100.0, 100.0))
    return {
        "model_key": metadata.get("model_key") or normalize_model_key(model_key, task),
        "version": metadata.get("version") or version or "",
        "task_type": task,
        "score": round(score, 4),
        "label": _label_for_score(task, score),
        "confidence": round(max(probability, 1.0 - probability) * 100.0, 4),
        "features_used": row,
        "metadata": {
            "framework": metadata.get("framework") or "",
            "trained_at": metadata.get("trained_at") or "",
            "training_source": metadata.get("training_source") or "",
        },
    }


def evaluate_drift(*, model_key: str, version: str, task_type: str, current_features: dict[str, Any]) -> dict[str, Any]:
    package = load_model_package(model_key, version)
    metadata = package.get("metadata") or {}
    feature_stats = metadata.get("feature_stats") or {}
    signals = []
    distances = []
    for key in metadata.get("feature_keys") or FEATURE_KEYS:
        stats = feature_stats.get(key) or {}
        std = float(stats.get("std") or 0)
        mean = float(stats.get("mean") or 0)
        current = float(current_features.get(key) or 0)
        distance = abs(current - mean) / std if std > 0 else 0.0
        distances.append(distance)
        if distance >= 3:
            signals.append({"feature_key": key, "distance": round(distance, 4), "current": current, "baseline_mean": mean})
    drift_score = min(100.0, float(np.mean(distances) * 20.0 if distances else 0.0))
    status = "degraded" if drift_score >= 50 or len(signals) >= 3 else "watch" if drift_score >= 25 or signals else "healthy"
    return {
        "model_key": metadata.get("model_key") or model_key,
        "version": metadata.get("version") or version or "",
        "task_type": normalize_task(task_type),
        "drift_score": round(drift_score, 4),
        "status": status,
        "signals": signals[:20],
        "baseline": {key: feature_stats.get(key, {}) for key in metadata.get("feature_keys") or FEATURE_KEYS},
        "current": {key: float(current_features.get(key) or 0) for key in metadata.get("feature_keys") or FEATURE_KEYS},
    }


def list_local_models() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    root = model_root()
    for model_dir in sorted([path for path in root.iterdir() if path.is_dir()]):
        for version_dir in sorted([path for path in model_dir.iterdir() if path.is_dir()]):
            metadata_path = version_dir / "metadata.json"
            metadata: dict[str, Any] = {}
            if metadata_path.exists():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            items.append(
                {
                    "model_key": metadata.get("model_key") or model_dir.name,
                    "version": metadata.get("version") or version_dir.name,
                    "task_type": metadata.get("task_type") or "",
                    "framework": metadata.get("framework") or "",
                    "artifact_uri": str(version_dir / "model.joblib"),
                    "metrics": metadata.get("metrics") or {},
                    "trained_at": metadata.get("trained_at") or "",
                }
            )
    return items
