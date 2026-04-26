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


def resolve_workflow(image_type: str) -> str:
    normalized = image_type.lower()
    if normalized in {"white_bg", "main_white", "main_white_background"}:
        return "white_main"
    if normalized in {"scene_main", "main_scene", "scene_lifestyle", "lifestyle"}:
        return "scene_main"
    if normalized in {"selling_point", "feature_detail", "feature_detail_1", "feature_detail_2", "detail"}:
        return "detail"
    if normalized == "size_compare":
        return "size_compare"
    if normalized == "multilingual_text":
        return "multilingual_text"
    return "detail"
