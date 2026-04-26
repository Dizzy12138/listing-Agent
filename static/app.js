/**
 * 电商批量生图平台 - 前端逻辑
 */

// === State ===
let currentPage = 'dashboard';
let products = [];
let tasksList = [];
let assetsList = [];
let workflowsList = [];
let agentsList = [];
let agentStandards = null;
let reviewList = [];
let agentBlueprint = null;
let agentRuns = [];
let selectedAgentRun = null;

// === Init ===
document.addEventListener('DOMContentLoaded', () => {
    loadDashboard();
    loadProducts();
    loadTasks();
    loadModels();
    loadAssets();
    loadWorkflows();
    loadAgents();
    loadAgentWorkbench();
    loadReviews();
    loadSettings();
    setupDragDrop();
});

// === Navigation ===
function showPage(page) {
    currentPage = page;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.getElementById(`page-${page}`).classList.add('active');
    document.querySelectorAll('.header-nav button').forEach(b => b.classList.remove('active'));
    const pageLabels = {
        dashboard: '数据看板',
        'agent-workbench': 'Agent工作台',
        products: 'SKU',
        assets: '图片资产',
        workflows: '工作流',
        agents: 'Agent配置',
        tasks: '任务',
        review: '审核',
        settings: '模型',
    };
    document.querySelectorAll('.header-nav button').forEach(b => {
        if (b.textContent.includes(pageLabels[page] || '')) b.classList.add('active');
    });

    if (page === 'products') loadProducts();
    if (page === 'agent-workbench') loadAgentWorkbench();
    if (page === 'assets') loadAssets();
    if (page === 'workflows') loadWorkflows();
    if (page === 'agents') loadAgents();
    if (page === 'tasks') loadTasks();
    if (page === 'review') loadReviews();
    if (page === 'dashboard') loadDashboard();
    if (page === 'settings') loadSettings();
}

// === Agent Workbench ===
async function loadAgentWorkbench() {
    try {
        await Promise.all([loadProducts(), loadAgentBlueprint(), loadAgentRuns()]);
        populateAgentSkuSelect();
    } catch (e) { /* handled */ }
}

async function loadAgentBlueprint() {
    const data = await api('/api/agent-blueprint');
    agentBlueprint = data;
    renderAgentBlueprint();
}

function renderAgentBlueprint() {
    const desc = document.getElementById('agentBlueprintDesc');
    const list = document.getElementById('agentPatternList');
    if (!desc || !list || !agentBlueprint) return;
    desc.textContent = agentBlueprint.description || '';
    list.innerHTML = (agentBlueprint.patterns || []).map(pattern => `
        <div class="pattern-item">
            <strong>${pattern.name}</strong>
            <span>${pattern.purpose}</span>
        </div>
    `).join('');
}

function populateAgentSkuSelect() {
    const select = document.getElementById('agentSkuSelect');
    if (!select) return;
    const current = select.value;
    select.innerHTML = products.map(p => `
        <option value="${p.product_id}" ${p.product_id === current ? 'selected' : ''}>${p.product_id} - ${p.name}</option>
    `).join('');
}

async function loadAgentRuns() {
    const data = await api('/api/agent-runs');
    agentRuns = data.runs || [];
    renderAgentRuns();
}

function runStatusText(status) {
    return {
        running: '运行中',
        needs_input: '等待澄清',
        ready_for_generation: '可发起生图',
        generation_launched: '已发起生图',
        error: '失败',
    }[status] || status || '-';
}

function renderAgentRuns() {
    const list = document.getElementById('agentRunList');
    if (!list) return;
    if (agentRuns.length === 0) {
        list.innerHTML = '<div class="empty-state compact-empty"><h3>暂无 Agent Run</h3><p>从左侧选择 SKU 后启动。</p></div>';
        return;
    }
    list.innerHTML = agentRuns.map(run => `
        <button class="agent-run-item" type="button" onclick="selectAgentRun('${run.run_id}')">
            <span class="task-id">${run.run_id}</span>
            <strong>${run.sku_id}</strong>
            <em>${runStatusText(run.status)}</em>
            <small>${run.updated_at || run.created_at}</small>
        </button>
    `).join('');
}

async function selectAgentRun(runId) {
    selectedAgentRun = await api(`/api/agent-runs/${runId}`);
    renderAgentRunDetail(selectedAgentRun);
}

