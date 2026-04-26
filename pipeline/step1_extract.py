"""
Step 1: 白图修复 - 背景去除 / 透明底 / 白底图生成
"""
from collections import deque

from PIL import Image
from PIL import ImageFilter
from rich.console import Console

from models.gpt_image import edit_image, generate_image

console = Console()


def _has_useful_alpha(image: Image.Image) -> bool:
    """判断图片是否真的包含透明通道，而不是整张图 alpha 都是 255。"""
    if image.mode != "RGBA":
        return False
    alpha = image.getchannel("A")
    return alpha.getextrema()[0] < 245


def _is_background_candidate(pixel: tuple[int, int, int, int]) -> bool:
    """识别白底/透明底/模型烘焙棋盘格背景候选像素。"""
    r, g, b, a = pixel
    if a < 20:
        return True

    mx = max(r, g, b)
    mn = min(r, g, b)
    mean = (r + g + b) / 3

    near_white = r > 232 and g > 232 and b > 232
    neutral_checker = mean > 170 and (mx - mn) < 18
    light_gray_ui_bg = mean > 205 and (mx - mn) < 28
    return near_white or neutral_checker or light_gray_ui_bg


def clean_baked_background(image: Image.Image) -> Image.Image:
    """
    清理模型烘焙进去的白底/棋盘格背景。

    一些图像编辑模型不会返回真正透明通道，而是把透明背景画成白底或棋盘格。
    这里从画布边缘做连通域清理，只删除与边缘连通的背景候选像素，尽量保留商品主体。
    """
    rgba = image.convert("RGBA")
    if _has_useful_alpha(rgba):
        return rgba

    w, h = rgba.size
    pixels = rgba.load()
    visited = bytearray(w * h)
    mask = Image.new("L", (w, h), 255)
    mask_px = mask.load()
    queue: deque[tuple[int, int]] = deque()

    def push(x: int, y: int):
        idx = y * w + x
        if visited[idx]:
            return
        visited[idx] = 1
        if _is_background_candidate(pixels[x, y]):
            queue.append((x, y))

    for x in range(w):
        push(x, 0)
        push(x, h - 1)
    for y in range(h):
        push(0, y)
        push(w - 1, y)

    while queue:
        x, y = queue.popleft()
        mask_px[x, y] = 0
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h:
                push(nx, ny)

    mask = mask.filter(ImageFilter.GaussianBlur(radius=0.6))
    rgba.putalpha(mask)
    return rgba


def remove_background(product_image: Image.Image, model: str = "gpt-image-2") -> dict:
    """去除产品图背景，生成透明底图和白底图"""
    console.print(f"[bold cyan]Step 1:[/] 白图修复 - 使用 {model}", style="bold")

    prompt = (
        "Remove the background from this product image completely. "
        "Keep only the product itself with perfectly clean edges. "
        "Make the background fully transparent/white. "
        "Preserve all product details, colors, textures and proportions exactly as they are. "
        "Do not modify, distort or regenerate the product in any way."
    )

    results = edit_image(product_image, prompt, model=model)

    if not results:
        raise RuntimeError("抠图失败：模型未返回结果")

    transparent_img = clean_baked_background(results[0])
    white_bg = Image.new("RGBA", transparent_img.size, (255, 255, 255, 255))
    white_bg = Image.alpha_composite(white_bg, transparent_img)
    white_bg = white_bg.convert("RGB")

    console.print("  ✅ 背景去除完成", style="green")
    return {"transparent": transparent_img, "white_bg": white_bg}


def create_main_image(white_bg_image: Image.Image, target_size=(2000, 2000), fill_ratio=0.85) -> Image.Image:
    """生成 Amazon 首图（白底，产品占比 85%+）"""
    w, h = white_bg_image.size
    tw, th = target_size
    scale = min(tw * fill_ratio / w, th * fill_ratio / h)
    new_w, new_h = int(w * scale), int(h * scale)
    resized = white_bg_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", target_size, (255, 255, 255))
    canvas.paste(resized, ((tw - new_w) // 2, (th - new_h) // 2))
    console.print("  ✅ 白底首图生成完成", style="green")
    return canvas
