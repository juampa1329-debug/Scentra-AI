-- Phase 24.5 Agent Multimodal Tools.
-- Adds premium feature flags for agent-scoped multimodal tool execution.
-- Tool execution reuses existing Agent OS tool-run traces and Phase 24 media/search tables.

UPDATE saas_plan_limits
SET feature_flags_json =
    '{
      "agent_multimodal_tools": false,
      "agent_voice_tools": false,
      "agent_vision_tools": false,
      "agent_external_search_tools": false
    }'::jsonb || COALESCE(feature_flags_json, '{}'::jsonb),
    updated_at = NOW();

CREATE INDEX IF NOT EXISTS idx_saas_ai_agent_tool_runs_multimodal
    ON saas_ai_agent_tool_runs (tenant_id, agent_id, tool_code, status, updated_at DESC)
    WHERE tool_code IN ('media.voice_analyze', 'media.vision_analyze', 'media.web_image_search');
