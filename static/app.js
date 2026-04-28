/* ===== State ===== */
let currentPage = 'workbench';
let currentSku = null;
let products = [];
let tasksList = [];
let kbTab = 'category';

/* ===== Navigation ===== */
function showPage(page) {
    currentPage = page;
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    const el = document.getElementById('page-' + page);
    if (el) el.classList.add('active');
    document.querySelectorAll('#topNav button').forEach(b => b.classList.remove('active'));
    const btns = document.querySelectorAll('#topNav button');
    const map = { workbench: 0, tasks: 1, assets: 2, knowledge: 3, settings: 4 };
    if (map[page] !== undefined && btns[map[page]]) btns[map[page]].classList.add('active');
    if (page === 'tasks') loadTasks();
    if (page === 'assets') renderAssets();
    if (page === 'knowledge') renderKb();
    if (page === 'settings') renderSettings();
}

/* ===== Toast ===== */
function toast(msg, type = 'info') {
    const c = document.getElementById('toastContainer');
    const t = document.createElement('div');
    t.className = 'toast toast-' + type;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => t.remove(), 3000);
}

/* ===== Modal ===== */
function openModal(id) { document.getElementById(id).classList.add('show'); }
function closeModal(id) { document.getElementById(id).classList.remove('show'); }
function openNewProductModal() { openModal('productModal'); }
function openNewTaskModal() {
    const sel = document.getElementById('taskProductSelect');
    sel.innerHTML = '<option value="">-- 选择 --</option>' + products.map(p =>
        `<option value="${p.product_id}">${p.product_id} - ${p.name || ''}</option>`).join('');
    openModal('taskModal');
}

/* ===== Products ===== */
async function loadProducts() {
    try {
        const r = await fetch('/api/products');
        const d = await r.json();
        products = d.products || [];
    } catch { products = []; }
    renderSkuList();
    if (products.length && !currentSku) selectSku(products[0]);
}

function renderSkuList() {
    const el = document.getElementById('skuList');
    if (!products.length) { el.innerHTML = '<div style="padding:20px;text-align:center;color:var(--text-muted);font-size:12px;">暂无 SKU<br><button class="btn btn-primary btn-sm" style="margin-top:8px" onclick="openNewProductModal()">新建</button></div>'; return; }
    el.innerHTML = products.map(p => {
        const active = currentSku && currentSku.product_id === p.product_id ? ' active' : '';
        const img = p.image_url ? `<img src="${p.image_url}" alt="">` : '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:16px">📦</div>';
        const cat = p.category || 'Cat Tree';
        return `<div class="sku-card${active}" onclick="selectSku(products.find(x=>x.product_id==='${p.product_id}'))">
            <div class="sku-card-top">
                <div class="sku-card-thumb">${img}</div>
                <div class="sku-card-info">
                    <div class="sku-card-id">${p.product_id}</div>
                    <div class="sku-card-name">${p.name || p.product_id}</div>
                </div>
            </div>
            <div class="sku-card-meta">
                <span class="sku-tag explore">Explore</span>
                <span class="sku-tag pending">待选图</span>
            </div>
        </div>`;
    }).join('');
}

