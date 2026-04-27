"""
SellingPointAnnotationWorkflow — VisionAgent-driven selling point images.

Three selling point types:
A. Structural annotation (6 resting areas, climbing path, double base)
   → Uses ProductVisionAgent bbox coordinates
B. Material closeup (plush fabric, sisal rope, board material)
   → Generates closeup crops based on material_regions from VisionAgent
C. Scene demonstration (multi-cat usage, family interaction)
   → Delegated to SceneWorkflow — not handled here

Fallback annotations (when VisionAgent data is from fallback) are marked
as fallback_annotation and cannot pass quality gate.
"""
from __future__ import annotations

import math
from typing import Any

from PIL import Image, ImageDraw

from pipeline.step4_enhance import _content_bbox, _fit_image, _load_font, _wrap_text
from core.tools.reference_generation import reference_guided_scene_generation
from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


def _classify_selling_point(description: str) -> tuple[str, str]:
    """Classify selling point type and sub-type.
    Returns (category, annotation_type).
    category: structural / material / scene_demo
    """
    text = description.lower()
    if any(k in text for k in ["休息", "平台", "吊床", "窝", "rest", "platform", "hammock", "区域"]):
        return "structural", "resting_areas"
    if any(k in text for k in ["动线", "攀爬", "路线", "path", "climb", "route"]):
        return "structural", "climbing_path"
    if any(k in text for k in ["底板", "稳定", "base", "stability", "stable"]):
        return "structural", "stability_base"
    if any(k in text for k in ["抓挠", "剑麻", "猫抓", "scratch", "sisal", "rope"]):
        return "structural", "scratching_system"
    if any(k in text for k in ["绒布", "材质", "板材", "面料", "plush", "fabric", "board", "material", "工艺"]):
        return "material", "material_closeup"
    if any(k in text for k in ["多猫", "亲子", "互动", "小孩", "multi-cat", "family", "child"]):
        return "scene_demo", "scene_demonstration"
    return "structural", "general_annotation"


def _pct_to_px(bbox_pct: list[float], canvas_w: int, canvas_h: int,
                offset_x: int = 0, offset_y: int = 0) -> tuple[int, int, int, int]:
    """Convert percentage bbox to pixel coords with offset."""
    return (
        int(bbox_pct[0] / 100 * canvas_w) + offset_x,
        int(bbox_pct[1] / 100 * canvas_h) + offset_y,
        int(bbox_pct[2] / 100 * canvas_w) + offset_x,
        int(bbox_pct[3] / 100 * canvas_h) + offset_y,
    )


