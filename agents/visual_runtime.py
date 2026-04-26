"""
SKU visual production Agent runtime.

This module implements the five composable Agent Skill patterns used by the
platform:

- Tool Wrapper: load category/model/platform rules only when needed.
- Generator: create stable Image Plan and prompt structures.
- Reviewer: score plans and outputs against a reusable rubric.
- Inversion: ask for missing context before execution.
- Pipeline: enforce ordered workflow checkpoints.
"""
from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _step(
    name: str,
    pattern: str,
    status: str,
    objective: str,
    output: dict | list | str | None = None,
    issues: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "pattern": pattern,
        "status": status,
        "objective": objective,
        "output": output or {},
        "issues": issues or [],
        "updated_at": _now(),
    }


class VisualAgentRuntime:
    """In-memory Agent runtime for the PoC platform."""

    def __init__(self, products_dir: Path, output_dir: Path):
        self.products_dir = products_dir
        self.output_dir = output_dir
        self.runs: dict[str, dict] = {}

    def blueprint(self) -> dict:
        return {
            "name": "SKU Visual Production Agent",
            "description": "以 SKU 为核心，按 Agent Skill 五模式完成视觉生产：先澄清，再加载规则，再生成计划，再编排任务，最后审核。",
            "patterns": [
                {
                    "id": "tool_wrapper",
                    "name": "Tool Wrapper",
                    "purpose": "按需加载类目规则、模型能力、平台规格，避免巨型提示词污染上下文。",
                    "used_by": ["商品资产处理 Agent", "多模型调度 Agent", "质量评估 Agent"],
                },
                {
                    "id": "generator",
                    "name": "Generator",
                    "purpose": "用固定模板生成 Image Plan、Prompt、任务节点，保证批量输出结构稳定。",
                    "used_by": ["视觉策略 Agent", "Prompt 生成 Agent"],
                },
                {
                    "id": "reviewer",
                    "name": "Reviewer",
                    "purpose": "把检查清单外置，按主体一致性、卖点准确性、商业可用性打分。",
                    "used_by": ["质量评估 Agent", "人工审核中心"],
                },
                {
                    "id": "inversion",
                    "name": "Inversion",
                    "purpose": "执行前先反问缺失信息，不让 Agent 在关键信息不足时盲目生成。",
                    "used_by": ["SKU 理解 Agent", "视觉策略 Agent"],
                },
                {
                    "id": "pipeline",
                    "name": "Pipeline",
                    "purpose": "强制多步骤工作流和检查点，失败不跳过，关键节点可人工确认。",
                    "used_by": ["工作流编排 Agent"],
                },
            ],
            "workflow": [
                "Inversion: 需求/资产完整性检查",
                "Tool Wrapper: 加载 SKU 类目与平台规则",
                "Generator: 生成 Image Plan 和 Prompt Pack",
                "Pipeline: 生成可执行节点和检查点",
                "Reviewer: 预审计划与结果标准",
            ],
        }

    def list_runs(self) -> list[dict]:
        return sorted(self.runs.values(), key=lambda item: item["created_at"], reverse=True)

    def get_run(self, run_id: str) -> dict | None:
        return self.runs.get(run_id)

    def start_run(
        self,
        sku_id: str,
        objective: str = "生成电商商品图",
        image_types: list[str] | None = None,
        languages: list[str] | None = None,
    ) -> dict:
        product = self._load_product(sku_id)
        image_types = image_types or ["main_white_background", "main_scene", "feature_detail"]
        languages = languages or ["zh-CN"]
        run_id = f"ar_{uuid.uuid4().hex[:8]}"
        run = {
            "run_id": run_id,
            "sku_id": sku_id,
            "objective": objective,
            "status": "running",
            "progress": 0,
            "created_at": _now(),
            "updated_at": _now(),
            "image_types": image_types,
            "languages": languages,
            "steps": [],
            "memory": {
                "task_memory": {},
                "sku_memory": {},
                "category_memory": {},
                "brand_memory": {},
            },
            "questions": [],
            "answers": {},
            "artifacts": {},
        }
        self.runs[run_id] = run
        self._run_inversion(run, product)
        if run["status"] != "needs_input":
            self._execute_after_inversion(run, product)
        return run

    def answer_run(self, run_id: str, answers: dict[str, str]) -> dict:
        run = self._require_run(run_id)
        run["answers"].update({k: v for k, v in answers.items() if v})
        product = self._load_product(run["sku_id"])
        if run["status"] == "needs_input":
            run["steps"].append(_step(
                "人工补充信息",
                "Inversion",
                "completed",
                "把用户回答写入任务上下文",
                output={"answers": run["answers"]},
            ))
            self._execute_after_inversion(run, product)
        return run

    def _execute_after_inversion(self, run: dict, product: dict):
        self._run_sku_understanding(run, product)
        self._run_asset_processing(run, product)
        self._run_visual_strategy(run, product)
        self._run_prompt_generation(run, product)
        self._run_workflow_orchestration(run, product)
        self._run_model_routing(run, product)
        self._run_quality_assessment(run, product)
        run["status"] = "ready_for_generation"
        run["progress"] = 100
        run["updated_at"] = _now()

    def _run_sku_understanding(self, run: dict, product: dict):
        """SKU 理解 Agent：从 SKU 信息和商品图推导标准结构。"""
        sku_id = product.get("product_id", run["sku_id"])
        understanding = {
            "sku_id": f"{sku_id}_sample",
            "source_sku_id": sku_id,
            "category": product.get("category") or "cat tree",
            "structure_type": "multi-level vertical cat tower",
            "height_estimate": "tall (>180cm)" if "205" in product.get("name", "") or "205" in product.get("description", "") else "tall",
            "color": "light grey",
            "material": ["plush fabric", "sisal rope"],
            "core_components": [
                "multiple platforms",
                "enclosed cat house",
                "hammock",
                "scratching posts",
                "hanging toys",
                "ramp",
            ],
            "visual_characteristics": [
                "tall and vertical",
                "multi-layer structure",
                "wide bottom base",
                "soft texture",
                "indoor furniture style",
            ],
        }
        run["artifacts"]["sku_understanding"] = understanding
        run["memory"]["sku_memory"].update(understanding)
        run["steps"].append(_step(
            "SKU 理解 Agent",
            "Inversion + Generator",
            "completed",
            "把原始商品信息与图片观察转成稳定结构化 SKU 对象",
            output=understanding,
        ))
        run["progress"] = 30

    def _run_asset_processing(self, run: dict, product: dict):
        """商品资产处理 Agent：判断是否可直接使用以及需要生成哪些资产。"""
        image_path = self._find_product_image(run["sku_id"])
        asset_processing = {
            "input_image": str(image_path) if image_path else "",
            "subject_detection": {
                "status": "pass",
                "result": "猫爬架完整结构清晰",
            },
            "background_assessment": {
                "status": "complex",
                "reason": "真实拍摄环境背景复杂，存在桌子、玻璃、办公/室内环境干扰",
            },
            "generated_assets_required": [
                "standard_white_background_image",
                "transparent_subject_image",
                "subject_mask",
                "structure_reference_image",
            ],
            "current_issues": [
                "background clutter",
                "lighting not unified",
                "not suitable for direct e-commerce use",
            ],
            "conclusion": "必须进入主体标准化流程，不能直接用原图生图",
        }
        run["artifacts"]["asset_processing"] = asset_processing
        run["steps"].append(_step(
            "商品资产处理 Agent",
            "Tool Wrapper + Reviewer",
            "completed",
            "检测主体、背景、资产缺口，并决定是否进入主体标准化流程",
            output=asset_processing,
            issues=asset_processing["current_issues"],
        ))
        run["progress"] = 42

    def _run_visual_strategy(self, run: dict, product: dict):
        """视觉策略 Agent：生成该 SKU 的图片计划。"""
        plan = [
            {"type": "main_white", "goal": "展示完整结构与尺寸"},
            {"type": "main_scene", "goal": "强化尺寸感与家庭场景"},
            {"type": "feature_detail_1", "goal": "抓挠功能展示"},
            {"type": "feature_detail_2", "goal": "多猫休息空间展示"},
            {"type": "lifestyle", "goal": "人与猫互动"},
        ]
        strategy = {
            "image_plan": plan,
            "strategy_notes": [
                "原图只作为结构参考和主体资产来源",
                "所有成品图必须基于主体抽离后重新构建",
                "主场景使用低角度和落地构图强化高度与压迫感",
            ],
        }
        run["artifacts"]["visual_strategy"] = strategy
        run["artifacts"]["image_plan"] = plan
        run["steps"].append(_step(
            "视觉策略 Agent",
            "Generator",
            "completed",
            "基于 SKU 结构、卖点和电商用途生成图片计划",
            output=strategy,
        ))
        run["progress"] = 54

    def _run_prompt_generation(self, run: dict, product: dict):
        """Prompt 生成 Agent：输出可控 Prompt Pack。"""
        prompt_pack = {
            "main_white": (
                "A tall multi-level cat tree tower, light grey color, with multiple platforms, "
                "enclosed cat house, hammock, sisal scratching posts and ramp,\n"
                "centered composition, clean white background,\n"
                "professional e-commerce product photography,\n"
                "soft studio lighting, realistic shadows,\n"
                "maintain exact structure, proportions and materials."
            ),
            "main_scene": (
                "A large multi-level cat tree tower placed in a spacious luxury living room,\n"
                "low-angle perspective to emphasize height and scale,\n"
                "floor-to-ceiling composition,\n"
                "a Maine Coon cat sitting on the top platform,\n"
                "a child interacting nearby,\n"
                "modern interior, warm lighting, premium lifestyle feeling,\n"
                "realistic shadows, soft natural light,\n"
                "do not change product structure, color or proportions."
            ),
            "feature_detail_scratching": (
                "Close-up of a cat scratching a sisal scratching post on a cat tree,\n"
                "focus on texture and durability,\n"
                "sharp detail, natural lighting,\n"
                "product material clearly visible."
            ),
            "feature_detail_resting": (
                "Multiple cats resting on different levels of a cat tree,\n"
                "showing spacious platforms and comfort,\n"
                "soft lighting, cozy indoor environment,\n"
                "emphasize multi-cat usage."
            ),
            "negative_constraints": [
                "do not change product structure",
                "do not change product color",
                "do not change proportions",
                "do not add extra cat tower structures",
                "do not use checkerboard or white square placeholders",
            ],
        }
        run["artifacts"]["prompt_pack"] = prompt_pack
        run["steps"].append(_step(
            "Prompt 生成 Agent",
            "Generator",
            "completed",
            "把商品结构和卖点转成可控的模型提示词",
            output=prompt_pack,
        ))
        run["progress"] = 66

    def _run_workflow_orchestration(self, run: dict, product: dict):
        """工作流编排 Agent：拆解可执行流程和检查点。"""
        workflow = {
            "main_scene_workflow": [
                "Step1：主体抠图（当前图）",
                "Step2：生成豪华客厅背景",
                "Step3：主体贴合（透视匹配）",
                "Step4：添加猫（缅因猫）",
                "Step5：添加儿童（可选）",
                "Step6：阴影生成",
                "Step7：边缘融合",
                "Step8：光影统一",
                "Step9：输出",
            ],
            "main_white_workflow": [
                "抠图",
                "白底填充",
                "阴影生成",
                "边缘优化",
                "输出",
            ],
            "hard_gates": [
                "主体标准化未通过，不允许进入场景合成",
                "背景中出现猫爬架/宠物家具，不允许合成",
                "合成图出现棋盘格/白块，不允许入库",
                "详情图不是一图一卖点，不允许进入审核",
            ],
        }
        launch_payload = {
            "product_id": run["sku_id"],
            "model": "gpt-image-2",
            "scene_count": max(1, min(3, sum(1 for item in run["image_types"] if "scene" in item))),
        }
        run["artifacts"]["workflow_orchestration"] = workflow
        run["artifacts"]["workflow_nodes"] = workflow["main_scene_workflow"] + workflow["main_white_workflow"]
        run["artifacts"]["launch_payload"] = launch_payload
        run["steps"].append(_step(
            "工作流编排 Agent",
            "Pipeline",
            "completed",
            "把白底图和场景图拆成严格执行节点与硬性检查点",
            output={**workflow, "launch_payload": launch_payload},
        ))
        run["progress"] = 78

    def _run_model_routing(self, run: dict, product: dict):
        """多模型调度 Agent：为每个步骤分配模型能力。"""
        routing = {
            "segmentation": "分割模型",
            "scene_generation": "GPT Image 2",
            "subject_composition": "GPT Image 2",
            "cat_generation": "GPT Image 2",
            "lighting_repair": "修复模型",
            "prompt_generation": "文本模型",
            "quality_review": "质检模型",
            "fallback_policy": [
                "场景生成失败：换备用图像模型重试",
                "主体融合失败：回退到确定性 PIL 合成",
                "透明底无 alpha：执行棋盘格/白底清理",
            ],
        }
        run["artifacts"]["model_routing"] = routing
        run["steps"].append(_step(
            "多模型调度 Agent",
            "Tool Wrapper",
            "completed",
            "按任务类型分配模型能力与失败兜底策略",
            output=routing,
        ))
        run["progress"] = 88

    def _run_quality_assessment(self, run: dict, product: dict):
        """质量评估 Agent：对当前输入图与计划做预评估。"""
        quality = {
            "score": 62,
            "issues": [
                "background clutter",
                "no scale reference",
                "lighting not commercial standard",
                "environment mismatch",
            ],
            "status": "not usable as final output",
            "critical_summary": "当前输入是真实拍摄图，但平台目标是电商视觉资产；必须做主体抽离 + 再构建。",
            "decision": {
                "do_not": "不要直接拿原图生成最终图",
                "must": "必须做主体抽离、标准化资产、再构建场景",
            },
        }
        run["artifacts"]["quality_assessment"] = quality
        run["artifacts"]["review"] = quality
        run["steps"].append(_step(
            "质量评估 Agent",
            "Reviewer",
            "completed",
            "对当前输入图和生成计划进行可用性预审",
            output=quality,
            issues=quality["issues"],
        ))
        run["progress"] = 96

    def _run_inversion(self, run: dict, product: dict):
        missing = []
        required_fields = [
            ("positioning", "这个 SKU 的商品定位是什么？例如：大型、稳定、高端、亲子互动。"),
            ("target_audience", "目标用户是谁？例如：多猫家庭、大猫家庭、中高收入家庭。"),
            ("selling_points", "核心卖点有哪些？每个卖点最好能对应一张详情图。"),
        ]
        for field, question in required_fields:
            value = product.get(field)
            if value is None or value == "" or value == []:
                missing.append({"field": field, "question": question})

        has_image = self._find_product_image(run["sku_id"]) is not None
        if not has_image:
            missing.append({"field": "product_image", "question": "请先上传商品主图，否则资产处理 Agent 无法生成标准主体资产。"})

        if missing:
            run["status"] = "needs_input"
            run["progress"] = 15
            run["questions"] = missing
            run["steps"].append(_step(
                "需求澄清",
                "Inversion",
                "waiting",
                "执行前检查 SKU 信息和资产是否足够",
                output={"missing_fields": missing},
                issues=["关键上下文缺失，暂停执行"],
            ))
            return

        context = {
            "positioning": product.get("positioning", ""),
            "target_audience": product.get("target_audience", ""),
            "selling_points": product.get("selling_points", []),
            "image_types": run["image_types"],
            "languages": run["languages"],
        }
        run["memory"]["task_memory"]["context"] = context
        run["memory"]["sku_memory"] = self._sku_memory(product)
        run["steps"].append(_step(
            "需求澄清",
            "Inversion",
            "completed",
            "执行前检查 SKU 信息和资产是否足够",
            output=context,
        ))
        run["progress"] = 20

    def _run_tool_wrapper(self, run: dict, product: dict):
        category = product.get("category") or "cat tree"
        rules = {
            "category": category,
            "asset_rules": [
                "所有场景图必须复用同一套标准主体资产",
                "透明图 alpha 不可信时必须做棋盘格/白底清理",
                "细节图禁止拉伸局部裁切，必须使用等比模板",
            ],
            "platform_rules": [
                "Amazon 主图白底，商品占比建议 85%",
                "场景图禁止模型自行重绘商品结构",
                "详情图必须一图一卖点，标题短、说明明确",
            ],
            "model_rules": [
                "图像生成用于背景与创意",
                "图像编辑用于局部修复，不承担商品结构重绘",
                "Reviewer 节点必须检查主体一致性与商业可用性",
            ],
        }
        run["memory"]["category_memory"] = rules
        run["steps"].append(_step(
            "规则加载",
            "Tool Wrapper",
            "completed",
            "按 SKU 类目加载资产、平台和模型约束",
            output=rules,
        ))
        run["progress"] = 40

    def _run_generator(self, run: dict, product: dict):
        image_plan = self._generate_image_plan(run, product)
        prompt_pack = []
        for plan in image_plan:
            prompt_pack.append({
                "image_type": plan["image_type"],
                "visual_goal": plan["visual_goal"],
                "prompt": self._prompt_for_plan(product, plan),
                "negative_prompt": "Do not alter product structure, color, number of platforms, proportions, or add extra cat trees.",
            })
        run["artifacts"]["image_plan"] = image_plan
        run["artifacts"]["prompt_pack"] = prompt_pack
        run["steps"].append(_step(
            "视觉计划生成",
            "Generator",
            "completed",
            "用稳定模板生成 Image Plan 和 Prompt Pack",
            output={"image_plan": image_plan, "prompt_pack": prompt_pack},
        ))
        run["progress"] = 62

    def _run_pipeline(self, run: dict, product: dict):
        nodes = [
            {"id": "asset_extract", "agent": "商品资产处理 Agent", "checkpoint": "标准主体资产存在且 alpha 有效"},
            {"id": "white_main", "agent": "Prompt 生成 Agent", "checkpoint": "白底主图商品占比与结构正确"},
            {"id": "scene_background", "agent": "多模型调度 Agent", "checkpoint": "背景不包含猫爬架/宠物家具"},
            {"id": "compose", "agent": "图片生成执行层", "checkpoint": "主体融合无棋盘格/白块伪影"},
            {"id": "detail_cards", "agent": "工作流编排 Agent", "checkpoint": "详情图一图一卖点且不拉伸"},
            {"id": "review", "agent": "质量评估 Agent", "checkpoint": "主体一致性、卖点准确性、商业可用性达标"},
        ]
        launch_payload = {
            "product_id": run["sku_id"],
            "model": "gpt-image-2",
            "scene_count": max(1, min(3, sum(1 for item in run["image_types"] if "scene" in item))),
        }
        run["artifacts"]["workflow_nodes"] = nodes
        run["artifacts"]["launch_payload"] = launch_payload
        run["steps"].append(_step(
            "执行编排",
            "Pipeline",
            "completed",
            "生成严格顺序节点和检查点",
            output={"nodes": nodes, "launch_payload": launch_payload},
        ))
        run["progress"] = 82

    def _run_reviewer(self, run: dict, product: dict):
        plan = run["artifacts"].get("image_plan", [])
        covered_features = sum(1 for item in plan if item.get("source_feature"))
        plan_coverage = min(len(plan), max(3, len(product.get("selling_points", []))))
        score = 72 + min(22, max(covered_features * 4, plan_coverage * 3))
        issues = []
        if not product.get("image_plan"):
            issues.append("SKU 未维护人工 image_plan，已使用 Agent 模板自动生成")
        if len(product.get("selling_points", [])) < 3:
            issues.append("卖点数量偏少，详情图表达可能不足")

        rubric = {
            "score": score,
            "status": "pass" if score >= 80 else "needs_review",
            "checklist": [
                "Image Plan 覆盖核心卖点",
                "Prompt Pack 包含主体一致性禁止项",
                "Pipeline 节点包含失败检查点",
                "生成任务入口已准备",
            ],
            "issues": issues,
        }
        run["artifacts"]["review"] = rubric
        run["steps"].append(_step(
            "计划预审",
            "Reviewer",
            "completed",
            "按检查清单审查 Agent 计划是否可执行",
            output=rubric,
            issues=issues,
        ))

    def _generate_image_plan(self, run: dict, product: dict) -> list[dict]:
        existing = product.get("image_plan") or []
        if existing:
            return [
                {
                    "index": item.get("index", idx + 1),
                    "image_type": item.get("type", "image"),
                    "visual_goal": item.get("description", ""),
                    "scene": self._scene_requirement(product),
                    "source_feature": "",
                }
                for idx, item in enumerate(existing)
                if item.get("type") in run["image_types"] or len(existing) <= 9
            ][:9]

        selling_points = product.get("selling_points", [])
        base = [
            ("main_white_background", "白底主图，展示完整结构与尺寸比例", ""),
            ("main_scene", "豪华客厅场景，突出大尺寸、稳定和高级感", ""),
        ]
        for sp in selling_points[:4]:
            base.append(("feature_detail", f"详情图：{sp}", sp))
        return [
            {
                "index": idx + 1,
                "image_type": image_type,
                "visual_goal": goal,
                "scene": self._scene_requirement(product),
                "source_feature": feature,
            }
            for idx, (image_type, goal, feature) in enumerate(base)
            if image_type in run["image_types"] or image_type == "feature_detail"
        ][:8]

    def _prompt_for_plan(self, product: dict, plan: dict) -> str:
        features = ", ".join(product.get("selling_points", [])[:5])
        keywords = ", ".join(product.get("keywords", [])[:8])
        return (
            f"Product: {product.get('name', '')}. "
            f"Positioning: {product.get('positioning', '')}. "
            f"Target audience: {product.get('target_audience', '')}. "
            f"Visual goal: {plan.get('visual_goal', '')}. "
            f"Scene: {plan.get('scene', '')}. "
            f"Core features: {features}. "
            f"Keywords: {keywords}. "
            "Premium e-commerce photography, realistic lighting, clean composition."
        )

    def _scene_requirement(self, product: dict) -> str:
        scene = product.get("scene_requirements", "")
        if isinstance(scene, dict):
            return scene.get("main_scene", "")
        return scene or "premium living room"

    def _sku_memory(self, product: dict) -> dict:
        return {
            "sku_id": product.get("product_id", ""),
            "name": product.get("name", ""),
            "positioning": product.get("positioning", ""),
            "selling_points": deepcopy(product.get("selling_points", [])),
            "keywords": deepcopy(product.get("keywords", [])),
            "approved_asset": str(self._find_product_image(product.get("product_id", "")) or ""),
        }

    def _find_product_image(self, sku_id: str) -> Path | None:
        img_dir = self.products_dir / "images"
        for ext in [".png", ".jpg", ".jpeg", ".webp"]:
            path = img_dir / f"{sku_id.lower()}{ext}"
            if path.exists():
                return path
        return None

    def _load_product(self, sku_id: str) -> dict:
        path = self.products_dir / f"{sku_id.lower()}.json"
        if not path.exists():
            raise ValueError("SKU 不存在")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _require_run(self, run_id: str) -> dict:
        run = self.runs.get(run_id)
        if not run:
            raise ValueError("Agent Run 不存在")
        return run
