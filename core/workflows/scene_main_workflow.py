"""
SceneMainWorkflow — three-mode scene generation.

Mode A (true_fusion):  multi-input fusion available → output formal scene.
Mode B (rough_only):   fusion not supported → save rough only, no formal image.
Mode C (blocked):      core view not implemented or asset quality fail → no image.

trace always records `scene_generation_mode` explicitly.
"""
from __future__ import annotations

from pipeline.step3_compose import composite_product_on_background
from pipeline.step3_compose import generate_background
from pipeline.step3_compose import image_edit_fusion

from core.agents.scene_requirement_checker import check_scene_requirements
from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


def _determine_scene_mode(view_asset, asset_quality: dict, fusion_mode: str | None = None) -> str:
    """
    Decide the scene generation mode BEFORE outputting any formal image.

    Returns one of: "true_fusion", "rough_only", "blocked".
    """
    view_issues = view_asset.issues or []

    # ---- Mode C: blocked ----
    # If the view requires model_synthesis but it's not implemented,
    # we cannot produce a scene_main that satisfies the requested angle.
    if "model_synthesis_not_implemented" in view_issues:
        return "blocked"

    # If asset quality blocks scene workflows entirely.
    if not asset_quality.get("allow_scene_workflow", True):
        return "blocked"

    # ---- After fusion ----
    if fusion_mode == "true_fusion":
        return "true_fusion"

    # fusion_not_supported → rough only
    return "rough_only"


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
        asset_quality = context.base_assets.get("asset_quality", {})

        with context.trace.timed("workflow.scene_main"):
            # ---- Pre-flight: check if we should even attempt generation ----
            pre_mode = _determine_scene_mode(view_asset, asset_quality)
            if pre_mode == "blocked":
                return self._handle_blocked(context, view_asset, view_path, scene_description, asset_quality)

            # ---- Generate background + rough composite ----
            backgrounds = generate_background(scene_description, model=context.model, size="1536x1024", quality="high", n=1)
            if not backgrounds:
                return self._handle_blocked(context, view_asset, view_path, scene_description, asset_quality,
                                            reason="background_generation_failed")

            background = backgrounds[0]
            rough = composite_product_on_background(
                view_asset.image,
                background,
                scale_factor=0.75 if view_asset.view_type == "low_angle_hero" else 0.68,
            )
            artifacts = []
            rough_artifact = self.save_image(rough, context, f"{context.job.image_type}_rough", "rough_scene")
            artifacts.append(rough_artifact)

            # ---- Attempt fusion ----
            fused, fusion_issues, fusion_mode = image_edit_fusion(
                background=background,
                product_subject=view_asset.image,
                rough_composite=rough,
                scene_prompt=scene_description,
                model=context.model,
            )

            final_mode = _determine_scene_mode(view_asset, asset_quality, fusion_mode)

            # ---- Scene requirement check ----
            scene_req_result = check_scene_requirements(scene_description)

            if final_mode == "true_fusion":
                # Mode A: output formal scene image
                formal_artifact = self.save_image(fused, context, context.job.image_type, "scene")
                formal_artifact.metadata.update({
                    "scene_generation_mode": "true_fusion",
                    "view_generation_mode": view_asset.mode,
                    "view_issues": (view_asset.issues or []) + fusion_issues,
                    "view_asset_path": str(view_path),
                    "view_locked": bool(context.job.params.get("view_locked")),
                    "rough_composite_path": rough_artifact.path,
                    "fusion_status": "fused",
                    "scene_prompt": scene_description,
                    "scene_requirement_check": scene_req_result,
                })
                artifacts.append(formal_artifact)
                context.trace.add(
                    step="workflow.scene_main.true_fusion",
                    status="success",
                    input=self._trace_input(context, view_asset, scene_description, "true_fusion"),
                    output_artifact=formal_artifact.path,
                    model=context.model,
                    issues=(view_asset.issues or []) + fusion_issues,
                )
                return self.ok_result(context, artifacts, context.trace.records[-2:])

            else:
                # Mode B: rough_only — save the refined rough but NOT as formal output.
                # Also save the fused-but-not-qualified image as rough.
                if fused is not rough:
                    refined_artifact = self.save_image(fused, context, f"{context.job.image_type}_rough_refined", "rough_scene")
                    refined_artifact.metadata.update({
                        "scene_generation_mode": "rough_only",
                        "fusion_status": "fusion_not_supported",
                        "view_generation_mode": view_asset.mode,
                        "view_issues": (view_asset.issues or []) + fusion_issues,
                        "scene_prompt": scene_description,
                        "scene_requirement_check": scene_req_result,
                    })
                    artifacts.append(refined_artifact)

                # Save blocked report
                blocked_artifact = self.save_blocked_report(
                    context,
                    context.job.image_type,
                    reason="fusion_not_supported",
                    details={
                        "scene_generation_mode": "rough_only",
                        "fusion_issues": fusion_issues,
                        "scene_requirement_check": scene_req_result,
                    },
                )
                artifacts.append(blocked_artifact)

                context.trace.add(
                    step="workflow.scene_main.rough_only",
                    status="warning",
                    input=self._trace_input(context, view_asset, scene_description, "rough_only"),
                    issues=["fusion_not_supported: formal scene NOT generated"] + fusion_issues,
                )
                return self.blocked_result(
                    context, artifacts,
                    reason="fusion_not_supported: only rough scene saved, formal output blocked",
                    traces=context.trace.records[-2:],
                )

    def _handle_blocked(self, context, view_asset, view_path, scene_description, asset_quality, reason=None):
        """Mode C: blocked — no formal output, no rough generation attempt."""
        if reason is None:
            view_issues = view_asset.issues or []
            if "model_synthesis_not_implemented" in view_issues:
                reason = "model_synthesis_not_implemented"
            elif not asset_quality.get("allow_scene_workflow", True):
                reason = "asset_quality_blocked"
            else:
                reason = "unknown_block"

        blocked_artifact = self.save_blocked_report(
            context,
            context.job.image_type,
            reason=reason,
            details={
                "scene_generation_mode": "blocked",
                "view_type": view_asset.view_type,
                "view_issues": view_asset.issues or [],
                "asset_quality": asset_quality,
            },
        )
        context.trace.add(
            step="workflow.scene_main.blocked",
            status="fail",
            input=self._trace_input(context, view_asset, scene_description, "blocked"),
            issues=[f"scene_blocked: {reason}"],
        )
        return self.blocked_result(
            context, [blocked_artifact],
            reason=f"scene_blocked: {reason}",
            traces=context.trace.records[-2:],
        )

    def _trace_input(self, context, view_asset, scene_description, mode):
        return {
            "sku_id": context.sku.product_id,
            "job_id": context.job.job_id,
            "view_type": view_asset.view_type,
            "generation_mode": view_asset.mode,
            "camera_angle": view_asset.spec.camera_angle,
            "scene_prompt": scene_description,
            "scene_generation_mode": mode,
        }

    def _scene_description(self, context: WorkflowContext) -> str:
        if context.scenes:
            idx = int(context.job.params.get("scene_idx", 0))
            idx = min(max(idx, 0), len(context.scenes) - 1)
            return context.scenes[idx].get("description_en") or context.scenes[0].get("description_en", "")
        return (
            f"{context.sku.scene_requirements.main_scene}. "
            "Luxury living room, product placed prominently, realistic commercial photography."
        )