function filterSkuList() {
    const q = document.getElementById('skuSearchInput').value.toLowerCase();
    document.querySelectorAll('.sku-card').forEach(c => {
        c.style.display = c.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
}

function selectSku(sku) {
    if (!sku) return;
    currentSku = sku;
    renderSkuList();
    renderWorkbench();
}

/* ===== Workbench Center ===== */
function renderWorkbench() {
    if (!currentSku) return;
    const s = currentSku;
    document.getElementById('wbSkuTitle').textContent = `${s.product_id}｜${s.name || ''}`;
    document.getElementById('wbSkuMeta').innerHTML = `<span>品类：${s.category || 'Cat Tree / Cat Tower'}</span><span>定位：${(s.selling_points || []).slice(0, 3).join('、') || '高端大型猫爬架'}</span><span>关联知识库：猫爬架 Amazon 上货图通用提示词模板</span>`;
    renderImagePlan();
    renderRightPanel();
}

/* ===== Image Plan ===== */
const IMAGE_PLAN = [
    { key: 'hero_scene', label: '首图1', type: 'Hero Scene' },
    { key: 'hero_scene_2', label: '首图2', type: 'Hero Scene' },
    { key: 'lifestyle_scene', label: '场景图1', type: 'Lifestyle Scene' },
    { key: 'lifestyle_scene_2', label: '场景图2', type: 'Lifestyle Scene' },
    { key: 'material_plush', label: '材质图1', type: 'Material Detail' },
    { key: 'material_sisal', label: '材质图2', type: 'Material Detail' },
    { key: 'size_compare', label: '尺寸图', type: 'Size Compare' },
    { key: 'selling_1', label: '卖点图1', type: 'Selling Point' },
    { key: 'selling_2', label: '卖点图2', type: 'Selling Point' },
];

function renderImagePlan() {
    const area = document.getElementById('imagePlanArea');
    area.innerHTML = `<div class="plan-section-title">📋 图片计划 <span class="count">${IMAGE_PLAN.length} 张</span></div>
    <div class="plan-grid">${IMAGE_PLAN.map(p => imgCard(p.label, p.type, '2000×2000')).join('')}</div>`;
    renderExploreCandidates();
}

function imgCard(label, type, size, imgSrc, scores, badge) {
    const badgeHtml = badge ? `<div class="img-card-badge ${badge}">${badge === 'recommended' ? '推荐' : badge === 'candidate' ? '候选' : badge === 'failed' ? '失败' : '未开始'}</div>` : '';
    const bodyHtml = imgSrc ? `<img src="${imgSrc}" alt="${label}">${badgeHtml}` : `<div class="img-card-placeholder"><span class="icon">🖼</span>${size}</div>${badgeHtml}`;
    const scoresHtml = scores ? `<div class="img-card-scores">
        <div class="score"><span class="score-label">商业</span><span class="score-val ${scoreClass(scores.c)}">${scores.c}</span></div>
        <div class="score"><span class="score-label">一致性</span><span class="score-val ${scoreClass(scores.k)}">${scores.k}</span></div>
        <div class="score"><span class="score-label">缺陷</span><span class="score-val ${scoreClass(scores.d)}">${scores.d}</span></div>
    </div>` : '';
    return `<div class="img-card">
        <div class="img-card-head"><span class="img-card-title">${label}｜${type}</span><span class="img-card-size">${size}</span></div>
        <div class="img-card-body">${bodyHtml}</div>
        <div class="img-card-foot">${scoresHtml}
            <div class="img-card-actions">
                <button class="btn btn-xs btn-secondary">查看候选</button>
                <button class="btn btn-xs btn-secondary">重新生成</button>
            </div>
        </div>
    </div>`;
}

function scoreClass(v) { return v >= 85 ? 'high' : v >= 65 ? 'mid' : 'low'; }

/* ===== Explore Candidates ===== */
const MOCK_EXPLORE = [
    { group: '首图 Hero Scene', candidates: [
        { id: '首图1 - 候选1', scores: { c: 92, k: 88, d: 78 }, badge: 'candidate' },
        { id: '首图1 - 候选2', scores: { c: 92, k: 90, d: 86 }, badge: 'recommended' },
        { id: '首图1 - 候选3', scores: { c: 92, k: 94, d: 78 }, badge: 'recommended' },
        { id: '首图1 - 候选4', scores: { c: 92, k: 88, d: 78 }, badge: 'candidate' },
    ]},
    { group: '生活方式 Lifestyle Scene', candidates: [
        { id: '场景图1 - 候选1', scores: { c: 88, k: 83, d: 62 }, badge: 'candidate' },
        { id: '场景图1 - 候选2', scores: { c: 85, k: 82, d: 60 }, badge: 'candidate' },
        { id: '场景图1 - 候选3', scores: { c: 88, k: 92, d: 62 }, badge: 'candidate' },
        { id: '场景图1 - 候选4', scores: { c: 92, k: 90, d: 85 }, badge: 'recommended' },
    ]},
    { group: '材质细节 Material Detail', candidates: [
        { id: '材质图1 - 候选1', scores: { c: 78, k: 34, d: 90 }, badge: 'candidate' },
        { id: '材质图1 - 候选2', scores: { c: 78, k: 22, d: 92 }, badge: 'failed' },
        { id: '材质图1 - 候选3', scores: { c: 90, k: 68, d: 92 }, badge: 'candidate' },
        { id: '材质图1 - 候选4', scores: { c: 88, k: 62, d: 92 }, badge: 'candidate' },
    ]},
];

function renderExploreCandidates() {
    const area = document.getElementById('exploreCandidateArea');
    area.innerHTML = `<div class="plan-section-title" style="margin-top:12px">🔍 Explore 候选图 <span class="count">3 组 × 4 候选</span></div>` +
        MOCK_EXPLORE.map(g => `<div style="margin-bottom:8px;font-size:13px;font-weight:600;">${g.group}</div>
        <div class="candidate-row">${g.candidates.map(c =>
            imgCard(c.id, '', '2000×2000', null, c.scores, c.badge)
        ).join('')}</div>`).join('');
}

/* ===== Right Panel ===== */
function toggleRightPanel() {
    const r = document.getElementById('wbRight');
    r.classList.toggle('collapsed');
}

function renderRightPanel() {
    const body = document.getElementById('wbRightBody');
    body.innerHTML = `
    <div class="ctx-section">
        <div class="ctx-section-title">📂 当前品类知识</div>
        <div class="ctx-item"><span class="label">品类路径</span>Pet Supplies &gt; Cat Supplies &gt; Cat Furniture &gt; Cat Tree / Cat Tower / Cat Condo</div>
        <div class="ctx-item"><span class="label">文档名称</span>猫爬架 Amazon 上货图通用提示词模板</div>
        <div class="ctx-item"><span class="label">全局规则</span>保持产品结构、比例、颜色、材质、功能部件一致；不要重设计产品</div>
        <div class="ctx-item"><span class="label">场景规则</span>靠墙摆放；明显窗户光源；上午阳光；现代美国住宅风格</div>
        <div class="ctx-item"><span class="label">图形规则</span>橙色辅助色；宠物图标；手绘元素轻量使用</div>
        <div class="ctx-item"><span class="label">负面规则</span>
            <div><span class="ctx-tag">不改变材质</span><span class="ctx-tag">不改变结构</span><span class="ctx-tag">不遮挡核心结构</span><span class="ctx-tag">不用深色光照</span><span class="ctx-tag">不加水印</span></div>
        </div>
        <div class="ctx-item"><span class="label">检查清单</span>
            <ul class="ctx-checklist">
                <li>产品主体结构完整可识别</li>
                <li>颜色和材质与原图一致</li>
                <li>底座稳固感明确</li>
                <li>无多余文字/水印</li>
                <li>光照自然、阴影合理</li>
            </ul>
        </div>
    </div>
    <div class="ctx-section">
        <div class="ctx-section-title">🎨 素材选择</div>
        <div class="ctx-item"><span class="label">素材灵感库</span><span class="ctx-tag">竞品参考 ×3</span></div>
        <div class="ctx-item"><span class="label">标准素材库</span><span class="ctx-tag">图标包</span><span class="ctx-tag">品牌色</span></div>
        <div class="ctx-item"><span class="label">手绘装饰</span><span class="ctx-tag">轻量爪印</span></div>
    </div>
    <div class="ctx-section">
        <div class="ctx-section-title">⚙️ Agent 设置</div>
        <div class="agent-mini-form">
            <div class="row"><span class="label">SKU一致性等级</span><span class="value">medium_high</span></div>
            <div class="row"><span class="label">生成模式</span><span class="value">Explore</span></div>
            <div class="row"><span class="label">候选数量</span><span class="value">4</span></div>
            <div class="row"><span class="label">尺寸</span><span class="value">2000×2000</span></div>
            <div class="row"><span class="label">品类模板</span><span class="value">Cat Tree Amazon</span></div>
        </div>
    </div>`;
}

/* ===== Product Form ===== */
async function handleProductSubmit(e) {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
        await fetch('/api/products', { method: 'POST', body: fd });
        closeModal('productModal');
        toast('SKU 创建成功', 'success');
        e.target.reset();
        await loadProducts();
    } catch (err) { toast('创建失败: ' + err.message, 'error'); }
}

function handleImagePreview(e, zoneId) {
    const file = e.target.files[0];
    if (!file) return;
    const zone = document.getElementById(zoneId);
    const reader = new FileReader();
    reader.onload = (ev) => {
        zone.innerHTML = `<img src="${ev.target.result}" style="max-height:120px;border-radius:8px;"><input type="file" name="product_image" accept="image/*" onchange="handleImagePreview(event,'${zoneId}')">`;
    };
    reader.readAsDataURL(file);
}

/* ===== Task Form ===== */
async function handleTaskSubmit(e) {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
        const r = await fetch('/api/tasks', { method: 'POST', body: fd });
        const d = await r.json();
        closeModal('taskModal');
        toast(`任务 ${d.task_id} 已创建 (${d.mode})`, 'success');
        showPage('tasks');
    } catch (err) { toast('创建失败: ' + err.message, 'error'); }
}

