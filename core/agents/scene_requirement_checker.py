"""
SceneRequirementChecker — 场景元素合规检查器

从 scene_prompt 中解析出 required_elements，并与实际检测结果对比。
在没有 VLM 视觉审核模型的情况下，所有检测标记为 manual_required，
不允许自动 pass。
"""
from __future__ import annotations

import re
from typing import Any


# Mapping from canonical element names to keyword patterns that indicate
# the element is requested in the prompt.
ELEMENT_KEYWORD_MAP: dict[str, list[str]] = {
    "cats": ["cat", "cats", "maine coon", "feline", "kitten", "猫"],
    "child": ["child", "kid", "toddler", "小朋友", "儿童", "小孩"],
    "family_interaction": [
        "family", "interaction", "亲子", "互动", "parent",
    ],
    "low_angle": [
        "low angle", "low-angle", "仰拍", "底部", "upward",
        "floor-to-ceiling",
    ],
    "floor_contact": [
        "floor", "ground", "standing on", "grounded", "contact shadow",
        "落地", "接地",
    ],
    "luxury_living_room": [
        "luxury", "living room", "premium", "spacious", "豪华", "客厅",
        "大房子",
    ],
}


def extract_required_elements(scene_prompt: str) -> list[str]:
    """Parse a scene prompt and return canonical element names that are requested."""
    text = scene_prompt.lower()
    required: list[str] = []
    for element, keywords in ELEMENT_KEYWORD_MAP.items():
        if any(kw in text for kw in keywords):
            required.append(element)
    return required


def check_scene_requirements(
    scene_prompt: str,
    detected_elements: list[str] | None = None,
    has_vlm: bool = False,
) -> dict[str, Any]:
    """
    Check whether a scene image satisfies the elements demanded by the prompt.

    Parameters
    ----------
    scene_prompt : str
        The English scene description used for generation.
    detected_elements : list[str] | None
        Elements confirmed present in the image (by VLM or human).
        None means no detection has been performed.
    has_vlm : bool
        Whether a VLM model is available for automated detection.

    Returns
    -------
    dict with keys:
        required_elements, detected_elements, missing_elements, status
        status is one of: "pass", "needs_review", "fail", "manual_required"
    """
    required = extract_required_elements(scene_prompt)

    if detected_elements is None:
        # No detection has been performed — cannot auto-pass.
        return {
            "required_elements": required,
            "detected_elements": [],
            "missing_elements": required,  # all presumed missing
            "status": "manual_required",
            "reason": "no VLM detection performed; manual review required",
        }

    detected_set = set(detected_elements)
    missing = [e for e in required if e not in detected_set]

    if not missing:
        status = "pass"
        reason = "all required elements detected"
    elif has_vlm:
        status = "fail"
        reason = f"VLM confirmed missing elements: {missing}"
    else:
        status = "needs_review"
        reason = f"elements not confirmed: {missing}"

    return {
        "required_elements": required,
        "detected_elements": detected_elements,
        "missing_elements": missing,
        "status": status,
        "reason": reason,
    }
