from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from core.schemas.sku import SKU
from core.schemas.view import CAT_TREE_VIEW_PRESETS, ViewSpec


@dataclass
class ViewAsset:
    view_type: str
    spec: ViewSpec
    image: Image.Image
    path: Path | None = None
    generated: bool = False


class ViewAgent:
    """
    Controls product view selection.

    The PoC keeps structure fidelity by reusing standardized subject assets. The
    Agent still assigns per-job view specs and traceable intent. A production
    adapter can replace _generate_controlled_view with model-based view synthesis.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def resolve_view(self, sku: SKU, image_type: str, requested_view: str | None = None) -> ViewSpec:
        if requested_view:
            return self._preset(requested_view)
        if image_type in {"scene_main", "main_scene"}:
            return self._preset("low_angle_hero")
        if image_type in {"scene_lifestyle", "lifestyle"}:
            return self._preset("right_45")
        if image_type in {"selling_point", "detail", "feature_detail_1", "feature_detail_2"}:
            return self._preset("detail_closeup")
        if image_type in {"size_compare"}:
            return self._preset("front_open")
        return self._preset("front_open")

    def get_or_generate_view(
        self,
        sku: SKU,
        base_subject: Image.Image,
        image_type: str,
        requested_view: str | None = None,
    ) -> ViewAsset:
        spec = self.resolve_view(sku, image_type, requested_view)
        image = self._generate_controlled_view(base_subject, spec)
        return ViewAsset(view_type=spec.view_type, spec=spec, image=image, generated=spec.view_type != "front_open")

    def _preset(self, view_type: str) -> ViewSpec:
        return CAT_TREE_VIEW_PRESETS.get(view_type, CAT_TREE_VIEW_PRESETS["front_open"])

    def _generate_controlled_view(self, base_subject: Image.Image, spec: ViewSpec) -> Image.Image:
        # Conservative PoC behavior: never invent structure in deterministic mode.
        # For left/right views, mirroring creates a visibly different direction
        # while preserving all visible product geometry.
        rgba = base_subject.convert("RGBA")
        if spec.view_type == "right_45":
            return rgba.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        return rgba
