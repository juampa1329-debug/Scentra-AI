-- 046_saas_intelligence_engine_phase11.sql
-- Foundation for Scentra Intelligence Engine: event store, feature store,
-- predictions, recommendations, model registry, licensing and usage.

CREATE TABLE IF NOT EXISTS saas_intelligence_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    conversation_id UUID NULL REFERENCES saas_conversations(id) ON DELETE SET NULL,
    customer_key TEXT NOT NULL DEFAULT '',
    occurred_at TIMESTAMP NOT NULL DEFAULT NOW(),
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    correlation_id TEXT NOT NULL DEFAULT '',
    replay_key TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_events_tenant_type_time
ON saas_intelligence_events (tenant_id, event_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_events_tenant_entity
ON saas_intelligence_events (tenant_id, entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_events_conversation
ON saas_intelligence_events (tenant_id, conversation_id, occurred_at DESC)
WHERE conversation_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_saas_intelligence_events_replay_key
ON saas_intelligence_events (tenant_id, replay_key)
WHERE replay_key <> '';

CREATE TABLE IF NOT EXISTS saas_intelligence_feature_values (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL DEFAULT 'tenant',
    subject_id TEXT NOT NULL DEFAULT '',
    feature_key TEXT NOT NULL,
    window_key TEXT NOT NULL DEFAULT 'latest',
    value_numeric NUMERIC(18,6) NULL,
    value_text TEXT NOT NULL DEFAULT '',
    value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT 'snapshot',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, subject_type, subject_id, feature_key, window_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_features_tenant_subject
ON saas_intelligence_feature_values (tenant_id, subject_type, subject_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_features_key
ON saas_intelligence_feature_values (tenant_id, feature_key, computed_at DESC);

CREATE TABLE IF NOT EXISTS saas_intelligence_predictions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    subject_type TEXT NOT NULL DEFAULT 'tenant',
    subject_id TEXT NOT NULL DEFAULT '',
    prediction_type TEXT NOT NULL,
    model_key TEXT NOT NULL DEFAULT 'baseline_rules',
    model_version TEXT NOT NULL DEFAULT 'v1',
    mode TEXT NOT NULL DEFAULT 'demo',
    score NUMERIC(8,4) NOT NULL DEFAULT 0,
    label TEXT NOT NULL DEFAULT '',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ready',
    explanation_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    features_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMP NULL
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_predictions_tenant_type
ON saas_intelligence_predictions (tenant_id, prediction_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_predictions_subject
ON saas_intelligence_predictions (tenant_id, subject_type, subject_id, created_at DESC);

CREATE TABLE IF NOT EXISTS saas_intelligence_recommendations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    recommendation_type TEXT NOT NULL,
    source_prediction_id UUID NULL REFERENCES saas_intelligence_predictions(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    confidence NUMERIC(8,4) NOT NULL DEFAULT 0,
    action_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_recommendations_tenant_status
ON saas_intelligence_recommendations (tenant_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS saas_intelligence_feature_grants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    feature_key TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    mode TEXT NOT NULL DEFAULT 'disabled',
    quota_monthly INTEGER NOT NULL DEFAULT 0,
    source TEXT NOT NULL DEFAULT 'admin',
    valid_until TIMESTAMP NULL,
    notes TEXT NOT NULL DEFAULT '',
    updated_by_user_id UUID NULL REFERENCES saas_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, feature_key)
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_grants_tenant_feature
ON saas_intelligence_feature_grants (tenant_id, feature_key);

CREATE TABLE IF NOT EXISTS saas_intelligence_model_registry (
    model_key TEXT PRIMARY KEY,
    model_type TEXT NOT NULL DEFAULT 'rules',
    task_type TEXT NOT NULL DEFAULT '',
    framework TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT 'v1',
    status TEXT NOT NULL DEFAULT 'active',
    stage TEXT NOT NULL DEFAULT 'production',
    artifact_uri TEXT NOT NULL DEFAULT '',
    shadow_mode BOOLEAN NOT NULL DEFAULT FALSE,
    metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS saas_intelligence_usage (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES saas_tenants(id) ON DELETE CASCADE,
    feature_key TEXT NOT NULL,
    usage_metric TEXT NOT NULL DEFAULT 'prediction_requests',
    quantity INTEGER NOT NULL DEFAULT 1,
    period_yyyymm TEXT NOT NULL,
    source_event_id UUID NULL REFERENCES saas_intelligence_events(id) ON DELETE SET NULL,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_usage_tenant_period
ON saas_intelligence_usage (tenant_id, period_yyyymm, feature_key);

UPDATE saas_plan_limits
SET feature_flags_json =
    '{
      "intelligence_demo": true,
      "ai_premium": false,
      "ml_predictions": false,
      "lead_scoring_ml": false,
      "churn_prediction": false,
      "smart_remarketing": false,
      "ai_operational_intelligence": false,
      "predictive_recommendations": false,
      "advanced_analytics": false,
      "ai_advisors_premium": false
    }'::jsonb || COALESCE(feature_flags_json, '{}'::jsonb),
    updated_at = NOW();

INSERT INTO saas_intelligence_model_registry (
    model_key, model_type, task_type, framework, version, status, stage,
    shadow_mode, metrics_json, metadata_json, updated_at
)
VALUES
    ('baseline_lead_scoring_v1', 'rules', 'lead_scoring', 'postgresql_sql', 'v1', 'active', 'production', FALSE, '{}'::jsonb, '{"phase":"11","purpose":"safe_baseline"}'::jsonb, NOW()),
    ('baseline_churn_prediction_v1', 'rules', 'churn_prediction', 'postgresql_sql', 'v1', 'active', 'production', FALSE, '{}'::jsonb, '{"phase":"11","purpose":"safe_baseline"}'::jsonb, NOW()),
    ('baseline_smart_remarketing_v1', 'rules', 'smart_remarketing', 'postgresql_sql', 'v1', 'active', 'production', FALSE, '{}'::jsonb, '{"phase":"11","purpose":"safe_baseline"}'::jsonb, NOW()),
    ('baseline_operational_anomaly_v1', 'rules', 'operational_anomaly', 'postgresql_sql', 'v1', 'active', 'production', FALSE, '{}'::jsonb, '{"phase":"11","purpose":"safe_baseline"}'::jsonb, NOW())
ON CONFLICT (model_key)
DO UPDATE SET
    model_type = EXCLUDED.model_type,
    task_type = EXCLUDED.task_type,
    framework = EXCLUDED.framework,
    version = EXCLUDED.version,
    status = EXCLUDED.status,
    stage = EXCLUDED.stage,
    shadow_mode = EXCLUDED.shadow_mode,
    metadata_json = saas_intelligence_model_registry.metadata_json || EXCLUDED.metadata_json,
    updated_at = NOW();
