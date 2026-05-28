from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

from app_saas.db import db_session
from app_saas.ml_service.db_ops import try_record_training_dataset

TASK_FEATURE_KEYS: dict[str, list[str]] = {
    "lead_scoring": [
        "response_time",
        "message_count",
        "asked_for_price",
        "engagement_score",
        "avg_reply_speed",
        "channel_source_score",
        "followup_count",
    ],
    "churn_prediction": [
        "inactivity_days",
        "negative_sentiment_ratio",
        "response_drop",
        "ticket_frequency",
        "engagement_decline",
        "message_count",
        "engagement_score",
    ],
    "smart_remarketing": [
        "open_rate",
        "click_rate",
        "best_hour",
        "best_channel_score",
        "campaign_engagement",
        "engagement_score",
        "inactivity_days",
    ],
    "operational_anomaly": [
        "webhook_errors_24h",
        "ai_failed_24h",
        "outbound_failed_24h",
        "dead_letters_open",
        "event_failure_rate",
    ],
}


def normalize_task(value: str) -> str:
    task = str(value or "lead_scoring").strip().lower().replace("-", "_")
    if task not in TASK_FEATURE_KEYS:
        raise ValueError(f"unsupported_task:{task}")
    return task


def feature_set_key(task_type: str) -> str:
    return f"{normalize_task(task_type)}_v1"


def dataset_root() -> Path:
    root = Path(os.getenv("SAAS_ML_DATASET_DIR") or os.getenv("SAAS_ML_MODEL_DIR") or "/models") / "datasets"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _dataset_version(version: str) -> str:
    return str(version or datetime.now(timezone.utc).strftime("v%Y%m%d%H%M%S")).strip()


def _dataset_key(value: str, task_type: str, tenant_id: str, window_key: str) -> str:
    clean = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if clean:
        return clean
    scope = tenant_id[:8] if tenant_id else "global"
    return f"{normalize_task(task_type)}_{scope}_{window_key}".replace("-", "_")


def _feature_summary(frame: pd.DataFrame) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for column in frame.columns:
        series = frame[column]
        summary[column] = {
            "mean": float(series.mean()) if len(series) else 0.0,
            "std": float(series.std() or 0.0) if len(series) else 0.0,
            "min": float(series.min()) if len(series) else 0.0,
            "max": float(series.max()) if len(series) else 0.0,
            "missing": int(series.isna().sum()),
        }
    return summary