async function handleAgentRunSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const imageTypes = Array.from(form.querySelectorAll('input[name="image_types"]:checked')).map(input => input.value);
    const body = {
        sku_id: form.sku_id.value,
        objective: form.objective.value.trim(),
        image_types: imageTypes,
        languages: ['zh-CN'],
    };
    const run = await api('/api/agent-runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    selectedAgentRun = run;
    showToast(`Agent Run ${run.run_id} 已启动`, 'success');
    await loadAgentRuns();
    renderAgentRunDetail(run);
}

function statusClass(status) {
    if (status === 'completed' || status === 'ready_for_generation' || status === 'generation_launched') return 'done';
    if (status === 'waiting' || status === 'needs_input') return 'pending';
    if (status === 'error') return 'error';
    return 'running';
}

function renderAgentRunDetail(run) {
    if (!run) return;
    selectedAgentRun = run;
    const card = document.getElementById('agentRunDetailCard');
    const title = document.getElementById('agentRunDetailTitle');
    const summary = document.getElementById('agentRunSummary');
    if (card) card.style.display = 'block';
    if (title) title.textContent = `${run.run_id} · ${run.sku_id} · ${runStatusText(run.status)}`;
    if (summary) summary.textContent = run.objective || '';
    renderAgentQuestions(run);
    renderAgentSteps(run);
    renderAgentMemory(run);
}

function renderAgentQuestions(run) {
    const el = document.getElementById('agentQuestions');
    if (!el) return;
    if (run.status !== 'needs_input' || !(run.questions || []).length) {
        el.innerHTML = '';
        return;
    }
    el.innerHTML = `
        <div class="question-box">
            <strong>Inversion 检查点：需要补充信息</strong>
            <form onsubmit="submitAgentAnswers(event)">
                ${(run.questions || []).map(q => `
                    <label>${q.question}
                        <textarea class="form-textarea" name="${q.field}" rows="2"></textarea>
                    </label>
                `).join('')}
                <button class="btn btn-primary" type="submit">提交并继续</button>
            </form>
        </div>
    `;
}

async function submitAgentAnswers(e) {
    e.preventDefault();
    if (!selectedAgentRun) return;
    const data = new FormData(e.target);
    const answers = {};
    for (const [key, value] of data.entries()) answers[key] = value;
    const run = await api(`/api/agent-runs/${selectedAgentRun.run_id}/answers`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ answers }),
    });
    selectedAgentRun = run;
    showToast('Agent 已继续执行', 'success');
    await loadAgentRuns();
    renderAgentRunDetail(run);
}

function renderAgentSteps(run) {
    const el = document.getElementById('agentStepList');
    if (!el) return;
    el.innerHTML = (run.steps || []).map(step => `
        <div class="agent-step ${statusClass(step.status)}">
            <div>
                <span class="pattern-badge">${step.pattern}</span>
                <strong>${step.name}</strong>
                <p>${step.objective}</p>
                ${(step.issues || []).map(issue => `<em>${issue}</em>`).join('')}
            </div>
            <small>${step.status}</small>
        </div>
    `).join('');
}

function renderKeyValuePanel(title, data) {
    return `
        <div class="kv-panel">
            <strong>${title}</strong>
            <pre>${escapeHtml(JSON.stringify(data || {}, null, 2))}</pre>
        </div>
    `;
}

function renderArtifactCard(title, artifact, accent = '') {
    if (!artifact) return '';
    return `
        <div class="artifact-card ${accent}">
            <strong>${title}</strong>
            <pre>${escapeHtml(JSON.stringify(artifact, null, 2))}</pre>
        </div>
    `;
}

function renderAgentArtifactCards(artifacts = {}) {
    const cards = [
        ['SKU 理解 Agent', artifacts.sku_understanding, 'blue'],
        ['商品资产处理 Agent', artifacts.asset_processing, 'amber'],
        ['视觉策略 Agent', artifacts.visual_strategy, 'green'],
        ['Prompt 生成 Agent', artifacts.prompt_pack, 'blue'],
        ['工作流编排 Agent', artifacts.workflow_orchestration, 'green'],
        ['多模型调度 Agent', artifacts.model_routing, 'blue'],
        ['质量评估 Agent', artifacts.quality_assessment, 'red'],
    ];
    return `<div class="artifact-grid">${cards.map(([title, data, accent]) => renderArtifactCard(title, data, accent)).join('')}</div>`;
}

function escapeHtml(str) {
    return String(str)
        .replaceAll('&', '&amp;')
        .replaceAll('<', '&lt;')
        .replaceAll('>', '&gt;')
        .replaceAll('"', '&quot;')
        .replaceAll("'", '&#039;');
}

