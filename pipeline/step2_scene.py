"""
Step 2: 场景描述生成 - LLM 反推 + 用户输入
"""
import json
import re

from PIL import Image
from rich.console import Console

from models.llm import chat

console = Console()

SCENE_PROMPT_TEMPLATE = """你是一位专业的电商产品摄影师和场景设计师。
请根据以下产品信息，生成适合 Amazon 商品 listing 的场景图描述。

## 产品信息
- 产品名称：{product_name}
- 产品描述：{product_description}
- 核心卖点：
{selling_points}
- 目标人群：{target_audience}
- 产品定位：{positioning}

## 用户场景需求
{user_scene_requirements}

## 输出要求
请生成 {scene_count} 个不同的场景描述，每个场景描述应包含：
1. 环境设置（室内/室外、房间类型、装修风格）
2. 光线描述（自然光/人工光、方向、色温）
3. 产品在画面中的位置和角度
4. 配角元素（人物、宠物、装饰物等）
5. 整体色调和氛围
6. 特殊拍摄技巧（仰拍/俯拍/特写等）

请直接以 JSON 格式输出，不要用 markdown 代码块包裹，格式如下：
{{
    "scenes": [
        {{
            "name": "场景名称",
            "description_zh": "中文场景描述",
            "description_en": "English scene description for image generation prompt, must be very detailed and specific, at least 100 words",
            "key_elements": ["关键元素1", "关键元素2"],
            "mood": "情绪/氛围",
            "camera_angle": "拍摄角度"
        }}
    ]
}}
"""


def _parse_json_response(text: str) -> dict:
    """解析 LLM 返回的 JSON，兼容 markdown 代码块包裹"""
    # 去掉 markdown 代码块
    text = text.strip()
    match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if match:
        text = match.group(1).strip()
    return json.loads(text)


def generate_scene_descriptions(
    product_info: dict,
    user_requirements: str = "",
    scene_count: int = 3,
    model: str | None = None,
    product_image: Image.Image | None = None,
) -> list[dict]:
    """LLM 反推 + 用户输入 → 生成结构化场景描述"""
    console.print("[bold cyan]Step 2:[/] 场景描述生成 (LLM 反推)", style="bold")

    if model is None:
        import config
        model = config.MODELS.get("llm_primary", "gpt-5.2")

    selling_points_str = "\n".join(
        f"  - {sp}" for sp in product_info.get("selling_points", [])
    )

    prompt = SCENE_PROMPT_TEMPLATE.format(
        product_name=product_info.get("name", ""),
        product_description=product_info.get("description", ""),
        selling_points=selling_points_str,
        target_audience=product_info.get("target_audience", ""),
        positioning=product_info.get("positioning", ""),
        user_scene_requirements=user_requirements or "无额外要求",
        scene_count=scene_count,
    )

    console.print(f"  → 使用 {model} 分析产品并生成场景描述...")

    response = chat(prompt=prompt, model=model, image=product_image, response_format="json")

    try:
        result = _parse_json_response(response)
        scenes = result.get("scenes", [])
    except (json.JSONDecodeError, Exception) as e:
        console.print(f"  ⚠️ JSON 解析失败: {e}，尝试提取...", style="yellow")
        scenes = [{"name": "默认场景", "description_en": response[:500], "description_zh": response[:500]}]

    console.print(f"  ✅ 生成 {len(scenes)} 个场景描述", style="green")
    for i, scene in enumerate(scenes, 1):
        console.print(f"    {i}. {scene.get('name', '未命名')}: {scene.get('description_zh', '')[:60]}...")

    return scenes
