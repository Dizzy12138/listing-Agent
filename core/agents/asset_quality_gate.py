from __future__ import annotations

from PIL import Image

from pipeline.step1_extract import _has_useful_alpha
from pipeline.step3_compose import has_checkerboard_artifact


class AssetQualityGate:
    """Gate standardized product assets before downstream scene workflows."""

    def evaluate(self, transparent: Image.Image, white_bg: Image.Image) -> dict:
        issues: list[str] = []

        if transparent.mode != "RGBA":
            issues.append("transparent asset is not RGBA")
        elif not _has_useful_alpha(transparent):
            issues.append("transparent asset has no useful alpha channel")

        if has_checkerboard_artifact(transparent):
            issues.append("transparent asset contains baked checkerboard")
        if has_checkerboard_artifact(white_bg):
            issues.append("white background asset contains checkerboard or gray-white block")

        if self._has_large_baked_light_background(transparent):
            issues.append("transparent asset appears to contain baked light background residue")

        return {
            "status": "pass" if not issues else "fail",
            "issues": issues,
            "allow_scene_workflow": not any("checkerboard" in issue or "baked" in issue for issue in issues),
        }

    def _has_large_baked_light_background(self, image: Image.Image) -> bool:
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        if alpha.getextrema()[0] < 20:
            return False
        rgb = rgba.convert("RGB").resize((160, 160), Image.Resampling.BILINEAR)
        pixels = list(rgb.getdata())
        neutral_light = 0
        for r, g, b in pixels:
            mean = (r + g + b) / 3
            if mean > 190 and max(r, g, b) - min(r, g, b) < 24:
                neutral_light += 1
        return neutral_light / max(len(pixels), 1) > 0.45
