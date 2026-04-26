"""
ProductVisionAgent — VLM-based product structural analysis.

Uses GPT-4o / GPT-5.2 / Gemini vision to analyze the product image and
return structured part detection with bounding boxes.

All downstream workflows (selling point annotation, detail, etc.) must
use coordinates from this agent — hardcoded percentages are only fallback.
"""
from __future__ import annotations

import json
import re
from typing import Any

from PIL import Image
from rich.console import Console

from models.llm import chat

console = Console()

VISION_ANALYSIS_PROMPT = """You are a product image structural analyst for e-commerce.

Analyze this product image (a large cat tree tower) and return a JSON object describing its physical structure.

IMPORTANT: Return bounding boxes as [x1, y1, x2, y2] in percentage coordinates (0-100) relative to the product image.

Return this EXACT JSON structure:
{
  "product_bbox": [x1, y1, x2, y2],
  "overall_height_estimate": "tall/medium/short",
  "structure_type": "multi-level cat tower",
  "visible_parts": {
    "platforms": [
      {"name": "top platform", "bbox": [x1, y1, x2, y2], "level": "top", "confidence": 0.9},
      {"name": "upper perch", "bbox": [x1, y1, x2, y2], "level": "upper", "confidence": 0.8}
    ],
    "sisal_posts": [
      {"name": "left post", "bbox": [x1, y1, x2, y2], "confidence": 0.8}
    ],
    "scratch_boards": [
      {"name": "lower scratch board", "bbox": [x1, y1, x2, y2], "confidence": 0.7}
    ],
    "base_area": {"bbox": [x1, y1, x2, y2], "has_double_base": true, "confidence": 0.9},
    "hammock_area": [
      {"name": "main hammock", "bbox": [x1, y1, x2, y2], "confidence": 0.7}
    ],
    "condo_area": [
      {"name": "enclosed condo", "bbox": [x1, y1, x2, y2], "confidence": 0.8}
    ],
    "ramp_area": [
      {"name": "climbing ramp", "bbox": [x1, y1, x2, y2], "confidence": 0.6}
    ],
    "hanging_toys": [
      {"name": "dangling toy", "bbox": [x1, y1, x2, y2], "confidence": 0.5}
    ]
  },
  "climbing_path": [
    {"from": "base", "to": "lower platform", "approximate_route": [[x, y], [x, y]]},
    {"from": "lower platform", "to": "mid section", "approximate_route": [[x, y], [x, y]]}
  ],
  "material_regions": {
    "plush_fabric": [{"bbox": [x1, y1, x2, y2], "confidence": 0.8}],
    "sisal_rope": [{"bbox": [x1, y1, x2, y2], "confidence": 0.9}],
    "board_material": [{"bbox": [x1, y1, x2, y2], "confidence": 0.7}]
  },
  "occluded_or_uncertain_parts": ["back side platforms", "internal condo space"]
}

Be accurate with bounding boxes — they must correspond to real visible parts.
If a part is not visible, don't include it.
If a part is partially visible, mark confidence accordingly.
Output ONLY the JSON, no markdown code blocks."""

QUALITY_VERIFY_PROMPT = """You are an e-commerce image quality reviewer.

Analyze this generated product image and answer:

1. Is the product fully visible and not clipped?
2. Are there any checkerboard or transparent artifacts?
3. Is the product floating or properly grounded?
4. Does the product structure look distorted compared to what you'd expect?
5. For scene images: are the requested elements present?

Requested elements to check: {required_elements}

Return JSON:
{{
  "product_visible": true/false,
  "has_artifacts": true/false,
  "artifact_type": "none/checkerboard/white_block/cutout_edges",
  "is_grounded": true/false,
  "structure_distorted": true/false,
  "distortion_description": "",
  "detected_elements": ["cat", "child", ...],
  "missing_elements": ["element1", ...],
  "overall_quality": "pass/needs_review/fail",
  "issues": ["issue1", ...]
}}

Output ONLY the JSON, no markdown code blocks."""

SELLING_POINT_VERIFY_PROMPT = """You are an e-commerce selling point image reviewer.

This image is supposed to convey the selling point: "{selling_point}"
The annotation type is: {annotation_type}

Check:
1. Does the image clearly express this selling point?
2. Are the annotation markers (numbers, arrows, highlights) properly positioned on the relevant parts?
3. Is the product clearly visible?
4. Would a customer understand the selling point from this image?

Return JSON:
{{
  "selling_point_expressed": true/false,
  "annotations_positioned_correctly": true/false,
  "product_visible": true/false,
  "customer_understandable": true/false,
  "overall": "pass/needs_review/fail",
  "issues": []
}}

Output ONLY the JSON, no markdown code blocks."""


