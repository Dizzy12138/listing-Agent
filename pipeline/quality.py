"""
质量检测 Agent
使用 gpt-5.2 评估生成图片的质量
"""
import json

from PIL import Image
from rich.console import Console

from models.llm import chat
from config import MODELS, PIPELINE

console = Console()

QUALITY_PROMPT = """你是电商产品图片质量审核专家。请评估这张产品图片的质量。

评估维度（每项0-1分）：
1. product_consistency: 产品外观是否保真（颜色、形状、细节）
2. scene_quality: 场景是否自然、美观、符合产品定位
3. lighting_match: 光影是否自然、产品与场景光线是否匹配
4. composition: 构图是否合理、产品是否突出
5. overall: 整体质量评分

输出 JSON:
{{
    "scores": {{
        "product_consistency": 0.0,
        "scene_quality": 0.0,
        "lighting_match": 0.0,
        "composition": 0.0,
        "overall": 0.0
    }},
    "issues": ["问题1", "问题2"],
    "pass": true/false
}}"""


def check_quality(
    image: Image.Image,
    threshold: float | None = None,
) -> dict:
    """
    检测生成图片质量

    Returns:
        {"scores": {...}, "issues": [...], "pass": bool}
    """
    console.print("[bold cyan]质量检测:[/]", style="bold")

    if threshold is None:
        threshold = PIPELINE["quality_threshold"]

    model = MODELS["quality"]
    console.print(f"  → 使用 {model} 评估图片质量...")

    response = chat(prompt=QUALITY_PROMPT, model=model, image=image, response_format="json")

    try:
        result = json.loads(response)
        overall = result.get("scores", {}).get("overall", 0)
        result["pass"] = overall >= threshold
    except json.JSONDecodeError:
        result = {"scores": {"overall": 0}, "issues": ["质量检测解析失败"], "pass": False}

    status = "✅ 通过" if result["pass"] else "❌ 不通过"
    overall = result.get("scores", {}).get("overall", 0)
    console.print(f"  {status} (得分: {overall:.2f}, 阈值: {threshold})", 
                  style="green" if result["pass"] else "red")

    if result.get("issues"):
        for issue in result["issues"]:
            console.print(f"    ⚠️ {issue}", style="yellow")

    return result
