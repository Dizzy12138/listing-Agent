from __future__ import annotations

from pydantic import BaseModel


class ViewSpec(BaseModel):
    view_type: str
    camera_angle: str
    composition: str
    purpose: str
    strength: float = 0.7


CAT_TREE_VIEW_PRESETS: dict[str, ViewSpec] = {
    "front_open": ViewSpec(
        view_type="front_open",
        camera_angle="front view, slightly low angle",
        composition="full product, open structure visible",
        purpose="show full structure clearly",
        strength=0.65,
    ),
    "left_45": ViewSpec(
        view_type="left_45",
        camera_angle="left 45-degree angle",
        composition="show depth and layered platforms",
        purpose="show depth and layered structure",
        strength=0.7,
    ),
    "right_45": ViewSpec(
        view_type="right_45",
        camera_angle="right 45-degree angle",
        composition="show opposite side and avoid repeated product angle",
        purpose="avoid repeated product angle",
        strength=0.7,
    ),
    "low_angle_hero": ViewSpec(
        view_type="low_angle_hero",
        camera_angle="dramatic low-angle upward shot",
        composition="floor-to-ceiling hero composition",
        purpose="make the product look tall and impressive",
        strength=0.8,
    ),
    "detail_closeup": ViewSpec(
        view_type="detail_closeup",
        camera_angle="close-up macro view",
        composition="material detail, sisal rope, plush fabric, platform edges",
        purpose="show materials and details",
        strength=0.75,
    ),
}
