-- Phase 11 ML infrastructure.
-- Optional runtime tables for real trained-ML rollout, disabled by default.

CREATE TABLE IF NOT EXISTS saas_ml_training_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL DEFAULT 'synthetic',
    prediction_type TEXT NOT NULL DEFAULT '',
    model_key TEXT NOT NULL DEFAULT '',
    framework TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned',
    source TEXT NOT NULL DEFAULT 'admin',
    dataset_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    params_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    result_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT NOT NULL DEFAULT '',
    mlflow_run_id TEXT NOT NULL DEFAULT '',
    bentoml_tag TEXT NOT NULL DEFAULT '',
    artifact_uri TEXT NOT NULL DEFAULT '',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ml_training_jobs_tenant_status
    ON saas_ml_training_jobs (tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ml_training_jobs_model
    ON saas_ml_training_jobs (model_key, prediction_type, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ml_model_artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    model_key TEXT NOT NULL,
    prediction_type TEXT NOT NULL DEFAULT '',
    framework TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT 'v1',
    artifact_uri TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL DEFAULT '',
    mlflow_run_id TEXT NOT NULL DEFAULT '',
    bentoml_tag TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    training_job_id UUID NULL REFERENCES saas_ml_training_jobs(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (model_key, version)
);

CREATE INDEX IF NOT EXISTS idx_saas_ml_model_artifacts_task_status
    ON saas_ml_model_artifacts (prediction_type, status, updated_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ml_model_artifacts_tenant
    ON saas_ml_model_artifacts (tenant_id, prediction_type, updated_at DESC)
    WHERE tenant_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS saas_ml_inference_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    prediction_id UUID NULL REFERENCES saas_intelligence_predictions(id) ON DELETE SET NULL,
    model_key TEXT NOT NULL DEFAULT '',
    model_version TEXT NOT NULL DEFAULT '',
    prediction_type TEXT NOT NULL DEFAULT '',
    subject_type TEXT NOT NULL DEFAULT 'tenant',
    subject_id TEXT NOT NULL DEFAULT '',
    mode TEXT NOT NULL DEFAULT 'shadow',
    status TEXT NOT NULL DEFAULT 'ok',
    score NUMERIC(8,4) NULL,
    label TEXT NOT NULL DEFAULT '',
    confidence NUMERIC(8,4) NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    fallback_used BOOLEAN NOT NULL DEFAULT FALSE,
    input_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ml_inference_runs_tenant_time
    ON saas_ml_inference_runs (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ml_inference_runs_model_status
    ON saas_ml_inference_runs (model_key, status, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ml_drift_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    model_key TEXT NOT NULL DEFAULT '',
    prediction_type TEXT NOT NULL DEFAULT '',
    window_key TEXT NOT NULL DEFAULT '30d',
    baseline_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    drift_score NUMERIC(8,4) NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    signals_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ml_drift_snapshots_model_time
    ON saas_ml_drift_snapshots (model_key, prediction_type, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ml_drift_snapshots_tenant_status
    ON saas_ml_drift_snapshots (tenant_id, status, computed_at DESC)
    WHERE tenant_id IS NOT NULL;
