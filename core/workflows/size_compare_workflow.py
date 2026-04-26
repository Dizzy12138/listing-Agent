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
        product = context.base_assets["white_bg"].copy().convert("RGB")
        content = product.crop(_content_bbox(product))
        out = _fit_image(content, (940, 1080), background=(255, 255, 255))
        canvas = Image.new("RGB", (1500, 1500), "#ffffff")
        canvas.paste(out, (350, 260))
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(58, bold=True)
        body_font = _load_font(34)
        label_font = _load_font(48, bold=True)

        # Header stays outside the product safe area.
        draw.text((95, 86), "205cm XXL Cat Tree Tower", font=title_font, fill="#172033")
        draw.text((98, 158), "Full front view with clear height reference", font=body_font, fill="#536173")

        # Vertical dimension line placed beside the product, never on top of it.
        x = 265
        y1, y2 = 285, 1308
        draw.line((x, y1, x, y2), fill="#2563eb", width=8)
        draw.line((x - 42, y1, x + 42, y1), fill="#2563eb", width=8)
        draw.line((x - 42, y2, x + 42, y2), fill="#2563eb", width=8)
        draw.polygon([(x, y1 - 26), (x - 18, y1 + 8), (x + 18, y1 + 8)], fill="#2563eb")
        draw.polygon([(x, y2 + 26), (x - 18, y2 - 8), (x + 18, y2 - 8)], fill="#2563eb")
        draw.rounded_rectangle((90, 720, 235, 835), radius=18, fill="#eff6ff", outline="#2563eb", width=3)
        draw.text((113, 748), "205", font=label_font, fill="#1d4ed8")
        draw.text((130, 798), "cm", font=body_font, fill="#1d4ed8")

        draw.rounded_rectangle((1060, 1230, 1405, 1330), radius=18, fill="#f8fafc", outline="#d8dee6", width=2)
        draw.text((1090, 1260), "Complete structure shown", font=body_font, fill="#475569")
        return canvas
