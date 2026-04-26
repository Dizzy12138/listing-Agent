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
    {
        "keywords": ["材质", "工艺", "绒布", "板材", "material", "texture", "plush", "fabric", "board"],
        "target_region": "material_texture",
        "crop_strategy": "vertical_middle_left",
        "annotation_title": "Material Close-Up",
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

    def crop_by_strategy(self, image: Image.Image, crop_strategy: str, variant: int = 0) -> Image.Image:
        rgba = image.convert("RGBA")
        content_box = self._content_bbox(rgba)
        content = rgba.crop(content_box)
        w, h = content.size
        offset = (variant % 3) * 0.04
        boxes = {
            "vertical_middle_left": (0.02 + offset, 0.12, 0.68 + offset, 0.92),
            "upper_platforms": (0.04, 0.02 + offset, 0.96, 0.68 + offset),
            "bottom_base": (0.04, 0.50 - offset, 0.96, 0.98),
            "full_vertical_path": (0.12 + offset, 0.02, 0.88 + offset, 0.98),
            "center_structure": (0.14 + offset, 0.10, 0.86 + offset, 0.90),
        }
        x1, y1, x2, y2 = boxes.get(crop_strategy, boxes["center_structure"])
        x1, y1, x2, y2 = max(0, x1), max(0, y1), min(1, x2), min(1, y2)
        box = (int(w * x1), int(h * y1), int(w * x2), int(h * y2))
        crop = content.crop(box)

        canvas = Image.new("RGBA", image.size, (255, 255, 255, 0))
        crop.thumbnail((int(image.width * 0.94), int(image.height * 0.94)), Image.Resampling.LANCZOS)
        canvas.paste(crop, ((image.width - crop.width) // 2, (image.height - crop.height) // 2), crop)
        return canvas

    def _content_bbox(self, image: Image.Image) -> tuple[int, int, int, int]:
        rgba = image.convert("RGBA")
        w, h = rgba.size
        px = rgba.load()
        xs: list[int] = []
        ys: list[int] = []
        step = max(1, min(w, h) // 500)
        for y in range(0, h, step):
            for x in range(0, w, step):
                r, g, b, a = px[x, y]
                if a > 25 and not (r > 242 and g > 242 and b > 242):
                    xs.append(x)
                    ys.append(y)
        if not xs:
            return (0, 0, w, h)
        pad = int(min(w, h) * 0.035)
        return max(0, min(xs) - pad), max(0, min(ys) - pad), min(w, max(xs) + pad), min(h, max(ys) + pad)
