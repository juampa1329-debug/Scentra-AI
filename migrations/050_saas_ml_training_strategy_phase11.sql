-- Phase 11 ML training strategy.
-- Event contracts, auto-labels, feature pipeline runs, training datasets and model evaluations.

CREATE TABLE IF NOT EXISTS saas_intelligence_event_contracts (
    event_type TEXT PRIMARY KEY,
    version TEXT NOT NULL DEFAULT 'v1',
    category TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    required_fields_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    schema_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    pii_policy TEXT NOT NULL DEFAULT 'no_raw_content',
    retention_days INTEGER NOT NULL DEFAULT 365,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_event_contracts_category
    ON saas_intelligence_event_contracts (category, enabled);

CREATE TABLE IF NOT EXISTS saas_intelligence_event_replay_cursors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    source_name TEXT NOT NULL,
    cursor_key TEXT NOT NULL DEFAULT '',
    last_event_at TIMESTAMP NULL,
    last_replay_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, source_name, cursor_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_event_replay_cursors_source
    ON saas_intelligence_event_replay_cursors (source_name, status, updated_at DESC);

ALTER TABLE saas_intelligence_feature_values
    ADD COLUMN IF NOT EXISTS feature_set_key TEXT NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS feature_version TEXT NOT NULL DEFAULT 'v1',
    ADD COLUMN IF NOT EXISTS quality_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_features_set
    ON saas_intelligence_feature_values (tenant_id, feature_set_key, feature_version, computed_at DESC);

CREATE TABLE IF NOT EXISTS saas_ml_auto_labels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    prediction_type TEXT NOT NULL,
    subject_type TEXT NOT NULL DEFAULT 'tenant',
    subject_id TEXT NOT NULL DEFAULT '',
    label_key TEXT NOT NULL,
    label_value BOOLEAN NOT NULL,
    label_text TEXT NOT NULL DEFAULT '',
    label_confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    source_event_id UUID NULL REFERENCES saas_intelligence_events(id) ON DELETE SET NULL,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    window_key TEXT NOT NULL DEFAULT '90d',
    generated_by TEXT NOT NULL DEFAULT 'auto_labeler_v1',
    generated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NULL,
    replay_key TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, prediction_type, subject_type, subject_id, label_key, window_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_ml_auto_labels_replay_key
    ON saas_ml_auto_labels (tenant_id, replay_key)
    WHERE replay_key <> '';

CREATE INDEX IF NOT EXISTS idx_saas_ml_auto_labels_training
    ON saas_ml_auto_labels (tenant_id, prediction_type, window_key, generated_at DESC);

CREATE TABLE IF NOT EXISTS saas_ml_feature_sets (
    feature_set_key TEXT PRIMARY KEY,
    prediction_type TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT 'v1',
    status TEXT NOT NULL DEFAULT 'active',
    feature_keys_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    definitions_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ml_feature_sets_prediction
    ON saas_ml_feature_sets (prediction_type, status);

CREATE TABLE IF NOT EXISTS saas_ml_feature_pipeline_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    pipeline_key TEXT NOT NULL,
    prediction_type TEXT NOT NULL DEFAULT '',
    feature_set_key TEXT NOT NULL DEFAULT '',
    window_key TEXT NOT NULL DEFAULT '90d',
    status TEXT NOT NULL DEFAULT 'running',
    subjects_processed INTEGER NOT NULL DEFAULT 0,
    features_written INTEGER NOT NULL DEFAULT 0,
    labels_generated INTEGER NOT NULL DEFAULT 0,
    stats_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_text TEXT NOT NULL DEFAULT '',
    started_at TIMESTAMP NULL,
    completed_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ml_feature_pipeline_runs_tenant
    ON saas_ml_feature_pipeline_runs (tenant_id, prediction_type, status, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_ml_training_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    dataset_key TEXT NOT NULL,
    prediction_type TEXT NOT NULL,
    feature_set_key TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT 'v1',
    window_key TEXT NOT NULL DEFAULT '90d',
    label_policy TEXT NOT NULL DEFAULT 'auto_label_v1',
    source TEXT NOT NULL DEFAULT 'postgres_feature_store',
    sample_count INTEGER NOT NULL DEFAULT 0,
    positive_count INTEGER NOT NULL DEFAULT 0,
    negative_count INTEGER NOT NULL DEFAULT 0,
    label_distribution_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    feature_summary_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    dataset_uri TEXT NOT NULL DEFAULT '',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (dataset_key, version)
);

CREATE INDEX IF NOT EXISTS idx_saas_ml_training_datasets_task
    ON saas_ml_training_datasets (prediction_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ml_training_datasets_tenant
    ON saas_ml_training_datasets (tenant_id, prediction_type, created_at DESC)
    WHERE tenant_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS saas_ml_model_evaluations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    model_key TEXT NOT NULL,
    model_version TEXT NOT NULL DEFAULT '',
    prediction_type TEXT NOT NULL DEFAULT '',
    evaluation_type TEXT NOT NULL DEFAULT 'offline',
    dataset_id UUID NULL REFERENCES saas_ml_training_datasets(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'completed',
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    slices_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_ml_model_evaluations_model
    ON saas_ml_model_evaluations (model_key, model_version, evaluation_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_ml_model_evaluations_tenant
    ON saas_ml_model_evaluations (tenant_id, prediction_type, created_at DESC)
    WHERE tenant_id IS NOT NULL;
