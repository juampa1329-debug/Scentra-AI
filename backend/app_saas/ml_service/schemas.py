from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TrainRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    tenant_id: str = Field(default="", max_length=80)
    task_type: str = Field(default="lead_scoring", max_length=120)
    model_key: str = Field(default="", max_length=160)
    framework: str = Field(default="lightgbm", max_length=80)
    version: str = Field(default="", max_length=80)
    sample_size: int = Field(default=1000, ge=50, le=100000)
    seed: int = Field(default=42, ge=1, le=1000000000)
    register_artifact: bool = True
    notes: str = Field(default="", max_length=1000)


class DatasetBuildRequest(BaseModel):
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


class AutoLabelTrainRequest(BaseModel):
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
    register_artifact: bool = True
    notes: str = Field(default="", max_length=1000)


class PredictRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    tenant_id: str = Field(default="", max_length=80)
    prediction_id: str = Field(default="", max_length=80)
    task_type: str = Field(default="lead_scoring", max_length=120)
    model_key: str = Field(min_length=2, max_length=160)
    version: str = Field(default="", max_length=80)
    subject_type: str = Field(default="tenant", max_length=80)
    subject_id: str = Field(default="", max_length=160)
    mode: str = Field(default="shadow", max_length=40)
    features: dict[str, Any] = Field(default_factory=dict)


class DriftRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    tenant_id: str = Field(default="", max_length=80)
    model_key: str = Field(min_length=2, max_length=160)
    version: str = Field(default="", max_length=80)
    task_type: str = Field(default="lead_scoring", max_length=120)
    window_key: str = Field(default="30d", max_length=80)
    current_features: dict[str, Any] = Field(default_factory=dict)
