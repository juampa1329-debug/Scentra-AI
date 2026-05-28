from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TrustPolicyIn(BaseModel):
    policy_key: str = Field(..., min_length=3, max_length=180)
    name: str = Field(..., min_length=2, max_length=180)
    description: str | None = Field(default="", max_length=1500)
    status: str | None = Field(default="enabled", max_length=40)
    risk_tier: str | None = Field(default="standard", max_length=40)
    enforcement_mode: str | None = Field(default="monitor", max_length=60)
    applies_to_json: list[str] = Field(default_factory=list)
    rules_json: dict[str, Any] = Field(default_factory=dict)


class TrustPolicyPatchIn(BaseModel):
    name: str | None = Field(default=None, max_length=180)
    description: str | None = Field(default=None, max_length=1500)
    status: str | None = Field(default=None, max_length=40)
    risk_tier: str | None = Field(default=None, max_length=40)
    enforcement_mode: str | None = Field(default=None, max_length=60)
    applies_to_json: list[str] | None = None
    rules_json: dict[str, Any] | None = None


class TrustPolicyAttestationIn(BaseModel):
    attestation_type: str | None = Field(default="human_review", max_length=80)
    status: str | None = Field(default="attested", max_length=40)
    evidence_json: dict[str, Any] = Field(default_factory=dict)
    notes: str | None = Field(default="", max_length=1500)


class RiskAssessmentRunIn(BaseModel):
    scope: str | None = Field(default="all", max_length=80)
    persist: bool = True
    max_items: int = Field(default=120, ge=1, le=300)


class RiskAssessmentPatchIn(BaseModel):
    status: str | None = Field(default=None, max_length=40)
    risk_level: str | None = Field(default=None, max_length=40)
    mitigations_json: list[dict[str, Any]] | None = None
    evidence_json: dict[str, Any] | None = None


class ModelCardIn(BaseModel):
    model_key: str = Field(..., min_length=2, max_length=180)
    provider_key: str | None = Field(default="", max_length=80)
    task_type: str | None = Field(default="", max_length=100)
    version: str | None = Field(default="v1", max_length=80)
    status: str | None = Field(default="draft", max_length=40)
    intended_use: str | None = Field(default="", max_length=2000)
    limitations: str | None = Field(default="", max_length=2000)
    training_data_json: dict[str, Any] = Field(default_factory=dict)
    evaluation_json: dict[str, Any] = Field(default_factory=dict)
    rollout_json: dict[str, Any] = Field(default_factory=dict)
    compliance_json: dict[str, Any] = Field(default_factory=dict)


class ModelCardPatchIn(BaseModel):
    provider_key: str | None = Field(default=None, max_length=80)
    task_type: str | None = Field(default=None, max_length=100)
    version: str | None = Field(default=None, max_length=80)
    status: str | None = Field(default=None, max_length=40)
    intended_use: str | None = Field(default=None, max_length=2000)
    limitations: str | None = Field(default=None, max_length=2000)
    training_data_json: dict[str, Any] | None = None
    evaluation_json: dict[str, Any] | None = None
    rollout_json: dict[str, Any] | None = None
    compliance_json: dict[str, Any] | None = None


class GovernanceIncidentIn(BaseModel):
    incident_type: str | None = Field(default="ai_governance", max_length=80)
    severity: str | None = Field(default="medium", max_length=40)
    entity_type: str | None = Field(default="", max_length=80)
    entity_id: str | None = Field(default="", max_length=180)
    title: str = Field(..., min_length=2, max_length=220)
    description: str | None = Field(default="", max_length=3000)
    remediation_json: dict[str, Any] = Field(default_factory=dict)


class GovernanceIncidentPatchIn(BaseModel):
    severity: str | None = Field(default=None, max_length=40)
    status: str | None = Field(default=None, max_length=40)
    description: str | None = Field(default=None, max_length=3000)
    remediation_json: dict[str, Any] | None = None


class GovernanceReportGenerateIn(BaseModel):
    report_type: str | None = Field(default="trust_summary", max_length=80)
    period_key: str | None = Field(default="", max_length=80)
