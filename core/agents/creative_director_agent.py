"""
CreativeDirectorAgent — generates visual plans (creative briefs) per image type.

Does NOT generate prompts directly. Outputs structured CreativeBrief objects
that downstream ImageGenerationAgent converts to model-specific prompts.
"""
from __future__ import annotations

import json
import re

from PIL import Image
from rich.console import Console

from core.schemas.creative_brief import CreativeBrief, CreativeBriefSet, SKUBrief
from models.llm import chat

console = Console()

DIRECTOR_PROMPT = """You are a Creative Director for premium e-commerce product photography.

Product Identity:
{sku_brief_json}

Generate creative briefs for these image types: {image_types}

For each image type, return a JSON object with this structure:
{{
  "image_type": "hero_scene",
  "visual_goal": "what this image should accomplish commercially",
  "composition": "camera angle, framing, product placement",
  "scene": "environment description",
  "actors": ["living beings in the scene"],
  "lighting": "lighting style",
  "style": "overall aesthetic reference",
  "sku_consistency_level": "high/medium_high/medium/low",
  "negative": ["things to avoid"]
}}

RULES:
- hero_scene: low-angle, dramatic height, luxury room, must feel premium and tall. Include a cat or child for scale. consistency=medium_high.
- lifestyle_scene: warm family moment, multi-cat or child interaction, cozy premium home. consistency=medium.
- material_detail: macro/closeup of specific materials. Generate 4 briefs for: plush_fabric, sisal_rope, board_ramp, cat_scratching_sisal.
- Apply knowledge_context.image_plan_templates, scene_rules, style_rules, negative_prompts and standard asset names from the Product Identity JSON whenever present.

Return a JSON array of creative briefs.
Output ONLY the JSON array, no markdown code blocks."""


# Fallback briefs when VLM is not available
FALLBACK_BRIEFS = {
    "hero_scene": CreativeBrief(
        image_type="hero_scene",
        visual_goal="make the product look tall, stable and premium — a showpiece in a luxury home",
        composition="low-angle wide shot, base close to bottom edge, floor-to-ceiling feeling of height",
        scene="luxury spacious living room with high ceiling, floor-to-ceiling windows, warm natural materials",
        actors=["one large Maine Coon cat resting on upper platform", "one child (age 5-7) standing nearby for scale reference"],
        lighting="warm natural daylight streaming through large windows, soft fill light",
        style="premium Amazon listing hero image, aspirational lifestyle photography",
        sku_consistency_level="medium_high",
        negative=["cutout look", "checkerboard artifacts", "white background residue", "floating base",
                  "office environment", "cheap apartment", "distorted proportions", "product too small in frame"],
    ),
    "lifestyle_scene": CreativeBrief(
        image_type="lifestyle_scene",
        visual_goal="show the product as part of a warm family life with pets — emotional connection",
        composition="medium shot from natural eye level, product occupying 40-60% of frame, room context visible",
        scene="cozy upscale family room in evening, warm ambient lighting, comfortable furnishings",
        actors=["two cats playing on different levels of the cat tree", "one child sitting nearby reading",
                "optional: parent in background on sofa"],
        lighting="warm evening ambient light, table lamps, cozy golden tones",
        style="lifestyle photography, editorial home magazine feel, candid family moment",
        sku_consistency_level="medium",
        negative=["studio look", "isolated product", "no living beings", "harsh lighting",
                  "cheap furniture", "messy room", "product floating"],
    ),
    "material_detail_plush": CreativeBrief(
        image_type="material_detail",
        visual_goal="showcase the premium soft plush fabric quality — tactile, luxurious feel",
        composition="extreme closeup macro shot of plush fabric surface, shallow depth of field",
        scene="product platform surface with soft studio lighting showing fabric texture",
        actors=[],
        lighting="soft diffused studio light, slight side light to reveal texture",
        style="material photography, textile closeup, commercial macro",
        sku_consistency_level="high",
        negative=["full product view", "distant shot", "blurry", "white background crop"],
        material_focus="plush_fabric",
    ),
    "material_detail_sisal": CreativeBrief(
        image_type="material_detail",
        visual_goal="showcase natural sisal rope wrapping — durable, natural, cat-friendly",
        composition="closeup of sisal-wrapped post, showing rope texture and wrapping pattern",
        scene="sisal post detail with warm lighting emphasizing natural fiber texture",
        actors=["optional: cat paw touching/scratching the sisal"],
        lighting="warm directional light revealing rope fiber detail",
        style="material closeup, natural fiber photography",
        sku_consistency_level="high",
        negative=["full product", "distant", "blurry texture", "white bg crop"],
        material_focus="sisal_rope",
    ),
    "material_detail_board": CreativeBrief(
        image_type="material_detail",
        visual_goal="showcase solid board construction — strong, reliable, well-finished edges",
        composition="closeup of ramp or platform edge showing board thickness and finish",
        scene="platform/ramp edge detail with studio lighting showing construction quality",
        actors=[],
        lighting="crisp studio light showing edge finish and material quality",
        style="construction detail photography, furniture quality documentation",
        sku_consistency_level="high",
        negative=["full product", "distant", "blurry"],
        material_focus="board_material",
    ),
    "material_detail_scratching": CreativeBrief(
        image_type="material_detail",
        visual_goal="show a cat actively using the sisal scratching post — action and durability",
        composition="medium-close shot of cat paw engaging with sisal post, dynamic angle",
        scene="cat actively scratching sisal post, showing the product in use",
        actors=["cat paw actively scratching sisal post"],
        lighting="natural warm light, action photography feel",
        style="pet action photography, product-in-use demonstration",
        sku_consistency_level="medium",
        negative=["static pose", "no cat", "distant shot"],
        material_focus="sisal_rope",
    ),
}


