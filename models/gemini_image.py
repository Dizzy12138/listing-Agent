"""
模型客户端 - Gemini 图像模型封装
当 Google API Key 不可用时，回退到 OpenAI 兼容网关
"""
import io

from PIL import Image


def _has_google_key() -> bool:
    import config
    return bool(getattr(config, 'GOOGLE_API_KEY', ''))


def generate_image(prompt: str, n: int = 1) -> list[Image.Image]:
    """生成图像 - 优先 Google 直连，无 key 则走 OpenAI 网关"""
    if _has_google_key():
        return _generate_google(prompt, n)
    else:
        print("  [Gemini] Google API Key 未配置，走 OpenAI 网关 (gpt-image-2)")
        from models.gpt_image import generate_image as gpt_gen
        return gpt_gen(prompt, n=n)


def edit_image(image: Image.Image, prompt: str) -> list[Image.Image]:
    """编辑图像 - 优先 Google 直连，无 key 则走 OpenAI 网关"""
    if _has_google_key():
        return _edit_google(image, prompt)
    else:
        print("  [Gemini] Google API Key 未配置，走 OpenAI 网关 (gpt-image-2)")
        from models.gpt_image import edit_image as gpt_edit
        return gpt_edit(image, prompt)


def _generate_google(prompt: str, n: int = 1) -> list[Image.Image]:
    import config
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GOOGLE_API_KEY)
    images = []
    for _ in range(n):
        response = client.models.generate_content(
            model="gemini-3.1-flash-image-preview",
            contents=prompt,
            config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
        )
        for part in response.candidates[0].content.parts:
            if part.inline_data and part.inline_data.mime_type.startswith("image/"):
                img = Image.open(io.BytesIO(part.inline_data.data))
                images.append(img)
    return images


def _edit_google(image: Image.Image, prompt: str) -> list[Image.Image]:
    import config
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=config.GOOGLE_API_KEY)
    img_buffer = io.BytesIO()
    image.save(img_buffer, format="PNG")

    response = client.models.generate_content(
        model="gemini-3.1-flash-image-preview",
        contents=[types.Content(parts=[
            types.Part.from_bytes(data=img_buffer.getvalue(), mime_type="image/png"),
            types.Part.from_text(text=prompt),
        ])],
        config=types.GenerateContentConfig(response_modalities=["IMAGE"]),
    )

    images = []
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.mime_type.startswith("image/"):
            img = Image.open(io.BytesIO(part.inline_data.data))
            images.append(img)
    return images
