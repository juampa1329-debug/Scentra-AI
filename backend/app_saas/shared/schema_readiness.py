from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


LEGACY_MIGRATION_VERSIONS = {"002", "003", "004"}

REQUIRED_TABLES = (
    "saas_tenants",
    "saas_users",
    "saas_memberships",
    "saas_integrations",
    "saas_webhook_endpoints",
    "saas_webhook_events",
    "saas_conversations",
    "saas_messages",
    "saas_outbound_messages",
    "saas_security_events",
    "saas_password_reset_tokens",
    "saas_mfa_challenges",
    "saas_billing_customers",
    "saas_billing_subscriptions",
    "saas_billing_checkout_sessions",
    "saas_billing_invoices",
    "saas_billing_payments",
    "saas_billing_credits",
    "saas_billing_provider_events",
    "saas_audit_events",
    "saas_labels",
    "saas_conversation_labels",
    "saas_crm_tasks",
    "saas_message_status_events",
    "saas_crm_custom_fields",
    "saas_crm_pipelines",
    "saas_crm_pipeline_stages",
    "saas_crm_timeline_events",
    "saas_crm_merge_events",
    "saas_message_templates",
    "saas_segments",
    "saas_campaigns",
    "saas_crm_triggers",
    "saas_remarketing_flows",
    "saas_campaign_quiet_hours",
    "saas_vertical_pack_applications",
    "saas_ai_agents",
    "saas_ai_runs",
    "saas_advisor_threads",
    "saas_advisor_messages",
    "saas_intelligence_events",
    "saas_intelligence_feature_values",
    "saas_intelligence_predictions",
    "saas_intelligence_recommendations",
    "saas_intelligence_model_registry",
    "saas_intelligence_model_rollout_events",
    "saas_knowledge_sources",
    "saas_ai_agent_collective_memory",
    "saas_voice_intelligence_analyses",
    "saas_vision_intelligence_analyses",
    "saas_web_search_intelligence_runs",
    "saas_web_search_intelligence_results",
    "saas_multimodal_memory_events",
)

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "saas_tenants": (
        "id",
        "name",
        "slug",
        "status",
        "plan_code",
        "industry_code",
        "vertical_pack_version",
        "vertical_pack_json",
        "vertical_pack_applied_at",
    ),
    "saas_users": (
        "id",
        "email",
        "password_hash",
        "status",
        "failed_login_count",
        "locked_until",
        "password_changed_at",
        "two_factor_enabled",
        "two_factor_method",
        "two_factor_secret_ref",
        "two_factor_recovery_hashes_json",
    ),
    "saas_integrations": (
        "id",
        "tenant_id",
        "provider",
        "channel",
        "status",
        "secret_ref",
        "config_json",
        "last_sync_at",
        "updated_at",
    ),
    "saas_conversations": (
        "id",
        "tenant_id",
        "channel",
        "external_contact_id",
        "phone",
        "display_name",
        "first_name",
        "last_name",
        "city",
        "customer_type",
        "interests",
        "takeover",
        "last_message_text",
        "last_message_at",
        "unread_count",
        "tags",
        "notes",
        "payment_status",
        "payment_reference",
        "crm_stage",
        "intent",
        "assigned_user_id",
        "assigned_ai_agent_id",
        "ai_owner_mode",
        "ai_owner_locked_at",
        "priority",
        "sla_due_at",
        "first_response_due_at",
        "lead_score",
        "lead_temperature",
        "last_customer_message_at",
        "last_agent_message_at",
        "profile_json",
        "last_profiled_at",
        "updated_at",
    ),
    "saas_messages": (
        "id",
        "tenant_id",
        "conversation_id",
        "channel",
        "external_message_id",
        "direction",
        "msg_type",
        "text",
        "media_id",
        "mime_type",
        "payload_json",
        "created_at",
    ),
    "saas_billing_subscriptions": (
        "id",
        "tenant_id",
        "status",
        "current_period_end",
        "cancel_at_period_end",
        "past_due_at",
        "lifecycle_last_checked_at",
        "payment_failed_notice_sent_at",
        "trial_expired_notice_sent_at",
        "suspension_notice_sent_at",
    ),
    "saas_billing_invoices": (
        "id",
        "tenant_id",
        "status",
        "amount_cents",
        "currency",
        "payment_failed_notice_sent_at",
        "pdf_generated_at",
    ),
    "saas_billing_checkout_sessions": (
        "id",
        "tenant_id",
        "provider",
        "status",
        "last_provider_event_at",
    ),
    "saas_audit_events": (
        "id",
        "tenant_id",
        "actor_user_id",
        "action",
        "resource_type",
        "resource_id",
        "details_json",
        "created_at",
    ),
    "saas_crm_custom_fields": (
        "id",
        "tenant_id",
        "field_key",
        "label",
        "field_type",
        "options_json",
        "is_required",
        "is_active",
        "display_order",
        "created_by_user_id",
    ),
    "saas_crm_pipelines": ("id", "tenant_id", "name", "industry_code", "is_default", "created_by_user_id"),
    "saas_crm_pipeline_stages": (
        "id",
        "tenant_id",
        "pipeline_id",
        "stage_key",
        "label",
        "probability",
        "display_order",
        "is_won",
        "is_lost",
        "is_active",
    ),
    "saas_crm_tasks": ("id", "tenant_id", "conversation_id", "title", "status", "due_at"),
    "saas_labels": ("id", "tenant_id", "name", "color", "description", "category", "is_active"),
    "saas_conversation_labels": ("tenant_id", "conversation_id", "label_id"),
    "saas_message_templates": (
        "id",
        "tenant_id",
        "name",
        "channel",
        "category",
        "body",
        "status",
        "variables_json",
        "blocks_json",
        "params_json",
        "render_mode",
        "template_scope",
        "source",
        "created_by_user_id",
    ),
    "saas_segments": ("id", "tenant_id", "name", "description", "filters_json", "created_by_user_id"),
    "saas_campaigns": ("id", "tenant_id", "name", "status", "preflight_json"),
    "saas_crm_triggers": (
        "id",
        "tenant_id",
        "name",
        "channel",
        "event_type",
        "trigger_type",
        "flow_event",
        "conditions_json",
        "actions_json",
        "priority",
        "cooldown_minutes",
        "is_active",
        "assistant_enabled",
        "assistant_message_type",
        "block_ai",
        "stop_on_match",
        "only_when_no_takeover",
        "quiet_hours_json",
        "ab_test_json",
        "preflight_json",
        "created_by_user_id",
    ),
    "saas_remarketing_flows": (
        "id",
        "tenant_id",
        "name",
        "description",
        "channel",
        "status",
        "entry_rules_json",
        "exit_rules_json",
        "steps_json",
        "quiet_hours_json",
        "ab_test_json",
        "preflight_json",
        "created_by_user_id",
    ),
    "saas_campaign_quiet_hours": (
        "id",
        "tenant_id",
        "channel",
        "entity_type",
        "enabled",
        "timezone",
        "start_time",
        "end_time",
        "days_json",
        "created_by_user_id",
    ),
    "saas_vertical_pack_applications": ("id", "tenant_id", "industry_code", "pack_version", "created_at"),
    "saas_ai_agents": ("id", "tenant_id", "name", "agent_type", "status"),
    "saas_intelligence_events": (
        "id",
        "tenant_id",
        "event_type",
        "source",
        "entity_type",
        "entity_id",
        "conversation_id",
        "payload_json",
        "replay_key",
        "created_at",
    ),
    "saas_intelligence_feature_values": (
        "id",
        "tenant_id",
        "subject_type",
        "subject_id",
        "feature_key",
        "window_key",
        "value_numeric",
        "value_text",
        "value_json",
        "feature_set_key",
        "feature_version",
        "quality_json",
        "computed_at",
        "updated_at",
    ),
    "saas_intelligence_predictions": (
        "id",
        "tenant_id",
        "prediction_type",
        "subject_type",
        "subject_id",
        "score",
        "label",
        "confidence",
        "status",
        "output_json",
        "created_at",
    ),
    "saas_intelligence_recommendations": (
        "id",
        "tenant_id",
        "recommendation_type",
        "status",
        "created_at",
    ),
    "saas_intelligence_model_registry": (
        "model_key",
        "model_type",
        "task_type",
        "framework",
        "version",
        "status",
        "stage",
        "rollout_mode",
        "traffic_percent",
        "min_labeled_count",
        "min_accuracy",
        "max_drift_score",
        "promotion_status",
        "approved_by_user_id",
        "approved_at",
        "updated_at",
    ),
    "saas_intelligence_model_rollout_events": (
        "id",
        "model_key",
        "tenant_id",
        "action",
        "previous_state_json",
        "next_state_json",
        "reason",
        "created_at",
    ),
    "saas_knowledge_sources": (
        "id",
        "tenant_id",
        "source_type",
        "title",
        "url",
        "filename",
        "content",
        "status",
        "metadata_json",
        "content_hash",
        "chunk_count",
        "updated_at",
    ),
    "saas_ai_agent_collective_memory": (
        "id",
        "tenant_id",
        "source_agent_id",
        "memory_type",
        "title",
        "content",
        "visibility",
        "tags_json",
        "updated_at",
    ),
    "saas_voice_intelligence_analyses": (
        "id",
        "tenant_id",
        "conversation_id",
        "message_id",
        "media_id",
        "provider_code",
        "model",
        "transcript",
        "summary",
        "sentiment",
        "intent",
        "confidence",
        "analysis_json",
        "metadata_json",
        "updated_at",
    ),
    "saas_vision_intelligence_analyses": (
        "id",
        "tenant_id",
        "conversation_id",
        "message_id",
        "media_id",
        "media_kind",
        "visual_description",
        "extracted_text",
        "summary",
        "document_type",
        "sentiment",
        "intent",
        "topics_json",
        "product_hints_json",
        "analysis_json",
        "metadata_json",
        "updated_at",
    ),
    "saas_web_search_intelligence_runs": (
        "id",
        "tenant_id",
        "conversation_id",
        "message_id",
        "query",
        "search_type",
        "provider_code",
        "status",
        "access_mode",
        "result_count",
        "approved_count",
        "blocked_count",
        "metadata_json",
        "created_at",
    ),
    "saas_web_search_intelligence_results": (
        "id",
        "tenant_id",
        "run_id",
        "result_type",
        "title",
        "url",
        "display_url",
        "snippet",
        "source_name",
        "image_url",
        "thumbnail_url",
        "safety_status",
        "approval_status",
        "metadata_json",
        "updated_at",
    ),
    "saas_multimodal_memory_events": (
        "id",
        "tenant_id",
        "conversation_id",
        "message_id",
        "agent_id",
        "source_kind",
        "source_id",
        "event_type",
        "status",
        "privacy_level",
        "approval_status",
        "eligible_for_training",
        "eligible_for_rag",
        "eligible_for_agent_memory",
        "memory_text",
        "rag_text",
        "training_features_json",
        "training_labels_json",
        "source_payload_json",
        "safety_json",
        "intelligence_event_id",
        "knowledge_source_id",
        "collective_memory_id",
        "replay_key",
        "updated_at",
    ),
}


