"""
Step 5: 多语言文案图层叠加
图层化处理：文案翻译 → 位置计算 → 文字渲染
"""
import json

from PIL import Image, ImageDraw, ImageFont
from rich.console import Console

from models.llm import chat
from config import MODELS

console = Console()

FONT_SIZES = {"title": 48, "subtitle": 36, "body": 28, "caption": 22}


def translate_text(texts: list[str], target_lang: str, model: str | None = None) -> list[str]:
    """翻译文案列表到目标语言"""
    if model is None:
        model = MODELS["translation"]

    prompt = f"""Translate to {target_lang} for e-commerce product listing.
Texts:
{chr(10).join(f'{i+1}. {t}' for i, t in enumerate(texts))}
Output JSON: {{"translations": ["text1", "text2", ...]}}"""

    response = chat(prompt=prompt, model=model, response_format="json")
    try:
        return json.loads(response).get("translations", texts)
    except json.JSONDecodeError:
        return texts


def add_text_overlay(image: Image.Image, texts: list[dict]) -> Image.Image:
    """在图片上添加文字图层"""
    console.print("[bold cyan]Step 5:[/] 文案图层叠加", style="bold")

    result = image.copy().convert("RGBA")
    txt_layer = Image.new("RGBA", result.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    for text_cfg in texts:
        content = text_cfg["content"]
        position = text_cfg.get("position", (100, 100))
        size = text_cfg.get("size", "body")
        color = text_cfg.get("color", (255, 255, 255, 255))
        anchor = text_cfg.get("anchor", "lt")

        font_size = FONT_SIZES.get(size, 28) if isinstance(size, str) else size
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

        draw.text(position, content, fill=color, font=font, anchor=anchor)

    result = Image.alpha_composite(result, txt_layer).convert("RGB")
    console.print(f"  ✅ 添加 {len(texts)} 条文案完成", style="green")
    return result