class CreativeDirectorAgent:
    """Generate visual plans (creative briefs) for each image type."""

    def __init__(self, model: str | None = None):
        import config
        self.model = model or config.MODELS.get("quality", "gpt-5.2")

    def plan(self, sku_brief: SKUBrief, image_types: list[str] | None = None) -> CreativeBriefSet:
        """Generate creative briefs for requested image types."""
        if image_types is None:
            image_types = ["hero_scene", "lifestyle_scene", "material_detail"]

        console.print(f"[bold cyan]CreativeDirector:[/] 生成视觉方案 - {image_types}")

        vlm_briefs = []
        try:
            vlm_briefs = self._vlm_plan(sku_brief, image_types)
            if vlm_briefs:
                console.print(f"  ✅ VLM 生成 {len(vlm_briefs)} 个 creative briefs")
        except Exception as exc:
            console.print(f"  ⚠️ VLM 规划失败: {exc}，使用 fallback", style="yellow")

        # Check which types are covered by VLM
        covered_types = set()
        for b in vlm_briefs:
            covered_types.add(b.image_type)

        # Supplement missing types with fallback briefs
        fallback_briefs = []
        for it in image_types:
            if it not in covered_types:
                fb = self._fallback_plan([it], sku_brief)
                fallback_briefs.extend(fb)
                console.print(f"  → fallback 补充: {it} ({len(fb)} briefs)")

        all_briefs = vlm_briefs + fallback_briefs
        if not all_briefs:
            all_briefs = self._fallback_plan(image_types, sku_brief)
            console.print(f"  → 全 fallback: 生成 {len(all_briefs)} 个 creative briefs")

        return CreativeBriefSet(sku_id=sku_brief.sku_id, sku_brief=sku_brief, briefs=all_briefs)

    def _vlm_plan(self, sku_brief: SKUBrief, image_types: list[str]) -> list[CreativeBrief]:
        prompt = DIRECTOR_PROMPT.format(
            sku_brief_json=json.dumps(sku_brief.model_dump(), ensure_ascii=False, indent=2),
            image_types=", ".join(image_types),
        )
        response = chat(prompt=prompt, model=self.model, response_format="json")
        data = self._parse_json_array(response)
        return [CreativeBrief(**item) for item in data if "image_type" in item]

    def _fallback_plan(self, image_types: list[str], sku_brief: SKUBrief | None = None) -> list[CreativeBrief]:
        briefs = []
        for it in image_types:
            if it == "hero_scene":
                briefs.append(FALLBACK_BRIEFS["hero_scene"].model_copy(deep=True))
            elif it == "lifestyle_scene":
                briefs.append(FALLBACK_BRIEFS["lifestyle_scene"].model_copy(deep=True))
            elif it == "material_detail":
                briefs.append(FALLBACK_BRIEFS["material_detail_plush"].model_copy(deep=True))
                briefs.append(FALLBACK_BRIEFS["material_detail_sisal"].model_copy(deep=True))
                briefs.append(FALLBACK_BRIEFS["material_detail_board"].model_copy(deep=True))
                briefs.append(FALLBACK_BRIEFS["material_detail_scratching"].model_copy(deep=True))
        return self._apply_knowledge_to_briefs(briefs, sku_brief)

    def _apply_knowledge_to_briefs(self, briefs: list[CreativeBrief], sku_brief: SKUBrief | None) -> list[CreativeBrief]:
        if not sku_brief:
            return briefs
        context = sku_brief.knowledge_context or {}
        for brief in briefs:
            brief.knowledge_doc_ids = sku_brief.knowledge_doc_ids
            brief.knowledge_rules_used = context.get("knowledge_rules_used", [])
            brief.negative_prompts_used = context.get("negative_prompts_used", [])
            brief.standard_assets_used = context.get("standard_asset_names", [])
            brief.checklist_used = context.get("checklist_used", [])
            for negative in (context.get("negative_prompts") or [])[:12]:
                if negative not in brief.negative:
                    brief.negative.append(negative)
            if context.get("scene_rules") and brief.image_type in {"hero_scene", "lifestyle_scene"}:
                brief.scene = f"{brief.scene}. Knowledge scene rules: {'; '.join(context['scene_rules'][:4])}"
            if context.get("style_rules"):
                brief.style = f"{brief.style}. Knowledge style rules: {'; '.join(context['style_rules'][:4])}"
            if context.get("image_plan_templates"):
                brief.visual_goal = f"{brief.visual_goal}. Follow applicable knowledge image plan templates where relevant."
        return briefs

    def _parse_json_array(self, text: str) -> list[dict]:
        text = text.strip()
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        try:
            result = json.loads(text)
            return result if isinstance(result, list) else [result]
        except json.JSONDecodeError:
            start = text.find('[')
            end = text.rfind(']')
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return []