/* ===== Explore Launch ===== */
async function launchExplore() {
    if (!currentSku) { toast('请先选择 SKU', 'error'); return; }
    try {
        const fd = new FormData();
        fd.append('product_id', currentSku.product_id);
        const r = await fetch('/api/explore-tasks', { method: 'POST', body: fd });
        const d = await r.json();
        toast(`Explore 任务 ${d.task_id} 已创建`, 'success');
    } catch (err) { toast('创建失败: ' + err.message, 'error'); }
}

/* ===== Tasks Page ===== */
async function loadTasks() {
    try {
        const r = await fetch('/api/tasks');
        const d = await r.json();
        tasksList = d.tasks || [];
    } catch { tasksList = []; }
    renderTasks();
}

function renderTasks() {
    const area = document.getElementById('taskListArea');
    if (!tasksList.length) { area.innerHTML = '<div style="text-align:center;padding:40px;color:var(--text-muted)">暂无任务</div>'; return; }
    area.innerHTML = tasksList.map(t => {
        const pct = t.progress || 0;
        const statusTag = t.status === 'done' ? '<span class="tag tag-green">完成</span>'
            : t.status === 'error' ? '<span class="tag tag-red">失败</span>'
            : t.status === 'running' ? '<span class="tag tag-blue">运行中</span>'
            : '<span class="tag tag-gray">等待</span>';
        return `<div class="task-row">
            <div class="task-id">${t.task_id}</div>
            <div class="task-sku">${t.product_id}</div>
            <div>${statusTag} <span class="tag tag-gray" style="margin-left:4px">${t.mode || 'batch'}</span></div>
            <div class="task-step">${t.current_step || ''}</div>
            <div class="task-progress"><div class="progress-bar"><div class="progress-bar-fill" style="width:${pct}%"></div></div></div>
        </div>`;
    }).join('');
}

