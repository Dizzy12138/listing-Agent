"""
Step 4: 光影渲染 + 细节图生成
"""
import re

from PIL import Image
from PIL import ImageDraw
from PIL import ImageFont
from rich.console import Console

from models.gpt_image import edit_image

console = Console()


def add_lighting_and_shadow(composed_image: Image.Image, model: str = "gpt-image-2") -> Image.Image:
    """为合成图添加自然的光影效果"""
    console.print(f"[bold cyan]Step 4a:[/] 光影渲染 - 使用 {model}", style="bold")

    prompt = (
        "Enhance this product scene photo with natural lighting and shadows. "
        "Add realistic shadows under and around the product. "
        "Match the product lighting to the environment. "
        "Keep the product exactly as it is - only add lighting effects."
    )

    results = edit_image(composed_image, prompt, model=model)
    if results:
        console.print("  ✅ 光影渲染完成", style="green")
        return results[0]
    return composed_image


def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """加载支持中英文的系统字体。"""
    font_candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc" if bold else "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in font_candidates:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _content_bbox(image: Image.Image) -> tuple[int, int, int, int]:
    """从白底商品图中找出非背景主体区域。"""
    rgb = image.convert("RGB")
    w, h = rgb.size
    px = rgb.load()
    xs = []
    ys = []
    step = max(1, min(w, h) // 500)
    for y in range(0, h, step):
        for x in range(0, w, step):
            r, g, b = px[x, y]
            if not (r > 242 and g > 242 and b > 242):
                xs.append(x)
                ys.append(y)
    if not xs:
        return (0, 0, w, h)
    pad = int(min(w, h) * 0.03)
    return (
        max(0, min(xs) - pad),
        max(0, min(ys) - pad),
        min(w, max(xs) + pad),
        min(h, max(ys) + pad),
    )


def _expand_box(box: tuple[int, int, int, int], image_size: tuple[int, int], pad_ratio: float = 0.08) -> tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    w, h = image_size
    pad = int(max(x2 - x1, y2 - y1) * pad_ratio)
    return max(0, x1 - pad), max(0, y1 - pad), min(w, x2 + pad), min(h, y2 + pad)


def _detail_box_for_selling_point(
    selling_point: str,
    content_box: tuple[int, int, int, int],
    image_size: tuple[int, int],
) -> tuple[int, int, int, int]:
    """用类目关键词把卖点映射到稳定的商品区域。"""
    x1, y1, x2, y2 = content_box
    bw = x2 - x1
    bh = y2 - y1
    text = selling_point.lower()

    if any(k in text for k in ["底板", "稳定", "base", "stable", "stability"]):
        box = (x1, y1 + int(bh * 0.58), x2, y2)
    elif any(k in text for k in ["剑麻", "抓", "scratch", "sisal", "post"]):
        box = (x1 + int(bw * 0.18), y1 + int(bh * 0.18), x1 + int(bw * 0.78), y1 + int(bh * 0.86))
    elif any(k in text for k in ["休息", "平台", "窝", "吊床", "rest", "platform", "hammock", "bed"]):
        box = (x1, y1, x2, y1 + int(bh * 0.68))
    elif any(k in text for k in ["尺寸", "体型", "大", "large", "xxl", "205"]):
        box = (x1, y1, x2, y2)
    elif any(k in text for k in ["动线", "攀爬", "路线", "route", "climb"]):
        box = (x1, y1 + int(bh * 0.22), x2, y1 + int(bh * 0.92))
    else:
        box = (x1, y1 + int(bh * 0.12), x2, y1 + int(bh * 0.78))

    return _expand_box(box, image_size)


def _fit_image(source: Image.Image, target_size: tuple[int, int], background=(255, 255, 255)) -> Image.Image:
    """等比缩放到目标框，不拉伸。"""
    tw, th = target_size
    src = source.convert("RGB")
    sw, sh = src.size
    scale = min(tw / sw, th / sh)
    nw, nh = max(1, int(sw * scale)), max(1, int(sh * scale))
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", target_size, background)
    canvas.paste(resized, ((tw - nw) // 2, (th - nh) // 2))
    return canvas


def _strip_index(text: str) -> str:
    return re.sub(r"^\s*\d+[\.、)\-]\s*", "", text).strip()


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font, max_width: int, max_lines: int) -> list[str]:
    """按显示宽度折行，适配中文无空格文本。"""
    lines: list[str] = []
    current = ""
    for char in text:
        test = current + char
        if draw.textlength(test, font=font) <= max_width:
            current = test
            continue
        if current:
            lines.append(current)
        current = char
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and draw.textlength(lines[-1], font=font) > max_width:
        while lines[-1] and draw.textlength(lines[-1] + "...", font=font) > max_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "..."
    return lines


def _description_for_selling_point(selling_point: str) -> str:
    text = selling_point.lower()
    if any(k in text for k in ["底板", "稳定", "base", "stable"]):
        return "加宽底部承托，提升大体型猫和多猫家庭使用时的稳定感。"
    if any(k in text for k in ["剑麻", "抓", "scratch", "sisal"]):
        return "抓挠区域集中展示，帮助买家快速理解耐抓材质与使用场景。"
    if any(k in text for k in ["休息", "平台", "窝", "吊床", "rest", "platform"]):
        return "多层休息空间清晰可见，适合多猫同时停留与互动。"
    if any(k in text for k in ["尺寸", "体型", "大", "large", "205"]):
        return "展示整体结构比例，突出 XXL 大尺寸和高承载视觉。"
    if any(k in text for k in ["动线", "攀爬", "路线", "climb"]):
        return "开放式攀爬路径更直观，体现活动路线和趣味性。"
    return "局部放大核心结构，让卖点在详情页中更容易被快速识别。"


def _make_detail_card(
    product_image: Image.Image,
    crop_box: tuple[int, int, int, int],
    selling_point: str,
    index: int,
    target_size: tuple[int, int] = (1500, 1500),
) -> Image.Image:
    """生成电商详情图卡片，而不是单纯裁切图。"""
    width, height = target_size
    card = Image.new("RGB", target_size, "#f4f7fb")
    draw = ImageDraw.Draw(card)

    title_font = _load_font(62, bold=True)
    body_font = _load_font(34)
    label_font = _load_font(28, bold=True)

    # Panels
    draw.rounded_rectangle((80, 88, 1420, 1040), radius=28, fill="#ffffff", outline="#d8dee6", width=3)
    draw.rounded_rectangle((80, 1090, 1420, 1418), radius=28, fill="#ffffff", outline="#d8dee6", width=3)
    draw.rounded_rectangle((106, 114, 950, 1014), radius=20, fill="#f8fafc")
    draw.rounded_rectangle((990, 114, 1394, 1014), radius=20, fill="#f8fafc")

    crop = product_image.crop(crop_box)
    crop_panel = _fit_image(crop, (820, 860), background=(248, 250, 252))
    card.paste(crop_panel, (118, 134))

    product_panel = _fit_image(product_image, (354, 760), background=(248, 250, 252))
    card.paste(product_panel, (1015, 180))

    draw.rounded_rectangle((118, 134, 938, 994), radius=18, outline="#2563eb", width=5)
    draw.rounded_rectangle((1015, 180, 1369, 940), radius=18, outline="#cbd5e1", width=2)

    draw.rounded_rectangle((122, 128, 360, 190), radius=31, fill="#2563eb")
    draw.text((154, 142), f"DETAIL {index:02d}", font=label_font, fill="#ffffff")
    draw.text((1035, 136), "FULL VIEW", font=label_font, fill="#64748b")

    title = _strip_index(selling_point)
    title_lines = _wrap_text(draw, title, title_font, 1180, 2)
    y = 1138
    for line in title_lines:
        draw.text((130, y), line, font=title_font, fill="#172033")
        y += 74

    desc = _description_for_selling_point(selling_point)
    for line in _wrap_text(draw, desc, body_font, 1180, 2):
        draw.text((132, y + 10), line, font=body_font, fill="#536173")
        y += 46

    return card


def generate_detail_crops(product_image: Image.Image, selling_points: list[str], model: str | None = None) -> list[dict]:
    """根据卖点生成稳定的详情页细节卡片。"""
    console.print("[bold cyan]Step 4b:[/] 细节图生成", style="bold")

    if not selling_points:
        selling_points = ["产品结构细节", "材质与做工细节", "底部稳定结构"]

    content_box = _content_bbox(product_image)
    details = []
    for i, selling_point in enumerate(selling_points[:6]):
        box = _detail_box_for_selling_point(selling_point, content_box, product_image.size)
        card = _make_detail_card(product_image, box, selling_point, i + 1)
        details.append({
            "selling_point": selling_point,
            "crop": card,
            "description": _description_for_selling_point(selling_point),
            "crop_box": box,
        })
        console.print(f"  ✅ 详情卡片 {i+1}: {selling_point[:30]}", style="green")

    return details
