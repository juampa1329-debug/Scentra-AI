-- 048_saas_intelligence_model_rollouts_phase11.sql
-- Phase 11 model rollout governance: model registry controls, shadow/canary
-- metadata and auditable rollout events. No external ML runtime required.

ALTER TABLE saas_intelligence_model_registry
    ADD COLUMN IF NOT EXISTS rollout_mode TEXT NOT NULL DEFAULT 'production',
    ADD COLUMN IF NOT EXISTS traffic_percent INTEGER NOT NULL DEFAULT 100,
    ADD COLUMN IF NOT EXISTS min_labeled_count INTEGER NOT NULL DEFAULT 10,
    ADD COLUMN IF NOT EXISTS min_accuracy NUMERIC(8,4) NOT NULL DEFAULT 70,
    ADD COLUMN IF NOT EXISTS max_drift_score NUMERIC(8,4) NOT NULL DEFAULT 25,
    ADD COLUMN IF NOT EXISTS promotion_status TEXT NOT NULL DEFAULT 'approved',
    ADD COLUMN IF NOT EXISTS approved_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP NULL;

CREATE TABLE IF NOT EXISTS saas_intelligence_model_rollout_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    model_key TEXT NOT NULL REFERENCES saas_intelligence_model_registry(model_key) ON DELETE CASCADE,
    tenant_id UUID NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    action TEXT NOT NULL DEFAULT '',
    previous_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    next_state_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    reason TEXT NOT NULL DEFAULT '',
    created_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_rollout_events_model_time
ON saas_intelligence_model_rollout_events (model_key, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_rollout_events_tenant_time
ON saas_intelligence_model_rollout_events (tenant_id, created_at DESC)
WHERE tenant_id IS NOT NULL;

UPDATE saas_intelligence_model_registry
SET rollout_mode = COALESCE(NULLIF(rollout_mode, ''), 'production'),
    traffic_percent = LEAST(100, GREATEST(0, COALESCE(traffic_percent, 100))),
    min_labeled_count = GREATEST(0, COALESCE(min_labeled_count, 10)),
    min_accuracy = LEAST(100, GREATEST(0, COALESCE(min_accuracy, 70))),
    max_drift_score = LEAST(100, GREATEST(0, COALESCE(max_drift_score, 25))),
    promotion_status = COALESCE(NULLIF(promotion_status, ''), 'approved'),
    metadata_json = metadata_json || '{"rollout_governance":"phase11"}'::jsonb,
    updated_at = NOW()
WHERE model_key IN (
    'baseline_lead_scoring_v1',
    'baseline_churn_prediction_v1',
    'baseline_smart_remarketing_v1',
    'baseline_operational_anomaly_v1'
);