/* ===== Assets Page ===== */
function renderAssets() {
    const area = document.getElementById('assetLibraryArea');
    const mockAssets = ['01_white_bg.png', '01_transparent.png', 'hero_scene_main_01.png', 'hero_scene_main_02.png', 'lifestyle_scene_main_01.png', 'material_detail_plush_01.png'];
    area.innerHTML = `<div class="asset-grid">${mockAssets.map(a => `<div class="asset-thumb">
        <div class="asset-thumb-img">🖼</div>
        <div class="asset-thumb-label">${a}</div>
    </div>`).join('')}</div>`;
}

/* ===== Knowledge Base ===== */
function showKbTab(tab) {
    kbTab = tab;
    document.querySelectorAll('#kbTabs button').forEach(b => b.classList.remove('active'));
    const btns = document.querySelectorAll('#kbTabs button');
    const map = { category: 0, inspiration: 1, standard: 2 };
    if (btns[map[tab]]) btns[map[tab]].classList.add('active');
    renderKb();
}

function renderKb() {
    const body = document.getElementById('kbBody');
    if (kbTab === 'category') renderKbCategory(body);
    else if (kbTab === 'inspiration') renderKbInspiration(body);
    else renderKbStandard(body);
}

function renderKbCategory(el) {
    el.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <div style="font-size:15px;font-weight:600;">品类知识库</div>
        <button class="btn btn-primary btn-sm" onclick="toast('上传文档功能即将上线','info')">📄 上传文档</button>
    </div>
    <table class="data-table"><thead><tr>
        <th>文档名称</th><th>适用品类</th><th>上传时间</th><th>解析状态</th><th>规则数</th><th>检查清单</th><th>关联SKU</th>
    </tr></thead><tbody>
        <tr>
            <td><strong>猫爬架 Amazon 上货图通用提示词模板</strong><br><span style="font-size:11px;color:var(--text-muted)">Cat Tree / Cat Tower Amazon Listing Image Prompt Template</span></td>
            <td><span class="tag tag-blue">Cat Tree</span></td>
            <td>2026-04-28</td>
            <td><span class="tag tag-green">已解析</span></td>
            <td>12</td><td>8</td><td>1</td>
        </tr>
        <tr>
            <td><strong>宠物用品 Amazon 主图规范</strong></td>
            <td><span class="tag tag-blue">Pet Supplies</span></td>
            <td>2026-04-20</td>
            <td><span class="tag tag-yellow">待解析</span></td>
            <td>-</td><td>-</td><td>0</td>
        </tr>
    </tbody></table>`;
}

function renderKbInspiration(el) {
    const items = [
        { name: 'Amazon Top 1 Cat Tree Listing', type: '竞品图', cat: 'Cat Tree', tags: ['hero', 'lifestyle'] },
        { name: '现代客厅猫爬架场景', type: '风格图', cat: 'Cat Tree', tags: ['scene', 'interior'] },
        { name: '宠物摄影灯光参考', type: '场景图', cat: 'Pet', tags: ['lighting', 'studio'] },
        { name: 'Infographic 排版参考', type: '排版参考', cat: 'General', tags: ['layout', 'info'] },
    ];
    el.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <div style="font-size:15px;font-weight:600;">素材灵感库</div>
        <button class="btn btn-primary btn-sm" onclick="toast('上传素材功能即将上线','info')">📎 上传素材</button>
    </div>
    <div class="insp-grid">${items.map(i => `<div class="insp-card">
        <div class="insp-card-img">🎨</div>
        <div class="insp-card-body">
            <h4>${i.name}</h4>
            <div class="meta"><span class="tag tag-gray">${i.type}</span> <span class="tag tag-blue">${i.cat}</span></div>
            <div style="margin-top:6px">${i.tags.map(t => `<span class="ctx-tag">${t}</span>`).join('')}</div>
        </div>
    </div>`).join('')}</div>`;
}