def build_training_dataset(
    *,
    tenant_id: str = "",
    task_type: str = "lead_scoring",
    dataset_key: str = "",
    version: str = "",
    window_key: str = "90d",
    min_samples: int = 50,
    include_global: bool = False,
    created_by_user_id: str = "",
    notes: str = "",
) -> dict[str, Any]:
    task = normalize_task(task_type)
    keys = TASK_FEATURE_KEYS[task]
    clean_tenant = str(tenant_id or "").strip()
    clean_window = str(window_key or "90d").strip() or "90d"
    resolved_key = _dataset_key(dataset_key, task, clean_tenant, clean_window)
    resolved_version = _dataset_version(version)
    min_count = max(5, int(min_samples or 50))

    with db_session() as conn:
        rows = conn.execute(
            text(
                """
                SELECT l.tenant_id::text AS tenant_id,
                       l.subject_type,
                       l.subject_id,
                       l.label_value,
                       l.label_key,
                       l.label_confidence,
                       l.evidence_json,
                       jsonb_object_agg(f.feature_key, COALESCE(f.value_numeric, 0)) FILTER (WHERE f.feature_key IS NOT NULL) AS features_json
                FROM saas_ml_auto_labels l
                LEFT JOIN saas_intelligence_feature_values f
                  ON f.tenant_id = l.tenant_id
                 AND f.subject_type = l.subject_type
                 AND f.subject_id = l.subject_id
                 AND f.window_key = l.window_key
                WHERE l.prediction_type = :task_type
                  AND l.window_key = :window_key
                  AND (CAST(NULLIF(:tenant_id, '') AS uuid) IS NULL OR l.tenant_id = CAST(NULLIF(:tenant_id, '') AS uuid) OR :include_global = TRUE)
                GROUP BY l.tenant_id, l.subject_type, l.subject_id, l.label_value, l.label_key, l.label_confidence, l.evidence_json
                ORDER BY MAX(l.generated_at) DESC
                """
            ),
            {
                "task_type": task,
                "window_key": clean_window,
                "tenant_id": clean_tenant,
                "include_global": bool(include_global),
            },
        ).mappings().all()

    feature_rows: list[dict[str, float]] = []
    labels: list[int] = []
    subjects: list[dict[str, Any]] = []
    for row in rows:
        features_json = row.get("features_json") or {}
        if isinstance(features_json, str):
            try:
                features_json = json.loads(features_json)
            except json.JSONDecodeError:
                features_json = {}
        feature_row = {key: float((features_json or {}).get(key) or 0) for key in keys}
        if not any(value != 0 for value in feature_row.values()):
            continue
        feature_rows.append(feature_row)
        labels.append(1 if bool(row.get("label_value")) else 0)
        subjects.append(
            {
                "tenant_id": row.get("tenant_id") or "",
                "subject_type": row.get("subject_type") or "",
                "subject_id": row.get("subject_id") or "",
                "label_key": row.get("label_key") or "",
                "label_confidence": float(row.get("label_confidence") or 0),
            }
        )

    sample_count = len(feature_rows)
    positive_count = int(sum(labels))
    negative_count = int(sample_count - positive_count)
    if sample_count < min_count:
        raise ValueError(f"insufficient_labeled_samples:{sample_count}/{min_count}")
    if positive_count <= 0 or negative_count <= 0:
        raise ValueError("single_class_dataset")

    frame = pd.DataFrame(feature_rows, columns=keys).fillna(0.0)
    target = pd.Series(labels, name="label")
    dataset_dir = dataset_root() / resolved_key / resolved_version
    dataset_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = dataset_dir / "dataset.csv"
    manifest_path = dataset_dir / "manifest.json"
    export_frame = frame.copy()
    export_frame["label"] = target
    export_frame.to_csv(dataset_path, index=False)
    summary = {
        "dataset_key": resolved_key,
        "version": resolved_version,
        "task_type": task,
        "tenant_id": clean_tenant,
        "feature_set_key": feature_set_key(task),
        "feature_keys": keys,
        "sample_count": sample_count,
        "positive_count": positive_count,
        "negative_count": negative_count,
        "label_distribution": {"positive": positive_count, "negative": negative_count},
        "feature_summary": _feature_summary(frame),
        "dataset_uri": str(dataset_path),
        "manifest_uri": str(manifest_path),
        "window_key": clean_window,
        "include_global": bool(include_global),
        "notes": notes,
        "subjects_sample": subjects[:20],
        "raw_content_used": False,
    }
    manifest_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    dataset_id = try_record_training_dataset(
        {
            "tenant_id": clean_tenant,
            "dataset_key": resolved_key,
            "prediction_type": task,
            "feature_set_key": feature_set_key(task),
            "version": resolved_version,
            "window_key": clean_window,
            "sample_count": sample_count,
            "positive_count": positive_count,
            "negative_count": negative_count,
            "label_distribution_json": summary["label_distribution"],
            "feature_summary_json": summary["feature_summary"],
            "dataset_uri": str(dataset_path),
            "metadata_json": {
                "manifest_uri": str(manifest_path),
                "feature_keys": keys,
                "include_global": bool(include_global),
                "raw_content_used": False,
                "notes": notes,
            },
            "created_by_user_id": created_by_user_id,
        }
    )
    summary["dataset_id"] = dataset_id
    return {"frame": frame, "target": target.to_numpy(dtype=int), "summary": summary}
