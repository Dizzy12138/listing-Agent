"""
ViewReconstructionAgent — real view candidate generation.

Uses image generation/editing models to synthesize view candidates
(low_angle_hero, left_45, right_45) from the original product image.

Does NOT:
- Mirror/flip and pretend it's a different angle.
- Use the original front view and claim it's low_angle.

When reliable generation is not possible, explicitly blocks.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PIL import Image
from rich.console import Console

from models.gpt_image import edit_image

console = Console()


@dataclass
class ViewCandidate:
    """A candidate view image with quality metadata."""
    view_type: str
    image: Image.Image
    method: str  # "generated" | "edit_reconstruction" | "blocked"
    confidence: float  # 0-1
    issues: list[str] = field(default_factory=list)
    verification: dict = field(default_factory=dict)


VIEW_RECONSTRUCTION_PROMPTS = {
    "low_angle_hero": (
        "Reconstruct this cat tree tower as viewed from a very low angle, looking upward from floor level. "
        "The base of the cat tree should be very close to the viewer, appearing large. "
        "The upper platforms should recede upward, creating a dramatic sense of height. "
        "Maintain the exact same product structure, color, material, platform count and proportions. "
        "Keep clean white background. Professional e-commerce product photography. "
        "The perspective should make the cat tree look impressively tall and massive."
    ),
    "left_45": (
        "Reconstruct this cat tree tower as viewed from a 45-degree angle to the left. "
        "Show the left side and partial front of the cat tree. "
        "Reveal some side details that are not visible from the front view. "
        "Maintain the exact same product structure, color, material, platform count and proportions. "
        "Keep clean white background. Professional e-commerce product photography."
    ),
    "right_45": (
        "Reconstruct this cat tree tower as viewed from a 45-degree angle to the right. "
        "Show the right side and partial front of the cat tree. "
        "Reveal some side details that are not visible from the front view. "
        "Maintain the exact same product structure, color, material, platform count and proportions. "
        "Keep clean white background. Professional e-commerce product photography."
    ),
    "detail_closeup": (
        "Create a close-up detail view of the key structural elements of this cat tree. "
        "Focus on material quality, craftsmanship, and texture details. "
        "Show the sisal rope wrapping, plush fabric texture, and platform construction. "
        "Maintain exact colors and materials. Studio macro photography lighting."
    ),
}


class ViewReconstructionAgent:
    """Generate real view candidates from the original product image."""

    def __init__(self, model: str = "gpt-image-2", n_candidates: int = 2):
        self.model = model
        self.n_candidates = n_candidates

    def generate_view(
        self,
        original_image: Image.Image,
        product_analysis: dict[str, Any],
        target_view: str,
        vision_agent=None,
    ) -> list[ViewCandidate]:
        """
        Generate view candidates for the target view type.

        Parameters
        ----------
        original_image : Image.Image
            The original product image (white bg).
        product_analysis : dict
            Product structural analysis from ProductVisionAgent.
        target_view : str
            Target view type (low_angle_hero, left_45, right_45, detail_closeup).
        vision_agent : ProductVisionAgent, optional
            For post-generation structural verification.

        Returns list of ViewCandidates, possibly empty if generation fails.
        """
        prompt = VIEW_RECONSTRUCTION_PROMPTS.get(target_view)
        if not prompt:
            console.print(f"  ⚠️ 未知视角: {target_view}，blocked", style="yellow")
            return [ViewCandidate(
                view_type=target_view, image=original_image,
                method="blocked", confidence=0.0,
                issues=[f"unknown_view_type: {target_view}"],
            )]

        console.print(f"  [ViewReconstruction] 生成 {target_view} 候选 (model={self.model})")

        candidates = []
        try:
            results = edit_image(
                original_image,
                prompt=prompt,
                model=self.model,
                size="1024x1024",
                quality="high",
            )
        except Exception as exc:
            console.print(f"  ⚠️ 视角重建失败: {exc}", style="yellow")
            return [ViewCandidate(
                view_type=target_view, image=original_image,
                method="blocked", confidence=0.0,
                issues=[f"view_reconstruction_failed: {exc}"],
            )]

        if not results:
            return [ViewCandidate(
                view_type=target_view, image=original_image,
                method="blocked", confidence=0.0,
                issues=["view_reconstruction_returned_no_image"],
            )]

        for i, result_img in enumerate(results):
            img = result_img.convert("RGB")
            confidence = 0.6  # base confidence for edit-based reconstruction

            # Post-generation verification with VLM
            verification = {}
            if vision_agent:
                try:
                    verification = vision_agent.verify_quality(img, required_elements=[])
                    if verification.get("structure_distorted"):
                        confidence *= 0.3
                    if verification.get("has_artifacts"):
                        confidence *= 0.4
                    if not verification.get("product_visible", True):
                        confidence = 0.0
                except Exception:
                    pass

            candidates.append(ViewCandidate(
                view_type=target_view,
                image=img,
                method="edit_reconstruction",
                confidence=confidence,
                issues=[],
                verification=verification,
            ))

        # Sort by confidence
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        return candidates

    def select_best_candidate(self, candidates: list[ViewCandidate], min_confidence: float = 0.3) -> ViewCandidate | None:
        """Select the best candidate above the confidence threshold."""
        for c in candidates:
            if c.method != "blocked" and c.confidence >= min_confidence:
                return c
        return None

    def save_candidates(
        self,
        candidates: list[ViewCandidate],
        output_dir: Path,
        image_index: int,
    ) -> list[dict]:
        """Save all candidates and return metadata."""
        saved = []
        for i, c in enumerate(candidates):
            filename = f"img{image_index:02d}_view_{c.view_type}_candidate_{i+1}.png"
            path = output_dir / "views" / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            c.image.save(path, "PNG")
            saved.append({
                "filename": filename,
                "path": str(path),
                "view_type": c.view_type,
                "method": c.method,
                "confidence": c.confidence,
                "issues": c.issues,
                "verification": c.verification,
            })
        return saved
