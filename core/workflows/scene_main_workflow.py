from __future__ import annotations

from pipeline.step3_compose import generate_scene_with_product

from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("scene_main")
class SceneMainWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        view_asset = context.view_agent.get_or_generate_view(
            sku=context.sku,
            base_subject=context.base_assets["transparent"],
            image_type=context.job.image_type,
            requested_view=context.job.view_type,
        )
        scene_description = self._scene_description(context)
        with context.trace.timed("workflow.scene_main"):
            images = generate_scene_with_product(
                product_transparent=view_asset.image,
                scene_description=scene_description,
                model=context.model,
                candidates=1,
                scale_factor=0.75 if view_asset.view_type == "low_angle_hero" else 0.68,
            )
            artifacts = []
            if images:
                artifact = self.save_image(images[0], context, context.job.image_type, "scene")
                artifacts.append(artifact)
                context.trace.add(
                    step="view_agent.select",
                    status="success",
                    input={
                        "sku_id": context.sku.product_id,
                        "job_id": context.job.job_id,
                        "view_type": view_asset.view_type,
                        "camera_angle": view_asset.spec.camera_angle,
                    },
                    output_artifact=artifact.path,
                    model=context.model,
                )
            return self.ok_result(context, artifacts, context.trace.records[-2:])

    def _scene_description(self, context: WorkflowContext) -> str:
        if context.scenes:
            idx = min(max(context.job.image_index - 1, 0), len(context.scenes) - 1)
            return context.scenes[idx].get("description_en") or context.scenes[0].get("description_en", "")
        return (
            f"{context.sku.scene_requirements.main_scene}. "
            "Luxury living room, product placed prominently, realistic commercial photography."
        )
