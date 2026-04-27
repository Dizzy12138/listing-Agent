"""
SizeCompareWorkflow — improved layout.

Key rules:
- Title and product are in separate zones — title never overlaps product.
- Real 205cm vertical dimension line with arrow caps and proper spacing.
- Product is fully visible, unobstructed.
"""
from __future__ import annotations

from PIL import Image
from PIL import ImageDraw

from pipeline.step4_enhance import _content_bbox
from pipeline.step4_enhance import _fit_image
from pipeline.step4_enhance import _load_font

from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("size_compare")
class SizeCompareWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        with context.trace.timed("workflow.size_compare"):
            canvas = self._render(context)
            artifact = self.save_image(canvas, context, "size_compare", "size_compare")
            artifact.metadata.update({
                "generation_strategy": "info_graph_annotation",
                "commercial_quality_level": "info_graph_pass",
                "reference_assets_used": ["white_bg", "product_analysis"],
                "direct_white_bg_subject": True,
                "has_dimension_line": True,
                "dimension_label": "205cm",
                "title_safe_area": "top_band_outside_product",
            })
            context.trace.add(
                step="workflow.size_compare.output",
                status="success",
                input={"job_id": context.job.job_id, "view_type": context.job.view_type or "front_open"},
                output_artifact=artifact.path,
            )
            return self.ok_result(context, [artifact], context.trace.records[-2:])

    def _render(self, context: WorkflowContext) -> Image.Image:
        canvas = Image.new("RGB", (1500, 1500), "#ffffff")
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(54, bold=True)
        body_font = _load_font(32)
        dim_label_font = _load_font(52, bold=True)
        dim_unit_font = _load_font(30)

        # ===== TITLE ZONE: top band (0-200px), completely separate from product =====
        draw.rectangle((0, 0, 1500, 200), fill="#f8fafc")
        draw.line((0, 200, 1500, 200), fill="#e2e8f0", width=2)
        draw.text((80, 50), "205cm XXL Cat Tree Tower", font=title_font, fill="#172033")
        draw.text((82, 120), "Full front view with real height reference", font=body_font, fill="#536173")

        # ===== PRODUCT ZONE: 220-1380px, centered =====
        product = context.base_assets["white_bg"].copy().convert("RGB")
        content = product.crop(_content_bbox(product))
        # Product fits in a zone that leaves room for the dimension line on the left
        product_zone_left = 380
        product_zone_top = 230
        product_zone_w = 950
        product_zone_h = 1130
        out = _fit_image(content, (product_zone_w, product_zone_h), background=(255, 255, 255))
        canvas.paste(out, (product_zone_left, product_zone_top))

        # ===== DIMENSION LINE: left side, vertically aligned with product =====
        dim_x = 280  # x position of the dimension line
        dim_top = product_zone_top + 20
        dim_bottom = product_zone_top + product_zone_h - 20

        # Main vertical line
        draw.line((dim_x, dim_top, dim_x, dim_bottom), fill="#2563eb", width=6)

        # Top arrow cap + horizontal tick
        draw.line((dim_x - 36, dim_top, dim_x + 36, dim_top), fill="#2563eb", width=6)
        draw.polygon([
            (dim_x, dim_top - 24),
            (dim_x - 16, dim_top + 6),
            (dim_x + 16, dim_top + 6),
        ], fill="#2563eb")

        # Bottom arrow cap + horizontal tick
        draw.line((dim_x - 36, dim_bottom, dim_x + 36, dim_bottom), fill="#2563eb", width=6)
        draw.polygon([
            (dim_x, dim_bottom + 24),
            (dim_x - 16, dim_bottom - 6),
            (dim_x + 16, dim_bottom - 6),
        ], fill="#2563eb")

        # Dimension label box centered on the line
        label_center_y = (dim_top + dim_bottom) // 2
        label_box = (dim_x - 80, label_center_y - 55, dim_x + 80, label_center_y + 55)
        draw.rounded_rectangle(label_box, radius=16, fill="#eff6ff", outline="#2563eb", width=3)
        draw.text((dim_x - 52, label_center_y - 42), "205", font=dim_label_font, fill="#1d4ed8")
        draw.text((dim_x - 22, label_center_y + 14), "cm", font=dim_unit_font, fill="#1d4ed8")

        # ===== BOTTOM INFO BAR =====
        draw.rectangle((0, 1400, 1500, 1500), fill="#f8fafc")
        draw.line((0, 1400, 1500, 1400), fill="#e2e8f0", width=2)
        draw.rounded_rectangle((80, 1420, 450, 1480), radius=14, fill="#eff6ff", outline="#2563eb", width=2)
        draw.text((100, 1434), "Full structure visible", font=body_font, fill="#1d4ed8")
        draw.rounded_rectangle((500, 1420, 850, 1480), radius=14, fill="#f0fdf4", outline="#16a34a", width=2)
        draw.text((520, 1434), "Real height: 205cm", font=body_font, fill="#166534")

        return canvas
