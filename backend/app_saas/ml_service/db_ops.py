from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from app_saas.db import db_session


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False, default=str)


def _list_json(value: Any) -> str:
    return json.dumps(value if value is not None else [], ensure_ascii=False, default=str)


def try_record_training_job_start(payload: dict[str, Any]) -> str:
    try:
        with db_session() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_ml_training_jobs (
                        tenant_id, job_type, prediction_type, model_key, framework, status,
                        source, dataset_summary_json, params_json, created_by_user_id, started_at, updated_at
                    )
                    VALUES (
                        CAST(NULLIF(:tenant_id, '') AS uuid), :job_type, :prediction_type, :model_key,
                        :framework, 'running', :source, CAST(:dataset_summary_json AS jsonb),
                        CAST(:params_json AS jsonb), CAST(NULLIF(:created_by_user_id, '') AS uuid), NOW(), NOW()
                    )
                    RETURNING id::text
                    """
                ),
                {
                    "tenant_id": str(payload.get("tenant_id") or ""),
                    "job_type": str(payload.get("job_type") or "synthetic"),
                    "prediction_type": str(payload.get("prediction_type") or ""),
                    "model_key": str(payload.get("model_key") or ""),
                    "framework": str(payload.get("framework") or ""),
                    "source": str(payload.get("source") or "ml_service"),
                    "dataset_summary_json": _json(payload.get("dataset_summary_json") or {}),
                    "params_json": _json(payload.get("params_json") or {}),
                    "created_by_user_id": str(payload.get("created_by_user_id") or ""),
                },
            ).mappings().first()
            return str((row or {}).get("id") or "")
    except Exception:
        return ""


def try_record_training_job_complete(job_id: str, *, result: dict[str, Any], error: str = "") -> None:
    if not job_id:
        return
    try:
        with db_session() as conn:
            conn.execute(
                text(
                    """
                    UPDATE saas_ml_training_jobs
                    SET status = :status,
                        result_json = CAST(:result_json AS jsonb),
                        error_text = :error_text,
                        mlflow_run_id = :mlflow_run_id,
                        bentoml_tag = :bentoml_tag,
                        artifact_uri = :artifact_uri,
                        completed_at = NOW(),
                        updated_at = NOW()
                    WHERE id = CAST(:job_id AS uuid)
                    """
                ),
                {
                    "job_id": job_id,
                    "status": "failed" if error else "succeeded",
                    "result_json": _json(result or {}),
                    "error_text": str(error or "")[:2000],
                    "mlflow_run_id": str((result or {}).get("mlflow_run_id") or ""),
                    "bentoml_tag": str((result or {}).get("bentoml_tag") or ""),
                    "artifact_uri": str((result or {}).get("artifact_uri") or ""),
                },
            )
    except Exception:
        return


def try_record_model_artifact(payload: dict[str, Any]) -> None:
    try:
        with db_session() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO saas_ml_model_artifacts (
                        tenant_id, model_key, prediction_type, framework, version, artifact_uri,
                        local_path, mlflow_run_id, bentoml_tag, status, metrics_json,
                        training_job_id, metadata_json, updated_at
                    )
                    VALUES (
                        CAST(NULLIF(:tenant_id, '') AS uuid), :model_key, :prediction_type,
                        :framework, :version, :artifact_uri, :local_path, :mlflow_run_id,
                        :bentoml_tag, :status, CAST(:metrics_json AS jsonb),
                        CAST(NULLIF(:training_job_id, '') AS uuid), CAST(:metadata_json AS jsonb), NOW()
                    )
                    ON CONFLICT (model_key, version)
                    DO UPDATE SET
                        artifact_uri = EXCLUDED.artifact_uri,
                        local_path = EXCLUDED.local_path,
                        mlflow_run_id = EXCLUDED.mlflow_run_id,
                        bentoml_tag = EXCLUDED.bentoml_tag,
                        metrics_json = EXCLUDED.metrics_json,
                        metadata_json = EXCLUDED.metadata_json,
                        updated_at = NOW()
                    """
                ),
                {
                    "tenant_id": str(payload.get("tenant_id") or ""),
                    "model_key": str(payload.get("model_key") or ""),
                    "prediction_type": str(payload.get("prediction_type") or payload.get("task_type") or ""),
                    "framework": str(payload.get("framework") or ""),
                    "version": str(payload.get("version") or ""),
                    "artifact_uri": str(payload.get("artifact_uri") or ""),
                    "local_path": str(payload.get("local_path") or payload.get("artifact_uri") or ""),
                    "mlflow_run_id": str(payload.get("mlflow_run_id") or ""),
                    "bentoml_tag": str(payload.get("bentoml_tag") or ""),
                    "status": str(payload.get("status") or "candidate"),
                    "metrics_json": _json(payload.get("metrics") or {}),
                    "training_job_id": str(payload.get("training_job_id") or ""),
                    "metadata_json": _json(payload.get("metadata") or {}),
                },
            )
    except Exception:
        return


