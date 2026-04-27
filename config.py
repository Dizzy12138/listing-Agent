"""
批量生图平台 - 配置文件
模型路由策略与全局配置
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# --- API Keys ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# Auto-load settings.json if present (for CLI runs)
_settings_path = Path(__file__).parent / "settings.json"
if _settings_path.exists():
    import json as _json
    with open(_settings_path, "r", encoding="utf-8") as _f:
        _saved = _json.load(_f)
    _keys = _saved.get("api_keys", {})
    if _keys.get("openai_api_key"):
        OPENAI_API_KEY = _keys["openai_api_key"]
    if _keys.get("openai_base_url"):
        OPENAI_BASE_URL = _keys["openai_base_url"]
    if _keys.get("google_api_key"):
        GOOGLE_API_KEY = _keys["google_api_key"]


# --- Directories ---
BASE_DIR = Path(__file__).parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "./output"))
PRODUCTS_DIR = BASE_DIR / "products"

# --- Model Config ---
MODELS = {
    # 图像生成/编辑模型
    "image_primary": "gpt-image-2",
    "image_secondary": "gemini-3.1-flash-image-preview",

    # 文本/推理模型
    "llm_primary": "gemini-3.0-pro-preview",
    "llm_secondary": "gpt-5.2",

    # 翻译模型
    "translation": "gemma-4-31b-it",

    # 质量评估模型
    "quality": "gpt-5.2",
}

# --- Pipeline Config ---
PIPELINE = {
    # 每步生成候选数量
    "candidates_per_step": 2,
    # 质量检测阈值 (0-1)
    "quality_threshold": 0.85,
    # 最大重试次数
    "max_retries": 3,
    # 输出图片尺寸
    "output_sizes": {
        "main": (2000, 2000),      # Amazon 主图
        "detail": (1500, 1500),    # 细节图
    },
}

# --- Image Generation Config ---
IMAGE_GEN = {
    "gpt-image-2": {
        "default_size": "1024x1024",
        "quality": "high",
        "supported_sizes": ["1024x1024", "1024x1792", "1792x1024"],
    },
    "gemini-3.1-flash-image-preview": {
        "default_size": "1024x1024",
    },
}
