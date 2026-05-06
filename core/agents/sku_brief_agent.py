"""
SKUBriefAgent — extract stable product identity from SKU data + images.

Outputs a SKUBrief (product identity) NOT a prompt.
Uses VLM when available, fallback to structured extraction from SKU JSON.
"""
from __future__ import annotations

import json
import re

from PIL import Image
from rich.console import Console

from core.schemas.creative_brief import SKUBrief
from core.schemas.sku import SKU
from models.llm import chat

console = Console()

BRIEF_PROMPT = """You are a product analyst for e-commerce.

Analyze this product image and the provided SKU data to create a stable product identity brief.

SKU Data:
{sku_json}

Return a JSON object with EXACTLY this structure:
{{
  "sku_id": "{sku_id}",
  "product_type": "short product type description",
  "core_identity": ["list of visual features that define THIS specific product"],
  "target_audience": ["who buys this"],
  "must_show": ["what must be visible in commercial images"],
  "sku_consistency_rules": {{
    "strict": ["features that MUST match in every image"],
    "flexible": ["features that can vary slightly across images"]
  }}
}}

Focus on VISUAL identity — what makes this product recognizable across different images.
Output ONLY the JSON, no markdown code blocks."""


class SKUBriefAgent:
    """Extract stable product identity from SKU data + product images."""

    def __init__(self, model: str | None = None):
        import config
        self.model = model or config.MODELS.get("quality", "gpt-5.2")

    def generate_brief(
        self,
        sku: SKU,
        product_image: Image.Image | None = None,
        knowledge_context: dict | None = None,
    ) -> SKUBrief:
        """Generate SKUBrief from SKU data and optionally a product image."""
        console.print(f"[bold cyan]SKUBriefAgent:[/] 提取商品身份 - {sku.product_id}")
        knowledge_context = knowledge_context or {}

        sku_data = {
            "product_id": sku.product_id,
            "name": sku.name,
            "description": sku.description,
            "positioning": sku.positioning,
            "target_audience": sku.target_audience,
            "selling_points": sku.selling_points,
            "keywords": sku.keywords,
            "knowledge_category_path": knowledge_context.get("category_path", ""),
            "knowledge_global_rules": knowledge_context.get("global_rules", []),
            "knowledge_keyword_bank": knowledge_context.get("keyword_bank", []),
            "knowledge_replaceable_variables": knowledge_context.get("replaceable_variables", []),
        }

        try:
            prompt = BRIEF_PROMPT.format(
                sku_json=json.dumps(sku_data, ensure_ascii=False, indent=2),
                sku_id=sku.product_id,
            )
            response = chat(
                prompt=prompt,
                model=self.model,
                image=product_image,
                response_format="json",
            )
            data = self._parse_json(response)
            if data and "core_identity" in data:
                console.print(f"  ✅ VLM 商品身份提取: {len(data['core_identity'])} 个特征")
                return self._apply_knowledge_to_brief(SKUBrief(**data), knowledge_context)
        except Exception as exc:
            console.print(f"  ⚠️ VLM 提取失败: {exc}，使用 fallback", style="yellow")

        return self._fallback_brief(sku, knowledge_context)

    def _fallback_brief(self, sku: SKU, knowledge_context: dict | None = None) -> SKUBrief:
        """Structured extraction from SKU JSON without VLM."""
        console.print("  → fallback: 从 SKU JSON 直接提取商品身份")
        knowledge_context = knowledge_context or {}

        # Extract product type from name
        name = sku.name or ""
        desc = sku.description or ""
        combined = f"{name} {desc}".lower()

        product_type = name or "cat tree tower"
        core_identity = []
        if "205" in combined or "xxl" in combined:
            core_identity.append("tall 205cm XXL cat tree")
        if any(k in combined for k in ["grey", "gray", "灰"]):
            core_identity.append("grey plush fabric")
        if any(k in combined for k in ["sisal", "剑麻"]):
            core_identity.append("cream sisal posts")
        core_identity.extend(["multi-level structure", "condo houses", "hammock", "ramp", "wide stable double base"])

        must_show = ["large scale", "stable base", "multi-cat use", "scratching areas", "premium home setting"]
        for sp in sku.selling_points[:3]:
            if sp and sp not in must_show:
                must_show.append(sp[:50])

        brief = SKUBrief(
            sku_id=sku.product_id,
            product_type=product_type,
            core_identity=core_identity,
            target_audience=sku.target_audience.split(",") if isinstance(sku.target_audience, str) else ["cat owners", "families"],
            must_show=must_show,
            sku_consistency_rules={
                "strict": ["product type", "grey plush", "cream sisal", "multi-level", "cat condo", "hammock", "ramp"],
                "flexible": ["exact number of posts", "exact platform position", "minor perspective changes"],
            },
        )
        return self._apply_knowledge_to_brief(brief, knowledge_context)

    def _apply_knowledge_to_brief(self, brief: SKUBrief, knowledge_context: dict) -> SKUBrief:
        brief.knowledge_doc_ids = knowledge_context.get("knowledge_doc_ids", [])
        brief.knowledge_context = knowledge_context
        brief.knowledge_rules_used = knowledge_context.get("knowledge_rules_used", [])
        brief.negative_prompts_used = knowledge_context.get("negative_prompts_used", [])
        brief.standard_assets_used = knowledge_context.get("standard_asset_names", [])
        if knowledge_context.get("category_path"):
            label = f"category path: {knowledge_context['category_path']}"
            if label not in brief.core_identity:
                brief.core_identity.append(label)
        for keyword in (knowledge_context.get("keyword_bank") or [])[:12]:
            if keyword not in brief.core_identity:
                brief.core_identity.append(keyword)
        for rule in (knowledge_context.get("global_rules") or [])[:8]:
            if rule not in brief.must_show:
                brief.must_show.append(rule)
        for variable in (knowledge_context.get("replaceable_variables") or [])[:8]:
            label = f"replaceable variable: {variable}"
            if label not in brief.must_show:
                brief.must_show.append(label)
        for negative in (knowledge_context.get("negative_prompts") or [])[:12]:
            if negative not in brief.sku_consistency_rules["strict"]:
                brief.sku_consistency_rules["strict"].append(negative)
        return brief

    def _parse_json(self, text: str) -> dict:
        text = text.strip()
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find('{')
            end = text.rfind('}')
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return {}