function renderAgentMemory(run) {
    const memoryEl = document.getElementById('agentMemoryPanel');
    const artifactEl = document.getElementById('agentArtifactPanel');
    if (memoryEl) memoryEl.innerHTML = renderKeyValuePanel('Memory', run.memory);
    if (artifactEl) artifactEl.innerHTML = renderAgentArtifactCards(run.artifacts);
}

async function launchGenerationFromRun() {
    if (!selectedAgentRun) {
        showToast('请先选择一个 Agent Run', 'error');
        return;
    }
    if (selectedAgentRun.status !== 'ready_for_generation') {
        showToast('当前 Agent Run 尚未通过计划预审', 'error');
        return;
    }
    const data = await api(`/api/agent-runs/${selectedAgentRun.run_id}/launch-generation`, { method: 'POST' });
    selectedAgentRun = data.run;
    showToast(`生图任务 #${data.task.task_id} 已创建`, 'success');
    await loadAgentRuns();
    renderAgentRunDetail(data.run);
    pollTaskProgress(data.task.task_id);
}

// === API Helpers ===
async function api(url, options = {}) {
    try {
        const res = await fetch(url, options);
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || '请求失败');
        }
        return await res.json();
    } catch (e) {
        showToast(e.message, 'error');
        throw e;
    }
}

// === Dashboard ===
async function loadDashboard() {
    try {
        const [prodData, taskData, dashData] = await Promise.all([
            api('/api/products'),
            api('/api/tasks'),
            api('/api/dashboard'),
        ]);
        products = prodData.products || [];
        tasksList = taskData.tasks || [];
        const stats = dashData.stats || {};

        document.getElementById('statProducts').textContent = stats.sku_count ?? products.length;
        document.getElementById('statTasks').textContent = stats.task_count ?? tasksList.length;
        document.getElementById('statDone').textContent = stats.done_count ?? tasksList.filter(t => t.status === 'done').length;
        document.getElementById('statImages').textContent = stats.asset_count ?? tasksList.reduce((s, t) => s + (t.images?.length || 0), 0);
        renderPipeline(dashData.pipeline || []);
    } catch (e) { /* handled by api() */ }
}

function renderPipeline(pipeline) {
    const el = document.getElementById('pipelineStrip');
    if (!el) return;
    el.innerHTML = pipeline.map((step, index) => `
        <div class="pipeline-step">
            <div class="pipeline-index">${String(index + 1).padStart(2, '0')}</div>
            <div>
                <strong>${step.name}</strong>
                <span>${step.status}</span>
            </div>
        </div>
    `).join('');
}

async function loadModels() {
    try {
        const data = await api('/api/models');
        const el = document.getElementById('modelConfig');
        if (!el) return;
        const labels = {
            image_primary: '图像生成(主)', image_secondary: '图像生成(备)',
            llm_primary: 'LLM(主)', llm_secondary: 'LLM(备)',
            translation: '翻译', quality: '质量评估',
        };
        el.innerHTML = Object.entries(data.models).map(([k, v]) => `
            <div style="display:flex; justify-content:space-between; padding:10px 14px; background:var(--bg-input); border-radius:8px;">
                <span style="color:var(--text-muted); font-size:13px;">${labels[k] || k}</span>
                <span style="color:var(--accent); font-size:13px; font-weight:600;">${v}</span>
            </div>
        `).join('');
    } catch (e) { /* ignore */ }
}

// === Products ===
async function loadProducts() {
    try {
        const data = await api('/api/products');
        products = data.products || [];
        renderProducts();
    } catch (e) { /* handled */ }
}

function renderProducts() {
    const grid = document.getElementById('productGrid');
    const empty = document.getElementById('productEmpty');

    if (products.length === 0) {
        grid.innerHTML = '';
        empty.style.display = 'block';
        return;
    }

    empty.style.display = 'none';
    grid.innerHTML = products.map(p => `
        <div class="product-card" onclick="viewProduct('${p.product_id}')">
            <div class="product-card-img">
                ${p.image_url ? `<img src="${p.image_url}" alt="${p.product_id}">` : `<div class="placeholder">SKU</div>`}
            </div>
            <div class="product-card-body">
                <div class="id">${p.product_id}</div>
                <h3>${p.name || '未命名产品'}</h3>
                <p>${p.description || '暂无描述'}</p>
            </div>
            <div class="product-card-footer">
                <span class="sp-count">${(p.selling_points || []).length} 个卖点 / ${(p.image_plan || []).length} 张计划图</span>
                <button class="btn btn-sm btn-secondary" onclick="event.stopPropagation(); startTask('${p.product_id}')">生图</button>
            </div>
        </div>
    `).join('');
}

