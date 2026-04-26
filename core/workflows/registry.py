from __future__ import annotations

from typing import Type


WORKFLOW_REGISTRY: dict[str, Type] = {}


def register_workflow(key: str):
    def wrapper(cls):
        WORKFLOW_REGISTRY[key] = cls
        return cls
    return wrapper


def get_workflow(key: str):
    if key not in WORKFLOW_REGISTRY:
        raise KeyError(f"Workflow not registered: {key}")
    return WORKFLOW_REGISTRY[key]


ANNOTATION_KEYWORDS = {
    "休息",
    "区域",
    "动线",
    "攀爬",
    "路线",
    "底板",
    "稳定",
    "高亮",
    "编号",
    "rest",
    "platform",
    "climb",
    "path",
    "base",
    "stability",
}

DETAIL_MATERIAL_KEYWORDS = {
    "材质",
    "工艺",
    "绒布",
    "板材",
    "近景",
    "texture",
    "material",
    "plush",
    "fabric",
    "board",
}

SCRATCHING_KEYWORDS = {"抓挠", "剑麻", "猫抓", "scratch", "sisal", "rope"}


def resolve_workflow(image_type: str, description: str = "") -> str:
    normalized = image_type.lower()
    text = f"{normalized} {description}".lower()
    if normalized in {"white_bg", "main_white", "main_white_background"}:
        return "white_main"
    if normalized in {"scene_main", "main_scene", "scene_lifestyle", "lifestyle"}:
        return "scene_main"
    if normalized in {"selling_point", "feature_detail", "feature_detail_1", "feature_detail_2"}:
        if any(keyword.lower() in text for keyword in DETAIL_MATERIAL_KEYWORDS):
            return "detail_material"
        if any(keyword.lower() in text for keyword in ANNOTATION_KEYWORDS | SCRATCHING_KEYWORDS):
            return "selling_point_annotation"
        raise ValueError(f"Unsupported selling_point description: {description}")
    if normalized == "detail":
        return "detail_material"
    if normalized == "size_compare":
        return "size_compare"
    if normalized == "multilingual_text":
        return "multilingual_text"
    raise ValueError(f"Unsupported image_type: {image_type}")