@register_workflow("selling_point_annotation")
class SellingPointAnnotationWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        category, annotation_type = _classify_selling_point(context.job.description)

        # Scene demonstration for action-driven selling points.
        if category == "scene_demo" or annotation_type in {"scratching_system", "stability_base"}:
            return self._run_scene_demo(context, annotation_type)

        # Material closeup → generate crop
        if category == "material":
            return self._run_material_closeup(context, annotation_type)

        # Structural annotation → use VisionAgent data
        return self._run_structural(context, annotation_type)

    def _run_structural(self, context: WorkflowContext, annotation_type: str):
        """Structural annotation using VisionAgent real part coordinates."""
        product_analysis = context.base_assets.get("_product_analysis", {})
        is_fallback = product_analysis.get("source") == "fallback"

        with context.trace.timed("workflow.selling_point_annotation.structural"):
            image, annotation_meta = self._render_structural(context, annotation_type, product_analysis)
            stem = context.job.image_type

            if is_fallback:
                artifact = self.save_image(image, context, stem, "selling_point")
                artifact.metadata.update({
                    "generation_strategy": "info_graph_annotation",
                    "commercial_quality_level": "needs_review",
                    "reference_assets_used": ["white_bg", "product_analysis"],
                    "direct_white_bg_subject": True,
                    "annotation_type": annotation_type,
                    "has_annotation": True,
                    "is_fallback_annotation": True,
                    "title": self._title(context.job.description, annotation_type),
                    "vision_source": "fallback",
                    **annotation_meta,
                })
                context.trace.add(step="workflow.selling_point.fallback", status="warning",
                    input={"annotation_type": annotation_type, "vision_source": "fallback"},
                    output_artifact=artifact.path,
                    issues=["fallback_annotation: coordinates not from VLM"])
                return self.ok_result(context, [artifact], context.trace.records[-2:])
            else:
                # VLM coordinates — formal output
                artifact = self.save_image(image, context, stem, "selling_point")
                artifact.metadata.update({
                    "generation_strategy": "info_graph_annotation",
                    "commercial_quality_level": "info_graph_pass",
                    "reference_assets_used": ["white_bg", "product_analysis"],
                    "direct_white_bg_subject": True,
                    "annotation_type": annotation_type,
                    "has_annotation": True,
                    "is_fallback_annotation": False,
                    "title": self._title(context.job.description, annotation_type),
                    "vision_source": "vlm",
                    **annotation_meta,
                })
                context.trace.add(step="workflow.selling_point.vlm", status="success",
                    input={"annotation_type": annotation_type, "vision_source": "vlm"},
                    output_artifact=artifact.path)
                return self.ok_result(context, [artifact], context.trace.records[-2:])

    def _run_material_closeup(self, context: WorkflowContext, annotation_type: str):
        """Material closeup — generate zoomed crop based on material_regions."""
        product_analysis = context.base_assets.get("_product_analysis", {})
        material_regions = product_analysis.get("material_regions", {})

        with context.trace.timed("workflow.selling_point_annotation.material"):
            image, meta = self._render_material_closeup(context, material_regions)
            stem = context.job.image_type

            if meta.get("material_found"):
                artifact = self.save_image(image, context, stem, "selling_point")
                artifact.metadata.update({
                    "annotation_type": "material_closeup",
                    "has_annotation": True,
                    "title": self._title(context.job.description, annotation_type),
                    **meta,
                })
                context.trace.add(step="workflow.selling_point.material", status="success",
                    output_artifact=artifact.path)
                return self.ok_result(context, [artifact], context.trace.records[-2:])
            else:
                # Cannot locate material region
                artifact = self.save_image(image, context, f"{stem}_candidate", "selling_point_candidate")
                artifact.metadata.update({"annotation_type": "material_closeup", **meta})
                self._save_reason(context, f"Cannot locate material region for closeup. needs_review.")
                blocked = self.save_blocked_report(context, stem, reason="material_region_not_found")
                context.trace.add(step="workflow.selling_point.material_fail", status="warning",
                    issues=["material_region_not_found"])
                return self.blocked_result(context, [artifact, blocked],
                    reason="material_region_not_found", traces=context.trace.records[-2:])

    def _run_scene_demo(self, context: WorkflowContext, annotation_type: str):
        """Generate action demo as a whole scene, not a marked white-background diagram."""
        with context.trace.timed("workflow.selling_point_annotation.scene_demo"):
            product_analysis = context.base_assets.get("_product_analysis", {})
            prompt = self._scene_demo_prompt(context, annotation_type)
            image, issues, mode = reference_guided_scene_generation(
                original_photo=context.base_assets["original"],
                white_bg_reference=context.base_assets["white_bg"],
                product_analysis=product_analysis,
                scene_prompt=prompt,
                model=context.model,
                image_type=context.job.image_type,
            )
            vision_agent = context.base_assets.get("_vision_agent")
            vlm_quality = {}
            commercial_level = "needs_review"
            if vision_agent:
                required = self._required_elements(annotation_type)
                vlm_quality = vision_agent.verify_quality(image, required_elements=required)
                if (
                    vlm_quality.get("overall_quality") == "pass"
                    and not vlm_quality.get("has_artifacts", False)
                    and not vlm_quality.get("structure_distorted", False)
                    and mode != "reference_based_fallback"
                ):
                    commercial_level = "commercial_scene_pass"
            artifact = self.save_image(image, context, context.job.image_type, "selling_point")
            artifact.metadata.update({
                "generation_strategy": "reference_guided_scene_generation",
                "generation_mode": mode,
                "commercial_quality_level": commercial_level,
                "reference_assets_used": ["original", "white_bg", "product_analysis"],
                "direct_white_bg_subject": False,
                "annotation_type": annotation_type,
                "has_annotation": False,
                "scene_demo": True,
                "scene_prompt": prompt,
                "vlm_quality_check": vlm_quality,
                "product_analysis_source": product_analysis.get("source", "unknown"),
            })
            context.trace.add(
                step="workflow.selling_point.scene_demo.output",
                status="success" if commercial_level == "commercial_scene_pass" else "warning",
                input={
                    "annotation_type": annotation_type,
                    "generation_strategy": "reference_guided_scene_generation",
                    "mode": mode,
                    "reference_assets_used": ["original", "white_bg", "product_analysis"],
                },
                output_artifact=artifact.path,
                issues=issues + vlm_quality.get("issues", []),
            )
            return self.ok_result(context, [artifact], context.trace.records[-2:])

    # ---- Rendering ----

    def _render_structural(self, context: WorkflowContext, annotation_type: str,
                           product_analysis: dict) -> tuple[Image.Image, dict]:
        width, height = 1500, 1500
        canvas = Image.new("RGB", (width, height), "#f6f8fb")
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(54, bold=True)
        body_font = _load_font(30)
        label_font = _load_font(32, bold=True)
        small_font = _load_font(26, bold=True)

        # Card
        draw.rounded_rectangle((42, 42, 1458, 1458), radius=24, fill="#ffffff", outline="#d7dee8", width=3)

        # Title
        title = self._title(context.job.description, annotation_type)
        y = 72
        for line in _wrap_text(draw, title, title_font, 1200, 2):
            draw.text((88, y), line, font=title_font, fill="#172033")
            y += 66
        subtitle = self._subtitle(annotation_type)
        draw.text((90, y + 4), subtitle, font=body_font, fill="#536173")

        # Product panel
        panel_top = 210
        draw.rounded_rectangle((80, panel_top, 1420, 1400), radius=18, fill="#f8fafc", outline="#e2e8f0", width=2)

        product = context.base_assets["white_bg"].convert("RGB")
        content = product.crop(_content_bbox(product))
        pw, ph = 1200, 1100
        fitted = _fit_image(content, (pw, ph), background=(248, 250, 252))
        paste_x = (1500 - pw) // 2
        paste_y = panel_top + 40
        canvas.paste(fitted, (paste_x, paste_y))

        # Get real part coords from VisionAgent analysis
        visible_parts = product_analysis.get("visible_parts", {})
        meta = {}

        if annotation_type == "resting_areas":
            meta = self._annotate_resting_areas(draw, visible_parts, pw, ph, paste_x, paste_y, small_font, label_font)
        elif annotation_type == "climbing_path":
            climbing_path = product_analysis.get("climbing_path", [])
            meta = self._annotate_climbing_path(draw, climbing_path, pw, ph, paste_x, paste_y, small_font)
        elif annotation_type == "stability_base":
            meta = self._annotate_stability(draw, visible_parts, pw, ph, paste_x, paste_y, label_font, small_font)
        elif annotation_type == "scratching_system":
            meta = self._annotate_scratching(draw, visible_parts, pw, ph, paste_x, paste_y, label_font, small_font)
        else:
            meta = {"annotation_type": "general"}

        return canvas, meta

    def _annotate_resting_areas(self, draw, visible_parts, pw, ph, ox, oy, small_font, label_font):
        platforms = visible_parts.get("platforms", [])
        hammocks = visible_parts.get("hammock_area", [])
        condos = visible_parts.get("condo_area", [])
        all_areas = platforms + hammocks + condos

        drawn_count = 0
        labels = ["Top Platform", "Upper Perch", "Condo Area", "Mid Hammock", "Side Rest", "Lower Bed"]
        colors = ["#2563eb", "#7c3aed", "#059669", "#d97706", "#dc2626", "#0891b2"]

        for i, area in enumerate(all_areas[:6]):
            bbox = area.get("bbox", [])
            if len(bbox) != 4:
                continue
            x1, y1, x2, y2 = _pct_to_px(bbox, pw, ph, ox, oy)
            color = colors[i % len(colors)]
            label = labels[i] if i < len(labels) else area.get("name", f"Area {i+1}")

            # Draw highlight rect
            draw.rounded_rectangle((x1, y1, x2, y2), radius=8, outline=color, width=5)

            # Badge with number
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            badge_r = 22
            draw.ellipse((cx - badge_r, cy - badge_r, cx + badge_r, cy + badge_r),
                         fill=color, outline="#ffffff", width=3)
            tw = draw.textlength(str(i + 1), font=small_font)
            draw.text((cx - tw / 2, cy - badge_r + 6), str(i + 1), font=small_font, fill="#ffffff")

            # Label tag positioned outside the box
            tag_x = x2 + 10 if x2 + 150 < 1420 else x1 - 150
            tag_y = y1
            tag_w = draw.textlength(label, font=small_font) + 20
            draw.rounded_rectangle((tag_x, tag_y, tag_x + tag_w, tag_y + 30), radius=6,
                                   fill=color + "22", outline=color, width=2)
            draw.text((tag_x + 10, tag_y + 3), label, font=small_font, fill=color)
            # Connector line
            draw.line([(x2, (y1+y2)//2), (tag_x, tag_y + 15)], fill=color, width=2)
            drawn_count += 1

        return {"annotation_badges_drawn": drawn_count > 0, "annotation_badge_count": drawn_count}

    def _annotate_climbing_path(self, draw, climbing_path, pw, ph, ox, oy, small_font):
        if not climbing_path:
            return {"annotation_arrows_drawn": False, "annotation_arrow_count": 0}

        all_points = []
        for segment in climbing_path:
            route = segment.get("approximate_route", [])
            for pt in route:
                if len(pt) >= 2:
                    px = int(pt[0] / 100 * pw) + ox
                    py = int(pt[1] / 100 * ph) + oy
                    all_points.append((px, py))

        if len(all_points) < 2:
            return {"annotation_arrows_drawn": False, "annotation_arrow_count": 0}

        # Draw path
        draw.line(all_points, fill="#f97316", width=8, joint="curve")
        for start, end in zip(all_points, all_points[1:]):
            self._draw_arrow_head(draw, start, end, "#f97316")

        # Start/end labels
        sp = all_points[0]
        ep = all_points[-1]
        draw.rounded_rectangle((sp[0]-40, sp[1]+5, sp[0]+50, sp[1]+35), radius=6,
                               fill="#fff7ed", outline="#f97316", width=2)
        draw.text((sp[0]-30, sp[1]+9), "START", font=small_font, fill="#9a3412")
        draw.rounded_rectangle((ep[0]-25, ep[1]-35, ep[0]+45, ep[1]-5), radius=6,
                               fill="#fff7ed", outline="#f97316", width=2)
        draw.text((ep[0]-15, ep[1]-31), "TOP", font=small_font, fill="#9a3412")

        return {"annotation_arrows_drawn": True, "annotation_arrow_count": len(all_points) - 1}

    def _annotate_stability(self, draw, visible_parts, pw, ph, ox, oy, label_font, small_font):
        base = visible_parts.get("base_area", {})
        bbox = base.get("bbox", [])
        if len(bbox) != 4:
            return {"annotation_highlight_drawn": False}

        x1, y1, x2, y2 = _pct_to_px(bbox, pw, ph, ox, oy)
        draw.rounded_rectangle((x1, y1, x2, y2), radius=12, outline="#16a34a", width=8)

        # Dimension line below base
        line_y = y2 + 20
        draw.line((x1, line_y, x2, line_y), fill="#16a34a", width=6)
        draw.line((x1, line_y-14, x1, line_y+14), fill="#16a34a", width=5)
        draw.line((x2, line_y-14, x2, line_y+14), fill="#16a34a", width=5)

        # Label
        lx = x2 + 15
        draw.rounded_rectangle((lx, y1, lx + 180, y1 + 80), radius=12, fill="#dcfce7", outline="#16a34a", width=3)
        draw.text((lx + 12, y1 + 8), "DOUBLE", font=small_font, fill="#166534")
        draw.text((lx + 12, y1 + 38), "BASE", font=label_font, fill="#166534")

        has_double = base.get("has_double_base", False)
        callout = "Enhanced double base for max stability" if has_double else "Wide base support"
        draw.rounded_rectangle((x1, y1 - 40, x1 + draw.textlength(callout, font=small_font) + 20, y1 - 6),
                               radius=6, fill="#f0fdf4", outline="#16a34a", width=2)
        draw.text((x1 + 10, y1 - 36), callout, font=small_font, fill="#166534")

        return {"annotation_highlight_drawn": True}

    def _annotate_scratching(self, draw, visible_parts, pw, ph, ox, oy, label_font, small_font):
        posts = visible_parts.get("sisal_posts", [])
        boards = visible_parts.get("scratch_boards", [])
        drawn = 0

        for i, post in enumerate(posts[:4]):
            bbox = post.get("bbox", [])
            if len(bbox) != 4:
                continue
            x1, y1, x2, y2 = _pct_to_px(bbox, pw, ph, ox, oy)
            draw.rounded_rectangle((x1, y1, x2, y2), radius=10, outline="#f97316", width=6)
            lx = (x1 + x2) // 2
            draw.rounded_rectangle((lx-25, y1-28, lx+25, y1-2), radius=5, fill="#ffedd5", outline="#f97316", width=2)
            draw.text((lx-18, y1-24), f"S{i+1}", font=small_font, fill="#9a3412")
            drawn += 1

        for board in boards[:2]:
            bbox = board.get("bbox", [])
            if len(bbox) != 4:
                continue
            x1, y1, x2, y2 = _pct_to_px(bbox, pw, ph, ox, oy)
            draw.rounded_rectangle((x1, y1, x2, y2), radius=8, outline="#ea580c", width=5)
            drawn += 1

        # System label
        draw.rounded_rectangle((1200, 250, 1400, 330), radius=12, fill="#ffedd5", outline="#f97316", width=3)
        draw.text((1214, 260), "SISAL", font=label_font, fill="#9a3412")
        draw.text((1214, 292), "SYSTEM", font=small_font, fill="#9a3412")

        return {"annotation_highlights_drawn": drawn > 0, "annotation_highlight_count": drawn}

    def _render_material_closeup(self, context: WorkflowContext, material_regions: dict) -> tuple[Image.Image, dict]:
        """Generate material closeup images by cropping the detected material region."""
        width, height = 1500, 1500
        canvas = Image.new("RGB", (width, height), "#f6f8fb")
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(52, bold=True)
        body_font = _load_font(30)
        label_font = _load_font(28, bold=True)

        draw.rounded_rectangle((42, 42, 1458, 1458), radius=24, fill="#ffffff", outline="#d7dee8", width=3)

        desc = context.job.description.lower()
        material_types = [
            ("plush_fabric", "Plush Fabric", "绒布面料细节", "#7c3aed"),
            ("sisal_rope", "Sisal Rope", "剑麻绳柱细节", "#f97316"),
            ("board_material", "Board Material", "板材工艺细节", "#0891b2"),
        ]

        # Find best matching material
        best_material = None
        for key, en_name, cn_name, color in material_types:
            if key in desc or en_name.lower() in desc or cn_name in desc:
                if key in material_regions and material_regions[key]:
                    best_material = (key, en_name, cn_name, color, material_regions[key][0])
                    break

        # If no specific match, try all materials
        if not best_material:
            for key, en_name, cn_name, color in material_types:
                if key in material_regions and material_regions[key]:
                    best_material = (key, en_name, cn_name, color, material_regions[key][0])
                    break

        product = context.base_assets["white_bg"].convert("RGB")

        if best_material:
            key, en_name, cn_name, color, region = best_material
            bbox = region.get("bbox", [])

            draw.text((88, 72), f"Material Detail: {en_name}", font=title_font, fill="#172033")
            draw.text((90, 140), cn_name, font=body_font, fill="#536173")

            if len(bbox) == 4:
                pw, ph = product.size
                x1 = int(bbox[0] / 100 * pw)
                y1 = int(bbox[1] / 100 * ph)
                x2 = int(bbox[2] / 100 * pw)
                y2 = int(bbox[3] / 100 * ph)

                # Expand crop region for context
                margin_x = int((x2 - x1) * 0.5)
                margin_y = int((y2 - y1) * 0.5)
                cx1 = max(0, x1 - margin_x)
                cy1 = max(0, y1 - margin_y)
                cx2 = min(pw, x2 + margin_x)
                cy2 = min(ph, y2 + margin_y)

                closeup = product.crop((cx1, cy1, cx2, cy2))
                fitted = _fit_image(closeup, (1200, 1000), background=(248, 250, 252))
                canvas.paste(fitted, (150, 240))

                # Highlight rectangle on the material area within the crop
                rel_x1 = int((x1 - cx1) / (cx2 - cx1) * 1200) + 150
                rel_y1 = int((y1 - cy1) / (cy2 - cy1) * 1000) + 240
                rel_x2 = int((x2 - cx1) / (cx2 - cx1) * 1200) + 150
                rel_y2 = int((y2 - cy1) / (cy2 - cy1) * 1000) + 240
                draw.rounded_rectangle((rel_x1, rel_y1, rel_x2, rel_y2), radius=10, outline=color, width=6)

                # Label
                draw.rounded_rectangle((rel_x2+10, rel_y1, rel_x2+150, rel_y1+36), radius=8,
                                       fill=color+"22", outline=color, width=2)
                draw.text((rel_x2+18, rel_y1+6), en_name, font=label_font, fill=color)

                return canvas, {"material_found": True, "material_type": key, "confidence": region.get("confidence", 0.5)}

        # Fallback: show full product with label
        draw.text((88, 72), "Material & Craftsmanship", font=title_font, fill="#172033")
        draw.text((90, 140), "材质工艺展示", font=body_font, fill="#536173")
        content = product.crop(_content_bbox(product))
        fitted = _fit_image(content, (1200, 1100), background=(248, 250, 252))
        canvas.paste(fitted, (150, 240))
        return canvas, {"material_found": False, "material_type": "unknown"}

    def _draw_arrow_head(self, draw, start, end, color):
        angle = math.atan2(end[1] - start[1], end[0] - start[0])
        size = 18
        p1 = (end[0] - size * math.cos(angle - 0.5), end[1] - size * math.sin(angle - 0.5))
        p2 = (end[0] - size * math.cos(angle + 0.5), end[1] - size * math.sin(angle + 0.5))
        draw.polygon([end, p1, p2], fill=color)

    def _save_reason(self, context, reason: str):
        filename = f"img{context.job.image_index:02d}_{context.job.image_type}_reason.txt"
        path = context.output_dir / filename
        path.write_text(reason, encoding="utf-8")

    def _scene_demo_prompt(self, context: WorkflowContext, annotation_type: str) -> str:
        prompts = {
            "scratching_system": (
                "Commercial ecommerce scene demonstration: a cat is actively scratching the sisal rope post or scratch board "
                "on the light grey multi-level cat tree. Keep the product SKU recognizable and show the scratching function clearly."
            ),
            "stability_base": (
                "Commercial ecommerce scene demonstration: a large cat moves on the cat tree while a child or family member is nearby, "
                "showing that the wide double base keeps the tall cat tree stable and grounded."
            ),
            "resting_areas": (
                "Commercial ecommerce scene demonstration: multiple cats rest on different platforms, condo and hammock areas of the cat tree."
            ),
            "climbing_path": (
                "Commercial ecommerce scene demonstration: a cat moves along the ramp and platforms, showing the climbing route."
            ),
        }
        return prompts.get(annotation_type, context.job.description)

    def _required_elements(self, annotation_type: str) -> list[str]:
        if annotation_type == "scratching_system":
            return ["cat", "scratching action", "sisal post"]
        if annotation_type == "stability_base":
            return ["large cat", "wide base", "family or child"]
        if annotation_type == "resting_areas":
            return ["multiple cats", "resting platforms"]
        if annotation_type == "climbing_path":
            return ["cat", "climbing route"]
        return ["cat tree"]

    def _title(self, description, annotation_type):
        titles = {
            "resting_areas": "6 Resting Areas for Multi-Cat Use",
            "climbing_path": "Clear Multi-Level Climbing Path",
            "stability_base": "Wide Double Base for Stability",
            "scratching_system": "Multiple Sisal Scratching Points",
            "material_closeup": "Material & Craftsmanship Detail",
        }
        return titles.get(annotation_type, description)

    def _subtitle(self, annotation_type):
        subtitles = {
            "resting_areas": "Each platform and resting space marked with real detected positions.",
            "climbing_path": "Route arrows follow actual climbable paths detected in the product.",
            "stability_base": "Base support area highlighted at detected position.",
            "scratching_system": "Sisal posts and scratch boards highlighted at detected positions.",
            "material_closeup": "Zoomed into the actual material region for texture detail.",
        }
        return subtitles.get(annotation_type, "Annotated structure view.")