function viewProduct(productId) {
    const p = products.find(x => x.product_id === productId);
    if (!p) return;

    const modal = document.getElementById('taskDetailModal');
    document.getElementById('taskDetailTitle').textContent = `SKU ${p.product_id} · ${p.name}`;
    document.getElementById('taskDetailContent').innerHTML = `
        <div class="form-grid">
            <div class="form-group">
                <div class="form-label">产品编号</div>
                <div style="color:var(--accent); font-weight:700; font-size:16px;">${p.product_id}</div>
            </div>
            <div class="form-group">
                <div class="form-label">定位</div>
                <div>${p.positioning || '-'}</div>
            </div>
            <div class="form-group full">
                <div class="form-label">描述</div>
                <div style="color:var(--text-secondary);">${p.description || '-'}</div>
            </div>
            <div class="form-group full">
                <div class="form-label">目标人群</div>
                <div style="color:var(--text-secondary);">${p.target_audience || '-'}</div>
            </div>
            <div class="form-group full">
                <div class="form-label">卖点</div>
                <div>${(p.selling_points || []).map(sp => `<div style="padding:6px 0; border-bottom:1px solid var(--border);">• ${sp}</div>`).join('')}</div>
            </div>
            <div class="form-group full">
                <div class="form-label">生成计划</div>
                <div class="mini-table">
                    ${(p.image_plan || []).map(plan => `
                        <div class="mini-row">
                            <span>${plan.index || '-'}</span>
                            <strong>${plan.type || 'image'}</strong>
                            <em>${plan.description || ''}</em>
                        </div>
                    `).join('') || '<span style="color:var(--text-muted);">暂无生成计划</span>'}
                </div>
            </div>
            <div class="form-group full">
                <div class="form-label">关键词</div>
                <div style="display:flex; flex-wrap:wrap; gap:6px;">
                    ${(p.keywords || []).map(k => `<span class="tag">${k}</span>`).join('')}
                </div>
            </div>
            <div class="form-group full">
                <div class="form-label">竞品参考</div>
                <div>${(p.competitors || []).map(link => `<a class="text-link" href="${link}" target="_blank" rel="noreferrer">${link}</a>`).join('') || '-'}</div>
            </div>
        </div>
        <div class="btn-group">
            <button class="btn btn-primary" onclick="closeModal('taskDetailModal'); startTask('${p.product_id}')">创建生图任务</button>
        </div>
    `;
    modal.classList.add('active');
}

// === Asset Library ===
async function loadAssets() {
    try {
        const data = await api('/api/assets');
        assetsList = data.assets || [];
        renderAssets();
    } catch (e) { /* handled */ }
}

function renderAssets() {
    const el = document.getElementById('assetLibrary');
    if (!el) return;
    if (assetsList.length === 0) {
        el.innerHTML = '<div class="empty-state"><h3>暂无图片资产</h3><p>上传 SKU 图片或执行生图任务后会自动归档</p></div>';
        return;
    }
    el.innerHTML = assetsList.map(group => `
        <div class="card">
            <div class="card-header">
                <div class="card-title">${group.sku_id} · ${group.name}</div>
                <span class="tag">${group.asset_count} 个资产</span>
            </div>
            <div class="asset-grid">
                ${(group.assets || []).map(asset => `
                    <div class="asset-item">
                        ${asset.url ? `<img src="${asset.url}" alt="${asset.name}" loading="lazy">` : '<div class="asset-placeholder">No Image</div>'}
                        <div>
                            <strong>${asset.type}</strong>
                            <span>${asset.name}</span>
                        </div>
                    </div>
                `).join('') || '<p style="color:var(--text-muted);">暂无资产</p>'}
            </div>
        </div>
    `).join('');
}

// === Workflows ===
async function loadWorkflows() {
    try {
        const data = await api('/api/workflows');
        workflowsList = data.workflows || [];
        renderWorkflows();
    } catch (e) { /* handled */ }
}

function renderWorkflows() {
    const el = document.getElementById('workflowGrid');
    if (!el) return;
    el.innerHTML = workflowsList.map(w => `
        <div class="workflow-card">
            <div class="workflow-head">
                <span class="tag">${w.priority}</span>
                <strong>${w.name}</strong>
                <small>${w.category}</small>
            </div>
            <p>${w.usage}</p>
            <div class="node-list">${(w.nodes || []).map(n => `<span>${n}</span>`).join('')}</div>
        </div>
    `).join('');
}

