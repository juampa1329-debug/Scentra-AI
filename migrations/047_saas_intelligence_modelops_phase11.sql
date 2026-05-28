-- 047_saas_intelligence_modelops_phase11.sql
-- Phase 11 ModelOps foundation: prediction feedback, model metrics and
-- feedback-aware baseline registry metadata. No external ML runtime required.

CREATE TABLE IF NOT EXISTS saas_intelligence_prediction_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    prediction_id UUID NOT NULL REFERENCES saas_intelligence_predictions(id) ON DELETE CASCADE,
    feedback_type TEXT NOT NULL DEFAULT 'outcome',
    actual_label TEXT NOT NULL DEFAULT '',
    actual_score NUMERIC(8,4) NULL,
    is_correct BOOLEAN NULL,
    outcome_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    notes TEXT NOT NULL DEFAULT '',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, prediction_id, feedback_type)
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_feedback_tenant_time
ON saas_intelligence_prediction_feedback (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_feedback_prediction
ON saas_intelligence_prediction_feedback (tenant_id, prediction_id);

CREATE TABLE IF NOT EXISTS saas_intelligence_model_metrics (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    model_key TEXT NOT NULL,
    prediction_type TEXT NOT NULL DEFAULT '',
    window_key TEXT NOT NULL DEFAULT '90d',
    sample_size INTEGER NOT NULL DEFAULT 0,
    labeled_count INTEGER NOT NULL DEFAULT 0,
    accuracy NUMERIC(8,4) NULL,
    precision_score NUMERIC(8,4) NULL,
    recall_score NUMERIC(8,4) NULL,
    avg_confidence NUMERIC(8,4) NULL,
    avg_score NUMERIC(8,4) NULL,
    avg_error NUMERIC(8,4) NULL,
    drift_score NUMERIC(8,4) NULL,
    status TEXT NOT NULL DEFAULT 'insufficient_data',
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, model_key, prediction_type, window_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_model_metrics_tenant_status
ON saas_intelligence_model_metrics (tenant_id, status, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_model_metrics_model
ON saas_intelligence_model_metrics (model_key, prediction_type, computed_at DESC);

UPDATE saas_intelligence_model_registry
SET metadata_json = metadata_json || '{"requires_feedback":true,"modelops_phase":"11","training_state":"baseline_rules"}'::jsonb,
    updated_at = NOW()
WHERE model_key IN (
    'baseline_lead_scoring_v1',
    'baseline_churn_prediction_v1',
    'baseline_smart_remarketing_v1',
    'baseline_operational_anomaly_v1'
);
