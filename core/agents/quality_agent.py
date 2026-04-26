from __future__ import annotations

from collections import Counter
from pathlib import Path

from PIL import Image

from core.schemas.job import Artifact, ImageJob, QualityReport
from pipeline.step3_compose import has_checkerboard_artifact


class QualityAgent:
    def evaluate_artifacts(self, job: ImageJob, artifacts: list[Artifact]) -> QualityReport:
        issues: list[str] = []
        image_artifacts = [a for a in artifacts if Path(a.path).suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}]
        if not image_artifacts:
            issues.append("no output image artifact")

        for artifact in image_artifacts:
            try:
                image = Image.open(artifact.path)
            except OSError:
                issues.append(f"cannot open artifact: {artifact.name}")
                continue
            w, h = image.size
            if w < 1000 or h < 1000:
                issues.append(f"image too small: {artifact.name} {w}x{h}")
            if artifact.type == "scene" and has_checkerboard_artifact(image):
                issues.append(f"checkerboard or white block artifact: {artifact.name}")

        score = max(0, 90 - len(issues) * 18)
        return QualityReport(
            score=score,
            status="pass" if score >= 80 else "needs_review",
            issues=issues,
            suggestion="人工审核通过后入库" if score >= 80 else "修复问题后重试",
        )

    def evaluate_view_distribution(self, jobs: list[ImageJob]) -> dict:
        counts = Counter(job.view_type or "auto" for job in jobs)
        repeated = {view: count for view, count in counts.items() if count > 1}
        total = max(len(jobs), 1)
        unique = len(counts)
        diversity_score = round(unique / total, 2)
        return {
            "view_counts": dict(counts),
            "repeated_views": repeated,
            "view_diversity_score": diversity_score,
            "issues": [f"View repeated: {view} x {count}" for view, count in repeated.items()],
        }