// === Agents ===
async function loadAgents() {
    try {
        const [data, standards] = await Promise.all([
            api('/api/agents'),
            api('/api/agent-standards'),
        ]);
        agentsList = data.agents || [];
        agentStandards = standards;
        renderAgentStandards();
        renderAgents();
    } catch (e) { /* handled */ }
}

function standardStatusLabel(status) {
    return { pass: '已满足', partial: '部分满足', todo: '待补齐' }[status] || status;
}

function renderAgentStandards() {
    if (!agentStandards) return;
    const scoreEl = document.getElementById('agentComplianceScore');
    const verdictEl = document.getElementById('agentVerdict');
    const gridEl = document.getElementById('agentStandardGrid');
    const runtimeEl = document.getElementById('runtimeGrid');
    const handoffEl = document.getElementById('handoffList');
    if (scoreEl) scoreEl.textContent = `${agentStandards.compliance_score} / 100`;
    if (verdictEl) verdictEl.textContent = agentStandards.verdict;
    if (gridEl) {
        gridEl.innerHTML = (agentStandards.required_contract || []).map(item => `
            <div class="standard-item ${item.status}">
                <div>
                    <strong>${item.name}</strong>
                    <span>${item.description}</span>
                </div>
                <em>${standardStatusLabel(item.status)}</em>
            </div>
        `).join('');
    }
    if (runtimeEl) {
        runtimeEl.innerHTML = Object.entries(agentStandards.runtime_state || {}).map(([key, values]) => `
            <div class="runtime-card">
                <strong>${key}</strong>
                <div class="chip-list">${values.map(v => `<span>${v}</span>`).join('')}</div>
            </div>
        `).join('');
    }
    if (handoffEl) {
        handoffEl.innerHTML = (agentStandards.handoff_policy || []).map(rule => `<div>${rule}</div>`).join('');
    }
}

function renderAgents() {
    const el = document.getElementById('agentGrid');
    if (!el) return;
    el.innerHTML = agentsList.map(agent => `
        <div class="agent-card">
            <div class="agent-card-top">
                <strong>${agent.name}</strong>
                <span class="task-status ${agent.status === 'active' ? 'running' : agent.status === 'partial' ? 'pending' : 'done'}">● ${agent.status}</span>
            </div>
            <p>${agent.goal || ''}</p>
            <div class="agent-output">${agent.output}</div>
            <div class="agent-section"><b>输入</b><div class="chip-list">${(agent.inputs || []).map(c => `<span>${c}</span>`).join('')}</div></div>
            <div class="agent-section"><b>工具</b><div class="chip-list">${(agent.tools || []).map(c => `<span>${c}</span>`).join('')}</div></div>
            <div class="agent-section"><b>记忆</b><div class="chip-list">${(agent.memory || []).map(c => `<span>${c}</span>`).join('')}</div></div>
            <div class="agent-section"><b>护栏</b><div class="chip-list">${(agent.guardrails || []).map(c => `<span>${c}</span>`).join('')}</div></div>
            <div class="agent-section"><b>评估</b><div class="chip-list">${(agent.evals || []).map(c => `<span>${c}</span>`).join('')}</div></div>
        </div>
    `).join('');
}

function openNewProductModal() {
    document.getElementById('productForm').reset();
    const zone = document.getElementById('productUploadZone');
    zone.classList.remove('has-image');
    zone.querySelector('.icon').style.display = '';
    zone.querySelector('.text').style.display = '';
    const oldPreview = zone.querySelector('.upload-preview');
    if (oldPreview) oldPreview.remove();

    document.getElementById('productModal').classList.add('active');
}

async function handleProductSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const data = {
        product_id: form.product_id.value.trim(),
        name: form.name.value.trim(),
        description: form.description.value.trim(),
        target_audience: form.target_audience.value.trim(),
        positioning: form.positioning.value.trim(),
        selling_points: form.selling_points.value.split('\n').map(s => s.trim()).filter(Boolean),
        keywords: form.keywords.value.split(',').map(s => s.trim()).filter(Boolean),
        scene_requirements: form.scene_requirements.value.trim(),
    };

    try {
        await api('/api/products', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });

        // Upload image if selected
        const fileInput = form.querySelector('input[type="file"]');
        if (fileInput.files.length > 0) {
            const fd = new FormData();
            fd.append('file', fileInput.files[0]);
            await api(`/api/products/${data.product_id}/image`, { method: 'POST', body: fd });
        }

        showToast('产品保存成功！', 'success');
        closeModal('productModal');
        loadProducts();
        loadDashboard();
    } catch (e) { /* handled */ }
}

