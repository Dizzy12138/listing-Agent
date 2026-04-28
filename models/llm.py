"""
模型客户端 - 文本 LLM 封装
所有模型统一通过 OpenAI 兼容接口调用（支持网关路由）
"""
import base64
import io
import json

from PIL import Image


def _get_openai_client():
    import config
    from openai import OpenAI
    return OpenAI(api_key=config.OPENAI_API_KEY, base_url=config.OPENAI_BASE_URL, timeout=120.0)


def _image_to_base64(image: Image.Image) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def chat(
    prompt: str,
    model: str | None = None,
    image: Image.Image | None = None,
    response_format: str = "text",
) -> str:
    """
    统一 LLM 调用入口
    全部走 OpenAI 兼容网关，由网关负责路由到实际模型
    """
    import config
    if model is None:
        model = config.MODELS.get("llm_primary", "gpt-4o")

    client = _get_openai_client()

    content = []
    if image is not None:
        b64 = _image_to_base64(image)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    content.append({"type": "text", "text": prompt})

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": content}],
    }
    if response_format == "json":
        kwargs["response_format"] = {"type": "json_object"}

    print(f"  [LLM] 调用模型: {model}, base_url: {config.OPENAI_BASE_URL}")
    response = client.chat.completions.create(**kwargs)
    result = response.choices[0].message.content
    print(f"  [LLM] 返回 {len(result)} 字符")
    return result
