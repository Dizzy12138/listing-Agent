"""
批量生图平台 - Web 服务端
FastAPI 后端，提供 API + 静态页面
"""
import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from config import OUTPUT_DIR, PRODUCTS_DIR
from agents.visual_runtime import VisualAgentRuntime

app = FastAPI(title="电商批量生图平台", version="1.0.0")

# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/output", StaticFiles(directory="output"), name="output")
app.mount("/products", StaticFiles(directory="products"), name="products")

# 任务存储 (PoC 阶段用内存，后续可换 Redis/DB)
tasks: dict = {}
agent_runtime = VisualAgentRuntime(PRODUCTS_DIR, OUTPUT_DIR)


# --- Models ---
class ProductConfig(BaseModel):
    product_id: str
    name: str
    description: str = ""
    positioning: str = ""
    target_audience: str = ""
    selling_points: list[str] = []
    keywords: list[str] = []
    scene_requirements: str = ""
    image_plan: list[dict] = []
    competitors: list[str] = []
    internal_refs: list[str] = []


class TaskStatus(BaseModel):
    task_id: str
    product_id: str
    status: str  # pending, running, step1, step2, step3, step4, step5, quality, done, error
    current_step: str = ""
    progress: int = 0
    created_at: str = ""
    images: list[dict] = []
    error: str = ""


class AgentRunCreate(BaseModel):
    sku_id: str
    objective: str = "生成电商商品图"
    image_types: list[str] = []
    languages: list[str] = []


class AgentRunAnswers(BaseModel):
    answers: dict[str, str] = {}


