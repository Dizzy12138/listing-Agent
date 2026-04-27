"""
Creative Brief schemas — structured visual planning before generation.
"""
from __future__ import annotations
from pydantic import BaseModel, Field


class SKUBrief(BaseModel):
    """Stable product identity extracted from SKU data + images."""
    sku_id: str
    product_type: str = ""
    core_identity: list[str] = Field(default_factory=list)
    target_audience: list[str] = Field(default_factory=list)
    must_show: list[str] = Field(default_factory=list)
    sku_consistency_rules: dict = Field(default_factory=lambda: {"strict": [], "flexible": []})


class CreativeBrief(BaseModel):
    """Visual plan for a single image — NOT a prompt, but a design spec."""
    image_type: str  # hero_scene, lifestyle_scene, material_detail
    visual_goal: str = ""
    composition: str = ""
    scene: str = ""
    actors: list[str] = Field(default_factory=list)
    lighting: str = ""
    style: str = ""
    sku_consistency_level: str = "medium_high"  # high / medium_high / medium / low
    negative: list[str] = Field(default_factory=list)
    material_focus: str = ""  # For material_detail type


class CreativeBriefSet(BaseModel):
    """A collection of creative briefs for one SKU run."""
    sku_id: str
    sku_brief: SKUBrief
    briefs: list[CreativeBrief] = Field(default_factory=list)
