from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ImageJob(BaseModel):
    job_id: str
    sku_id: str
    image_index: int
    image_type: str
    description: str
    workflow_key: str
    view_type: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class Artifact(BaseModel):
    artifact_id: str
    job_id: str | None = None
    type: str
    name: str
    path: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    score: float = 0
    status: str = "pending"
    issues: list[str] = Field(default_factory=list)
    suggestion: str = ""


class WorkflowResult(BaseModel):
    job: ImageJob
    artifacts: list[Artifact] = Field(default_factory=list)
    quality: QualityReport = Field(default_factory=QualityReport)
    traces: list[dict[str, Any]] = Field(default_factory=list)
