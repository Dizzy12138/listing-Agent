"""
Step 3: 场景图合成 - 背景生成 + 产品合成
核心：产品图不重绘，仅生成高质量背景再合成
"""
from PIL import Image
from rich.console import Console

from models.gpt_image import generate_image
from models.gpt_image import edit_image
from pipeline.step1_extract import clean_baked_background

console = Console()


def generate_background(
    scene_description: str,
    model: str = "gpt-image-2",
    size: str = "1536x1024",
    quality: str = "high",
    n: int = 1,
) -> list[Image.Image]:
    """根据场景描述生成高质量背景图（不含产品）"""
    console.print(f"[bold cyan]Step 3:[/] 场景背景生成 - {model} ({size}, {quality})", style="bold")

    enhanced_prompt = (
        f"{scene_description}. "
        "IMPORTANT: Leave a clear, prominent empty space in the center of the frame "
        "where a product will be placed later. "
        "Generate ONLY the room/background plate. "
        "No products, no cat trees, no cat tower, no scratching posts, no pet furniture, "
        "no product placeholder, no white square, no transparent checkerboard pattern. "
        "No furniture in the center. "
        "Professional commercial photography, photorealistic, "
        "studio-quality lighting, shallow depth of field, "
        "high-end interior design magazine quality, 8K resolution."
    )

    try:
        backgrounds = generate_image(
            prompt=enhanced_prompt,
            model=model,
            size=size,
            quality=quality,
            n=n,
        )
    except Exception as exc:  # pragma: no cover - depends on external model service
        console.print(f"  ⚠️ 背景生成失败，使用本地客厅背景 fallback: {exc}", style="yellow")
        backgrounds = [_fallback_living_room_background(size) for _ in range(n)]
    console.print(f"  ✅ 生成 {len(backgrounds)} 张候选背景", style="green")
    return backgrounds


def _fallback_living_room_background(size: str) -> Image.Image:
    from PIL import ImageDraw

    w, h = (1536, 1024)
    if "x" in size:
        try:
            w, h = [int(part) for part in size.split("x", 1)]
        except ValueError:
            pass
    img = Image.new("RGB", (w, h), "#efe7dc")
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, w, int(h * 0.62)), fill="#ead8c4")
    draw.rectangle((0, int(h * 0.62), w, h), fill="#d8c3aa")
    draw.rectangle((int(w * 0.67), 80, int(w * 0.94), int(h * 0.62)), fill="#f8fbff", outline="#2f3a46", width=8)
    for x in range(int(w * 0.70), int(w * 0.94), 92):
        draw.line((x, 80, x, int(h * 0.62)), fill="#2f3a46", width=4)
    draw.rectangle((int(w * 0.05), int(h * 0.52), int(w * 0.34), int(h * 0.64)), fill="#f6eadc")
    draw.rounded_rectangle((int(w * 0.66), int(h * 0.58), int(w * 0.96), int(h * 0.77)), radius=28, fill="#efe0cf")
    draw.ellipse((int(w * 0.10), int(h * 0.78), int(w * 0.88), int(h * 1.10)), fill="#f3eee8")
    return img


def composite_product_on_background(
    product_transparent: Image.Image,
    background: Image.Image,
    position: str = "center",
    scale_factor: float = 0.75,
    vertical_bias: float = 0.5,
) -> Image.Image:
    """将透明底产品图合成到背景上"""
    console.print("  → 合成产品到背景...", style="bold")

    bg = background.copy().convert("RGBA")
    bg_w, bg_h = bg.size

    prod = clean_baked_background(product_transparent)
    prod_w, prod_h = prod.size

    # 缩放产品图使其占背景的 scale_factor
    target_h = int(bg_h * scale_factor)
    ratio = target_h / prod_h
    target_w = int(prod_w * ratio)

    # 确保不超出背景宽度
    if target_w > bg_w * 0.9:
        target_w = int(bg_w * 0.9)
        ratio = target_w / prod_w
        target_h = int(prod_h * ratio)

    prod = prod.resize((target_w, target_h), Image.Resampling.LANCZOS)

    # 计算放置位置
    if position == "left":
        x = int(bg_w * 0.15)
    elif position == "right":
        x = int(bg_w * 0.85) - target_w
    else:
        x = (bg_w - target_w) // 2

    y = int((bg_h - target_h) * vertical_bias)

    # 合成
    bg.paste(prod, (x, y), prod)

    result = bg.convert("RGB")
    console.print("  ✅ 产品合成完成", style="green")
    return result


