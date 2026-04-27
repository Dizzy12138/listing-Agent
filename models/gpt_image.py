"""
模型客户端 - 统一图像生成/编辑封装
全部走 OpenAI 兼容网关
严格按照 gpt-image-2 / gemini-3.1-flash-image-preview 的 API 规范调用
"""
import base64
import io

from openai import OpenAI
from PIL import Image


def _get_client() -> OpenAI:
    import config
    return OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL)


def generate_image(
    prompt: str,
    model: str = "gpt-image-2",
    size: str = "1536x1024",
    quality: str = "high",
    n: int = 1,
) -> list[Image.Image]:
    """
    文生图接口 - POST /v1/images/generations
    
    size 推荐值:
      - 横版场景图: 1536x1024 或 1792x1024
      - 正方形: 1024x1024
      - 竖版: 1024x1536
      - 高清大图: 2048x2048
    quality: low / medium / high
    """
    import config
    print(f"  [ImageGen] model={model}, size={size}, quality={quality}, n={n}")
    client = _get_client()

    kwargs = {
        "model": model,
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "n": n,
    }

    # gpt-image-2 支持 output_format
    if model == "gpt-image-2":
        kwargs["output_format"] = "png"

    result = client.images.generate(**kwargs)

    images = []
    for item in result.data:
        if item.b64_json:
            img_bytes = base64.b64decode(item.b64_json)
            img = Image.open(io.BytesIO(img_bytes))
            images.append(img)
        elif item.url:
            import httpx
            resp = httpx.get(item.url, timeout=60)
            img = Image.open(io.BytesIO(resp.content))
            images.append(img)

    print(f"  [ImageGen] 返回 {len(images)} 张图片, 尺寸: {[img.size for img in images]}")
    return images


def edit_image(
    image: Image.Image,
    prompt: str,
    model: str = "gpt-image-2",
    size: str = "1024x1024",
    quality: str = "high",
) -> list[Image.Image]:
    """
    图生图/编辑接口 - POST /v1/images/edits

    注意: gpt-image-2 不支持 transparent background
    """
    import config
    print(f"  [ImageEdit] model={model}, size={size}, quality={quality}")
    client = _get_client()

    # 转换图片为 PNG bytes
    img_buffer = io.BytesIO()
    image.save(img_buffer, format="PNG")
    img_bytes = img_buffer.getvalue()

    kwargs = {
        "model": model,
        "image": img_bytes,
        "prompt": prompt,
        "size": size,
        "n": 1,
    }

    # quality 参数 — some gateways don't support quality for edits
    # Try without quality to avoid 400 errors

    result = client.images.edit(**kwargs)

    images = []
    for item in result.data:
        if item.b64_json:
            decoded = base64.b64decode(item.b64_json)
            img = Image.open(io.BytesIO(decoded))
            images.append(img)
        elif item.url:
            import httpx
            resp = httpx.get(item.url, timeout=60)
            img = Image.open(io.BytesIO(resp.content))
            images.append(img)

    print(f"  [ImageEdit] 返回 {len(images)} 张图片")
    return images