# --- Routes ---
@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.get("/api/products")
async def list_products():
    """获取所有产品配置"""
    products = []
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    for f in PRODUCTS_DIR.glob("*.json"):
        with open(f, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            image_url = _find_product_image(data.get("product_id", ""))
            if image_url:
                data["image_url"] = image_url
            products.append(data)
    return {"products": products}


@app.get("/api/products/{product_id}")
async def get_product(product_id: str):
    """获取单个产品配置"""
    path = PRODUCTS_DIR / f"{product_id.lower()}.json"
    if not path.exists():
        raise HTTPException(404, "产品不存在")
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    image_url = _find_product_image(data.get("product_id", ""))
    if image_url:
        data["image_url"] = image_url
    return data


@app.post("/api/products")
async def create_product(config: ProductConfig):
    """创建/更新产品配置"""
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    path = PRODUCTS_DIR / f"{config.product_id.lower()}.json"
    data = config.model_dump()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return {"status": "ok", "product_id": config.product_id}


@app.post("/api/products/{product_id}/image")
async def upload_product_image(product_id: str, file: UploadFile = File(...)):
    """上传产品原图"""
    upload_dir = PRODUCTS_DIR / "images"
    upload_dir.mkdir(parents=True, exist_ok=True)

    ext = Path(file.filename).suffix or ".png"
    save_path = upload_dir / f"{product_id.lower()}{ext}"

    with open(save_path, "wb") as f:
        content = await file.read()
        f.write(content)

    return {"status": "ok", "path": str(save_path), "filename": file.filename}


@app.get("/api/agent-blueprint")
async def get_agent_blueprint():
    """获取 Agent 工作台蓝图。"""
    return agent_runtime.blueprint()


@app.get("/api/agent-runs")
async def list_agent_runs():
    """获取 Agent Run 列表。"""
    return {"runs": agent_runtime.list_runs()}


@app.post("/api/agent-runs")
async def create_agent_run(body: AgentRunCreate):
    """创建一次 SKU 视觉生产 Agent Run。"""
    try:
        run = agent_runtime.start_run(
            sku_id=body.sku_id,
            objective=body.objective,
            image_types=body.image_types,
            languages=body.languages,
        )
        return run
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.get("/api/agent-runs/{run_id}")
async def get_agent_run(run_id: str):
    """获取单个 Agent Run。"""
    run = agent_runtime.get_run(run_id)
    if not run:
        raise HTTPException(404, "Agent Run 不存在")
    return run


@app.post("/api/agent-runs/{run_id}/answers")
async def answer_agent_run(run_id: str, body: AgentRunAnswers):
    """提交 Inversion 阶段的澄清回答。"""
    try:
        return agent_runtime.answer_run(run_id, body.answers)
    except ValueError as e:
        raise HTTPException(404, str(e))


@app.post("/api/agent-runs/{run_id}/launch-generation")
async def launch_agent_generation(run_id: str):
    """从 Agent Run 的 Pipeline 节点发起真实生图任务。"""
    run = agent_runtime.get_run(run_id)
    if not run:
        raise HTTPException(404, "Agent Run 不存在")
    if run.get("status") != "ready_for_generation":
        raise HTTPException(400, "Agent Run 尚未通过计划预审")
    payload = run.get("artifacts", {}).get("launch_payload", {})
    result = _create_generation_task(
        product_id=payload.get("product_id") or run["sku_id"],
        model=payload.get("model", "gpt-image-2"),
        scene_count=int(payload.get("scene_count", 3)),
    )
    run["status"] = "generation_launched"
    run["artifacts"]["generation_task"] = result
    run["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return {"run": run, "task": result}


@app.post("/api/tasks")
async def create_task(
    product_id: str = Form(...),
    model: str = Form("gpt-image-2"),
    scene_count: int = Form(3),
):
    """创建生图任务"""
    return _create_generation_task(product_id=product_id, model=model, scene_count=scene_count)


def _create_generation_task(product_id: str, model: str = "gpt-image-2", scene_count: int = 3):
    """创建并启动生图任务，可由 API 或 Agent Run 复用。"""
    # 检查产品配置
    prod_path = PRODUCTS_DIR / f"{product_id.lower()}.json"
    if not prod_path.exists():
        raise HTTPException(404, "产品配置不存在")

    # 检查产品图
    img_dir = PRODUCTS_DIR / "images"
    img_path = None
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        p = img_dir / f"{product_id.lower()}{ext}"
        if p.exists():
            img_path = p
            break

    if img_path is None:
        raise HTTPException(400, "请先上传产品图片")

    task_id = str(uuid.uuid4())[:8]
    task = TaskStatus(
        task_id=task_id,
        product_id=product_id,
        status="pending",
        current_step="等待执行",
        progress=0,
        created_at=datetime.now().isoformat(),
    )
    tasks[task_id] = task.model_dump()
    tasks[task_id]["model"] = model
    tasks[task_id]["scene_count"] = scene_count
    tasks[task_id]["image_path"] = str(img_path)

    # 后台执行 Pipeline
    import threading
    threading.Thread(target=_run_task_real, args=(task_id,), daemon=True).start()

    return {"task_id": task_id, "status": "created"}


def _update_task(task_id: str, **kwargs):
    """更新任务状态"""
    if task_id in tasks:
        tasks[task_id].update(kwargs)


def _run_task_real(task_id: str):
    """配置驱动的 Agent/Workflow 执行（后台线程）"""
    import traceback
    task = tasks[task_id]
    product_id = task["product_id"]
    model = task.get("model", "gpt-image-2")
    img_path = Path(task["image_path"])
    generated_images: list[dict] = []

    try:
        from core.services.generation_service import GenerationService

        def progress(message: str, value: int):
            _update_task(task_id, status="running", current_step=message, progress=value)

        result = GenerationService().execute_run(
            product_id=product_id,
            product_image_path=img_path,
            model=model,
            run_id=f"task_{task_id}",
            progress=progress,
        )
        out_dir = Path(result["output_dir"])
        for artifact in result["artifacts"]:
            path = Path(artifact["path"])
            if path.suffix.lower() != ".png":
                continue
            generated_images.append({
                "name": artifact["name"],
                "filename": path.name,
                "type": artifact["type"],
                "job_id": artifact.get("job_id"),
                "metadata": artifact.get("metadata", {}),
            })

        _update_task(task_id,
            status="done",
            current_step="完成",
            progress=100,
            output_dir=str(out_dir),
            images=generated_images,
            jobs=result["jobs"],
            traces=result["traces"],
        )

    except Exception as e:
        traceback.print_exc()
        _update_task(task_id,
            status="error",
            current_step=f"Agent Workflow 错误: {str(e)}",
            progress=0,
            output_dir="",
            images=generated_images,
            error=str(e),
        )


@app.get("/api/tasks")
async def list_tasks():
    """获取所有任务"""
    return {"tasks": list(tasks.values())}


def _load_products() -> list[dict]:
    """读取所有 SKU 配置。"""
    products = []
    PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
    for f in PRODUCTS_DIR.glob("*.json"):
        with open(f, "r", encoding="utf-8") as fh:
            products.append(json.load(fh))
    return products


def _find_product_image(product_id: str) -> str:
    """查找 SKU 原始商品图。"""
    img_dir = PRODUCTS_DIR / "images"
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        p = img_dir / f"{product_id.lower()}{ext}"
        if p.exists():
            return f"/products/images/{p.name}"
    return ""


@app.get("/api/dashboard")
async def platform_dashboard():
    """SKU 视觉生产操作系统看板聚合数据。"""
    products = _load_products()
    task_values = list(tasks.values())
    output_dirs = [p for p in OUTPUT_DIR.glob("*") if p.is_dir()] if OUTPUT_DIR.exists() else []
    generated_count = sum(len(t.get("images", [])) for t in task_values)
    generated_count += len(list(OUTPUT_DIR.glob("*/*.png"))) if OUTPUT_DIR.exists() else 0
    done_count = sum(1 for t in task_values if t.get("status") == "done")
    review_count = sum(1 for t in task_values if t.get("status") in ["done", "quality", "待审核"])

    return {
        "stats": {
            "sku_count": len(products),
            "task_count": len(task_values) or len(output_dirs),
            "done_count": done_count or len(output_dirs),
            "asset_count": generated_count,
            "review_count": review_count or len(output_dirs),
        },
        "pipeline": [
            {"name": "SKU 数据层", "status": "active"},
            {"name": "商品理解 Agent", "status": "ready"},
            {"name": "视觉策略 Agent", "status": "ready"},
            {"name": "Prompt / 工作流生成 Agent", "status": "active"},
            {"name": "多模型调度 Agent", "status": "configured"},
            {"name": "图片生成执行层", "status": "running"},
            {"name": "质量评估 Agent", "status": "partial"},
            {"name": "人工审核 / 结果入库", "status": "ready"},
        ],
    }


@app.get("/api/assets")
async def list_assets():
    """按 SKU 汇总图片资产库。"""
    products = _load_products()
    assets = []
    for p in products:
        sku = p.get("product_id", "")
        sku_assets = []
        raw_image = _find_product_image(sku)
        if raw_image:
            sku_assets.append({"type": "原始图", "name": f"{sku} 原始商品图", "url": raw_image})

        if OUTPUT_DIR.exists():
            for out_dir in sorted(OUTPUT_DIR.glob(f"{sku}_*"), reverse=True):
                for img in sorted(out_dir.glob("*.png")):
                    asset_type = "最终成品图"
                    if "transparent" in img.name:
                        asset_type = "透明底图"
                    elif "white" in img.name:
                        asset_type = "白底图"
                    elif "detail" in img.name:
                        asset_type = "细节图"
                    elif "scene" in img.name:
                        asset_type = "场景图"
                    sku_assets.append({
                        "type": asset_type,
                        "name": img.name,
                        "url": f"/output/{out_dir.name}/{img.name}",
                    })
                if sku_assets:
                    break

        assets.append({
            "sku_id": sku,
            "name": p.get("name", ""),
            "asset_count": len(sku_assets),
            "assets": sku_assets[:12],
        })
    return {"assets": assets}


@app.get("/api/workflows")
async def list_workflows():
    """工作流模板中心。"""
    return {
        "workflows": [
            {
                "id": "cat_tree_main_scene",
                "name": "电商首图模板",
                "category": "猫爬架 / 家具",
                "usage": "白底图 / 场景首图",
                "nodes": ["读取 SKU 主体资产", "生成场景策略", "主体迁移", "光影融合", "质检", "入库"],
                "priority": "P0",
            },
            {
                "id": "detail_selling_points",
                "name": "详情页卖点模板",
                "category": "通用商品",
                "usage": "结构、功能、尺寸展示",
                "nodes": ["读取卖点", "裁切细节", "生成标注文案", "排版导出", "审核"],
                "priority": "P0",
            },
            {
                "id": "lifestyle_scene",
                "name": "生活方式图模板",
                "category": "宠物用品 / 家居",
                "usage": "用户、宠物、家庭场景",
                "nodes": ["生成场景底图", "主体融合", "人物/宠物关系校准", "边缘修复", "质检"],
                "priority": "P1",
            },
            {
                "id": "multilingual_text",
                "name": "多语言文案模板",
                "category": "跨境电商",
                "usage": "海外站点多国文案",
                "nodes": ["识别文案图层", "翻译", "字体适配", "替换文字", "导出版本"],
                "priority": "P1",
            },
        ]
    }


@app.get("/api/agents")
async def list_agents():
    """Agent 配置中心。"""
    return {
        "agents": [
            {
                "name": "SKU 理解 Agent",
                "status": "ready",
                "goal": "把原始商品资料转换成稳定、可复用的 SKU 结构化对象。",
                "inputs": ["SKU 编号", "标题", "类目", "详情页", "卖点", "关键词", "竞品链接"],
                "tools": ["category_taxonomy", "feature_normalizer", "keyword_mapper"],
                "memory": ["category vocabulary", "brand positioning history"],
                "guardrails": ["不得编造不存在的卖点", "无法确认的字段标记为 unknown"],
                "evals": ["字段完整率", "卖点归一化准确率", "类目一致性"],
                "config": ["字段抽取规则", "类目词库", "卖点归一化"],
                "output": "结构化 SKU 对象",
            },
            {
                "name": "商品资产处理 Agent",
                "status": "active",
                "goal": "为后续所有图片生产建立同一套标准主体资产。",
                "inputs": ["原始商品图", "白底图", "历史成品图"],
                "tools": ["background_remover", "mask_generator", "asset_versioner"],
                "memory": ["SKU asset manifest", "approved master asset"],
                "guardrails": ["不得改变商品结构", "主体比例偏差超过阈值需进入审核"],
                "evals": ["主体完整度", "边缘质量", "比例一致性"],
                "config": ["主体识别", "背景去除", "透明底生成", "主体 Mask"],
                "output": "标准主体资产",
            },
            {
                "name": "视觉策略 Agent",
                "status": "ready",
                "goal": "决定 SKU 应该生成哪些图，以及每张图表达什么商业目标。",
                "inputs": ["结构化 SKU", "类目模板", "目标平台", "用户画像", "竞品参考"],
                "tools": ["image_plan_template", "competitor_style_analyzer", "platform_spec_resolver"],
                "memory": ["category image playbook", "brand visual rules"],
                "guardrails": ["图片计划必须覆盖核心卖点", "禁止与平台规则冲突"],
                "evals": ["卖点覆盖率", "图片类型完整率", "平台规格匹配度"],
                "config": ["图片类型", "场景模板", "平台规格", "品牌规范"],
                "output": "Image Plan",
            },
            {
                "name": "Prompt 生成 Agent",
                "status": "active",
                "goal": "把卖点转成模型可执行、可控、可质检的提示词。",
                "inputs": ["SKU 对象", "Image Plan", "负面约束", "品牌语气"],
                "tools": ["visual_language_mapper", "prompt_template_renderer", "negative_prompt_builder"],
                "memory": ["prompt examples", "failed prompt patterns"],
                "guardrails": ["禁止提示词要求模型重绘商品结构", "必须包含主体一致性禁止项"],
                "evals": ["提示词可控性", "禁止项覆盖率", "视觉目标清晰度"],
                "config": ["Prompt 模板", "视觉语言映射", "负面词"],
                "output": "模型提示词",
            },
            {
                "name": "工作流编排 Agent",
                "status": "active",
                "goal": "把图片生产拆解成可追踪、可重试的节点任务。",
                "inputs": ["Image Plan", "工作流模板", "模型策略", "资产清单"],
                "tools": ["workflow_engine", "retry_policy", "task_queue"],
                "memory": ["workflow run history", "node failure reasons"],
                "guardrails": ["节点失败必须记录原因", "重试不得覆盖已通过资产"],
                "evals": ["节点成功率", "平均耗时", "重试有效率"],
                "config": ["节点顺序", "重试策略", "失败兜底"],
                "output": "Generation Task",
            },
            {
                "name": "多模型调度 Agent",
                "status": "configured",
                "goal": "按任务类型、成本、成功率和质量选择模型。",
                "inputs": ["任务节点", "模型能力表", "成本预算", "并发限制"],
                "tools": ["model_registry", "cost_estimator", "fallback_router"],
                "memory": ["model success metrics", "latency/cost history"],
                "guardrails": ["超预算任务需降级或等待确认", "失败重试必须切换策略或模型"],
                "evals": ["调用成功率", "单图成本", "平均延迟", "模型命中率"],
                "config": ["模型优先级", "成本限制", "并发限制", "备用模型"],
                "output": "模型调用计划",
            },
            {
                "name": "质量评估 Agent",
                "status": "partial",
                "goal": "自动判断图片是否可进入人工审核或入库。",
                "inputs": ["原始主体资产", "生成图片", "Image Plan", "质检规则"],
                "tools": ["visual_consistency_checker", "ocr_checker", "commercial_rubric"],
                "memory": ["approved examples", "rejected issue taxonomy"],
                "guardrails": ["低于阈值不得自动入库", "严重结构变形必须标记 fatal"],
                "evals": ["主体一致性", "卖点准确性", "场景合理性", "商业可用性"],
                "config": ["一致性阈值", "商业可用性评分", "问题标签"],
                "output": "质检报告",
            },
        ]
    }


@app.get("/api/agent-standards")
async def agent_standards():
    """标准 AI Agent 运行规范，用于约束每个 Agent 的设计。"""
    return {
        "compliance_score": 78,
        "verdict": "体系分层合理，已具备 Agent 平台雏形；距离标准化生产级 Agent 还需要补齐运行时、观测和评估闭环。",
        "required_contract": [
            {"field": "identity", "name": "身份与职责", "status": "pass", "description": "每个 Agent 必须有明确角色、目标和边界。"},
            {"field": "input_schema", "name": "输入契约", "status": "partial", "description": "输入字段需可验证，缺失字段要有默认策略。"},
            {"field": "output_schema", "name": "输出契约", "status": "partial", "description": "输出必须是结构化对象，供下游稳定消费。"},
            {"field": "tools", "name": "工具调用", "status": "partial", "description": "每个 Agent 应声明可调用工具、权限和失败兜底。"},
            {"field": "memory", "name": "状态与记忆", "status": "todo", "description": "需要区分短期任务状态、SKU 长期资产记忆、类目知识库。"},
            {"field": "planning", "name": "计划与执行", "status": "pass", "description": "工作流编排已承担任务拆解与节点执行。"},
            {"field": "guardrails", "name": "约束与安全", "status": "partial", "description": "要把商品一致性、平台规则、成本限制写成机器可执行规则。"},
            {"field": "evals", "name": "评估闭环", "status": "partial", "description": "质检 Agent 已有雏形，还需与人工审核结果形成反馈数据。"},
            {"field": "observability", "name": "可观测性", "status": "todo", "description": "每次 Agent 决策、工具调用、模型调用都应产生 trace。"},
        ],
        "runtime_state": {
            "task_context": ["task_id", "sku_id", "workflow_template", "image_plan_id", "current_node", "retry_count"],
            "agent_trace": ["agent_name", "input_hash", "decision", "tool_calls", "model_calls", "output_ref", "issues"],
            "memory_scopes": ["task_memory", "sku_memory", "category_memory", "brand_memory"],
        },
        "handoff_policy": [
            "上游 Agent 输出必须通过 schema 校验后才能交给下游。",
            "下游发现关键字段缺失时，任务进入 clarification 或 fallback 分支。",
            "质检失败不得直接覆盖原结果，应保留版本并记录失败原因。",
            "人工审核结果必须回写为训练样本或规则样本。",
        ],
    }


@app.get("/api/reviews")
async def list_reviews():
    """结果审核中心。"""
    review_items = []
    for t in tasks.values():
        if t.get("images"):
            review_items.append({
                "task_id": t.get("task_id"),
                "sku_id": t.get("product_id"),
                "status": "待审核" if t.get("status") == "done" else t.get("status"),
                "score": 86 if t.get("status") == "done" else None,
                "issue": "shadow slightly weak" if t.get("status") == "done" else "",
                "images": t.get("images", [])[:4],
            })

    if not review_items and OUTPUT_DIR.exists():
        for out_dir in sorted(OUTPUT_DIR.glob("*"), reverse=True)[:6]:
            if not out_dir.is_dir():
                continue
            sku_id = out_dir.name.split("_")[0]
            images = [{"name": p.name, "filename": p.name, "type": "output"} for p in sorted(out_dir.glob("*.png"))[:4]]
            review_items.append({
                "task_id": out_dir.name,
                "sku_id": sku_id,
                "status": "待审核",
                "score": 86,
                "issue": "product appears a bit smaller than expected",
                "output_dir": out_dir.name,
                "images": images,
            })
    return {"reviews": review_items}


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    """获取任务详情"""
    if task_id not in tasks:
        raise HTTPException(404, "任务不存在")
    return tasks[task_id]


@app.get("/api/tasks/{task_id}/images/{filename}")
async def get_task_image(task_id: str, filename: str):
    """获取任务生成的图片"""
    if task_id not in tasks:
        raise HTTPException(404, "任务不存在")

    task = tasks[task_id]
    out_dir = task.get("output_dir", "")
    if not out_dir:
        raise HTTPException(404, "任务无输出")

    img_path = Path(out_dir) / filename
    if not img_path.exists():
        raise HTTPException(404, "图片不存在")

    return FileResponse(img_path)


@app.get("/api/models")
async def list_models():
    """获取可用模型列表"""
    from config import MODELS
    return {"models": MODELS}


# --- Settings ---
SETTINGS_FILE = Path(__file__).parent / "settings.json"

def _load_settings() -> dict:
    """加载设置，合并默认值"""
    from config import MODELS
    defaults = {
        "api_keys": {
            "openai_api_key": "",
            "openai_base_url": "https://api.openai.com/v1",
            "google_api_key": "",
        },
        "models": MODELS.copy(),
        "pipeline": {
            "candidates_per_step": 2,
            "quality_threshold": 0.85,
            "max_retries": 3,
        },
    }
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            saved = json.load(f)
        # 合并：saved 覆盖 defaults
        for section in defaults:
            if section in saved:
                if isinstance(defaults[section], dict):
                    defaults[section].update(saved[section])
                else:
                    defaults[section] = saved[section]
    return defaults


def _save_settings(data: dict):
    """保存设置到文件"""
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@app.get("/api/settings")
async def get_settings():
    """获取平台设置 (API Key 脱敏返回)"""
    settings = _load_settings()
    # 脱敏 API Key
    masked = dict(settings)
    masked["api_keys"] = {}
    for k, v in settings["api_keys"].items():
        if "key" in k.lower() and v:
            masked["api_keys"][k] = v[:8] + "***" + v[-4:] if len(v) > 12 else "***"
        else:
            masked["api_keys"][k] = v
    # 同时返回原始值用于表单 (前端会判断是否显示)
    masked["_raw_keys_set"] = {k: bool(v) for k, v in settings["api_keys"].items()}
    return masked


@app.put("/api/settings")
async def update_settings(body: dict):
    """更新平台设置"""
    current = _load_settings()

    # 更新 API Keys (只更新非空的)
    if "api_keys" in body:
        for k, v in body["api_keys"].items():
            if v and "***" not in v:  # 不覆盖脱敏值
                current["api_keys"][k] = v

    # 更新模型配置
    if "models" in body:
        current["models"].update(body["models"])

    # 更新 Pipeline 参数
    if "pipeline" in body:
        current["pipeline"].update(body["pipeline"])

    _save_settings(current)

    # 同步更新运行时 config
    _apply_settings(current)

    return {"status": "ok", "message": "设置已保存"}


def _apply_settings(settings: dict):
    """将设置应用到运行时 config 模块"""
    import config
    keys = settings.get("api_keys", {})
    if keys.get("openai_api_key"):
        config.OPENAI_API_KEY = keys["openai_api_key"]
    if keys.get("openai_base_url"):
        config.OPENAI_BASE_URL = keys["openai_base_url"]
    if keys.get("google_api_key"):
        config.GOOGLE_API_KEY = keys["google_api_key"]
    if settings.get("models"):
        config.MODELS.update(settings["models"])
    if settings.get("pipeline"):
        config.PIPELINE.update(settings["pipeline"])


@app.post("/api/settings/test")
async def test_api_connection(body: dict):
    """测试 API 连接"""
    provider = body.get("provider", "")
    settings = _load_settings()

    if provider == "openai":
        try:
            from openai import OpenAI
            key = body.get("api_key") or settings["api_keys"].get("openai_api_key", "")
            base_url = body.get("base_url") or settings["api_keys"].get("openai_base_url", "")
            client = OpenAI(api_key=key, base_url=base_url, timeout=10)
            models = client.models.list()
            model_names = [m.id for m in models.data[:10]]
            return {"status": "ok", "message": f"连接成功，可用模型: {', '.join(model_names[:5])}"}
        except Exception as e:
            return {"status": "error", "message": f"连接失败: {str(e)}"}

    elif provider == "google":
        try:
            from google import genai
            key = body.get("api_key") or settings["api_keys"].get("google_api_key", "")
            client = genai.Client(api_key=key)
            models = client.models.list()
            model_names = [m.name for m in list(models)[:5]]
            return {"status": "ok", "message": f"连接成功，可用模型: {', '.join(model_names)}"}
        except Exception as e:
            return {"status": "error", "message": f"连接失败: {str(e)}"}

    return {"status": "error", "message": "未知的 provider"}


# 启动时加载已保存的设置
@app.on_event("startup")
async def startup_load_settings():
    if SETTINGS_FILE.exists():
        settings = _load_settings()
        _apply_settings(settings)


if __name__ == "__main__":
    import uvicorn
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    uvicorn.run(app, host="0.0.0.0", port=8090)
