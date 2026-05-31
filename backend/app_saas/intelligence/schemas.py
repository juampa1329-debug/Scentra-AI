from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IntelligenceEventIn(BaseModel):
    event_type: str = Field(min_length=2, max_length=160)
    source: str = Field(default="", max_length=120)
    channel: str = Field(default="", max_length=80)
    entity_type: str = Field(default="", max_length=120)
    entity_id: str = Field(default="", max_length=160)
    conversation_id: str = Field(default="", max_length=80)
    customer_key: str = Field(default="", max_length=180)
    occurred_at: str = Field(default="", max_length=80)
    payload_json: dict[str, Any] = Field(default_factory=dict)
    correlation_id: str = Field(default="", max_length=160)
    replay_key: str = Field(default="", max_length=240)


class FeatureRecomputeIn(BaseModel):
    subject_type: str = Field(default="tenant", max_length=80)
    subject_id: str = Field(default="", max_length=160)
    window_key: str = Field(default="latest", max_length=80)


class PredictionRequestIn(BaseModel):
    prediction_type: str = Field(default="lead_scoring", max_length=120)
    subject_type: str = Field(default="tenant", max_length=80)
    subject_id: str = Field(default="", max_length=160)
    window_key: str = Field(default="latest", max_length=80)
    persist_recommendations: bool = True


class PredictionFeedbackIn(BaseModel):
    feedback_type: str = Field(default="outcome", max_length=80)
    actual_label: str = Field(default="", max_length=120)
    actual_score: float | None = Field(default=None, ge=0, le=100)
    is_correct: bool | None = None
    outcome_json: dict[str, Any] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=1000)


class AutonomyPolicyPatchIn(BaseModel):
    autonomy_level: int = Field(default=0, ge=0, le=4)
    auto_remediation_enabled: bool = False
    low_risk_auto_execute: bool = False
    sensitivity: str = Field(default="medium", max_length=20)
    max_daily_actions: int = Field(default=0, ge=0, le=1000)
    approval_required_from_level: int = Field(default=2, ge=0, le=4)
    settings_json: dict[str, Any] = Field(default_factory=dict)


class OperationalAnalysisIn(BaseModel):
    dry_run: bool = False
    limit: int = Field(default=50, ge=1, le=200)


class EnterpriseNetworkRefreshIn(BaseModel):
    dry_run: bool = False
    limit: int = Field(default=50, ge=1, le=200)


class FederatedPolicyPatchIn(BaseModel):
    opt_in_enabled: bool = False
    auto_participation_enabled: bool = False
    privacy_mode: str = Field(default="aggregate_only", max_length=60)
    min_local_samples: int = Field(default=25, ge=1, le=1000000)
    min_cohort_tenants: int = Field(default=3, ge=3, le=10000)
    allowed_task_types_json: list[str] = Field(default_factory=lambda: ["lead_scoring", "churn_prediction", "smart_remarketing", "operational_anomaly"])
    differential_privacy_enabled: bool = True
    noise_multiplier: float = Field(default=0, ge=0, le=100)
    clipping_norm: float = Field(default=1, ge=0, le=1000000)
    share_model_metrics: bool = True
    share_feature_importance: bool = True
    settings_json: dict[str, Any] = Field(default_factory=dict)


class FederatedRoundPrepareIn(BaseModel):
    task_type: str = Field(default="lead_scoring", max_length=120)
    model_key: str = Field(default="", max_length=160)
    window_key: str = Field(default="90d", max_length=40)
    dry_run: bool = True
    min_participants: int = Field(default=3, ge=3, le=10000)
    min_total_samples: int = Field(default=100, ge=1, le=100000000)
    aggregation_strategy: str = Field(default="weighted_average", max_length=80)


class FederatedUpdateSubmitIn(BaseModel):
    dry_run: bool = False


class FederatedAggregateIn(BaseModel):
    dry_run: bool = False
    notes: str = Field(default="", max_length=1000)


class RevenuePolicyPatchIn(BaseModel):
    autonomy_level: int = Field(default=0, ge=0, le=4)
    currency: str = Field(default="USD", max_length=12)
    revenue_goal_cents: int = Field(default=0, ge=0, le=100000000000)
    approval_required_min_value_cents: int = Field(default=0, ge=0, le=100000000000)
    max_monthly_revenue_actions: int = Field(default=0, ge=0, le=1000000)
    auto_execute_low_risk: bool = False
    allowed_action_types_json: list[str] = Field(default_factory=list)
    settings_json: dict[str, Any] = Field(default_factory=dict)


