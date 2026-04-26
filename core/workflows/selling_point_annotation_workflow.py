from __future__ import annotations

import math

from PIL import Image
from PIL import ImageDraw

from pipeline.step4_enhance import _content_bbox
from pipeline.step4_enhance import _fit_image
from pipeline.step4_enhance import _load_font
from pipeline.step4_enhance import _wrap_text

from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


def _classify_annotation(description: str) -> str:
    text = description.lower()
    if any(k in text for k in ["休息", "平台", "吊床", "窝", "rest", "platform", "hammock"]):
        return "resting_areas"
    if any(k in text for k in ["动线", "攀爬", "路线", "path", "climb", "route"]):
        return "climbing_path"
    if any(k in text for k in ["底板", "稳定", "base", "stability", "stable"]):
        return "stability_base"
    if any(k in text for k in ["抓挠", "剑麻", "猫抓", "scratch", "sisal", "rope"]):
        return "scratching_system"
    return "general_annotation"


@register_workflow("selling_point_annotation")
class SellingPointAnnotationWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        annotation_type = _classify_annotation(context.job.description)
        with context.trace.timed("workflow.selling_point_annotation"):
            image = self._render(context, annotation_type)
            artifact = self.save_image(image, context, context.job.image_type, "selling_point")
            artifact.metadata.update({
                "annotation_type": annotation_type,
                "has_annotation": True,
                "title": self._title(context.job.description, annotation_type),
            })
            context.trace.add(
                step="workflow.selling_point_annotation.output",
                status="success",
                input={
                    "job_id": context.job.job_id,
                    "description": context.job.description,
                    "annotation_type": annotation_type,
                },
                output_artifact=artifact.path,
            )
            return self.ok_result(context, [artifact], context.trace.records[-2:])

    def _render(self, context: WorkflowContext, annotation_type: str) -> Image.Image:
        width, height = 1500, 1500
        canvas = Image.new("RGB", (width, height), "#f6f8fb")
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(60, bold=True)
        body_font = _load_font(32)
        label_font = _load_font(34, bold=True)

        draw.rounded_rectangle((58, 58, 1442, 1442), radius=24, fill="#ffffff", outline="#d7dee8", width=3)
        title = self._title(context.job.description, annotation_type)
        y = 92
        for line in _wrap_text(draw, title, title_font, 1100, 2):
            draw.text((104, y), line, font=title_font, fill="#172033")
            y += 72
        subtitle = self._subtitle(annotation_type)
        draw.text((106, y + 6), subtitle, font=body_font, fill="#536173")

        product_panel = (130, 245, 1370, 1365)
        draw.rounded_rectangle(product_panel, radius=18, fill="#f8fafc", outline="#e2e8f0", width=2)

        product = context.base_assets["white_bg"].convert("RGB")
        content = product.crop(_content_bbox(product))
        fitted = _fit_image(content, (1050, 1020), background=(248, 250, 252))
        canvas.paste(fitted, (225, 300))

        box = (225, 300, 1275, 1320)
        if annotation_type == "resting_areas":
            self._draw_resting_labels(draw, box, label_font)
        elif annotation_type == "climbing_path":
            self._draw_climbing_path(draw, box)
        elif annotation_type == "stability_base":
            self._draw_base_highlight(draw, box, label_font)
        elif annotation_type == "scratching_system":
            self._draw_scratching_highlights(draw, box, label_font)
        else:
            self._draw_general_highlight(draw, box, label_font)

        return canvas

    def _title(self, description: str, annotation_type: str) -> str:
        if annotation_type == "resting_areas":
            return "6 Resting Areas for Multi-Cat Use"
        if annotation_type == "climbing_path":
            return "Clear Multi-Level Climbing Path"
        if annotation_type == "stability_base":
            return "Wide Double Base for Stability"
        if annotation_type == "scratching_system":
            return "Multiple Sisal Scratching Points"
        return description

    def _subtitle(self, annotation_type: str) -> str:
        subtitles = {
            "resting_areas": "Numbered zones make each platform and resting space easy to read.",
            "climbing_path": "The route line shows how cats move through the tower.",
            "stability_base": "Bottom support is emphasized for large cats and multi-cat households.",
            "scratching_system": "Highlighted posts and boards show the main scratching surfaces.",
        }
        return subtitles.get(annotation_type, "Annotated structure view for ecommerce detail pages.")

    def _draw_badge(self, draw: ImageDraw.ImageDraw, center: tuple[int, int], text: str, font):
        x, y = center
        draw.ellipse((x - 28, y - 28, x + 28, y + 28), fill="#2563eb", outline="#ffffff", width=4)
        tw = draw.textlength(text, font=font)
        draw.text((x - tw / 2, y - 20), text, font=font, fill="#ffffff")

    def _draw_resting_labels(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font):
        x1, y1, x2, y2 = box
        points = [
            (x1 + 580, y1 + 72),
            (x1 + 365, y1 + 210),
            (x1 + 690, y1 + 325),
            (x1 + 475, y1 + 505),
            (x1 + 700, y1 + 655),
            (x1 + 525, y1 + 820),
        ]
        for idx, point in enumerate(points, 1):
            self._draw_badge(draw, point, str(idx), font)

    def _draw_climbing_path(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int]):
        x1, y1, x2, y2 = box
        points = [
            (x1 + 390, y1 + 860),
            (x1 + 560, y1 + 710),
            (x1 + 455, y1 + 545),
            (x1 + 675, y1 + 390),
            (x1 + 555, y1 + 210),
            (x1 + 735, y1 + 90),
        ]
        draw.line(points, fill="#f97316", width=12, joint="curve")
        for start, end in zip(points, points[1:]):
            self._draw_arrow_head(draw, start, end, "#f97316")

    def _draw_arrow_head(self, draw: ImageDraw.ImageDraw, start: tuple[int, int], end: tuple[int, int], color: str):
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        size = 26
        p1 = (end[0] - size * math.cos(angle - 0.55), end[1] - size * math.sin(angle - 0.55))
        p2 = (end[0] - size * math.cos(angle + 0.55), end[1] - size * math.sin(angle + 0.55))
        draw.polygon([end, p1, p2], fill=color)

    def _draw_base_highlight(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font):
        x1, y1, x2, y2 = box
        base = (x1 + 300, y1 + 750, x1 + 785, y1 + 965)
        draw.rounded_rectangle(base, radius=18, outline="#16a34a", width=10)
        draw.line((base[0], base[3] + 28, base[2], base[3] + 28), fill="#16a34a", width=8)
        draw.line((base[0], base[3] + 10, base[0], base[3] + 50), fill="#16a34a", width=8)
        draw.line((base[2], base[3] + 10, base[2], base[3] + 50), fill="#16a34a", width=8)
        draw.rounded_rectangle((x1 + 760, y1 + 770, x1 + 1030, y1 + 865), radius=16, fill="#dcfce7", outline="#16a34a", width=3)
        draw.text((x1 + 790, y1 + 793), "DOUBLE BASE", font=font, fill="#166534")

    def _draw_scratching_highlights(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font):
        x1, y1, x2, y2 = box
        columns = [
            (x1 + 375, y1 + 215, x1 + 465, y1 + 700),
            (x1 + 620, y1 + 170, x1 + 710, y1 + 760),
            (x1 + 815, y1 + 365, x1 + 905, y1 + 900),
        ]
        for col in columns:
            draw.rounded_rectangle(col, radius=18, outline="#f97316", width=8)
        draw.rounded_rectangle((x1 + 845, y1 + 190, x1 + 1050, y1 + 285), radius=16, fill="#ffedd5", outline="#f97316", width=3)
        draw.text((x1 + 875, y1 + 214), "SISAL", font=font, fill="#9a3412")

    def _draw_general_highlight(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font):
        x1, y1, x2, y2 = box
        draw.rounded_rectangle((x1 + 260, y1 + 150, x2 - 260, y2 - 120), radius=24, outline="#2563eb", width=8)
        draw.text((x1 + 340, y1 + 170), "KEY STRUCTURE", font=font, fill="#1d4ed8")