def _version_from_file(path: Path) -> str:
    return path.name.split("_", 1)[0]


def _migration_profile() -> str:
    return os.getenv("SAAS_MIGRATION_PROFILE", "core").strip().lower() or "core"


def _should_expect_migration(version: str, profile: str) -> bool:
    if profile in {"all", "legacy"}:
        return True
    return version not in LEGACY_MIGRATION_VERSIONS


def _default_migrations_dir() -> Path | None:
    env_dir = os.getenv("SAAS_MIGRATIONS_DIR", "").strip()
    candidates: list[Path] = []
    if env_dir:
        candidates.append(Path(env_dir))

    here = Path(__file__).resolve()
    candidates.extend(
        [
            Path("/app/migrations"),
            here.parents[2] / "migrations",
            here.parents[3] / "migrations",
        ]
    )
    for candidate in candidates:
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


def expected_migration_versions(migrations_dir: Path | None = None, profile: str | None = None) -> list[str]:
    directory = migrations_dir or _default_migrations_dir()
    if directory is None:
        return []

    active_profile = (profile or _migration_profile()).strip().lower() or "core"
    versions: list[str] = []
    for path in sorted(directory.glob("*.sql")):
        if not path.is_file():
            continue
        version = _version_from_file(path)
        if _should_expect_migration(version, active_profile):
            versions.append(version)
    return versions