def try_record_training_dataset(payload: dict[str, Any]) -> str:
    try:
        with db_session() as conn:
            row = conn.execute(
                text(
                    """
                    INSERT INTO saas_ml_training_datasets (
                        tenant_id, dataset_key, prediction_type, feature_set_key, version,
                        window_key, label_policy, source, sample_count, positive_count,
                        negative_count, label_distribution_json, feature_summary_json,
                        dataset_uri, metadata_json, created_by_user_id, updated_at
                    )
                    VALUES (
                        CAST(NULLIF(:tenant_id, '') AS uuid), :dataset_key, :prediction_type,
                        :feature_set_key, :version, :window_key, 'auto_label_v1',
                        'postgres_feature_store', :sample_count, :positive_count,
                        :negative_count, CAST(:label_distribution_json AS jsonb),
                        CAST(:feature_summary_json AS jsonb), :dataset_uri,
                        CAST(:metadata_json AS jsonb), CAST(NULLIF(:created_by_user_id, '') AS uuid), NOW()
                    )
                    ON CONFLICT (dataset_key, version)
                    DO UPDATE SET
                        sample_count = EXCLUDED.sample_count,
                        positive_count = EXCLUDED.positive_count,
                        negative_count = EXCLUDED.negative_count,
                        label_distribution_json = EXCLUDED.label_distribution_json,
                        feature_summary_json = EXCLUDED.feature_summary_json,
                        dataset_uri = EXCLUDED.dataset_uri,
                        metadata_json = EXCLUDED.metadata_json,
                        updated_at = NOW()
                    RETURNING id::text
                    """
                ),
                {
                    "tenant_id": str(payload.get("tenant_id") or ""),
                    "dataset_key": str(payload.get("dataset_key") or ""),
                    "prediction_type": str(payload.get("prediction_type") or payload.get("task_type") or ""),
                    "feature_set_key": str(payload.get("feature_set_key") or ""),
                    "version": str(payload.get("version") or "v1"),
                    "window_key": str(payload.get("window_key") or "90d"),
                    "sample_count": int(payload.get("sample_count") or 0),
                    "positive_count": int(payload.get("positive_count") or 0),
                    "negative_count": int(payload.get("negative_count") or 0),
                    "label_distribution_json": _json(payload.get("label_distribution_json") or {}),
                    "feature_summary_json": _json(payload.get("feature_summary_json") or {}),
                    "dataset_uri": str(payload.get("dataset_uri") or ""),
                    "metadata_json": _json(payload.get("metadata_json") or {}),
                    "created_by_user_id": str(payload.get("created_by_user_id") or ""),
                },
            ).mappings().first()
            return str((row or {}).get("id") or "")
    except Exception:
        return ""


