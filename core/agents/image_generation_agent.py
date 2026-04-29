"""
ImageGenerationAgent — multi-candidate generation from creative briefs.

Key rules:
- hero_scene / lifestyle_scene: white_bg is reference ONLY, not compositing base
- Uses whole-image generation (not paste/composite)
- Records generation_strategy honestly
- Generates N candidates per brief, tracks each with CandidateRecord
"""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from rich.console import Console

from core.schemas.candidate import CandidateRecord
from core.schemas.creative_brief import CreativeBrief, SKUBrief

console = Console()


def _brief_to_prompt(brief: CreativeBrief, sku_brief: SKUBrief) -> str:
    """Convert a CreativeBrief + SKUBrief into a generation prompt."""
    parts = []

    # SKU identity
    identity_str = ", ".join(sku_brief.core_identity[:8])
    parts.append(f"Product: {sku_brief.product_type}. Key features: {identity_str}.")

    # Visual goal
    if brief.visual_goal:
        parts.append(f"Goal: {brief.visual_goal}.")

    # Scene
    if brief.scene:
        parts.append(f"Scene: {brief.scene}.")

    # Composition
    if brief.composition:
        parts.append(f"Composition: {brief.composition}.")

    # Actors
    if brief.actors:
        parts.append(f"Include: {', '.join(brief.actors)}.")

    # Lighting
    if brief.lighting:
        parts.append(f"Lighting: {brief.lighting}.")

    # Style
    if brief.style:
        parts.append(f"Style: {brief.style}.")

    # Material focus
    if brief.material_focus:
        parts.append(f"Focus on: {brief.material_focus} material in extreme closeup detail.")

    # Negative
    if brief.negative:
        parts.append(f"AVOID: {', '.join(brief.negative)}.")

    # Commercial quality
    parts.append("Professional commercial e-commerce photography. Ultra high quality. 8K detail.")

    return " ".join(parts)


