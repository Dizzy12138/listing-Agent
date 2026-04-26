from __future__ import annotations

from pipeline.step3_compose import composite_product_on_background
from pipeline.step3_compose import generate_background
from pipeline.step3_compose import image_edit_fusion

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
        view_path = context.view_agent.save_view_asset(context.sku.product_id, context.job.image_index, view_asset)
        scene_description = self._scene_description(context)
        with context.trace.timed("workflow.scene_main"):
            artifacts = []
            asset_quality = context.base_assets.get("asset_quality", {})
            if not asset_quality.get("allow_scene_workflow", True):
                context.trace.add(
                    step="workflow.scene_main.asset_gate",
                    status="fail",
                    input={"job_id": context.job.job_id, "asset_quality": asset_quality},
                    issues=asset_quality.get("issues", []),
                )
                return self.ok_result(context, artifacts, context.trace.records[-2:])

            backgrounds = generate_background(scene_description, model=context.model, size="1536x1024", quality="high", n=1)
            if backgrounds:
                background = backgrounds[0]
                rough = composite_product_on_background(
                    view_asset.image,
                    background,
                    scale_factor=0.75 if view_asset.view_type == "low_angle_hero" else 0.68,
                )
                rough_artifact = self.save_image(rough, context, f"{context.job.image_type}_rough", "rough_scene")
                fused, fusion_issues = image_edit_fusion(
                    background=background,
                    product_subject=view_asset.image,
                    rough_composite=rough,
                    scene_prompt=scene_description,
                    model=context.model,
                )
                artifact = self.save_image(fused, context, context.job.image_type, "scene")
                artifact.metadata.update({
                    "view_generation_mode": view_asset.mode,
                    "view_issues": (view_asset.issues or []) + fusion_issues,
                    "view_asset_path": str(view_path),
                    "view_locked": bool(context.job.params.get("view_locked")),
                    "rough_composite_path": rough_artifact.path,
                    "fusion_status": "fallback_rough" if fusion_issues else "fused",
                    "scene_prompt": scene_description,
                })
                artifacts.extend([rough_artifact, artifact])
                context.trace.add(
                    step="workflow.scene_main.fusion",
                    status="warning" if view_asset.issues or fusion_issues else "success",
                    input={
                        "sku_id": context.sku.product_id,
                        "job_id": context.job.job_id,
                        "view_type": view_asset.view_type,
                        "generation_mode": view_asset.mode,
                        "camera_angle": view_asset.spec.camera_angle,
                        "scene_prompt": scene_description,
                    },
                    output_artifact=artifact.path,
                    model=context.model,
                    issues=(view_asset.issues or []) + fusion_issues,
                )
            return self.ok_result(context, artifacts, context.trace.records[-2:])

    def _scene_description(self, context: WorkflowContext) -> str:
        if context.scenes:
            idx = int(context.job.params.get("scene_idx", 0))
            idx = min(max(idx, 0), len(context.scenes) - 1)
            return context.scenes[idx].get("description_en") or context.scenes[0].get("description_en", "")
        return (
            f"{context.sku.scene_requirements.main_scene}. "
            "Luxury living room, product placed prominently, realistic commercial photography."
        )
