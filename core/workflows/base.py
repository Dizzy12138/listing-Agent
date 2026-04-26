from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import uuid

from PIL import Image

from core.agents.view_agent import ViewAgent
from core.schemas.job import Artifact, ImageJob, QualityReport, WorkflowResult
from core.schemas.sku import SKU
from core.tracing.trace import TraceRecorder


@dataclass
class WorkflowContext:
    run_id: str
    sku: SKU
    job: ImageJob
    output_dir: Path
    base_assets: dict[str, Image.Image]
    view_agent: ViewAgent
    trace: TraceRecorder
    scenes: list[dict[str, Any]] = field(default_factory=list)
    model: str = "gpt-image-2"


class BaseWorkflow:
    def run(self, context: WorkflowContext) -> WorkflowResult:
        raise NotImplementedError

    def save_image(self, image: Image.Image, context: WorkflowContext, stem: str, artifact_type: str) -> Artifact:
        filename = f"img{context.job.image_index:02d}_{stem}.png"
        path = context.output_dir / filename
        image.save(path, "PNG")
        artifact_id = f"{context.job.job_id}_{artifact_type}_{path.stem}_{uuid.uuid4().hex[:6]}"
        return Artifact(
            artifact_id=artifact_id,
            job_id=context.job.job_id,
            type=artifact_type,
            name=filename,
            path=str(path),
            metadata={
                "image_index": context.job.image_index,
                "image_type": context.job.image_type,
                "view_type": context.job.view_type,
            },
        )

    def ok_result(self, context: WorkflowContext, artifacts: list[Artifact], traces: list[dict[str, Any]] | None = None) -> WorkflowResult:
        return WorkflowResult(
            job=context.job,
            artifacts=artifacts,
            quality=QualityReport(score=0, status="pending_evaluation", issues=[]),
            traces=traces or [],
        )