class ImageGenerationAgent:
    """Generate multiple candidates from creative briefs."""

    def __init__(self, model: str = "gpt-image-2", candidates_per_brief: int = 4):
        self.model = model
        self.candidates_per_brief = candidates_per_brief

    def generate_candidates(
        self,
        brief: CreativeBrief,
        sku_brief: SKUBrief,
        original_image: Image.Image | None = None,
        white_bg_image: Image.Image | None = None,
        output_dir: Path | None = None,
    ) -> list[CandidateRecord]:
        """Generate N candidate images for a single creative brief."""
        console.print(f"  [ImageGen] {brief.image_type} × {self.candidates_per_brief} candidates")

        prompt = _brief_to_prompt(brief, sku_brief)
        candidates = []

        # Determine strategy
        is_scene = brief.image_type in ("hero_scene", "lifestyle_scene")
        is_material = brief.image_type == "material_detail"

        for i in range(self.candidates_per_brief):
            brief_key = self._candidate_brief_key(brief, prompt)
            cid = f"{brief.image_type}_{brief_key}_{i+1:02d}"

            if is_scene:
                record = self._generate_scene_candidate(cid, brief, prompt, original_image, white_bg_image)
            elif is_material:
                record = self._generate_material_candidate(cid, brief, prompt, original_image)
            else:
                record = self._generate_generic_candidate(cid, brief, prompt)

            # Save image if output_dir provided
            if output_dir and record.status in ("generated", "text_only_candidate") and record.image_path == "":
                # image_path set by generation methods when they have the image object
                pass

            candidates.append(record)

        success = sum(1 for c in candidates if c.status in ("generated", "text_only_candidate", "fallback"))
        console.print(f"    → {success}/{self.candidates_per_brief} candidates generated")
        return candidates

    def _generate_scene_candidate(
        self, cid: str, brief: CreativeBrief, prompt: str,
        original: Image.Image | None, white_bg: Image.Image | None,
    ) -> CandidateRecord:
        """Scene candidates: reference-guided whole-image generation preferred."""

        # Strategy 1: Reference-guided edit (original as reference)
        if original:
            try:
                result = self._edit_with_reference(original, prompt)
                if result:
                    record = CandidateRecord(
                        candidate_id=cid,
                        image_type=brief.image_type,
                        generation_strategy="reference_guided_whole_image_generation",
                        reference_assets_used=["original"],
                        sku_consistency_level=brief.sku_consistency_level,
                        prompt=prompt,
                        status="generated",
                    )
                    record._image = result  # type: ignore[attr-defined]
                    return record
            except Exception as exc:
                console.print(f"    ⚠️ reference edit failed: {exc}", style="yellow")

        # Strategy 2: Pure text generation (no reference available/failed)
        try:
            result = self._text_generate(prompt)
            if result:
                record = CandidateRecord(
                    candidate_id=cid,
                    image_type=brief.image_type,
                    generation_strategy="text_only_generation",
                    reference_assets_used=[],
                    sku_consistency_level=brief.sku_consistency_level,
                    prompt=prompt,
                    status="text_only_candidate",
                    issues=["reference_unavailable: generated without product reference image"],
                )
                record._image = result  # type: ignore[attr-defined]
                return record
        except Exception as exc:
            console.print(f"    ⚠️ text generation failed: {exc}", style="yellow")

        fallback = self._local_scene_fallback(original, brief, prompt)
        record = CandidateRecord(
            candidate_id=cid,
            image_type=brief.image_type,
            generation_strategy="local_reference_fallback",
            reference_assets_used=["original"] if original else [],
            sku_consistency_level=brief.sku_consistency_level,
            prompt=prompt,
            status="fallback",
            issues=[
                "model_unavailable_local_fallback",
                "manual_review_required",
                "not_commercial_scene_pass",
            ],
        )
        record._image = fallback
        return record

    def _generate_material_candidate(
        self, cid: str, brief: CreativeBrief, prompt: str, original: Image.Image | None,
    ) -> CandidateRecord:
        """Material candidates: crop from original + enhance, or generate macro."""

        # Strategy 1: Crop-and-enhance from original
        if original and brief.material_focus:
            try:
                crop = self._extract_material_crop(original, brief.material_focus)
                if crop:
                    enhanced = self._enhance_crop(crop, prompt)
                    if enhanced:
                        record = CandidateRecord(
                            candidate_id=cid,
                            image_type=brief.image_type,
                            generation_strategy="crop_enhance",
                            reference_assets_used=["original"],
                            sku_consistency_level=brief.sku_consistency_level,
                            prompt=prompt,
                            status="generated",
                        )
                        record._image = enhanced  # type: ignore[attr-defined]
                        return record
            except Exception:
                pass

        # Strategy 2: Generate macro from text
        try:
            result = self._text_generate(prompt, size="1024x1024")
            if result:
                record = CandidateRecord(
                    candidate_id=cid,
                    image_type=brief.image_type,
                    generation_strategy="text_only_generation",
                    reference_assets_used=[],
                    sku_consistency_level=brief.sku_consistency_level,
                    prompt=prompt,
                    status="text_only_candidate",
                    issues=["material closeup generated without original crop reference"],
                )
                record._image = result  # type: ignore[attr-defined]
                return record
        except Exception as exc:
            pass

        fallback = self._local_material_fallback(original, brief)
        record = CandidateRecord(
            candidate_id=cid,
            image_type=brief.image_type,
            generation_strategy="local_material_reference_fallback",
            reference_assets_used=["original"] if original else [],
            sku_consistency_level=brief.sku_consistency_level,
            prompt=prompt,
            status="fallback",
            issues=[
                "model_unavailable_local_fallback",
                "manual_review_required",
                "material_enhancement_not_performed",
            ],
        )
        record._image = fallback
        return record

    def _generate_generic_candidate(self, cid: str, brief: CreativeBrief, prompt: str) -> CandidateRecord:
        try:
            result = self._text_generate(prompt)
            if result:
                record = CandidateRecord(
                    candidate_id=cid, image_type=brief.image_type,
                    generation_strategy="text_only_generation",
                    prompt=prompt, status="text_only_candidate",
                )
                record._image = result  # type: ignore[attr-defined]
                return record
        except Exception:
            pass
        fallback = self._local_generic_fallback(brief, prompt)
        record = CandidateRecord(
            candidate_id=cid,
            image_type=brief.image_type,
            generation_strategy="local_reference_fallback",
            prompt=prompt,
            status="fallback",
            issues=["model_unavailable_local_fallback", "manual_review_required"],
        )
        record._image = fallback
        return record

    # ---- Model calls ----

    def _edit_with_reference(self, reference: Image.Image, prompt: str) -> Image.Image | None:
        from models.gpt_image import edit_image
        results = edit_image(reference, prompt=prompt, model=self.model, size="1536x1024", quality="high")
        return results[0].convert("RGB") if results else None

    def _text_generate(self, prompt: str, size: str = "1536x1024") -> Image.Image | None:
        from models.gpt_image import generate_image
        results = generate_image(prompt, model=self.model, size=size, quality="high", n=1)
        return results[0].convert("RGB") if results else None

    def _enhance_crop(self, crop: Image.Image, prompt: str) -> Image.Image | None:
        from models.gpt_image import edit_image
        enhance_prompt = (
            f"{prompt} "
            "Enhance this material closeup to look like professional macro photography. "
            "Improve clarity, add studio lighting, increase detail visibility. "
            "Keep the exact same material and color. Make it look premium and high-quality."
        )
        results = edit_image(crop, prompt=enhance_prompt, model=self.model, size="1024x1024", quality="high")
        return results[0].convert("RGB") if results else None

    def _extract_material_crop(self, original: Image.Image, material_focus: str) -> Image.Image | None:
        """Extract a rough material region from the original image."""
        w, h = original.size

        # Heuristic regions based on material type
        regions = {
            "plush_fabric": (int(w*0.3), int(h*0.3), int(w*0.7), int(h*0.5)),
            "sisal_rope": (int(w*0.2), int(h*0.2), int(w*0.4), int(h*0.6)),
            "board_material": (int(w*0.2), int(h*0.6), int(w*0.6), int(h*0.8)),
            "board_ramp": (int(w*0.2), int(h*0.6), int(w*0.6), int(h*0.8)),
        }
        region = regions.get(material_focus, (int(w*0.25), int(h*0.25), int(w*0.75), int(h*0.75)))
        crop = original.crop(region)
        # Only use if crop is meaningful (not too small)
        if crop.size[0] >= 200 and crop.size[1] >= 200:
            return crop.resize((1024, 1024), Image.LANCZOS)
        return None

    # ---- Local fallback renderers ----

    def _local_scene_fallback(
        self,
        original: Image.Image | None,
        brief: CreativeBrief,
        prompt: str,
    ) -> Image.Image:
        """Create a reviewable scene placeholder when model generation is unavailable."""
        canvas = Image.new("RGB", (1536, 1024), "#f6f1ea")
        draw = ImageDraw.Draw(canvas)
        font_title = self._font(46)
        font_body = self._font(28)
        font_small = self._font(22)

        # Simple room-like background so reviewers can distinguish this from a blank failure.
        draw.rectangle((0, 0, 1536, 620), fill="#eee3d5")
        draw.rectangle((0, 620, 1536, 1024), fill="#d8c7b4")
        draw.rectangle((1040, 120, 1440, 560), fill="#dfeaf0", outline="#aebdc7", width=8)
        draw.line((1040, 340, 1440, 340), fill="#aebdc7", width=4)
        draw.line((1240, 120, 1240, 560), fill="#aebdc7", width=4)

        if original:
            product = original.copy().convert("RGB")
            product.thumbnail((650, 840), Image.LANCZOS)
            x = 450 - product.width // 2
            y = 860 - product.height
            shadow = Image.new("RGBA", (product.width + 120, 60), (0, 0, 0, 0))
            sdraw = ImageDraw.Draw(shadow)
            sdraw.ellipse((20, 10, product.width + 100, 54), fill=(0, 0, 0, 70))
            shadow = shadow.filter(ImageFilter.GaussianBlur(18))
            canvas.paste(shadow.convert("RGB"), (x - 60, 842))
            canvas.paste(product, (x, y))

        draw.rounded_rectangle((900, 670, 1470, 900), radius=22, fill="#ffffff", outline="#d7dde7", width=3)
        draw.text((940, 708), "Review fallback", fill="#172033", font=font_title)
        lines = [
            brief.visual_goal[:48] or brief.image_type,
            "Model generation/editing was unavailable.",
            "Use as a reference candidate only.",
        ]
        for idx, line in enumerate(lines):
            draw.text((944, 778 + idx * 38), line, fill="#536173", font=font_body if idx == 0 else font_small)
        draw.text((88, 70), "REFERENCE-GUIDED SCENE TARGET", fill="#172033", font=font_title)
        draw.text((90, 134), prompt[:92], fill="#536173", font=font_small)
        return canvas

    def _local_material_fallback(self, original: Image.Image | None, brief: CreativeBrief) -> Image.Image:
        if original:
            crop = self._extract_material_crop(original, brief.material_focus or "")
            if crop:
                image = crop.filter(ImageFilter.SHARPEN).convert("RGB")
            else:
                image = original.copy().convert("RGB")
                image.thumbnail((1024, 1024), Image.LANCZOS)
                bg = Image.new("RGB", (1024, 1024), "#f7f8fb")
                bg.paste(image, ((1024 - image.width) // 2, (1024 - image.height) // 2))
                image = bg
        else:
            image = Image.new("RGB", (1024, 1024), "#f7f8fb")

        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 1024, 96), fill="#ffffff")
        draw.text(
            (38, 28),
            f"Material reference: {brief.material_focus or 'detail'}",
            fill="#172033",
            font=self._font(34),
        )
        draw.text((40, 76), "needs review: model enhancement unavailable", fill="#8a5960", font=self._font(18))
        return image

    def _local_generic_fallback(self, brief: CreativeBrief, prompt: str) -> Image.Image:
        image = Image.new("RGB", (1536, 1024), "#f7f8fb")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((120, 160, 1416, 864), radius=28, fill="#ffffff", outline="#d7dde7", width=4)
        draw.text((180, 230), brief.image_type, fill="#172033", font=self._font(54))
        draw.text((182, 310), "Local fallback candidate - manual review required", fill="#8a5960", font=self._font(30))
        draw.text((182, 380), prompt[:160], fill="#536173", font=self._font(26))
        return image

    def _font(self, size: int) -> ImageFont.ImageFont:
        for path in (
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
        return ImageFont.load_default()

    def _candidate_brief_key(self, brief: CreativeBrief, prompt: str) -> str:
        base = brief.material_focus or "main"
        digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:6]
        return f"{base}_{digest}"

    def save_candidates(
        self, candidates: list[CandidateRecord], output_dir: Path, image_type: str,
    ) -> list[CandidateRecord]:
        """Save candidate images to disk and update image_path."""
        type_dir = output_dir / image_type
        type_dir.mkdir(parents=True, exist_ok=True)

        for cand in candidates:
            img = getattr(cand, '_image', None)
            if img is None:
                continue
            filename = f"{cand.candidate_id}.png"
            path = type_dir / filename
            img.save(path, "PNG")
            cand.image_path = str(path)
            # Save metadata
            meta_path = type_dir / f"{cand.candidate_id}.json"
            meta_path.write_text(cand.model_dump_json(indent=2), encoding="utf-8")

        return candidates