// === Tasks ===
async function loadTasks() {
    try {
        const data = await api('/api/tasks');
        tasksList = data.tasks || [];
        renderTasks();
    } catch (e) { /* handled */ }
}

function renderTasks() {
    const list = document.getElementById('taskList');
    const empty = document.getElementById('taskEmpty');

    if (tasksList.length === 0) {
        list.innerHTML = '';
        empty.style.display = 'block';
        return;
    }

    empty.style.display = 'none';
    list.innerHTML = tasksList.map(t => {
        const statusClass = t.status || 'pending';
        const statusText = { done: '已完成', running: '运行中', pending: '等待中', error: '失败' }[statusClass] || t.status;
        const time = t.created_at ? new Date(t.created_at).toLocaleString('zh-CN') : '-';
        return `
        <div class="task-item" onclick="viewTask('${t.task_id}')">
            <div class="task-id">#${t.task_id}</div>
            <div class="task-product">${t.product_id}</div>
            <div class="task-status ${statusClass}">● ${statusText}</div>
            <div class="task-time">${time}</div>
            <div>
                <div class="progress-bar"><div class="progress-fill" style="width:${t.progress || 0}%"></div></div>
            </div>
        </div>`;
    }).join('');
}

function startTask(productId) {
    document.getElementById('taskProductSelect').value = productId;
    openNewTaskModal();
}

function openNewTaskModal() {
    // Populate product select
    const select = document.getElementById('taskProductSelect');
    const currentVal = select.value;
    select.innerHTML = '<option value="">-- 选择产品 --</option>' +
        products.map(p => `<option value="${p.product_id}" ${p.product_id === currentVal ? 'selected' : ''}>${p.product_id} - ${p.name}</option>`).join('');

    // Reset upload zone
    const zone = document.getElementById('taskUploadZone');
    if (zone) {
        zone.classList.remove('has-image');
        const icon = zone.querySelector('.icon');
        const text = zone.querySelector('.text');
        if (icon) icon.style.display = '';
        if (text) text.style.display = '';
        const oldPreview = zone.querySelector('.upload-preview');
        if (oldPreview) oldPreview.remove();
        const fileInput = zone.querySelector('input[type="file"]');
        if (fileInput) fileInput.value = '';
    }
    setupDragDrop();

    document.getElementById('taskModal').classList.add('active');
}

async function handleTaskSubmit(e) {
    e.preventDefault();
    const form = e.target;
    const productId = form.product_id.value;

    // Upload image first
    const fileInput = form.querySelector('input[name="product_image"]');
    if (fileInput && fileInput.files.length > 0) {
        const imgFd = new FormData();
        imgFd.append('file', fileInput.files[0]);
        try {
            await api(`/api/products/${productId}/image`, { method: 'POST', body: imgFd });
        } catch (err) {
            showToast('\u56fe\u7247\u4e0a\u4f20\u5931\u8d25', 'error');
            return;
        }
    }

    // Create task
    const fd = new FormData();
    fd.append('product_id', productId);
    fd.append('model', form.model.value);
    fd.append('scene_count', form.scene_count.value);

    try {
        const data = await api('/api/tasks', { method: 'POST', body: fd });
        showToast(`任务 #${data.task_id} 已创建，Pipeline 执行中...`, 'success');
        closeModal('taskModal');
        loadTasks();
        // 自动打开任务详情并轮询进度
        pollTaskProgress(data.task_id);
    } catch (e) { /* handled */ }
}

function pollTaskProgress(taskId) {
    viewTask(taskId);
    const interval = setInterval(async () => {
        const modal = document.getElementById('taskDetailModal');
        const isOpen = modal.classList.contains('active');
        try {
            const t = await fetch(`/api/tasks/${taskId}`).then(r => r.json());
            if (t.status === 'done' || t.status === 'error') {
                clearInterval(interval);
                loadTasks();
                loadDashboard();
                if (isOpen) updateTaskDetail(t);
                if (t.status === 'done') showToast(`任务 #${taskId} 已完成！`, 'success');
                if (t.status === 'error') showToast(`任务 #${taskId} 失败`, 'error');
            } else if (isOpen) {
                updateTaskDetail(t);
            }
        } catch (e) { clearInterval(interval); }
    }, 5000);
}

async function viewTask(taskId) {
    try {
        const t = await api(`/api/tasks/${taskId}`);
        updateTaskDetail(t);
        document.getElementById('taskDetailModal').classList.add('active');
    } catch (e) { /* handled */ }
}