function renderKbStandard(el) {
    const items = [
        { name: '宠物图标包', type: '图标包', enabled: true },
        { name: '手绘爪印装饰', type: '手绘元素', enabled: true },
        { name: 'Brand Orange #FF6B35', type: '品牌色', enabled: true },
        { name: 'Logo 透明底', type: 'Logo', enabled: false },
        { name: '标准尺寸线样式', type: '尺寸标注', enabled: true },
        { name: 'Amazon Infographic 组件', type: '版式组件', enabled: false },
    ];
    el.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <div style="font-size:15px;font-weight:600;">标准素材库</div>
        <button class="btn btn-primary btn-sm" onclick="toast('上传素材功能即将上线','info')">📎 上传素材</button>
    </div>
    <table class="data-table"><thead><tr><th>素材名称</th><th>类型</th><th>预览</th><th>默认启用</th></tr></thead><tbody>
    ${items.map(i => `<tr><td><strong>${i.name}</strong></td><td><span class="tag tag-gray">${i.type}</span></td><td style="font-size:20px">🎨</td>
        <td>${i.enabled ? '<span class="tag tag-green">启用</span>' : '<span class="tag tag-gray">未启用</span>'}</td></tr>`).join('')}
    </tbody></table>`;
}

/* ===== Settings Page ===== */
async function renderSettings() {
    let settings = {};
    try { const r = await fetch('/api/settings'); settings = await r.json(); } catch {}
    const keys = settings.api_keys || {};
    const models = settings.models || {};
    const body = document.getElementById('settingsBody');
    body.innerHTML = `
    <div class="settings-card"><h3>🔑 API 密钥</h3>
        <div class="form-grid">
            <div class="form-group full"><label class="form-label">OpenAI API Key</label><input class="form-input" id="sKey" type="password" value="${keys.openai_api_key || ''}"></div>
            <div class="form-group full"><label class="form-label">OpenAI Base URL</label><input class="form-input" id="sUrl" value="${keys.openai_base_url || ''}"></div>
            <div class="form-group full"><label class="form-label">Google API Key</label><input class="form-input" id="sGoogle" type="password" value="${keys.google_api_key || ''}"></div>
        </div>
    </div>
    <div class="settings-card"><h3>🤖 模型路由</h3>
        <div class="form-grid">
            <div class="form-group"><label class="form-label">图像生成(主)</label><input class="form-input" id="mImg" value="${models.image_primary || 'gpt-image-2'}"></div>
            <div class="form-group"><label class="form-label">图像生成(备)</label><input class="form-input" id="mImg2" value="${models.image_secondary || ''}"></div>
            <div class="form-group"><label class="form-label">LLM(主)</label><input class="form-input" id="mLlm" value="${models.llm_primary || ''}"></div>
            <div class="form-group"><label class="form-label">LLM(备)</label><input class="form-input" id="mLlm2" value="${models.llm_secondary || ''}"></div>
            <div class="form-group"><label class="form-label">质量评估</label><input class="form-input" id="mQa" value="${models.quality || ''}"></div>
        </div>
    </div>
    <button class="btn btn-primary" onclick="saveSettings()">💾 保存设置</button>`;
}

async function saveSettings() {
    const data = {
        api_keys: { openai_api_key: document.getElementById('sKey')?.value, openai_base_url: document.getElementById('sUrl')?.value, google_api_key: document.getElementById('sGoogle')?.value },
        models: { image_primary: document.getElementById('mImg')?.value, image_secondary: document.getElementById('mImg2')?.value, llm_primary: document.getElementById('mLlm')?.value, llm_secondary: document.getElementById('mLlm2')?.value, quality: document.getElementById('mQa')?.value },
    };
    try {
        await fetch('/api/settings', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
        toast('设置已保存', 'success');
    } catch (err) { toast('保存失败', 'error'); }
}

/* ===== Init ===== */
document.addEventListener('DOMContentLoaded', () => { loadProducts(); });