def try_record_model_evaluation(payload: dict[str, Any]) -> None:
    try:
        with db_session() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO saas_ml_model_evaluations (
                        tenant_id, model_key, model_version, prediction_type,
                        evaluation_type, dataset_id, status, metrics_json,
                        slices_json, notes
                    )
                    VALUES (
                        CAST(NULLIF(:tenant_id, '') AS uuid), :model_key,
                        :model_version, :prediction_type, :evaluation_type,
                        CAST(NULLIF(:dataset_id, '') AS uuid), :status,
                        CAST(:metrics_json AS jsonb), CAST(:slices_json AS jsonb),
                        :notes
                    )
                    """
                ),
                {
                    "tenant_id": str(payload.get("tenant_id") or ""),
                    "model_key": str(payload.get("model_key") or ""),
                    "model_version": str(payload.get("model_version") or payload.get("version") or ""),
                    "prediction_type": str(payload.get("prediction_type") or payload.get("task_type") or ""),
                    "evaluation_type": str(payload.get("evaluation_type") or "offline"),
                    "dataset_id": str(payload.get("dataset_id") or ""),
                    "status": str(payload.get("status") or "completed"),
                    "metrics_json": _json(payload.get("metrics_json") or payload.get("metrics") or {}),
                    "slices_json": _json(payload.get("slices_json") or {}),
                    "notes": str(payload.get("notes") or "")[:2000],
                },
            )
    except Exception:
        return


def try_record_inference(payload: dict[str, Any]) -> None:
    try:
        with db_session() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO saas_ml_inference_runs (
                        tenant_id, prediction_id, model_key, model_version, prediction_type,
                        subject_type, subject_id, mode, status, score, label, confidence,
                        latency_ms, fallback_used, input_json, output_json, error_text
                    )
                    VALUES (
                        CAST(:tenant_id AS uuid), CAST(NULLIF(:prediction_id, '') AS uuid),
                        :model_key, :model_version, :prediction_type, :subject_type, :subject_id,
                        :mode, :status, :score, :label, :confidence, :latency_ms, :fallback_used,
                        CAST(:input_json AS jsonb), CAST(:output_json AS jsonb), :error_text
                    )
                    """
                ),
                {
                    "tenant_id": str(payload.get("tenant_id") or ""),
                    "prediction_id": str(payload.get("prediction_id") or ""),
                    "model_key": str(payload.get("model_key") or ""),
                    "model_version": str(payload.get("model_version") or payload.get("version") or ""),
                    "prediction_type": str(payload.get("prediction_type") or payload.get("task_type") or ""),
                    "subject_type": str(payload.get("subject_type") or "tenant"),
                    "subject_id": str(payload.get("subject_id") or ""),
                    "mode": str(payload.get("mode") or "shadow"),
                    "status": str(payload.get("status") or "ok"),
                    "score": payload.get("score"),
                    "label": str(payload.get("label") or ""),
                    "confidence": payload.get("confidence"),
                    "latency_ms": int(payload.get("latency_ms") or 0),
                    "fallback_used": bool(payload.get("fallback_used", False)),
                    "input_json": _json(payload.get("input_json") or {}),
                    "output_json": _json(payload.get("output_json") or {}),
                    "error_text": str(payload.get("error_text") or "")[:2000],
                },
            )
    except Exception:
        return


def try_record_drift(payload: dict[str, Any]) -> None:
    try:
        with db_session() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO saas_ml_drift_snapshots (
                        tenant_id, model_key, prediction_type, window_key, baseline_json,
                        current_json, drift_score, status, signals_json, computed_at
                    )
                    VALUES (
                        CAST(NULLIF(:tenant_id, '') AS uuid), :model_key, :prediction_type,
                        :window_key, CAST(:baseline_json AS jsonb), CAST(:current_json AS jsonb),
                        :drift_score, :status, CAST(:signals_json AS jsonb), NOW()
                    )
                    """
                ),
                {
                    "tenant_id": str(payload.get("tenant_id") or ""),
                    "model_key": str(payload.get("model_key") or ""),
                    "prediction_type": str(payload.get("prediction_type") or payload.get("task_type") or ""),
                    "window_key": str(payload.get("window_key") or "30d"),
                    "baseline_json": _json(payload.get("baseline") or {}),
                    "current_json": _json(payload.get("current") or {}),
                    "drift_score": payload.get("drift_score"),
                    "status": str(payload.get("status") or "unknown"),
                    "signals_json": _list_json(payload.get("signals") or []),
                },
            )
    except Exception:
        return