function updateTaskDetail(t) {
    const taskId = t.task_id;
    document.getElementById('taskDetailTitle').textContent = `📋 任务 #${taskId}`;
    const statusClass = t.status || 'pending';
    const statusText = { done: '已完成', running: '运行中', pending: '等待中', error: '失败' }[statusClass] || t.status;

    let imagesHtml = '';
    if (t.images && t.images.length > 0) {
        imagesHtml = `
            <div class="form-label" style="margin:20px 0 12px;">生成图片</div>
            <div class="gallery-grid">
                ${t.images.map(img => `
                    <div class="gallery-item">
                        <img src="/api/tasks/${taskId}/images/${img.filename}" alt="${img.name}" loading="lazy">
                        <div class="info">
                            <h4>${img.name || img.filename}</h4>
                            <p>${img.type || ''}</p>
                        </div>
                    </div>
                `).join('')}
            </div>`;
    }

    document.getElementById('taskDetailContent').innerHTML = `
        <div class="form-grid">
            <div class="form-group">
                <div class="form-label">任务ID</div>
                <div style="font-family:monospace; color:var(--accent);">${taskId}</div>
            </div>
            <div class="form-group">
                <div class="form-label">状态</div>
                <div class="task-status ${statusClass}">● ${statusText}</div>
            </div>
            <div class="form-group">
                <div class="form-label">产品</div>
                <div>${t.product_id}</div>
            </div>
            <div class="form-group">
                <div class="form-label">当前步骤</div>
                <div>${t.current_step || '-'}</div>
            </div>
            <div class="form-group full">
                <div class="form-label">进度</div>
                <div class="progress-bar" style="height:10px;"><div class="progress-fill" style="width:${t.progress || 0}%"></div></div>
            </div>
        </div>
        ${imagesHtml}
    `;
}

// === Review Center ===
async function loadReviews() {
    try {
        const data = await api('/api/reviews');
        reviewList = data.reviews || [];
        renderReviews();
    } catch (e) { /* handled */ }
}

function reviewImageUrl(item, img) {
    if (item.output_dir) return `/output/${item.output_dir}/${img.filename}`;
    return `/api/tasks/${item.task_id}/images/${img.filename}`;
}

function renderReviews() {
    const el = document.getElementById('reviewList');
    const empty = document.getElementById('reviewEmpty');
    if (!el) return;
    if (reviewList.length === 0) {
        el.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
    }
    if (empty) empty.style.display = 'none';
    el.innerHTML = reviewList.map(item => `
        <div class="review-card">
            <div class="review-main">
                <div>
                    <div class="task-id">#${item.task_id}</div>
                    <h3>${item.sku_id}</h3>
                    <p>${item.issue || '等待人工审核确认商业可用性'}</p>
                </div>
                <div class="quality-score">
                    <span>${item.score || '-'}</span>
                    <small>质检分</small>
                </div>
                <span class="task-status pending">● ${item.status}</span>
            </div>
            <div class="review-images">
                ${(item.images || []).map(img => `<img src="${reviewImageUrl(item, img)}" alt="${img.name}" loading="lazy">`).join('')}
            </div>
            <div class="btn-group">
                <button class="btn btn-sm btn-primary" type="button">通过</button>
                <button class="btn btn-sm btn-secondary" type="button">驳回</button>
                <button class="btn btn-sm btn-secondary" type="button">一键重生成</button>
            </div>
        </div>
    `).join('');
}

// === Modals ===
function closeModal(id) {
    document.getElementById(id).classList.remove('active');
}

// Close modal on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) overlay.classList.remove('active');
    });
});

// === Image Upload ===
function handleImagePreview(e, zoneId) {
    const file = e.target.files[0];
    if (!file) return;

    const zone = document.getElementById(zoneId);
    const reader = new FileReader();
    reader.onload = (ev) => {
        zone.classList.add('has-image');
        zone.querySelector('.icon').style.display = 'none';
        zone.querySelector('.text').style.display = 'none';
        const oldPreview = zone.querySelector('.upload-preview');
        if (oldPreview) oldPreview.remove();
        const img = document.createElement('img');
        img.src = ev.target.result;
        img.className = 'upload-preview';
        zone.appendChild(img);
    };
    reader.readAsDataURL(file);
}

function setupDragDrop() {
    document.querySelectorAll('.upload-zone').forEach(zone => {
        zone.addEventListener('dragover', (e) => { e.preventDefault(); zone.classList.add('dragover'); });
        zone.addEventListener('dragleave', () => zone.classList.remove('dragover'));
        zone.addEventListener('drop', (e) => {
            e.preventDefault();
            zone.classList.remove('dragover');
            const input = zone.querySelector('input[type="file"]');
            if (e.dataTransfer.files.length > 0) {
                input.files = e.dataTransfer.files;
                input.dispatchEvent(new Event('change'));
            }
        });
    });
}