def _relation_exists(conn: Connection, table_name: str) -> bool:
    result = conn.execute(text("SELECT to_regclass(:table_name)"), {"table_name": f"public.{table_name}"}).scalar()
    return result is not None


def _applied_migration_versions(conn: Connection) -> list[str]:
    if not _relation_exists(conn, "saas_schema_migrations"):
        return []
    rows = conn.execute(text("SELECT version FROM saas_schema_migrations ORDER BY version")).mappings().all()
    return [str(row["version"]) for row in rows]


def _existing_columns(conn: Connection, table_name: str) -> set[str]:
    rows = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = :table_name
            """
        ),
        {"table_name": table_name},
    ).mappings().all()
    return {str(row["column_name"]) for row in rows}


def _cap(items: list[Any], limit: int = 80) -> list[Any]:
    if len(items) <= limit:
        return items
    return items[:limit] + [{"truncated": len(items) - limit}]


def schema_readiness_report(
    conn: Connection,
    migrations_dir: Path | None = None,
    profile: str | None = None,
) -> dict[str, Any]:
    active_profile = (profile or _migration_profile()).strip().lower() or "core"
    expected = expected_migration_versions(migrations_dir, active_profile)
    applied = _applied_migration_versions(conn)
    applied_set = set(applied)
    pending = [version for version in expected if version not in applied_set]

    missing_tables = [table_name for table_name in REQUIRED_TABLES if not _relation_exists(conn, table_name)]

    missing_columns: list[dict[str, str]] = []
    for table_name, expected_columns in REQUIRED_COLUMNS.items():
        if table_name in missing_tables:
            continue
        existing = _existing_columns(conn, table_name)
        for column_name in expected_columns:
            if column_name not in existing:
                missing_columns.append({"table": table_name, "column": column_name})

    warnings: list[str] = []
    if not expected:
        warnings.append("migration_files_unavailable")
    if not applied:
        warnings.append("migration_table_empty_or_missing")

    ok = bool(expected) and not pending and not missing_tables and not missing_columns
    return {
        "ok": ok,
        "profile": active_profile,
        "latest_expected_migration": expected[-1] if expected else None,
        "latest_applied_migration": applied[-1] if applied else None,
        "expected_migration_count": len(expected),
        "applied_migration_count": len(applied),
        "pending_migrations": _cap(pending),
        "missing_tables": _cap(missing_tables),
        "missing_columns": _cap(missing_columns),
        "warnings": warnings,
    }
