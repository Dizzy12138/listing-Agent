from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class ImagePlanItem(BaseModel):
    index: int
    type: str
    description: str
    view_type: str | None = None
    visual_goal: str | None = None
    required_elements: list[str] = Field(default_factory=list)
    forbidden_elements: list[str] = Field(default_factory=list)


class SceneRequirements(BaseModel):
    main_scene: str = ""
    visual_goals: list[str] = Field(default_factory=list)
    cat_breeds: list[str] = Field(default_factory=list)

    @field_validator("main_scene", mode="before")
    @classmethod
    def coerce_scene(cls, value: Any) -> str:
        if value is None:
            return ""
        return str(value)


class ViewStrategy(BaseModel):
    default_views: list[str] = Field(default_factory=lambda: [
        "front_open",
        "left_45",
        "right_45",
        "low_angle_hero",
        "detail_closeup",
    ])
    avoid_repeated_view: bool = True
    max_same_view_count: int = 1


class SKU(BaseModel):
    product_id: str
    name: str
    description: str = ""
    positioning: str = ""
    target_audience: str = ""
    selling_points: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    keyword_embedding: dict[str, str] = Field(default_factory=dict)
    scene_requirements: SceneRequirements = Field(default_factory=SceneRequirements)
    image_plan: list[ImagePlanItem] = Field(default_factory=list)
    competitors: list[str] = Field(default_factory=list)
    internal_refs: list[str] = Field(default_factory=list)
    knowledge_doc_ids: list[str] = Field(default_factory=list)
    asset_pack_ids: list[str] = Field(default_factory=list)
    standard_asset_item_ids: list[str] = Field(default_factory=list)
    inspiration_asset_ids: list[str] = Field(default_factory=list)
    view_strategy: ViewStrategy = Field(default_factory=ViewStrategy)

    @field_validator("scene_requirements", mode="before")
    @classmethod
    def coerce_scene_requirements(cls, value: Any) -> dict:
        if isinstance(value, str):
            return {"main_scene": value}
        if value is None:
            return {}
        return value
