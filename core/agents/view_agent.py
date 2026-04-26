from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from core.schemas.sku import SKU
from core.schemas.job import ImageJob
from core.schemas.view import CAT_TREE_VIEW_PRESETS, ViewSpec


@dataclass
class ViewAsset:
    view_type: str
    spec: ViewSpec
    image: Image.Image
    path: Path | None = None
    generated: bool = False
    mode: str = "reuse"
    issues: list[str] | None = None


class ViewAgent:
    """
    Controls product view selection.

    The PoC keeps structure fidelity by reusing standardized subject assets. The
    Agent still assigns per-job view specs and traceable intent. A production
    adapter can replace _generate_controlled_view with model-based view synthesis.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir

    def allocate_views(self, sku: SKU, jobs: list[ImageJob]) -> list[ImageJob]:
        """Assign views across the whole plan so repeated angles are explicit."""
        used: dict[str, int] = {}
        defaults = list(sku.view_strategy.default_views)
        allocated: list[ImageJob] = []
        for job in jobs:
            view_type = job.view_type or self.resolve_view(sku, job.image_type).view_type
            if sku.view_strategy.avoid_repeated_view and used.get(view_type, 0) >= sku.view_strategy.max_same_view_count:
                replacement = next((view for view in defaults if used.get(view, 0) < sku.view_strategy.max_same_view_count), view_type)
                view_type = replacement
            used[view_type] = used.get(view_type, 0) + 1
            allocated.append(job.model_copy(update={"view_type": view_type}))
        return allocated

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
        image, issues = self._generate_controlled_view(base_subject, spec)
        return ViewAsset(
            view_type=spec.view_type,
            spec=spec,
            image=image,
            generated=spec.generation_mode not in {"reuse"},
            mode=spec.generation_mode,
            issues=issues,
        )

    def _preset(self, view_type: str) -> ViewSpec:
        return CAT_TREE_VIEW_PRESETS.get(view_type, CAT_TREE_VIEW_PRESETS["front_open"])

    def _generate_controlled_view(self, base_subject: Image.Image, spec: ViewSpec) -> tuple[Image.Image, list[str]]:
        rgba = base_subject.convert("RGBA")
        if spec.generation_mode == "mirror":
            return rgba.transpose(Image.Transpose.FLIP_LEFT_RIGHT), []
        if spec.generation_mode == "crop":
            return self._crop_detail(rgba), []
        if spec.generation_mode == "model_synthesis":
            # Explicit capability boundary: real view synthesis is not enabled
            # in the PoC because it can hallucinate product structure.
            return rgba, ["model_synthesis_not_implemented"]
        return rgba, []

    def _crop_detail(self, image: Image.Image) -> Image.Image:
        w, h = image.size
        box = (int(w * 0.18), int(h * 0.12), int(w * 0.82), int(h * 0.88))
        crop = image.crop(box)
        canvas = Image.new("RGBA", image.size, (255, 255, 255, 0))
        crop.thumbnail((int(w * 0.9), int(h * 0.9)), Image.Resampling.LANCZOS)
        canvas.paste(crop, ((w - crop.width) // 2, (h - crop.height) // 2), crop)
        return canvas
