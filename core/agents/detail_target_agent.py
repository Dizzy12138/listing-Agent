from __future__ import annotations


DETAIL_TARGET_RULES = [
    {
        "keywords": ["抓挠", "剑麻", "猫抓", "scratching", "sisal", "rope"],
        "target_region": "sisal_posts",
        "crop_strategy": "vertical_middle_left",
        "annotation_title": "Scratching System",
    },
    {
        "keywords": ["休息", "平台", "吊床", "窝", "rest", "platform", "hammock", "condo"],
        "target_region": "resting_platforms",
        "crop_strategy": "upper_platforms",
        "annotation_title": "Multi-Cat Resting Areas",
    },
    {
        "keywords": ["底板", "稳定", "base", "bottom", "stability"],
        "target_region": "bottom_base",
        "crop_strategy": "bottom_base",
        "annotation_title": "Stable Double Base",
    },
    {
        "keywords": ["动线", "攀爬", "路线", "ramp", "path", "climb"],
        "target_region": "climbing_path",
        "crop_strategy": "full_vertical_path",
        "annotation_title": "Climbing Route",
    },
]


class DetailTargetAgent:
    def resolve(self, description: str) -> dict:
        text = description.lower()
        for rule in DETAIL_TARGET_RULES:
            if any(keyword.lower() in text for keyword in rule["keywords"]):
                return {
                    "target_region": rule["target_region"],
                    "crop_strategy": rule["crop_strategy"],
                    "annotation_title": rule["annotation_title"],
                    "matched_keywords": [kw for kw in rule["keywords"] if kw.lower() in text],
                }
        return {
            "target_region": "general_structure",
            "crop_strategy": "center_structure",
            "annotation_title": "Product Detail",
            "matched_keywords": [],
        }
