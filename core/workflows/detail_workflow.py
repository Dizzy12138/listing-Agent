"""
DetailWorkflow — Material-specific closeup generation.

For "材质工艺" type images:
- Parse description to identify specific materials (plush_fabric, sisal_rope, board_material)
- Use ProductVisionAgent material_regions for precise crop coordinates
- Generate multiple material candidates and select the clearest one
- If material region cannot be located → status = needs_review, not pass
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from pipeline.step4_enhance import _content_bbox, _fit_image, _load_font, generate_detail_crops
from core.agents.detail_target_agent import DetailTargetAgent
from core.tools.reference_generation import material_detail_enhancement
from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


MATERIAL_KEYWORDS = {
    "plush_fabric": ["绒布", "面料", "plush", "fabric", "soft", "毛绒"],
    "sisal_rope": ["剑麻", "sisal", "rope", "抓挠", "scratch", "麻绳"],
    "board_material": ["板材", "board", "particle", "木板", "底板", "panel"],
}


def _detect_material_types(description: str) -> list[str]:
    """Parse description to find requested material types."""
    text = description.lower()
    found = []
    for material, keywords in MATERIAL_KEYWORDS.items():
        if any(k in text for k in keywords):
            found.append(material)
    # If nothing specific matched, return all
    if not found:
        found = list(MATERIAL_KEYWORDS.keys())
    return found


@register_workflow("detail")
@register_workflow("detail_material")
class DetailWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        product_analysis = context.base_assets.get("_product_analysis", {})
        material_regions = product_analysis.get("material_regions", {})
        vision_source = product_analysis.get("source", "unknown")
        requested_materials = _detect_material_types(context.job.description)

        with context.trace.timed("workflow.detail"):
            candidates = self._generate_material_candidates(
                context, material_regions, requested_materials,
            )

            if not candidates:
                # Cannot locate any material region → needs_review
                return self._handle_no_material(context)

            # Select best candidate (highest confidence)
            best = max(candidates, key=lambda c: c["confidence"])
            artifacts = []

            if best["confidence"] >= 0.5 or vision_source == "vlm":
                # Good confidence or VLM-verified → formal detail candidate
                artifact = self.save_image(best["image"], context, context.job.image_type, "detail")
                artifact.metadata.update({
                    "generation_strategy": "material_detail_enhancement",
                    "commercial_quality_level": "needs_review" if best["mode"] == "reference_based_fallback" else "info_graph_pass",
                    "reference_assets_used": ["original", "product_analysis"],
                    "direct_white_bg_subject": False,
                    "material_type": best["material_type"],
                    "material_confidence": best["confidence"],
                    "enhancement_mode": best["mode"],
                    "enhancement_issues": best.get("issues", []),
                    "vision_source": vision_source,
                    "crop_region": best.get("crop_region", "unknown"),
                })
                artifacts.append(artifact)
                context.trace.add(
                    step="workflow.detail.output",
                    status="success",
                    input={
                        "job_id": context.job.job_id,
                        "material_type": best["material_type"],
                        "confidence": best["confidence"],
                        "vision_source": vision_source,
                    },
                    output_artifact=artifact.path,
                )

                # Also save other candidates
                for i, cand in enumerate(candidates):
                    if cand is not best:
                        cand_artifact = self.save_image(
                            cand["image"], context,
                            f"{context.job.image_type}_{cand['material_type']}_candidate",
                            "detail_candidate",
                        )
                        cand_artifact.metadata.update({
                            "generation_strategy": "material_detail_enhancement",
                            "commercial_quality_level": "needs_review",
                            "reference_assets_used": ["original", "product_analysis"],
                            "direct_white_bg_subject": False,
                            "material_type": cand["material_type"],
                            "material_confidence": cand["confidence"],
                            "enhancement_mode": cand["mode"],
                            "enhancement_issues": cand.get("issues", []),
                            "vision_source": vision_source,
                        })
                        artifacts.append(cand_artifact)

                return self.ok_result(context, artifacts, context.trace.records[-2:])
            else:
                # Low confidence fallback → needs_review
                for cand in candidates:
                    cand_artifact = self.save_image(
                        cand["image"], context,
                        f"{context.job.image_type}_{cand['material_type']}_candidate",
                        "detail_candidate",
                    )
                    cand_artifact.metadata.update({
                        "generation_strategy": "material_detail_enhancement",
                        "commercial_quality_level": "needs_review",
                        "reference_assets_used": ["original", "product_analysis"],
                        "direct_white_bg_subject": False,
                        "material_type": cand["material_type"],
                        "material_confidence": cand["confidence"],
                        "enhancement_mode": cand["mode"],
                        "enhancement_issues": cand.get("issues", []),
                        "vision_source": vision_source,
                    })
                    artifacts.append(cand_artifact)

                self._save_reason(context, f"Low confidence material detection ({best['confidence']:.2f}). needs_review.")
                blocked = self.save_blocked_report(
                    context, context.job.image_type,
                    reason="material_detection_low_confidence",
                    details={"best_confidence": best["confidence"], "vision_source": vision_source},
                )
                artifacts.append(blocked)
                context.trace.add(
                    step="workflow.detail.low_confidence",
                    status="warning",
                    issues=[f"material_confidence={best['confidence']:.2f}, vision_source={vision_source}"],
                )
                return self.blocked_result(
                    context, artifacts,
                    reason=f"material_detection_low_confidence: {best['confidence']:.2f}",
                    traces=context.trace.records[-2:],
                )

    def _generate_material_candidates(
        self, context: WorkflowContext, material_regions: dict, requested_materials: list[str],
    ) -> list[dict]:
        """Generate closeup candidates for each requested material type."""
        product = context.base_assets["original"].convert("RGB")
        pw, ph = product.size
        candidates = []

        for material_type in requested_materials:
            regions = material_regions.get(material_type, [])
            if not regions:
                continue

            for region in regions[:1]:  # Take best region per material
                bbox = region.get("bbox", [])
                confidence = region.get("confidence", 0.3)
                if len(bbox) != 4:
                    continue

                # Convert pct bbox to pixel coords with expansion for context
                x1 = int(bbox[0] / 100 * pw)
                y1 = int(bbox[1] / 100 * ph)
                x2 = int(bbox[2] / 100 * pw)
                y2 = int(bbox[3] / 100 * ph)

                # Expand by 60% for context
                margin_x = int((x2 - x1) * 0.6)
                margin_y = int((y2 - y1) * 0.6)
                cx1 = max(0, x1 - margin_x)
                cy1 = max(0, y1 - margin_y)
                cx2 = min(pw, x2 + margin_x)
                cy2 = min(ph, y2 + margin_y)

                enhanced, issues, mode = material_detail_enhancement(
                    original_photo=product,
                    crop_box=(cx1, cy1, cx2, cy2),
                    material_type=material_type,
                    model=context.model,
                )
                card = self._render_material_card(enhanced, material_type, confidence)
                candidates.append({
                    "image": card,
                    "material_type": material_type,
                    "confidence": confidence,
                    "crop_region": [cx1, cy1, cx2, cy2],
                    "mode": mode,
                    "issues": issues,
                })

        return candidates

    def _render_material_card(self, closeup: Image.Image, material_type: str, confidence: float) -> Image.Image:
        """Render a detail card for a material closeup."""
        canvas = Image.new("RGB", (1500, 1500), "#ffffff")
        draw = ImageDraw.Draw(canvas)
        title_font = _load_font(48, bold=True)
        body_font = _load_font(28)
        label_font = _load_font(26, bold=True)

        material_info = {
            "plush_fabric": ("Premium Plush Fabric", "柔软毛绒面料 — 舒适触感", "#7c3aed"),
            "sisal_rope": ("Natural Sisal Rope", "天然剑麻柱 — 耐磨抓挠", "#f97316"),
            "board_material": ("Solid Board Structure", "高密度板材 — 稳定承重", "#0891b2"),
        }
        en_name, cn_desc, color = material_info.get(material_type, ("Material Detail", "材质细节", "#6b7280"))

        # Header
        draw.rectangle((0, 0, 1500, 160), fill="#f8fafc")
        draw.line((0, 160, 1500, 160), fill="#e2e8f0", width=2)
        draw.text((80, 40), en_name, font=title_font, fill="#172033")
        draw.text((82, 100), cn_desc, font=body_font, fill="#536173")

        # Material closeup image
        fitted = _fit_image(closeup, (1300, 1150), background=(255, 255, 255))
        canvas.paste(fitted, (100, 200))

        # Confidence badge
        conf_text = f"Detection: {confidence:.0%}"
        badge_color = "#16a34a" if confidence >= 0.7 else "#d97706" if confidence >= 0.4 else "#dc2626"
        draw.rounded_rectangle((1100, 1380, 1400, 1420), radius=10, fill=badge_color, outline=badge_color)
        draw.text((1110, 1386), conf_text, font=label_font, fill="#ffffff")

        # Material type badge
        draw.rounded_rectangle((80, 1380, 350, 1420), radius=10, fill=color+"22", outline=color, width=2)
        draw.text((95, 1386), material_type.replace("_", " ").title(), font=label_font, fill=color)

        return canvas

    def _handle_no_material(self, context: WorkflowContext):
        """Fall back to general detail crop when no material region found."""
        target_agent = DetailTargetAgent()
        target = target_agent.resolve(context.job.description)
        detail_source = context.base_assets["original"]

        details = generate_detail_crops(detail_source, [context.job.description])
        artifacts = []
        if details:
            artifact = self.save_image(details[0]["crop"], context, f"{context.job.image_type}_candidate", "detail_candidate")
            artifact.metadata.update({
                "generation_strategy": "reference_based_fallback",
                "commercial_quality_level": "needs_review",
                "reference_assets_used": ["original"],
                "direct_white_bg_subject": False,
                "material_type": "unknown",
                "material_confidence": 0.0,
                "vision_source": "none",
                "target_region": target.get("target_region", ""),
            })
            artifacts.append(artifact)

        self._save_reason(context, "Cannot locate material region for closeup. Fallback to general crop.")
        context.trace.add(step="workflow.detail.no_material", status="warning",
            issues=["material_region_not_located: needs_review"])
        return self.ok_result(context, artifacts, context.trace.records[-2:])

    def _save_reason(self, context, reason: str):
        filename = f"img{context.job.image_index:02d}_{context.job.image_type}_reason.txt"
        path = context.output_dir / filename
        path.write_text(reason, encoding="utf-8")
