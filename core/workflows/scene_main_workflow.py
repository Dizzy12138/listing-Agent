from __future__ import annotations

from core.agents.scene_requirement_checker import check_scene_requirements
from core.tools.reference_generation import reference_guided_scene_generation
from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("scene_main")
class SceneMainWorkflow(BaseWorkflow):
    """Reference-guided whole-scene generation.

    White/transparent assets are reference only. They are not pasted into the
    scene and are not required to have a reconstructed low-angle view.
    """

    def run(self, context: WorkflowContext):
        scene_description = self._scene_description(context)
        product_analysis = context.base_assets.get("_product_analysis", {})
        vision_agent = context.base_assets.get("_vision_agent")

        with context.trace.timed("workflow.scene_main.reference_guided"):
            image, generation_issues, mode = reference_guided_scene_generation(
                original_photo=context.base_assets["original"],
                white_bg_reference=context.base_assets["white_bg"],
                product_analysis=product_analysis,
                scene_prompt=scene_description,
                model=context.model,
                image_type=context.job.image_type,
            )

            scene_req = check_scene_requirements(scene_description)
            required_elements = scene_req.get("required_elements", [])
            vlm_quality = {}
            commercial_level = "needs_review"
            if vision_agent:
                vlm_quality = vision_agent.verify_quality(image, required_elements=required_elements)
                if (
                    vlm_quality.get("overall_quality") == "pass"
                    and not vlm_quality.get("has_artifacts", False)
                    and not vlm_quality.get("structure_distorted", False)
                    and not vlm_quality.get("missing_elements")
                    and mode != "reference_based_fallback"
                ):
                    commercial_level = "commercial_scene_pass"

            if mode == "reference_based_fallback":
                commercial_level = "needs_review"

            artifact = self.save_image(image, context, context.job.image_type, "scene")
            artifact.metadata.update({
                "generation_strategy": "reference_guided_scene_generation",
                "generation_mode": mode,
                "commercial_quality_level": commercial_level,
                "reference_assets_used": ["original", "white_bg", "product_analysis"],
                "direct_white_bg_subject": False,
                "reference_based_fallback": mode == "reference_based_fallback",
                "scene_prompt": scene_description,
                "scene_requirement_check": scene_req,
                "vlm_quality_check": vlm_quality,
                "product_analysis_source": product_analysis.get("source", "unknown"),
                "source_priority": product_analysis.get("sku_facts", {}).get(
                    "source_priority",
                    ["SKU facts", "ProductVisionAgent", "heuristic fallback"],
                ),
            })
            context.trace.add(
                step="workflow.scene_main.reference_guided.output",
                status="success" if commercial_level == "commercial_scene_pass" else "warning",
                input={
                    "job_id": context.job.job_id,
                    "generation_strategy": "reference_guided_scene_generation",
                    "mode": mode,
                    "reference_assets_used": ["original", "white_bg", "product_analysis"],
                    "scene_prompt": scene_description[:300],
                },
                output_artifact=artifact.path,
                model=context.model,
                issues=generation_issues + vlm_quality.get("issues", []),
            )
            return self.ok_result(context, [artifact], context.trace.records[-2:])

    def _scene_description(self, context: WorkflowContext) -> str:
        if context.scenes:
            idx = int(context.job.params.get("scene_idx", 0))
            idx = min(max(idx, 0), len(context.scenes) - 1)
            return context.scenes[idx].get("description_en") or context.scenes[0].get("description_en", "")
        return (
            f"{context.sku.scene_requirements.main_scene}. "
            "Luxury living room, product placed prominently, realistic commercial photography."
        )
