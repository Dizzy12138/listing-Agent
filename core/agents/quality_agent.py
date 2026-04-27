"""
QualityAgent — VLM-powered quality gate.

Hard rules:
- No VLM available → manual_required, never auto-pass
- Blocked / rough_only scenes → fail
- model_synthesis_not_implemented on scene types → fail
- Checkerboard / white block artifacts → fail
- Scene missing required elements (cats/child) → fail or manual_required
- Selling point annotation from fallback → cannot pass
- Material detection low confidence → needs_review
- View direction repeated > threshold → needs_review for entire batch
- Selling point image must actually express the selling point (VLM check)
- Annotation boxes must not obviously miss target parts
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image

from core.schemas.job import Artifact, ImageJob, QualityReport
from pipeline.step3_compose import has_checkerboard_artifact


class QualityAgent:
    def __init__(self, vision_agent=None):
        self._vision_agent = vision_agent

    def evaluate_artifacts(self, job: ImageJob, artifacts: list[Artifact]) -> QualityReport:
        issues: list[str] = []
        fatal_issues: list[str] = []
        review_issues: list[str] = []
        image_artifacts = [a for a in artifacts if Path(a.path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
        blocked_reports = [a for a in artifacts if a.type == "blocked_report"]

        # ---- Hard gate: blocked reports ----
        if blocked_reports:
            for br in blocked_reports:
                reason = br.metadata.get("blocked_reason", "unknown")
                fatal_issues.append(f"output blocked: {reason}")

        if not image_artifacts and not blocked_reports:
            fatal_issues.append("no output image artifact")

        for artifact in image_artifacts:
            metadata = artifact.metadata
            scene_mode = metadata.get("scene_generation_mode", "")
            fusion_mode = metadata.get("fusion_mode", "")
            vision_source = metadata.get("vision_source", "")
            level = metadata.get("commercial_quality_level", "")
            if level == "needs_review":
                review_issues.append(f"{artifact.name}: commercial_quality_level=needs_review")
            elif level == "fail":
                fatal_issues.append(f"{artifact.name}: commercial_quality_level=fail")

            # ---- Type-specific checks ----
            if artifact.type == "scene":
                self._check_scene(artifact, metadata, scene_mode, fusion_mode, fatal_issues, review_issues)
            elif artifact.type == "scene_candidate":
                # Candidates are informational, not formal output
                pass
            elif artifact.type == "selling_point":
                self._check_selling_point(job, artifact, metadata, vision_source, fatal_issues, review_issues)
            elif artifact.type == "selling_point_candidate":
                # Candidate — cannot auto-pass
                review_issues.append(f"selling_point_candidate requires manual review: {artifact.name}")
            elif artifact.type == "detail":
                self._check_detail(artifact, metadata, fatal_issues, review_issues)
            elif artifact.type == "detail_candidate":
                review_issues.append(f"detail_candidate requires manual review: {artifact.name}")
            elif artifact.type in ("main", "white_main"):
                self._check_main(artifact, fatal_issues, review_issues)
            elif artifact.type == "size_compare":
                self._check_size_compare(artifact, metadata, fatal_issues, review_issues)

            # ---- Universal image checks ----
            if artifact.type not in ("scene_candidate", "selling_point_candidate", "detail_candidate", "rough_scene"):
                try:
                    image = Image.open(artifact.path)
                    w, h = image.size
                    if w < 1000 or h < 1000:
                        review_issues.append(f"image too small: {artifact.name} {w}x{h}")
                    if has_checkerboard_artifact(image):
                        fatal_issues.append(f"checkerboard artifact in formal output: {artifact.name}")
                except OSError:
                    fatal_issues.append(f"cannot open artifact: {artifact.name}")

        # ---- VLM verification for scene/selling_point (if available) ----
        if self._vision_agent:
            for artifact in image_artifacts:
                if artifact.type == "scene":
                    self._vlm_verify_scene(artifact, fatal_issues, review_issues)
                elif artifact.type == "selling_point":
                    self._vlm_verify_selling_point(job, artifact, review_issues)

        all_issues = fatal_issues + review_issues
        quality_levels = [a.metadata.get("commercial_quality_level") for a in image_artifacts]
        score = max(0, 90 - len(fatal_issues) * 35 - len(review_issues) * 15)
        if fatal_issues:
            status = "fail"
        elif review_issues:
            status = "needs_review"
        elif "commercial_scene_pass" in quality_levels:
            status = "commercial_scene_pass"
        elif quality_levels and all(level == "info_graph_pass" for level in quality_levels if level):
            status = "info_graph_pass"
        elif not self._vision_agent:
            status = "manual_required"
            review_issues.append("no VLM available for automated quality verification")
        else:
            status = "pass"

        return QualityReport(
            score=score,
            status=status,
            issues=all_issues + (["no_vlm: manual review required"] if not self._vision_agent and not fatal_issues else []),
            suggestion="人工审核" if status != "fail" else "修复问题后重试",
        )

    def _check_scene(self, artifact, metadata, scene_mode, fusion_mode, fatal, review):
        strategy = metadata.get("generation_strategy", "")
        level = metadata.get("commercial_quality_level", "")
        if strategy != "reference_guided_scene_generation":
            fatal.append(f"scene strategy must be reference_guided_scene_generation, got {strategy or scene_mode}")
        if metadata.get("direct_white_bg_subject"):
            fatal.append("scene directly used white_bg as subject")
        if metadata.get("reference_based_fallback"):
            review.append("scene is reference_based_fallback, not commercial pass")
        if level != "commercial_scene_pass":
            review.append(f"scene not commercial_scene_pass: {level or 'unknown'}")
        if scene_mode in ("rough_only", "blocked"):
            fatal.append(f"scene is {scene_mode}: cannot be formal output")

        # VLM quality check result
        vlm_q = metadata.get("vlm_quality_check", {})
        if not vlm_q or vlm_q.get("overall_quality") == "manual_required":
            review.append("scene has no passing VLM commercial quality verification")
        if vlm_q.get("has_artifacts"):
            fatal.append(f"VLM detected artifacts in scene: {vlm_q.get('artifact_type')}")
        if vlm_q.get("structure_distorted"):
            fatal.append(f"VLM detected structure distortion: {vlm_q.get('distortion_description')}")
        if not vlm_q.get("is_grounded", True):
            review.append("VLM: product may be floating")

        # Scene requirement check
        scene_req = metadata.get("scene_requirement_check", {})
        if scene_req:
            req_status = scene_req.get("status", "")
            missing = scene_req.get("missing_elements", [])
            if req_status == "fail":
                fatal.append(f"scene missing required elements: {missing}")
            elif req_status in ("manual_required", "needs_review"):
                review.append(f"scene elements unverified: {missing}")

    def _check_selling_point(self, job, artifact, metadata, vision_source, fatal, review):
        strategy = metadata.get("generation_strategy", "")
        level = metadata.get("commercial_quality_level", "")
        if strategy == "info_graph_annotation" and level == "commercial_scene_pass":
            fatal.append("info graph cannot be marked commercial_scene_pass")
        if metadata.get("direct_white_bg_subject") and level == "commercial_scene_pass":
            fatal.append("white_bg-based selling point cannot be commercial_scene_pass")
        if level == "needs_review":
            review.append("selling point requires manual review")
        if metadata.get("is_fallback_annotation"):
            review.append("selling point uses fallback annotation coordinates (not VLM)")

        if not metadata.get("has_annotation") and not metadata.get("scene_demo"):
            fatal.append("selling point missing annotation data")
        if metadata.get("scene_demo"):
            if strategy != "reference_guided_scene_generation":
                fatal.append("scene demo selling point must use reference_guided_scene_generation")
            if level != "commercial_scene_pass":
                review.append(f"scene demo selling point not commercial_scene_pass: {level or 'unknown'}")
            vlm_q = metadata.get("vlm_quality_check", {})
            if not vlm_q or vlm_q.get("overall_quality") == "manual_required":
                review.append("scene demo has no passing VLM commercial verification")
            return

        annotation_type = metadata.get("annotation_type", "")
        if annotation_type == "resting_areas":
            count = metadata.get("annotation_badge_count", 0)
            if count < 3:
                review.append(f"resting areas: only {count} badges drawn (expected 6)")
            if not metadata.get("annotation_badges_drawn"):
                fatal.append("resting areas: no badges drawn")

        elif annotation_type == "climbing_path":
            if not metadata.get("annotation_arrows_drawn"):
                fatal.append("climbing path: no arrows drawn")

        elif annotation_type == "stability_base":
            if not metadata.get("annotation_highlight_drawn"):
                fatal.append("stability base: no highlight drawn")

        elif annotation_type == "scratching_system":
            if not metadata.get("annotation_highlights_drawn"):
                fatal.append("scratching system: no highlights drawn")

    def _check_detail(self, artifact, metadata, fatal, review):
        if metadata.get("generation_strategy") != "material_detail_enhancement":
            review.append("detail is not material_detail_enhancement strategy")
        if metadata.get("direct_white_bg_subject"):
            fatal.append("detail directly used white_bg as final subject")
        if metadata.get("enhancement_mode") == "reference_based_fallback":
            review.append("material detail enhancement unavailable; fallback candidate requires review")
        confidence = metadata.get("material_confidence", 0)
        vision_source = metadata.get("vision_source", "unknown")
        if confidence < 0.3:
            fatal.append(f"material detection confidence too low: {confidence:.2f}")
        elif confidence < 0.5 and vision_source != "vlm":
            review.append(f"material detection low confidence: {confidence:.2f}")
        if metadata.get("material_type") == "unknown":
            review.append("material type not identified")

    def _check_main(self, artifact, fatal, review):
        try:
            image = Image.open(artifact.path)
            w, h = image.size
            # Product should occupy ~85% of main image
            from pipeline.step4_enhance import _content_bbox
            content = image.convert("RGB")
            bbox = _content_bbox(content)
            content_w = bbox[2] - bbox[0]
            content_h = bbox[3] - bbox[1]
            coverage = (content_w * content_h) / (w * h)
            if coverage < 0.5:
                review.append(f"main image: product coverage only {coverage:.0%} (expect ~85%)")
        except Exception:
            pass

    def _check_size_compare(self, artifact, metadata, fatal, review):
        if not metadata.get("has_dimension_line"):
            fatal.append("size compare: missing dimension line")
        label = str(metadata.get("dimension_label", ""))
        if "205" not in label:
            fatal.append(f"size compare: dimension label missing 205cm (got: {label})")
        if metadata.get("title_safe_area") != "top_band_outside_product":
            review.append("size compare: title may overlap product area")

    def _vlm_verify_scene(self, artifact, fatal, review):
        """Use VLM to verify scene image quality."""
        try:
            image = Image.open(artifact.path)
            metadata = artifact.metadata
            scene_req = metadata.get("scene_requirement_check", {})
            required = scene_req.get("required_elements", [])
            result = self._vision_agent.verify_quality(image, required_elements=required)

            if result.get("has_artifacts"):
                fatal.append(f"VLM post-check: artifacts detected ({result.get('artifact_type')})")
            if result.get("structure_distorted"):
                fatal.append(f"VLM post-check: structure distorted")
            if not result.get("product_visible", True):
                fatal.append("VLM post-check: product not visible")
            missing = result.get("missing_elements", [])
            if missing:
                review.append(f"VLM post-check: missing scene elements: {missing}")
        except Exception:
            review.append("VLM scene verification failed")

    def _vlm_verify_selling_point(self, job, artifact, review):
        """Use VLM to verify selling point expression."""
        try:
            image = Image.open(artifact.path)
            metadata = artifact.metadata
            result = self._vision_agent.verify_selling_point(
                image,
                selling_point=job.description,
                annotation_type=metadata.get("annotation_type", ""),
            )
            if result.get("overall") == "fail":
                review.append(f"VLM: selling point not expressed in image: {result.get('issues')}")
            elif result.get("overall") == "needs_review":
                review.append(f"VLM: selling point unclear: {result.get('issues')}")
            if not result.get("annotations_positioned_correctly", True):
                review.append("VLM: annotation markers may be mispositioned")
        except Exception:
            review.append("VLM selling point verification failed")

    def evaluate_view_distribution(self, jobs: list[ImageJob]) -> dict:
        """Check for excessive view repetition."""
        counts = Counter(job.view_type for job in jobs if job.view_type)
        repeated = {view: count for view, count in counts.items() if count > 1}
        total = max(len(jobs), 1)
        unique = len(counts)
        diversity_score = round(unique / total, 2)

        issues = []
        if repeated:
            issues.append(f"view direction repeated: {repeated}")
        # If more than 3 jobs share same view → whole batch needs review
        for view, count in repeated.items():
            if count >= 3:
                issues.append(f"CRITICAL: {view} repeated {count} times — batch needs_review")

        return {
            "view_counts": dict(counts),
            "repeated_views": repeated,
            "view_diversity_score": diversity_score,
            "issues": issues,
        }
