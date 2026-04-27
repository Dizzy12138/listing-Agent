from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class CreativeTask(BaseModel):
    task_id: str
    sku_id: str
    objective: str = "listing_creative_production"
    marketplace: str = "US"
    audience: list[str] = Field(default_factory=list)
    target_metrics: list[str] = Field(default_factory=list)
    strategy_brief: dict[str, Any] = Field(default_factory=dict)
    status: str = "draft"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class Layer(BaseModel):
    layer_id: str
    layer_type: Literal["image", "text", "shape", "dimension", "metadata"]
    name: str
    x: float = 0
    y: float = 0
    width: float | None = None
    height: float | None = None
    opacity: float = 1
    locked: bool = False
    source_path: str | None = None
    text: str | None = None
    style: dict[str, Any] = Field(default_factory=dict)
    data: dict[str, Any] = Field(default_factory=dict)


class LayeredAsset(BaseModel):
    asset_id: str
    version_id: str
    sku_id: str
    asset_type: str
    canvas: dict[str, int] = Field(default_factory=lambda: {"width": 1500, "height": 1500})
    layers: list[Layer] = Field(default_factory=list)
    rendered_path: str | None = None
    source_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class CreativeVersion(BaseModel):
    version_id: str
    task_id: str
    sku_id: str
    version_name: str
    status: str = "generated"
    generation_strategy: str = ""
    creative_factors: list[dict[str, Any]] = Field(default_factory=list)
    asset_ids: list[str] = Field(default_factory=list)
    trace_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class ReviewRecord(BaseModel):
    review_id: str
    version_id: str
    asset_id: str | None = None
    reviewer: str = ""
    decision: Literal["approved", "rejected", "needs_revision"] = "needs_revision"
    tags: list[str] = Field(default_factory=list)
    comment: str = ""
    created_at: str = Field(default_factory=now_iso)


class Experiment(BaseModel):
    experiment_id: str
    sku_id: str
    marketplace: str = "US"
    objective: str = "unknown"
    control_version_id: str | None = None
    treatment_version_ids: list[str] = Field(default_factory=list)
    status: str = "planned"
    external_variables: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)


class PerformanceMetric(BaseModel):
    metric_id: str
    experiment_id: str | None = None
    version_id: str
    metric_name: str
    value: float
    sample_size: int | None = None
    window: dict[str, str] = Field(default_factory=dict)
    confidence: float | None = None
    created_at: str = Field(default_factory=now_iso)


class KnowledgeRule(BaseModel):
    rule_id: str
    scope: str
    rule_type: str
    statement: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0
    status: str = "candidate"
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
