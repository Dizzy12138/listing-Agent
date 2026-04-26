from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image

from config import MODELS, OUTPUT_DIR, PRODUCTS_DIR
from core.agents.asset_quality_gate import AssetQualityGate
from core.agents.quality_agent import QualityAgent
from core.agents.view_agent import ViewAgent
from core.schemas.job import Artifact, ImageJob, WorkflowResult
from core.schemas.sku import SKU
from core.services.sku_service import SKUService
from core.tracing.trace import TraceRecorder
from core.workflows.base import WorkflowContext
from core.workflows.registry import get_workflow, resolve_workflow
from pipeline.step1_extract import remove_background
from pipeline.step2_scene import generate_scene_descriptions

# Import workflow modules so decorators register classes.
from core.workflows import detail_workflow  # noqa: F401
from core.workflows import multilingual_text_workflow  # noqa: F401
from core.workflows import scene_main_workflow  # noqa: F401
from core.workflows import selling_point_annotation_workflow  # noqa: F401
from core.workflows import size_compare_workflow  # noqa: F401
from core.workflows import white_main_workflow  # noqa: F401


ProgressCallback = Callable[[str, int], None]


class GenerationService:
    def __init__(self, products_dir: Path = PRODUCTS_DIR, output_dir: Path = OUTPUT_DIR):
        self.products_dir = products_dir
        self.output_dir = output_dir
        self.sku_service = SKUService(products_dir)

    def build_jobs_from_sku(self, sku: SKU) -> list[ImageJob]:
        jobs: list[ImageJob] = []
        scene_idx = 0
        for item in sku.image_plan:
            workflow_key = resolve_workflow(item.type, item.description)
            params = {
                "visual_goal": item.visual_goal,
                "required_elements": item.required_elements,
                "forbidden_elements": item.forbidden_elements,
            }
            if workflow_key == "scene_main":
                params["scene_idx"] = scene_idx
                scene_idx += 1
            jobs.append(ImageJob(
                job_id=f"{sku.product_id}_{item.index}",
                sku_id=sku.product_id,
                image_index=item.index,
                image_type=item.type,
                description=item.description,
                workflow_key=workflow_key,
                view_type=item.view_type,
                params=params,
            ))
        return jobs

    def execute_run(
        self,
        product_id: str,
        product_image_path: str | Path,
        model: str | None = None,
        run_id: str | None = None,
        progress: ProgressCallback | None = None,
    ) -> dict:
        sku = self.sku_service.load(product_id)
        model = model or MODELS.get("image_primary", "gpt-image-2")
        run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = self.output_dir / f"{product_id}_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)
        trace = TraceRecorder(run_id)

        image_path = Path(product_image_path)
        shutil.copy(image_path, output_dir / "original.png")
        product_image = Image.open(image_path).copy().convert("RGB")

        self._progress(progress, "AssetAgent: 主体标准化", 10)
        extracted = remove_background(product_image, model=model)
        extracted["transparent"].save(output_dir / "01_transparent.png", "PNG")
        extracted["white_bg"].save(output_dir / "01_white_bg.png", "PNG")
        asset_quality = AssetQualityGate().evaluate(extracted["transparent"], extracted["white_bg"])
        extracted["asset_quality"] = asset_quality
        trace.add(
            step="asset_agent.extract",
            status="success" if asset_quality["status"] == "pass" else "fail",
            input={"sku_id": sku.product_id, "image_path": str(image_path)},
            model=model,
            output_artifact=str(output_dir / "01_transparent.png"),
            issues=asset_quality["issues"],
        )

        scenes = self._generate_scenes(sku, product_image, model)
        with open(output_dir / "scenes.json", "w", encoding="utf-8") as f:
            json.dump(scenes, f, ensure_ascii=False, indent=2)

        view_agent = ViewAgent(output_dir)
        jobs = view_agent.allocate_views(sku, self.build_jobs_from_sku(sku))
        quality_agent = QualityAgent()
        view_distribution = quality_agent.evaluate_view_distribution(jobs)
        trace.add(
            step="quality_agent.view_distribution",
            status="warning" if view_distribution["issues"] else "success",
            input={"sku_id": sku.product_id},
            issues=view_distribution["issues"],
        )
        results: list[WorkflowResult] = []
        artifacts: list[Artifact] = [
            Artifact(artifact_id=f"{run_id}_original", type="original", name="original.png", path=str(output_dir / "original.png")),
            Artifact(artifact_id=f"{run_id}_transparent", type="extract", name="01_transparent.png", path=str(output_dir / "01_transparent.png")),
            Artifact(artifact_id=f"{run_id}_white_bg", type="extract", name="01_white_bg.png", path=str(output_dir / "01_white_bg.png")),
        ]

        total = max(len(jobs), 1)
        for idx, job in enumerate(jobs, 1):
            self._progress(progress, f"WorkflowAgent: {job.image_index}. {job.image_type}", 20 + int(idx / total * 70))
            workflow_cls = get_workflow(job.workflow_key)
            context = WorkflowContext(
                run_id=run_id,
                sku=sku,
                job=job,
                output_dir=output_dir,
                base_assets=extracted,
                view_agent=view_agent,
                trace=trace,
                scenes=scenes,
                model=model,
            )
            result = workflow_cls().run(context)
            result.quality = quality_agent.evaluate_artifacts(job, result.artifacts)
            trace.add(
                step="quality_agent.evaluate_artifacts",
                status=result.quality.status,
                input={"job_id": job.job_id, "artifact_count": len(result.artifacts)},
                issues=result.quality.issues,
            )
            results.append(result)
            artifacts.extend(result.artifacts)

        trace_path = output_dir / "trace.json"
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace.records, f, ensure_ascii=False, indent=2)
        artifacts.append(Artifact(artifact_id=f"{run_id}_trace", type="trace", name="trace.json", path=str(trace_path)))

        self._progress(progress, "完成", 100)
        return {
            "run_id": run_id,
            "sku_id": sku.product_id,
            "output_dir": str(output_dir),
            "jobs": [job.model_dump() for job in jobs],
            "artifacts": [artifact.model_dump() for artifact in artifacts],
            "results": [result.model_dump() for result in results],
            "view_distribution": view_distribution,
            "traces": trace.records,
        }

    def _generate_scenes(self, sku: SKU, product_image: Image.Image, model: str) -> list[dict]:
        scene_count = sum(1 for item in sku.image_plan if resolve_workflow(item.type, item.description) == "scene_main")
        scene_count = max(1, min(5, scene_count))
        return generate_scene_descriptions(
            product_info=sku.model_dump(),
            user_requirements=sku.scene_requirements.main_scene,
            scene_count=scene_count,
            product_image=product_image,
        )

    def _progress(self, callback: ProgressCallback | None, message: str, value: int):
        if callback:
            callback(message, value)
