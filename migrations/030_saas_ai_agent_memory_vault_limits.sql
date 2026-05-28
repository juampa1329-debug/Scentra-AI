-- 030_saas_ai_agent_memory_vault_limits.sql
-- Agrega limite de boveda de memorias para agentes eliminados por plan.

ALTER TABLE saas_ai_agent_plan_limits
ADD COLUMN IF NOT EXISTS max_memory_archives INTEGER NOT NULL DEFAULT 1;

UPDATE saas_ai_agent_plan_limits
SET max_memory_archives = GREATEST(
      saas_ai_agent_plan_limits.max_memory_archives,
      limits.max_memory_archives
    ),
    updated_at = NOW()
FROM (
  VALUES
    ('demo', 2),
    ('starter', 1),
    ('basic', 1),
    ('growth', 5),
    ('pro', 15),
    ('enterprise', 200)
) AS limits(plan_code, max_memory_archives)
WHERE saas_ai_agent_plan_limits.plan_code = limits.plan_code;
