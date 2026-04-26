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
        if not image_artifacts:
            fatal_issues.append("no output image artifact")

        for artifact in image_artifacts:
            view_issues = artifact.metadata.get("view_issues", [])
            if "model_synthesis_not_implemented" in view_issues:
                review_issues.append("requested view requires model synthesis but not implemented")
            try:
                image = Image.open(artifact.path)
            except OSError:
                fatal_issues.append(f"cannot open artifact: {artifact.name}")
                continue
            w, h = image.size
            if w < 1000 or h < 1000:
                review_issues.append(f"image too small: {artifact.name} {w}x{h}")
            if artifact.type == "scene" and has_checkerboard_artifact(image):
                fatal_issues.append(f"checkerboard or white block artifact: {artifact.name}")

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