def has_checkerboard_artifact(image: Image.Image) -> bool:
    """
    检测明显的透明棋盘格/白色占位块烘焙问题。

    该检查只作为兜底：如果中央区域同时存在大量近白块和中灰块，
    且都呈低饱和中高亮度，通常说明透明底被当作普通图片贴进了场景。
    """
    rgb = image.convert("RGB")
    w, h = rgb.size

    def region_has_artifact(region: Image.Image) -> bool:
        pixels = list(region.resize((96, 96), Image.Resampling.BILINEAR).getdata())
        total = len(pixels)
        light = 0
        mid = 0
        neutral = 0
        for r, g, b in pixels:
            mx = max(r, g, b)
            mn = min(r, g, b)
            if mx - mn > 14:
                continue
            mean = (r + g + b) / 3
            if mean > 170:
                neutral += 1
            if mean > 235:
                light += 1
            elif 175 < mean < 225:
                mid += 1

        neutral_ratio = neutral / total
        light_ratio = light / total
        mid_ratio = mid / total
        small = region.resize((32, 32), Image.Resampling.BILINEAR).convert("L")
        vals = list(small.getdata())
        alternating = 0
        comparisons = 0
        for y in range(31):
            for x in range(31):
                idx = y * 32 + x
                v = vals[idx]
                for nidx in (idx + 1, idx + 32):
                    diff = abs(v - vals[nidx])
                    if 18 <= diff <= 70:
                        alternating += 1
                    comparisons += 1
        alternating_ratio = alternating / max(comparisons, 1)
        return (
            neutral_ratio > 0.42
            and light_ratio > 0.12
            and mid_ratio > 0.08
            and alternating_ratio > 0.30
        )

    # Full-frame tile scan. This catches baked checkerboards outside the center
    # and white/gray blocks introduced during product compositing.
    cols, rows = 4, 4
    hits = 0
    for row in range(rows):
        for col in range(cols):
            box = (
                int(w * col / cols),
                int(h * row / rows),
                int(w * (col + 1) / cols),
                int(h * (row + 1) / rows),
            )
            if region_has_artifact(rgb.crop(box)):
                hits += 1
    if hits >= 2:
        return True

    crop = rgb.crop((int(w * 0.15), int(h * 0.08), int(w * 0.85), int(h * 0.92)))
    pixels = list(crop.resize((160, 160), Image.Resampling.BILINEAR).getdata())
    total = len(pixels)
    light = 0
    mid = 0
    neutral = 0
    for r, g, b in pixels:
        mx = max(r, g, b)
        mn = min(r, g, b)
        if mx - mn > 12:
            continue
        mean = (r + g + b) / 3
        if mean > 175:
            neutral += 1
        if mean > 235:
            light += 1
        elif 175 < mean < 225:
            mid += 1

    neutral_ratio = neutral / total
    light_ratio = light / total
    mid_ratio = mid / total
    small = crop.resize((32, 32), Image.Resampling.BILINEAR).convert("L")
    vals = list(small.getdata())
    alternating = 0
    comparisons = 0
    for y in range(31):
        for x in range(31):
            idx = y * 32 + x
            v = vals[idx]
            for nidx in (idx + 1, idx + 32):
                diff = abs(v - vals[nidx])
                if 18 <= diff <= 70:
                    alternating += 1
                comparisons += 1
    alternating_ratio = alternating / max(comparisons, 1)
    return neutral_ratio > 0.40 and light_ratio > 0.16 and mid_ratio > 0.08 and alternating_ratio > 0.30


def image_edit_fusion(
    background: Image.Image,
    product_subject: Image.Image,
    rough_composite: Image.Image,
    scene_prompt: str,
    model: str = "gpt-image-2",
) -> tuple[Image.Image, list[str]]:
    """
    Fuse a rough product composite into the scene with an image-edit model.

    The current adapter sends the rough composite as the edit source because the
    local model wrapper supports single-image edits. Background/product are kept
    in the signature so the workflow contract already matches the production
    fusion step.
    """
    del background, product_subject
    prompt = (
        f"{scene_prompt}\n\n"
        "Edit this rough ecommerce composite into a realistic final scene. "
        "Keep the cat tree product structure, color, platform count and proportions basically unchanged. "
        "Remove any transparent checkerboard, gray-white blocks, cutout edges or white rectangles. "
        "Blend the product naturally into the living room with correct perspective. "
        "The product must stand on the floor and must not float. "
        "Add natural contact shadows under the base and match lighting direction to the room. "
        "If cats, child, family interaction or multi-cat usage are requested, include them naturally in the scene. "
        "Do not replace the product with a different cat tree."
    )
    try:
        results = edit_image(
            rough_composite,
            prompt=prompt,
            model=model,
            size="1536x1024",
            quality="high",
        )
    except Exception as exc:  # pragma: no cover - network/model failures are runtime dependent
        return rough_composite, [f"image_edit_fusion_failed: {exc}"]
    if not results:
        return rough_composite, ["image_edit_fusion_failed: no image returned"]
    fused = results[0].convert("RGB")
    issues: list[str] = []
    if has_checkerboard_artifact(fused):
        issues.append("image_edit_fusion_checkerboard_artifact")
    return fused, issues


def generate_scene_with_product(
    product_transparent: Image.Image,
    scene_description: str,
    model: str = "gpt-image-2",
    candidates: int = 1,
    position: str = "center",
    scale_factor: float = 0.75,
) -> list[Image.Image]:
    """完整的场景图生成：生成背景 → 合成产品"""
    # 使用 1536x1024 横版场景图
    backgrounds = generate_background(
        scene_description,
        model=model,
        size="1536x1024",
        quality="high",
        n=candidates,
    )

    results = []
    for i, bg in enumerate(backgrounds):
        console.print(f"  → 合成候选 {i+1}/{len(backgrounds)}...")
        composed = composite_product_on_background(
            product_transparent, bg,
            position=position,
            scale_factor=scale_factor,
        )
        if has_checkerboard_artifact(composed):
            console.print("  ⚠️ 检测到透明棋盘格/白块伪影，跳过该候选", style="yellow")
            continue
        results.append(composed)

    return results
