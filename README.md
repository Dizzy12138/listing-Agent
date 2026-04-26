# 电商产品批量生图平台 PoC

Agent 模式 + 多模型融合的电商产品组图自动生成系统。

## 核心原则

- **产品图不重绘** — 产品主体始终来自原图，保证一致性
- **场景与产品分离生成** — 先生成背景，再合成
- **LLM 反推场景** — 自动分析产品生成最佳场景描述
- **多模型混合** — 按任务特征选择最优模型

## 模型配置

| 任务 | 模型 |
|------|------|
| 抠图/场景生成 | `gpt-image-2` / `gemini-3.1-flash-image-preview` |
| 卖点提炼/场景反推 | `gemini-3.0-pro-preview` / `gpt-5.2` |
| 文案翻译 | `gemma-4-31b-it` |
| 质量评估 | `gpt-5.2` |

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env 填入 OPENAI_API_KEY 和 GOOGLE_API_KEY

# 3. 运行 Pipeline (以 PCT020 猫爬架为例)
python main.py pct020 ./products/pct020_white.png
```

## 项目结构

```
image-demo/
├── main.py                  # 主入口
├── config.py                # 配置（模型/参数）
├── models/                  # 模型客户端
│   ├── gpt_image.py         # gpt-image-2
│   ├── gemini_image.py      # gemini-3.1-flash-image-preview
│   └── llm.py               # 文本LLM统一入口
├── pipeline/                # Pipeline 步骤
│   ├── step1_extract.py     # 白图修复（抠图）
│   ├── step2_scene.py       # 场景描述生成（LLM反推）
│   ├── step3_compose.py     # 场景图合成
│   ├── step4_enhance.py     # 光影渲染 + 细节图
│   ├── step5_text.py        # 多语言文案图层
│   └── quality.py           # 质量检测
├── products/                # 产品配置
│   └── pct020.json          # PCT020 猫爬架
└── output/                  # 生成结果
```

## Pipeline 流程

```
产品原图 → Step1:抠图 → Step2:场景反推 → Step3:合成 → Step4:光影 → Step5:文案 → 质量检测 → 输出
```

## 配置驱动执行架构

项目已从固定顺序脚本升级为：

```
SKU Schema
  → ImagePlan
  → ImageJob
  → View Agent
  → Workflow Registry
  → Tool / Model Adapter
  → Artifact + Trace
```

旧的 `pipeline/` 目录仍保留为底层工具函数，新入口是 `core/services/generation_service.py`。

关键对象：

- `core/schemas/sku.py`：SKU、ImagePlanItem、SceneRequirements、ViewStrategy。
- `core/schemas/job.py`：ImageJob、Artifact、WorkflowResult、QualityReport。
- `core/agents/view_agent.py`：为每个 ImageJob 绑定视角策略，避免所有图片角度完全一致。
- `core/workflows/registry.py`：按 image type 分配 workflow。
- `core/services/generation_service.py`：读取 SKU.image_plan，生成 ImageJob 并执行。
- `core/tracing/trace.py`：记录 Agent/Workflow/Model 调用 Trace。

现在 `main.py` 只是 CLI 入口，不再堆固定步骤。Web 任务也复用同一套 `GenerationService`。

### View Agent 能力边界

当前 `ViewAgent` 是“视角意图 + 保守执行”层，不把 PoC 能力包装成真正多视角重建。

视角模式：

- `reuse`：复用标准主体资产。
- `mirror`：镜像主体资产，作为保守兜底。
- `crop`：从标准主体资产生成细节视角。
- `model_synthesis`：可被分配为视角意图，但当前不会执行真实重建；系统会复用标准主体资产，并在 Trace / Artifact / Quality 中记录 `model_synthesis_not_implemented`。

这意味着当前系统已经能追踪每张图的视角意图、执行模式和重复情况，但 `low_angle_hero` / `left_45` 的真实视角重建仍属于下一阶段能力。

关键商业图会锁定核心视角，避免全局去重破坏图片目标：

- `scene_main`：锁定 `low_angle_hero`，优先服务“显高、显大”的商业目标。
- `size_compare`：锁定 `front_open`，优先保证尺寸对比清晰。

每次执行会额外保存视角资产到 `output/{run}/views/`，用于判断问题发生在视角资产阶段还是场景合成阶段。

### 质量与 Trace

`GenerationService` 会统一做基础质量评估：

- 是否有输出产物
- 图片尺寸是否过小
- 场景图是否出现透明棋盘格/白块伪影
- 请求了尚未实现的模型重建视角
- `view_distribution` 是否存在重复视角

所有结果会写入输出目录的 `trace.json`。

## SKU Agent 平台规范

当前原型已从“批量生图工具”升级为 SKU 视觉生产操作系统雏形，页面模块包含：

- SKU 管理
- 图片资产库
- 工作流模板中心
- Agent 配置中心
- 模型服务管理
- 生图任务中心
- 结果审核中心
- 数据看板

### Agent 标准化契约

每个 Agent 按以下契约描述，避免只停留在概念分层：

| 契约项 | 说明 |
| --- | --- |
| identity | Agent 身份、职责、边界 |
| goal | 本 Agent 需要完成的业务目标 |
| inputs | 结构化输入字段 |
| output | 下游可消费的结构化输出 |
| tools | 可调用工具与服务 |
| memory | 任务记忆、SKU 记忆、类目记忆、品牌记忆 |
| guardrails | 商品一致性、平台规则、成本限制等约束 |
| evals | 可量化评估指标 |

### 当前标准化判断

体系分层是合理的，已经具备 Agent 平台雏形；但生产级标准 AI Agent 还需要继续补齐：

- Schema 校验：每个 Agent 输入/输出都需要 Pydantic schema。
- Tool Registry：工具调用需要权限、超时、重试、失败兜底。
- Memory Store：区分 task_memory、sku_memory、category_memory、brand_memory。
- Trace：记录每次 Agent 决策、工具调用、模型调用和输出引用。
- Eval Loop：人工审核结果要回写为规则样本或评估样本。

## Agent Workbench

新增 `Agent工作台` 页面，把 Agent 从“配置项”升级成可运行对象。

后端入口：

- `GET /api/agent-blueprint`：读取 SKU Visual Production Agent 蓝图。
- `POST /api/agent-runs`：启动一次 Agent Run。
- `GET /api/agent-runs`：查看历史 Agent Run。
- `GET /api/agent-runs/{run_id}`：查看单次 Run 的步骤、记忆和产物。
- `POST /api/agent-runs/{run_id}/answers`：提交 Inversion 阶段澄清信息。
- `POST /api/agent-runs/{run_id}/launch-generation`：从 Agent Pipeline 发起真实生图任务。

### 5 种 Agent Skill 模式落地

| 模式 | 平台落点 |
| --- | --- |
| Tool Wrapper | 按 SKU 类目加载资产规则、平台规则、模型规则 |
| Generator | 生成稳定的 Image Plan 与 Prompt Pack |
| Reviewer | 按检查清单预审计划和结果 |
| Inversion | 执行前检查缺失信息，必要时先提问 |
| Pipeline | 强制执行资产处理、白底主图、场景背景、主体合成、详情卡片、质检节点 |
