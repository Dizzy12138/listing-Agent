"""
SellingPointAnnotationWorkflow — structure-first annotation system.

Key rules:
- Full product image is always used as primary view (not cropped).
- Resting areas: complete product + numbered 1-6 badges, most of structure visible.
- Climbing path: complete product + route arrows, not just a segment.
- Stability base: bottom highlight with support lines and stability label.
- Scratching system: multi-point highlights on sisal columns and boards.
- Annotation elements are tracked in metadata so QualityAgent can verify.
"""
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
            image, annotation_meta = self._render(context, annotation_type)
            artifact = self.save_image(image, context, context.job.image_type, "selling_point")
            artifact.metadata.update({
                "annotation_type": annotation_type,
                "has_annotation": True,
                "title": self._title(context.job.description, annotation_type),
                **annotation_meta,
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

    def _render(self, context: WorkflowContext, annotation_type: str) -> tuple[Image.Image, dict]:
        """Render annotation card. Returns (image, annotation_metadata)."""
        width, height = 1500, 1500
        canvas = Image.new("RGB", (width, height), "#f6f8fb")
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(56, bold=True)
        body_font = _load_font(30)
        label_font = _load_font(32, bold=True)
        small_font = _load_font(26, bold=True)

        # Outer card
        draw.rounded_rectangle((42, 42, 1458, 1458), radius=24, fill="#ffffff", outline="#d7dee8", width=3)

        # Title area
        title = self._title(context.job.description, annotation_type)
        y = 72
        for line in _wrap_text(draw, title, title_font, 1200, 2):
            draw.text((88, y), line, font=title_font, fill="#172033")
            y += 66
        subtitle = self._subtitle(annotation_type)
        draw.text((90, y + 4), subtitle, font=body_font, fill="#536173")

        # Product panel — FULL product view, not cropped
        product_panel_top = 210
        product_panel = (80, product_panel_top, 1420, 1400)
        draw.rounded_rectangle(product_panel, radius=18, fill="#f8fafc", outline="#e2e8f0", width=2)

        product = context.base_assets["white_bg"].convert("RGB")
        content = product.crop(_content_bbox(product))
        # Use full product fitting — key rule: no partial cropping for structural selling points
        fitted = _fit_image(content, (1200, 1100), background=(248, 250, 252))
        paste_x = (1500 - 1200) // 2
        paste_y = product_panel_top + 40
        canvas.paste(fitted, (paste_x, paste_y))

        # Annotation overlay box
        box = (paste_x, paste_y, paste_x + 1200, paste_y + 1100)

        annotation_meta = {}
        if annotation_type == "resting_areas":
            self._draw_resting_labels(draw, box, label_font, small_font)
            annotation_meta["annotation_badges_drawn"] = True
            annotation_meta["annotation_badge_count"] = 6
        elif annotation_type == "climbing_path":
            self._draw_climbing_path(draw, box, small_font)
            annotation_meta["annotation_arrows_drawn"] = True
            annotation_meta["annotation_arrow_count"] = 5
        elif annotation_type == "stability_base":
            self._draw_base_highlight(draw, box, label_font, small_font)
            annotation_meta["annotation_highlight_drawn"] = True
        elif annotation_type == "scratching_system":
            self._draw_scratching_highlights(draw, box, label_font, small_font)
            annotation_meta["annotation_highlights_drawn"] = True
            annotation_meta["annotation_highlight_count"] = 3
        else:
            self._draw_general_highlight(draw, box, label_font)
            annotation_meta["annotation_highlight_drawn"] = True

        return canvas, annotation_meta

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
            "resting_areas": "Each platform and resting space is numbered for clear multi-cat usage.",
            "climbing_path": "Route arrows show how cats navigate through the tower's levels.",
            "stability_base": "Enhanced bottom support keeps the tower stable for large cats.",
            "scratching_system": "Highlighted sisal posts and scratch boards show key scratching surfaces.",
        }
        return subtitles.get(annotation_type, "Annotated structure view for ecommerce detail pages.")

    # ---- Resting areas: 6 numbered badges on full product ----
    def _draw_badge(self, draw: ImageDraw.ImageDraw, center: tuple[int, int], text: str, font,
                    color: str = "#2563eb", size: int = 28):
        x, y = center
        # Outer circle with white border
        draw.ellipse((x - size, y - size, x + size, y + size), fill=color, outline="#ffffff", width=4)
        tw = draw.textlength(text, font=font)
        draw.text((x - tw / 2, y - size + 8), text, font=font, fill="#ffffff")

    def _draw_connector_line(self, draw: ImageDraw.ImageDraw, start: tuple[int, int],
                              end: tuple[int, int], color: str = "#2563eb"):
        draw.line([start, end], fill=color, width=3)

    def _draw_resting_labels(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
                              font, small_font):
        x1, y1, x2, y2 = box
        bw = x2 - x1
        bh = y2 - y1
        # 6 platform positions distributed across the full product height
        platform_positions = [
            (x1 + int(bw * 0.52), y1 + int(bh * 0.06)),   # 1 - top platform
            (x1 + int(bw * 0.32), y1 + int(bh * 0.19)),   # 2 - upper left
            (x1 + int(bw * 0.62), y1 + int(bh * 0.28)),   # 3 - upper right
            (x1 + int(bw * 0.42), y1 + int(bh * 0.44)),   # 4 - middle
            (x1 + int(bw * 0.64), y1 + int(bh * 0.58)),   # 5 - lower right
            (x1 + int(bw * 0.46), y1 + int(bh * 0.74)),   # 6 - bottom platform
        ]
        # Label positions (off to the side with connector lines)
        label_positions = [
            (x2 - 80, y1 + int(bh * 0.04)),
            (x1 + 40, y1 + int(bh * 0.17)),
            (x2 - 80, y1 + int(bh * 0.26)),
            (x1 + 40, y1 + int(bh * 0.42)),
            (x2 - 80, y1 + int(bh * 0.56)),
            (x1 + 40, y1 + int(bh * 0.72)),
        ]
        labels = [
            "Top Platform", "Upper Perch", "Condo Area",
            "Mid Hammock", "Side Rest", "Lower Bed",
        ]
        for idx, (platform_pos, label_pos) in enumerate(zip(platform_positions, label_positions)):
            self._draw_badge(draw, platform_pos, str(idx + 1), small_font)
            self._draw_connector_line(draw, platform_pos, label_pos, "#2563eb")
            # Small label tag
            tw = draw.textlength(labels[idx], font=small_font) + 16
            tag_box = (label_pos[0] - int(tw / 2), label_pos[1] - 16,
                       label_pos[0] + int(tw / 2), label_pos[1] + 16)
            draw.rounded_rectangle(tag_box, radius=8, fill="#eff6ff", outline="#2563eb", width=2)
            draw.text((tag_box[0] + 8, tag_box[1] + 2), labels[idx], font=small_font, fill="#1d4ed8")

    # ---- Climbing path: full product + route arrows ----
    def _draw_climbing_path(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], small_font):
        x1, y1, x2, y2 = box
        bw = x2 - x1
        bh = y2 - y1
        # Path from bottom to top across the full product
        path_points = [
            (x1 + int(bw * 0.38), y1 + int(bh * 0.82)),  # Start (bottom)
            (x1 + int(bw * 0.52), y1 + int(bh * 0.66)),
            (x1 + int(bw * 0.40), y1 + int(bh * 0.50)),
            (x1 + int(bw * 0.62), y1 + int(bh * 0.34)),
            (x1 + int(bw * 0.48), y1 + int(bh * 0.18)),
            (x1 + int(bw * 0.58), y1 + int(bh * 0.06)),  # End (top)
        ]
        # Draw path line
        draw.line(path_points, fill="#f97316", width=10, joint="curve")
        # Arrow heads at each segment endpoint
        for start, end in zip(path_points, path_points[1:]):
            self._draw_arrow_head(draw, start, end, "#f97316")
        # Start/end labels
        draw.rounded_rectangle(
            (path_points[0][0] - 50, path_points[0][1] + 8, path_points[0][0] + 60, path_points[0][1] + 42),
            radius=8, fill="#fff7ed", outline="#f97316", width=2,
        )
        draw.text((path_points[0][0] - 40, path_points[0][1] + 12), "START", font=small_font, fill="#9a3412")
        draw.rounded_rectangle(
            (path_points[-1][0] - 30, path_points[-1][1] - 38, path_points[-1][0] + 52, path_points[-1][1] - 4),
            radius=8, fill="#fff7ed", outline="#f97316", width=2,
        )
        draw.text((path_points[-1][0] - 20, path_points[-1][1] - 34), "TOP", font=small_font, fill="#9a3412")

    def _draw_arrow_head(self, draw: ImageDraw.ImageDraw, start: tuple[int, int],
                          end: tuple[int, int], color: str):
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        size = 22
        p1 = (end[0] - size * math.cos(angle - 0.55), end[1] - size * math.sin(angle - 0.55))
        p2 = (end[0] - size * math.cos(angle + 0.55), end[1] - size * math.sin(angle + 0.55))
        draw.polygon([end, p1, p2], fill=color)

    # ---- Stability base: highlight box + support lines ----
    def _draw_base_highlight(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
                              font, small_font):
        x1, y1, x2, y2 = box
        bw = x2 - x1
        bh = y2 - y1

        # Bottom highlight rectangle
        base_box = (x1 + int(bw * 0.18), y1 + int(bh * 0.72),
                     x1 + int(bw * 0.82), y1 + int(bh * 0.96))
        draw.rounded_rectangle(base_box, radius=18, outline="#16a34a", width=8)

        # Support/dimension lines under the base
        line_y = base_box[3] + 20
        draw.line((base_box[0], line_y, base_box[2], line_y), fill="#16a34a", width=6)
        # End caps
        draw.line((base_box[0], line_y - 16, base_box[0], line_y + 16), fill="#16a34a", width=6)
        draw.line((base_box[2], line_y - 16, base_box[2], line_y + 16), fill="#16a34a", width=6)

        # Second support line (inner base)
        inner_y = base_box[3] + 48
        inner_left = base_box[0] + int((base_box[2] - base_box[0]) * 0.15)
        inner_right = base_box[2] - int((base_box[2] - base_box[0]) * 0.15)
        draw.line((inner_left, inner_y, inner_right, inner_y), fill="#16a34a", width=4)
        draw.line((inner_left, inner_y - 12, inner_left, inner_y + 12), fill="#16a34a", width=4)
        draw.line((inner_right, inner_y - 12, inner_right, inner_y + 12), fill="#16a34a", width=4)

        # Label badge
        label_box = (base_box[2] + 20, base_box[1], base_box[2] + 240, base_box[1] + 90)
        draw.rounded_rectangle(label_box, radius=16, fill="#dcfce7", outline="#16a34a", width=3)
        draw.text((label_box[0] + 14, label_box[1] + 10), "DOUBLE", font=small_font, fill="#166534")
        draw.text((label_box[0] + 14, label_box[1] + 42), "BASE", font=font, fill="#166534")

        # Stability callout
        callout_y = base_box[1] - 50
        draw.rounded_rectangle(
            (x1 + int(bw * 0.28), callout_y, x1 + int(bw * 0.72), callout_y + 36),
            radius=8, fill="#f0fdf4", outline="#16a34a", width=2,
        )
        draw.text((x1 + int(bw * 0.30), callout_y + 4),
                   "Enhanced ground contact for max stability", font=small_font, fill="#166534")

    # ---- Scratching system: multi-point highlights ----
    def _draw_scratching_highlights(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
                                     font, small_font):
        x1, y1, x2, y2 = box
        bw = x2 - x1
        bh = y2 - y1

        # Highlight sisal column rectangles
        columns = [
            (x1 + int(bw * 0.30), y1 + int(bh * 0.20), x1 + int(bw * 0.38), y1 + int(bh * 0.65)),
            (x1 + int(bw * 0.48), y1 + int(bh * 0.15), x1 + int(bw * 0.56), y1 + int(bh * 0.70)),
            (x1 + int(bw * 0.66), y1 + int(bh * 0.30), x1 + int(bw * 0.74), y1 + int(bh * 0.80)),
        ]
        for i, col in enumerate(columns):
            draw.rounded_rectangle(col, radius=14, outline="#f97316", width=7)
            # Small sisal icon/label above each
            label_x = (col[0] + col[2]) // 2
            label_y = col[1] - 30
            draw.rounded_rectangle(
                (label_x - 35, label_y - 4, label_x + 35, label_y + 24),
                radius=6, fill="#ffedd5", outline="#f97316", width=2,
            )
            draw.text((label_x - 28, label_y), f"S{i+1}", font=small_font, fill="#9a3412")

        # Scratch board highlights (horizontal elements)
        boards = [
            (x1 + int(bw * 0.22), y1 + int(bh * 0.78), x1 + int(bw * 0.50), y1 + int(bh * 0.86)),
            (x1 + int(bw * 0.52), y1 + int(bh * 0.60), x1 + int(bw * 0.76), y1 + int(bh * 0.68)),
        ]
        for board in boards:
            draw.rounded_rectangle(board, radius=10, outline="#ea580c", width=5)

        # System label
        label_box = (x2 - 250, y1 + 20, x2 - 10, y1 + 100)
        draw.rounded_rectangle(label_box, radius=16, fill="#ffedd5", outline="#f97316", width=3)
        draw.text((label_box[0] + 14, label_box[1] + 10), "SISAL", font=font, fill="#9a3412")
        draw.text((label_box[0] + 14, label_box[1] + 44), "SYSTEM", font=small_font, fill="#9a3412")

    # ---- General highlight ----
    def _draw_general_highlight(self, draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], font):
        x1, y1, x2, y2 = box
        draw.rounded_rectangle((x1 + 260, y1 + 150, x2 - 260, y2 - 120), radius=24, outline="#2563eb", width=8)
        draw.text((x1 + 340, y1 + 170), "KEY STRUCTURE", font=font, fill="#1d4ed8")
