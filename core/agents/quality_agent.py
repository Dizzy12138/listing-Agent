"""
QualityAgent — upgraded with hard gating rules.

Key rules enforced:
- scene workflow rough_only / blocked → quality status = fail / blocked
- model_synthesis_not_implemented on scene_main → cannot pass
- SceneRequirementChecker missing elements (cats/child) → cannot pass
- checkerboard in any formal image → fail
- annotation elements must exist in metadata
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image

from core.schemas.job import Artifact, ImageJob, QualityReport
from pipeline.step3_compose import has_checkerboard_artifact


class QualityAgent:
    def evaluate_artifacts(self, job: ImageJob, artifacts: list[Artifact]) -> QualityReport:
        issues: list[str] = []
        fatal_issues: list[str] = []
        review_issues: list[str] = []
        image_artifacts = [a for a in artifacts if Path(a.path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
        blocked_reports = [a for a in artifacts if a.type == "blocked_report"]

        # ---- Hard gate: blocked reports mean this job cannot pass ----
        if blocked_reports:
            for br in blocked_reports:
                reason = br.metadata.get("blocked_reason", "unknown")
                fatal_issues.append(f"output blocked: {reason}")

        if not image_artifacts and not blocked_reports:
            fatal_issues.append("no output image artifact")

        for artifact in image_artifacts:
            view_issues = artifact.metadata.get("view_issues", [])
            scene_mode = artifact.metadata.get("scene_generation_mode", "")
            image_type = job.image_type.lower()

            # ---- Hard gate: scene mode checks ----
            if scene_mode == "rough_only":
                fatal_issues.append("scene is rough_only: fusion not supported, cannot be formal output")
            elif scene_mode == "blocked":
                fatal_issues.append("scene is blocked: core capability missing")

            # ---- Hard gate: model_synthesis_not_implemented on scene_main ----
            if "model_synthesis_not_implemented" in view_issues:
                if image_type in {"scene_main", "main_scene", "scene_lifestyle", "lifestyle"}:
                    fatal_issues.append(
                        "scene_main/scene_lifestyle requires model synthesis but not implemented; "
                        "cannot pass as formal output"
                    )
                elif artifact.type == "scene":
                    fatal_issues.append("scene artifact has model_synthesis_not_implemented in view_issues")
                else:
                    review_issues.append("requested view requires model synthesis but not implemented")

            # ---- Hard gate: SceneRequirementChecker ----
            scene_req = artifact.metadata.get("scene_requirement_check", {})
            if scene_req:
                req_status = scene_req.get("status", "")
                missing = scene_req.get("missing_elements", [])
                if req_status == "manual_required":
                    review_issues.append(f"scene requirement check is manual_required; missing: {missing}")
                elif req_status == "fail":
                    fatal_issues.append(f"scene requirement check failed; missing: {missing}")
                elif req_status == "needs_review":
                    review_issues.append(f"scene requirement check needs_review; missing: {missing}")

            # ---- Image quality checks ----
            try:
                image = Image.open(artifact.path)
            except OSError:
                fatal_issues.append(f"cannot open artifact: {artifact.name}")
                continue
            w, h = image.size
            if w < 1000 or h < 1000:
                review_issues.append(f"image too small: {artifact.name} {w}x{h}")

            # Checkerboard check on ALL formal image types
            if artifact.type in {"main", "scene", "selling_point", "size_compare", "detail"}:
                if has_checkerboard_artifact(image):
                    fatal_issues.append(f"checkerboard or white block artifact: {artifact.name}")

            # Even rough_scene images get a checkerboard flag
            if artifact.type == "rough_scene" and has_checkerboard_artifact(image):
                review_issues.append(f"rough scene has checkerboard artifact: {artifact.name}")

            self._business_quality_checks(job, artifact, fatal_issues, review_issues)

        issues = fatal_issues + review_issues
        score = max(0, 90 - len(fatal_issues) * 35 - len(review_issues) * 18)
        if fatal_issues:
            status = "fail"
        elif review_issues:
            status = "needs_review"
        else:
            status = "pass"
        return QualityReport(
            score=score,
            status=status,
            issues=issues,
            suggestion="人工审核通过后入库" if status == "pass" else "修复问题后重试",
        )

    def _business_quality_checks(
        self,
        job: ImageJob,
        artifact: Artifact,
        fatal_issues: list[str],
        review_issues: list[str],
    ):
        metadata = artifact.metadata
        image_type = job.image_type.lower()

        if artifact.type == "scene":
            fusion_status = metadata.get("fusion_status", "")
            scene_mode = metadata.get("scene_generation_mode", "")

            # If fusion was not successful, the scene is not qualified
            if fusion_status not in {"fused"} and scene_mode != "true_fusion":
                fatal_issues.append(f"scene fusion not confirmed (fusion_status={fusion_status}, mode={scene_mode})")

            # Prompt element check
            prompt = str(metadata.get("scene_prompt", "")).lower()
            requires_life = any(k in prompt for k in ["cat", "cats", "child", "family", "interaction", "maine coon"])
            if requires_life:
                scene_req = metadata.get("scene_requirement_check", {})
                if scene_req.get("status") in {"manual_required", "fail", "needs_review"}:
                    missing = scene_req.get("missing_elements", [])
                    review_issues.append(
                        f"scene prompt requires living elements but requirement check status="
                        f"{scene_req.get('status')}, missing={missing}"
                    )

        if artifact.type == "selling_point":
            annotation_type = metadata.get("annotation_type", "")
            title = str(metadata.get("title", "")).lower()
            has_annotation = metadata.get("has_annotation", False)

            if not has_annotation:
                fatal_issues.append("selling point image missing annotation metadata")

            # Verify annotation elements were actually drawn
            if annotation_type == "resting_areas":
                if "6" not in title:
                    review_issues.append("resting area selling point missing numbered-area title")
                if not metadata.get("annotation_badges_drawn"):
                    review_issues.append("resting areas: numbered badges may not be visible in output")

            if annotation_type == "climbing_path":
                if "path" not in title and "climbing" not in title:
                    review_issues.append("climbing path selling point title does not match path annotation")
                if not metadata.get("annotation_arrows_drawn"):
                    review_issues.append("climbing path: route arrows may not be visible in output")

            if annotation_type == "stability_base":
                if "base" not in title:
                    review_issues.append("stability selling point does not emphasize base")
                if not metadata.get("annotation_highlight_drawn"):
                    review_issues.append("stability base: highlight box may not be visible in output")

            if annotation_type == "scratching_system":
                if "scratch" not in title and "sisal" not in title:
                    review_issues.append("scratching selling point does not emphasize scratching system")
                if not metadata.get("annotation_highlights_drawn"):
                    review_issues.append("scratching system: highlight boxes may not be visible in output")

        if artifact.type == "size_compare" or image_type == "size_compare":
            if not metadata.get("has_dimension_line") or "205" not in str(metadata.get("dimension_label", "")):
                fatal_issues.append("size compare image missing 205cm dimension line")
            if metadata.get("title_safe_area") != "top_band_outside_product":
                review_issues.append("size compare title safe area not confirmed")

    def evaluate_view_distribution(self, jobs: list[ImageJob]) -> dict:
        missing = [job.job_id for job in jobs if not job.view_type]
        counts = Counter(job.view_type for job in jobs if job.view_type)
        repeated = {view: count for view, count in counts.items() if count > 1}
        total = max(len(jobs), 1)
        unique = len(counts)
        diversity_score = round(unique / total, 2)
        issues = [f"job missing view_type: {job_id}" for job_id in missing]
        issues.extend(f"View repeated: {view} x {count}" for view, count in repeated.items())
        return {
            "view_counts": dict(counts),
            "repeated_views": repeated,
            "view_diversity_score": diversity_score,
            "missing_view_jobs": missing,
            "issues": issues,
        }