def _parse_json_response(text: str) -> dict:
    """Parse JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to find first { to last }
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                pass
    return {}


class ProductVisionAgent:
    """Analyzes product images using VLM to detect structural parts with bounding boxes."""

    def __init__(self, model: str | None = None):
        import config
        self.model = model or config.MODELS.get("quality", "gpt-5.2")

    def analyze(self, product_image: Image.Image) -> dict[str, Any]:
        """
        Analyze product structure using VLM.

        Returns structured analysis with bboxes for all detected parts.
        """
        console.print(f"[bold cyan]ProductVisionAgent:[/] 结构分析 - 使用 {self.model}", style="bold")

        try:
            response = chat(
                prompt=VISION_ANALYSIS_PROMPT,
                model=self.model,
                image=product_image,
                response_format="json",
            )
            analysis = _parse_json_response(response)
            if not analysis or "visible_parts" not in analysis:
                console.print("  ⚠️ VLM 返回不完整，使用 fallback 分析", style="yellow")
                analysis = self._fallback_analysis(product_image)
                analysis["source"] = "fallback"
            else:
                analysis["source"] = "vlm"
                console.print(f"  ✅ VLM 结构分析完成: {len(analysis.get('visible_parts', {}).get('platforms', []))} 个平台", style="green")
        except Exception as exc:
            console.print(f"  ⚠️ VLM 分析失败: {exc}，使用 fallback", style="yellow")
            analysis = self._fallback_analysis(product_image)
            analysis["source"] = "fallback"

        return analysis

    def verify_quality(
        self,
        image: Image.Image,
        required_elements: list[str] | None = None,
    ) -> dict[str, Any]:
        """Use VLM to verify image quality and element presence."""
        console.print(f"  [VisionAgent] 质量审核 - {self.model}")
        elements_str = ", ".join(required_elements or []) or "none specified"

        try:
            prompt = QUALITY_VERIFY_PROMPT.format(required_elements=elements_str)
            response = chat(prompt=prompt, model=self.model, image=image, response_format="json")
            result = _parse_json_response(response)
            if not result:
                return self._fallback_quality_check()
            return result
        except Exception as exc:
            console.print(f"  ⚠️ VLM 质量审核失败: {exc}", style="yellow")
            return self._fallback_quality_check()

    def verify_selling_point(
        self,
        image: Image.Image,
        selling_point: str,
        annotation_type: str,
    ) -> dict[str, Any]:
        """Use VLM to verify selling point expression."""
        try:
            prompt = SELLING_POINT_VERIFY_PROMPT.format(
                selling_point=selling_point,
                annotation_type=annotation_type,
            )
            response = chat(prompt=prompt, model=self.model, image=image, response_format="json")
            result = _parse_json_response(response)
            if not result:
                return {"overall": "manual_required", "issues": ["VLM parse failed"]}
            return result
        except Exception:
            return {"overall": "manual_required", "issues": ["VLM call failed"]}

    def _bbox_to_pixels(self, bbox_pct: list[float], image_size: tuple[int, int]) -> tuple[int, int, int, int]:
        """Convert percentage bbox [x1,y1,x2,y2] to pixel coordinates."""
        w, h = image_size
        return (
            int(bbox_pct[0] / 100 * w),
            int(bbox_pct[1] / 100 * h),
            int(bbox_pct[2] / 100 * w),
            int(bbox_pct[3] / 100 * h),
        )

    def _fallback_analysis(self, product_image: Image.Image) -> dict[str, Any]:
        """Fallback structural analysis using simple image processing — NOT VLM."""
        from pipeline.step4_enhance import _content_bbox
        w, h = product_image.size
        bbox = _content_bbox(product_image.convert("RGB"))
        bx1, by1, bx2, by2 = bbox
        bw = bx2 - bx1
        bh = by2 - by1

        def to_pct(x1, y1, x2, y2):
            return [round(x1/w*100, 1), round(y1/h*100, 1), round(x2/w*100, 1), round(y2/h*100, 1)]

        return {
            "product_bbox": to_pct(bx1, by1, bx2, by2),
            "overall_height_estimate": "tall",
            "structure_type": "multi-level cat tower",
            "visible_parts": {
                "platforms": [
                    {"name": "top platform", "bbox": to_pct(bx1+bw*0.3, by1, bx1+bw*0.7, by1+bh*0.12), "level": "top", "confidence": 0.4},
                    {"name": "upper perch", "bbox": to_pct(bx1+bw*0.15, by1+bh*0.12, bx1+bw*0.55, by1+bh*0.25), "level": "upper", "confidence": 0.4},
                    {"name": "mid condo top", "bbox": to_pct(bx1+bw*0.4, by1+bh*0.22, bx1+bw*0.8, by1+bh*0.36), "level": "mid-upper", "confidence": 0.4},
                    {"name": "mid platform", "bbox": to_pct(bx1+bw*0.25, by1+bh*0.40, bx1+bw*0.65, by1+bh*0.52), "level": "mid", "confidence": 0.4},
                    {"name": "lower rest", "bbox": to_pct(bx1+bw*0.45, by1+bh*0.55, bx1+bw*0.85, by1+bh*0.68), "level": "lower", "confidence": 0.4},
                    {"name": "bottom bed", "bbox": to_pct(bx1+bw*0.2, by1+bh*0.72, bx1+bw*0.65, by1+bh*0.85), "level": "bottom", "confidence": 0.4},
                ],
                "sisal_posts": [
                    {"name": "left post", "bbox": to_pct(bx1+bw*0.20, by1+bh*0.18, bx1+bw*0.30, by1+bh*0.65), "confidence": 0.4},
                    {"name": "center post", "bbox": to_pct(bx1+bw*0.42, by1+bh*0.15, bx1+bw*0.52, by1+bh*0.70), "confidence": 0.4},
                    {"name": "right post", "bbox": to_pct(bx1+bw*0.62, by1+bh*0.30, bx1+bw*0.72, by1+bh*0.80), "confidence": 0.4},
                ],
                "scratch_boards": [
                    {"name": "lower board", "bbox": to_pct(bx1+bw*0.15, by1+bh*0.70, bx1+bw*0.50, by1+bh*0.82), "confidence": 0.3},
                    {"name": "mid board", "bbox": to_pct(bx1+bw*0.45, by1+bh*0.52, bx1+bw*0.75, by1+bh*0.62), "confidence": 0.3},
                ],
                "base_area": {
                    "bbox": to_pct(bx1, by1+bh*0.82, bx2, by2),
                    "has_double_base": True,
                    "confidence": 0.4,
                },
                "hammock_area": [
                    {"name": "mid hammock", "bbox": to_pct(bx1+bw*0.30, by1+bh*0.42, bx1+bw*0.60, by1+bh*0.55), "confidence": 0.3},
                ],
                "condo_area": [
                    {"name": "enclosed condo", "bbox": to_pct(bx1+bw*0.35, by1+bh*0.25, bx1+bw*0.75, by1+bh*0.42), "confidence": 0.4},
                ],
                "ramp_area": [
                    {"name": "lower ramp", "bbox": to_pct(bx1+bw*0.10, by1+bh*0.60, bx1+bw*0.45, by1+bh*0.78), "confidence": 0.3},
                ],
                "hanging_toys": [],
            },
            "climbing_path": [
                {"from": "base", "to": "lower rest", "approximate_route": [
                    [round((bx1+bw*0.35)/w*100, 1), round((by1+bh*0.85)/h*100, 1)],
                    [round((bx1+bw*0.55)/w*100, 1), round((by1+bh*0.65)/h*100, 1)],
                ]},
                {"from": "lower rest", "to": "mid platform", "approximate_route": [
                    [round((bx1+bw*0.55)/w*100, 1), round((by1+bh*0.65)/h*100, 1)],
                    [round((bx1+bw*0.40)/w*100, 1), round((by1+bh*0.48)/h*100, 1)],
                ]},
                {"from": "mid platform", "to": "condo", "approximate_route": [
                    [round((bx1+bw*0.40)/w*100, 1), round((by1+bh*0.48)/h*100, 1)],
                    [round((bx1+bw*0.58)/w*100, 1), round((by1+bh*0.32)/h*100, 1)],
                ]},
                {"from": "condo", "to": "upper perch", "approximate_route": [
                    [round((bx1+bw*0.58)/w*100, 1), round((by1+bh*0.32)/h*100, 1)],
                    [round((bx1+bw*0.38)/w*100, 1), round((by1+bh*0.18)/h*100, 1)],
                ]},
                {"from": "upper perch", "to": "top platform", "approximate_route": [
                    [round((bx1+bw*0.38)/w*100, 1), round((by1+bh*0.18)/h*100, 1)],
                    [round((bx1+bw*0.50)/w*100, 1), round((by1+bh*0.06)/h*100, 1)],
                ]},
            ],
            "material_regions": {
                "plush_fabric": [{"bbox": to_pct(bx1+bw*0.25, by1+bh*0.35, bx1+bw*0.70, by1+bh*0.55), "confidence": 0.4}],
                "sisal_rope": [{"bbox": to_pct(bx1+bw*0.20, by1+bh*0.18, bx1+bw*0.30, by1+bh*0.65), "confidence": 0.4}],
                "board_material": [{"bbox": to_pct(bx1+bw*0.15, by1+bh*0.70, bx1+bw*0.50, by1+bh*0.82), "confidence": 0.3}],
            },
            "occluded_or_uncertain_parts": ["back side", "internal condo space", "base underside"],
        }

    def _fallback_quality_check(self) -> dict:
        return {
            "product_visible": True,
            "has_artifacts": False,
            "is_grounded": True,
            "structure_distorted": False,
            "overall_quality": "manual_required",
            "issues": ["VLM quality check not available; manual review required"],
        }