// === Settings ===
async function loadSettings() {
    try {
        const data = await api('/api/settings');

        // API Keys (show masked values)
        document.getElementById('settingOpenaiKey').value = data.api_keys?.openai_api_key || '';
        document.getElementById('settingOpenaiBaseUrl').value = data.api_keys?.openai_base_url || '';
        document.getElementById('settingGoogleKey').value = data.api_keys?.google_api_key || '';

        // Status indicators
        const rawSet = data._raw_keys_set || {};
        document.getElementById('testResultOpenai').innerHTML = rawSet.openai_api_key
            ? '<span style="color:var(--success)">● 已配置</span>'
            : '<span style="color:var(--text-muted)">○ 未配置</span>';
        document.getElementById('testResultGoogle').innerHTML = rawSet.google_api_key
            ? '<span style="color:var(--success)">● 已配置</span>'
            : '<span style="color:var(--text-muted)">○ 未配置</span>';

        // Models
        document.getElementById('modelImagePrimary').value = data.models?.image_primary || '';
        document.getElementById('modelImageSecondary').value = data.models?.image_secondary || '';
        document.getElementById('modelLlmPrimary').value = data.models?.llm_primary || '';
        document.getElementById('modelLlmSecondary').value = data.models?.llm_secondary || '';
        document.getElementById('modelTranslation').value = data.models?.translation || '';
        document.getElementById('modelQuality').value = data.models?.quality || '';

        // Pipeline
        document.getElementById('pipelineCandidates').value = data.pipeline?.candidates_per_step || 2;
        document.getElementById('pipelineThreshold').value = data.pipeline?.quality_threshold || 0.85;
        document.getElementById('pipelineRetries').value = data.pipeline?.max_retries || 3;
    } catch (e) { /* handled */ }
}

async function saveSettings() {
    const body = {
        api_keys: {
            openai_api_key: document.getElementById('settingOpenaiKey').value,
            openai_base_url: document.getElementById('settingOpenaiBaseUrl').value,
            google_api_key: document.getElementById('settingGoogleKey').value,
        },
        models: {
            image_primary: document.getElementById('modelImagePrimary').value,
            image_secondary: document.getElementById('modelImageSecondary').value,
            llm_primary: document.getElementById('modelLlmPrimary').value,
            llm_secondary: document.getElementById('modelLlmSecondary').value,
            translation: document.getElementById('modelTranslation').value,
            quality: document.getElementById('modelQuality').value,
        },
        pipeline: {
            candidates_per_step: parseInt(document.getElementById('pipelineCandidates').value) || 2,
            quality_threshold: parseFloat(document.getElementById('pipelineThreshold').value) || 0.85,
            max_retries: parseInt(document.getElementById('pipelineRetries').value) || 3,
        },
    };

    try {
        await api('/api/settings', {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        showToast('设置已保存', 'success');
        loadModels(); // refresh dashboard model display
    } catch (e) { /* handled */ }
}

function togglePassword(inputId) {
    const input = document.getElementById(inputId);
    input.type = input.type === 'password' ? 'text' : 'password';
}

async function testConnection(provider) {
    const resultEl = document.getElementById(`testResult${provider === 'openai' ? 'Openai' : 'Google'}`);
    resultEl.innerHTML = '<span style="color:var(--warning)">⏳ 测试中...</span>';

    try {
        const body = { provider };
        if (provider === 'openai') {
            const key = document.getElementById('settingOpenaiKey').value;
            const baseUrl = document.getElementById('settingOpenaiBaseUrl').value;
            if (key && !key.includes('***')) body.api_key = key;
            if (baseUrl) body.base_url = baseUrl;
        } else {
            const key = document.getElementById('settingGoogleKey').value;
            if (key && !key.includes('***')) body.api_key = key;
        }

        const data = await api('/api/settings/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });

        if (data.status === 'ok') {
            resultEl.innerHTML = `<span style="color:var(--success)">✅ ${data.message}</span>`;
        } else {
            resultEl.innerHTML = `<span style="color:var(--error)">❌ ${data.message}</span>`;
        }
    } catch (e) {
        resultEl.innerHTML = `<span style="color:var(--error)">❌ 连接失败</span>`;
    }
}

// === Toast ===
function showToast(msg, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = msg;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}
