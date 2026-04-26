from __future__ import annotations

from PIL import Image


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

    def crop_by_strategy(self, image: Image.Image, crop_strategy: str) -> Image.Image:
        rgba = image.convert("RGBA")
        w, h = rgba.size
        boxes = {
            "vertical_middle_left": (0.02, 0.12, 0.68, 0.92),
            "upper_platforms": (0.04, 0.02, 0.96, 0.68),
            "bottom_base": (0.04, 0.50, 0.96, 0.98),
            "full_vertical_path": (0.12, 0.02, 0.88, 0.98),
            "center_structure": (0.14, 0.10, 0.86, 0.90),
        }
        x1, y1, x2, y2 = boxes.get(crop_strategy, boxes["center_structure"])
        box = (int(w * x1), int(h * y1), int(w * x2), int(h * y2))
        crop = rgba.crop(box)

        canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 0))
        crop.thumbnail((int(w * 0.94), int(h * 0.94)), Image.Resampling.LANCZOS)
        canvas.paste(crop, ((w - crop.width) // 2, (h - crop.height) // 2), crop)
        return canvas
