-- 074_saas_intelligence_runtime_ddl_deadlock_repair.sql
-- Intelligence schema drift repair for runtime read endpoints.
--
-- These columns are part of earlier Phase 11 migrations, but production can
-- have migration versions marked applied while the physical schema is partial.
-- Repair them during startup migrations so Intelligence read endpoints do not
-- need to run ALTER TABLE during normal browser traffic.

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

ALTER TABLE saas_intelligence_feature_values
  ADD COLUMN IF NOT EXISTS feature_set_key TEXT NOT NULL DEFAULT 'default',
  ADD COLUMN IF NOT EXISTS feature_version TEXT NOT NULL DEFAULT 'v1',
  ADD COLUMN IF NOT EXISTS quality_json JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_features_tenant_subject
  ON saas_intelligence_feature_values (tenant_id, subject_type, subject_id, computed_at DESC);

CREATE INDEX IF NOT EXISTS idx_saas_intelligence_features_set
  ON saas_intelligence_feature_values (tenant_id, feature_set_key, feature_version, computed_at DESC);

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
  ON saas_intelligence_model_rollout_events (tenant_id, created_at DESC) WHERE tenant_id IS NOT NULL;
