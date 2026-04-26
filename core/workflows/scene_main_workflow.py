"""
SceneMainWorkflow — VLM-aware scene generation with real fusion.

Flow:
1. ViewReconstructionAgent generates view candidate for the requested angle
2. Generate background scene
3. Compose rough composite
4. Multi-input fusion (Gemini multimodal or GPT single-edit)
5. Quality verification (VLM)

Output rules:
- true_fusion + quality pass → formal img0X.png
- single_edit_fallback → candidate only (img0X_candidate.png + blocked.json)
- fusion_not_supported / blocked → blocked.json only
"""
from __future__ import annotations

from pathlib import Path

from pipeline.step3_compose import composite_product_on_background
from pipeline.step3_compose import generate_background
from pipeline.step3_compose import generate_product_mask
from pipeline.step3_compose import image_edit_fusion

from core.agents.scene_requirement_checker import check_scene_requirements
from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("scene_main")
class SceneMainWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        scene_description = self._scene_description(context)

        # Get vision agent & view reconstruction agent from context
        vision_agent = context.base_assets.get("_vision_agent")
        view_recon = context.base_assets.get("_view_recon_agent")

        with context.trace.timed("workflow.scene_main"):
            # ---- Step 1: View candidate generation ----
            view_image = context.base_assets["white_bg"]
            view_method = "original_front"
            view_confidence = 0.8
            view_issues = []

            requested_view = context.job.view_type or "front_open"
            needs_reconstruction = requested_view in ("low_angle_hero", "left_45", "right_45")

            if needs_reconstruction and view_recon:
                product_analysis = context.base_assets.get("_product_analysis", {})
                candidates = view_recon.generate_view(
                    original_image=context.base_assets["white_bg"],
                    product_analysis=product_analysis,
                    target_view=requested_view,
                    vision_agent=vision_agent,
                )
                # Save all candidates
                view_recon.save_candidates(candidates, context.output_dir, context.job.image_index)

                best = view_recon.select_best_candidate(candidates, min_confidence=0.3)
                if best and best.method != "blocked":
                    view_image = best.image
                    view_method = best.method
                    view_confidence = best.confidence
                    view_issues = best.issues
                else:
                    # Cannot generate this view — blocked
                    return self._handle_blocked(
                        context, requested_view, scene_description,
                        reason=f"view_reconstruction_failed:{requested_view}",
                        details={"candidates": len(candidates), "best_confidence": best.confidence if best else 0},
                    )
            elif needs_reconstruction and not view_recon:
                # No reconstruction agent available
                return self._handle_blocked(
                    context, requested_view, scene_description,
                    reason="view_reconstruction_agent_not_available",
                )

            # ---- Step 2: Generate background ----
            backgrounds = generate_background(
                scene_description, model=context.model, size="1536x1024", quality="high", n=1,
            )
            if not backgrounds:
                return self._handle_blocked(
                    context, requested_view, scene_description,
                    reason="background_generation_failed",
                )

            background = backgrounds[0]

            # ---- Step 3: Rough composite ----
            scale = 0.75 if requested_view == "low_angle_hero" else 0.68
            rough = composite_product_on_background(view_image, background, scale_factor=scale)

            artifacts = []
            rough_artifact = self.save_image(rough, context, f"{context.job.image_type}_rough", "rough_scene")
            artifacts.append(rough_artifact)

            # ---- Step 4: Multi-input fusion ----
            product_mask = None
            transparent = context.base_assets.get("transparent")
            if transparent:
                product_mask = generate_product_mask(transparent)

            fused, fusion_issues, fusion_mode = image_edit_fusion(
                background=background,
                product_subject=view_image,
                rough_composite=rough,
                scene_prompt=scene_description,
                model=context.model,
                product_mask=product_mask,
            )

            # ---- Step 5: Scene requirement check ----
            scene_req_result = check_scene_requirements(scene_description)

            # ---- Step 6: Quality verification with VLM ----
            vlm_quality = {}
            if vision_agent and fusion_mode in ("true_fusion", "single_edit_fallback"):
                required_elements = scene_req_result.get("required_elements", [])
                vlm_quality = vision_agent.verify_quality(fused, required_elements=required_elements)

            # ---- Determine output mode ----
            if fusion_mode == "true_fusion":
                # Check VLM quality
                vlm_pass = vlm_quality.get("overall_quality", "manual_required") in ("pass", "manual_required")
                vlm_no_artifacts = not vlm_quality.get("has_artifacts", False)

                if vlm_pass and vlm_no_artifacts:
                    # TRUE FUSION + QUALITY OK → formal output
                    formal_artifact = self.save_image(fused, context, context.job.image_type, "scene")
                    formal_artifact.metadata.update(self._build_metadata(
                        "true_fusion", fusion_mode, fusion_issues, view_method, view_confidence,
                        view_issues, scene_description, scene_req_result, vlm_quality,
                    ))
                    artifacts.append(formal_artifact)
                    context.trace.add(
                        step="workflow.scene_main.true_fusion",
                        status="success",
                        input=self._trace_input(context, requested_view, "true_fusion", scene_description),
                        output_artifact=formal_artifact.path,
                        model=context.model,
                        issues=fusion_issues + view_issues,
                    )
                    return self.ok_result(context, artifacts, context.trace.records[-2:])
                else:
                    # True fusion but VLM found issues → candidate only
                    candidate_artifact = self.save_image(fused, context, f"{context.job.image_type}_candidate", "scene_candidate")
                    candidate_artifact.metadata.update(self._build_metadata(
                        "true_fusion_quality_fail", fusion_mode, fusion_issues, view_method,
                        view_confidence, view_issues, scene_description, scene_req_result, vlm_quality,
                    ))
                    artifacts.append(candidate_artifact)

                    # Save reason
                    reason_issues = vlm_quality.get("issues", [])
                    self._save_reason(context, f"True fusion quality fail: {reason_issues}")

                    blocked_artifact = self.save_blocked_report(
                        context, context.job.image_type,
                        reason="true_fusion_quality_fail",
                        details={"vlm_quality": vlm_quality, "scene_req": scene_req_result},
                    )
                    artifacts.append(blocked_artifact)
                    context.trace.add(
                        step="workflow.scene_main.true_fusion_quality_fail",
                        status="warning",
                        input=self._trace_input(context, requested_view, "true_fusion_quality_fail", scene_description),
                        issues=reason_issues + fusion_issues,
                    )
                    return self.blocked_result(
                        context, artifacts,
                        reason=f"true_fusion_quality_fail: {reason_issues}",
                        traces=context.trace.records[-2:],
                    )

            elif fusion_mode == "single_edit_fallback":
                # Single edit is NOT true fusion — save as candidate, blocked for formal
                candidate_artifact = self.save_image(fused, context, f"{context.job.image_type}_candidate", "scene_candidate")
                candidate_artifact.metadata.update(self._build_metadata(
                    "single_edit_fallback", fusion_mode, fusion_issues, view_method,
                    view_confidence, view_issues, scene_description, scene_req_result, vlm_quality,
                ))
                artifacts.append(candidate_artifact)

                self._save_reason(context, "Single edit fallback — not true multi-input fusion")

                blocked_artifact = self.save_blocked_report(
                    context, context.job.image_type,
                    reason="not_true_fusion",
                    details={
                        "fusion_mode": "single_edit_fallback",
                        "fusion_issues": fusion_issues,
                        "scene_req": scene_req_result,
                        "vlm_quality": vlm_quality,
                    },
                )
                artifacts.append(blocked_artifact)
                context.trace.add(
                    step="workflow.scene_main.single_edit_fallback",
                    status="warning",
                    input=self._trace_input(context, requested_view, "single_edit_fallback", scene_description),
                    issues=["not_true_fusion: formal scene NOT generated"] + fusion_issues,
                )
                return self.blocked_result(
                    context, artifacts,
                    reason="not_true_fusion: only candidate saved, formal output blocked",
                    traces=context.trace.records[-2:],
                )

            else:
                # fusion_not_supported — completely blocked
                return self._handle_blocked(
                    context, requested_view, scene_description,
                    reason=f"fusion_not_supported: {fusion_issues}",
                )

    def _handle_blocked(self, context, view_type, scene_description, reason, details=None):
        """No formal output, save blocked.json."""
        blocked_artifact = self.save_blocked_report(
            context, context.job.image_type,
            reason=reason,
            details={"view_type": view_type, **(details or {})},
        )
        self._save_reason(context, reason)
        context.trace.add(
            step="workflow.scene_main.blocked",
            status="fail",
            input=self._trace_input(context, view_type, "blocked", scene_description),
            issues=[f"scene_blocked: {reason}"],
        )
        return self.blocked_result(
            context, [blocked_artifact],
            reason=f"scene_blocked: {reason}",
            traces=context.trace.records[-2:],
        )

    def _save_reason(self, context, reason: str):
        """Save reason.txt next to the output."""
        filename = f"img{context.job.image_index:02d}_{context.job.image_type}_reason.txt"
        path = context.output_dir / filename
        path.write_text(reason, encoding="utf-8")

    def _build_metadata(self, scene_mode, fusion_mode, fusion_issues, view_method,
                         view_confidence, view_issues, scene_description, scene_req, vlm_quality):
        return {
            "scene_generation_mode": scene_mode,
            "fusion_mode": fusion_mode,
            "fusion_issues": fusion_issues,
            "view_method": view_method,
            "view_confidence": view_confidence,
            "view_issues": view_issues,
            "scene_prompt": scene_description,
            "scene_requirement_check": scene_req,
            "vlm_quality_check": vlm_quality,
        }

    def _trace_input(self, context, view_type, mode, scene_description):
        return {
            "sku_id": context.sku.product_id,
            "job_id": context.job.job_id,
            "view_type": view_type,
            "scene_generation_mode": mode,
            "scene_prompt": scene_description[:200],
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