class RevenueAnalysisIn(BaseModel):
    dry_run: bool = False
    limit: int = Field(default=50, ge=1, le=200)


class RevenueOpportunityActionIn(BaseModel):
    dry_run: bool = False
    notes: str = Field(default="", max_length=1000)


class MemoryNetworkPolicyPatchIn(BaseModel):
    privacy_mode: str = Field(default="tenant_private", max_length=40)
    retention_days: int = Field(default=365, ge=1, le=3650)
    auto_capture_enabled: bool = False
    require_review_for_customer_content: bool = True
    allow_cross_agent_retrieval: bool = True
    allowed_scopes_json: list[str] = Field(default_factory=lambda: ["tenant", "agent", "customer", "knowledge", "workflow"])
    settings_json: dict[str, Any] = Field(default_factory=dict)


class MemoryNetworkSyncIn(BaseModel):
    dry_run: bool = False
    limit: int = Field(default=80, ge=1, le=300)
    source_types: list[str] = Field(default_factory=list)


class MemoryNetworkNodeReviewIn(BaseModel):
    status: str = Field(default="published", max_length=40)
    notes: str = Field(default="", max_length=1000)


class MemoryNetworkImportIn(BaseModel):
    dry_run: bool = True
    nodes_json: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class RealtimeSessionIn(BaseModel):
    session_key: str = Field(default="", max_length=120)
    channel: str = Field(default="tenant", max_length=80)
    last_event_id: str = Field(default="", max_length=80)
    filters_json: dict[str, Any] = Field(default_factory=dict)
    client_meta_json: dict[str, Any] = Field(default_factory=dict)


class RealtimeCursorPatchIn(BaseModel):
    cursor_key: str = Field(default="default", max_length=80)
    last_event_id: str = Field(default="", max_length=80)
    filters_json: dict[str, Any] = Field(default_factory=dict)


class MultimodalObservabilityRefreshIn(BaseModel):
    window_key: str = Field(default="30d", max_length=20)
    dry_run: bool = False
    limit: int = Field(default=20, ge=1, le=100)


class MultimodalRolloutPolicyPatchIn(BaseModel):
    feature_key: str = Field(default="multimodal_safe_rollout", max_length=120)
    modality: str = Field(default="all", max_length=40)
    provider_code: str = Field(default="", max_length=120)
    enabled: bool = True
    mode: str = Field(default="demo", max_length=40)
    demo_enabled: bool = True
    canary_percent: int = Field(default=0, ge=0, le=100)
    max_error_rate: float = Field(default=0, ge=0, le=1)
    max_latency_p95_ms: int = Field(default=0, ge=0, le=600000)
    min_quality_score: float = Field(default=0, ge=0, le=100)
    monthly_cost_limit_cents: int = Field(default=0, ge=0, le=1000000000)
    allowed_roles_json: list[str] = Field(default_factory=lambda: ["owner", "admin", "supervisor"])
    settings_json: dict[str, Any] = Field(default_factory=dict)


class AutonomousActionExecuteIn(BaseModel):
    dry_run: bool = False


class ModelMetricsRecomputeIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    tenant_id: str = Field(default="", max_length=80)
    model_key: str = Field(default="", max_length=160)
    prediction_type: str = Field(default="", max_length=120)
    window_key: str = Field(default="90d", max_length=80)


class ModelRegistryPatchIn(BaseModel):
    status: str = Field(default="active", max_length=40)
    stage: str = Field(default="production", max_length=40)
    shadow_mode: bool = False
    rollout_mode: str = Field(default="production", max_length=40)
    traffic_percent: int = Field(default=100, ge=0, le=100)
    min_labeled_count: int = Field(default=10, ge=0, le=1000000)
    min_accuracy: float = Field(default=70, ge=0, le=100)
    max_drift_score: float = Field(default=25, ge=0, le=100)
    promotion_status: str = Field(default="approved", max_length=40)
    reason: str = Field(default="", max_length=1000)


class ModelRegistryCreateIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    model_key: str = Field(min_length=2, max_length=160)
    model_type: str = Field(default="external", max_length=80)
    task_type: str = Field(default="lead_scoring", max_length=120)
    framework: str = Field(default="pending", max_length=120)
    version: str = Field(default="v1", max_length=80)
    status: str = Field(default="active", max_length=40)
    stage: str = Field(default="shadow", max_length=40)
    artifact_uri: str = Field(default="", max_length=1000)
    shadow_mode: bool = True
    rollout_mode: str = Field(default="shadow", max_length=40)
    traffic_percent: int = Field(default=0, ge=0, le=100)
    min_labeled_count: int = Field(default=10, ge=0, le=1000000)
    min_accuracy: float = Field(default=70, ge=0, le=100)
    max_drift_score: float = Field(default=25, ge=0, le=100)
    promotion_status: str = Field(default="pending_review", max_length=40)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(default="", max_length=1000)


class SyntheticTrainingRequestIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    tenant_id: str = Field(default="", max_length=80)
    task_type: str = Field(default="lead_scoring", max_length=120)
    model_key: str = Field(default="", max_length=160)
    framework: str = Field(default="lightgbm", max_length=80)
    version: str = Field(default="", max_length=80)
    sample_size: int = Field(default=1000, ge=50, le=100000)
    seed: int = Field(default=42, ge=1, le=1000000000)
    register_model_registry: bool = True
    notes: str = Field(default="", max_length=1000)


class AutoLabelGenerationRequestIn(BaseModel):
    prediction_type: str = Field(default="", max_length=120)
    tenant_id: str = Field(default="", max_length=80)
    window_key: str = Field(default="90d", max_length=80)
    limit: int = Field(default=1000, ge=1, le=25000)


class FeaturePipelineRequestIn(BaseModel):
    prediction_type: str = Field(default="", max_length=120)
    tenant_id: str = Field(default="", max_length=80)
    window_key: str = Field(default="90d", max_length=80)
    limit: int = Field(default=1000, ge=1, le=25000)


class DatasetBuildRequestIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    tenant_id: str = Field(default="", max_length=80)
    task_type: str = Field(default="lead_scoring", max_length=120)
    dataset_key: str = Field(default="", max_length=180)
    version: str = Field(default="", max_length=80)
    window_key: str = Field(default="90d", max_length=80)
    min_samples: int = Field(default=50, ge=5, le=1000000)
    include_global: bool = False
    include_internal_demo: bool = False
    notes: str = Field(default="", max_length=1000)


class AutoLabelTrainingRequestIn(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    tenant_id: str = Field(default="", max_length=80)
    task_type: str = Field(default="lead_scoring", max_length=120)
    model_key: str = Field(default="", max_length=160)
    framework: str = Field(default="lightgbm", max_length=80)
    version: str = Field(default="", max_length=80)
    dataset_key: str = Field(default="", max_length=180)
    window_key: str = Field(default="90d", max_length=80)
    min_samples: int = Field(default=50, ge=5, le=1000000)
    include_global: bool = False
    include_internal_demo: bool = False
    seed: int = Field(default=42, ge=1, le=1000000000)
    register_model_registry: bool = True
    notes: str = Field(default="", max_length=1000)


class AdminIntelligenceFeaturePatchIn(BaseModel):
    feature_key: str = Field(min_length=2, max_length=120)
    enabled: bool = True
    mode: str = Field(default="demo", max_length=40)
    quota_monthly: int = Field(default=0, ge=0, le=1000000000)
    valid_until: str = Field(default="", max_length=80)
    source: str = Field(default="admin", max_length=80)
    notes: str = Field(default="", max_length=1000)


class AdminIntelligencePlanFeaturePatchIn(BaseModel):
    feature_key: str = Field(min_length=2, max_length=120)
    enabled: bool = True
    mode: str = Field(default="demo", max_length=40)
    quota_monthly: int = Field(default=0, ge=0, le=1000000000)
    notes: str = Field(default="", max_length=1000)


class AdminAiProviderPolicyPatchIn(BaseModel):
    scope_type: str = Field(default="global", max_length=40)
    scope_id: str = Field(default="", max_length=120)
    provider_category: str = Field(default="ai", max_length=40)
    provider_code: str = Field(min_length=2, max_length=80)
    model_id: str = Field(default="", max_length=240)
    enabled: bool = True
    input_cost_cents_per_1k: float = Field(default=0, ge=0, le=1000000000)
    output_cost_cents_per_1k: float = Field(default=0, ge=0, le=1000000000)
    request_cost_cents: float = Field(default=0, ge=0, le=1000000000)
    monthly_request_quota: int = Field(default=0, ge=0, le=1000000000)
    monthly_cost_limit_cents: int = Field(default=0, ge=0, le=1000000000)
    currency: str = Field(default="USD", max_length=12)
    notes: str = Field(default="", max_length=1000)
    metadata_json: dict[str, Any] = Field(default_factory=dict)
