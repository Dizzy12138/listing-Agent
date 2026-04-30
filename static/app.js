/* ===== State ===== */
let currentPage = 'workbench';
let currentSku = null;
let products = [];
let tasksList = [];
let kbTab = 'category';
let currentTaskId = null;
let selectedCandidate = null;
const uploadOps = {};

function escapeHtml(v) {
    return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function scoreFromQa(qa) {
    if (!qa) return null;
    return {
        c: qa.commercial_score ?? qa.commercial ?? 0,
        k: qa.sku_consistency_score ?? qa.consistency ?? 0,
        d: qa.defect_score ?? qa.defect ?? 0,
    };
}

function statusLabel(status) {
    const map = { pending: '待解析', parsing: '解析中', parsed: '已解析', error: '失败' };
    return map[status] || status || '-';
}

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
function openSkuAssetModal() {
    if (!currentSku) { toast('请先选择 SKU', 'error'); return; }
    document.getElementById('skuAssetTitle').textContent = `${currentSku.product_id} 素材管理`;
    document.getElementById('skuAssetProductId').value = currentSku.product_id;
    renderSkuAssetList();
    openModal('skuAssetModal');
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
    document.getElementById('wbSkuMeta').innerHTML = `<span>品类：${s.category || '-'}</span><span>定位：${(s.selling_points || []).slice(0, 3).join('、') || '-'}</span>`;
    renderImagePlan();
    renderRightPanel();
}

/* ===== Image Plan ===== */
let currentExploreData = null;

async function renderImagePlan() {
    const area = document.getElementById('imagePlanArea');
    // Try to load real explore data for this SKU
    currentExploreData = null;
    currentTaskId = null;
    if (currentSku) {
        try {
            const r = await fetch('/api/tasks');
            const d = await r.json();
            const tasks = (d.tasks || []).filter(t => t.product_id === currentSku.product_id && t.mode === 'explore');
            if (tasks.length) {
                const latest = tasks[tasks.length - 1];
                currentTaskId = latest.task_id;
                const er = await fetch(`/api/tasks/${latest.task_id}/explore`);
                currentExploreData = await er.json();
            }
        } catch {}
    }
    if (currentExploreData && currentExploreData.candidates) {
        const types = Object.keys(currentExploreData.candidates);
        area.innerHTML = `<div class="plan-section-title">📋 图片计划 <span class="count">${types.length} 组</span></div>
        <div class="plan-grid">${types.map(t => {
            const g = currentExploreData.candidates[t];
            const recId = g.recommendation?.recommended;
            const rec = (g.candidates || []).find(c => (c.metadata?.candidate_id || c.filename?.replace(/\.png$/, '')) === recId) || (g.candidates || [])[0];
            const imgSrc = rec ? rec.image_url : (g.candidates[0]?.image_url || null);
            const scores = scoreFromQa(rec?.qa);
            return imgCard(t, '', '2000×2000', imgSrc, scores, rec ? 'recommended' : null);
        }).join('')}</div>`;
        renderExploreCandidates();
    } else {
        area.innerHTML = `<div class="plan-section-title">📋 图片计划</div>
        <div style="text-align:center;padding:40px;color:var(--text-muted);font-size:13px;">
            <div style="font-size:32px;margin-bottom:12px;">📷</div>
            尚无图片计划<br>点击「启动 Explore」生成候选图
        </div>`;
        document.getElementById('exploreCandidateArea').innerHTML = '';
    }
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
                <button class="btn btn-xs btn-secondary" onclick="renderExploreCandidates()">查看候选</button>
                <button class="btn btn-xs btn-secondary" onclick="launchExplore()">重新生成</button>
            </div>
        </div>
    </div>`;
}

function scoreClass(v) { return v >= 85 ? 'high' : v >= 65 ? 'mid' : 'low'; }

/* ===== Explore Candidates ===== */
function renderExploreCandidates() {
    const area = document.getElementById('exploreCandidateArea');
    if (!currentExploreData || !currentExploreData.candidates) {
        area.innerHTML = '';
        return;
    }
    const types = Object.keys(currentExploreData.candidates);
    area.innerHTML = `<div class="plan-section-title" style="margin-top:12px">🔍 Explore 候选图 <span class="count">${types.length} 组</span></div>` +
        types.map(t => {
            const g = currentExploreData.candidates[t];
            const cands = g.candidates || [];
            return `<div style="margin-bottom:8px;font-size:13px;font-weight:600;">${t}</div>
            <div class="candidate-row">${cands.map(c => {
                const candidateId = c.metadata?.candidate_id || (c.filename || '').replace(/\.png$/, '');
                const scores = scoreFromQa(c.qa);
                const review = c.review || currentExploreData.candidate_reviews?.[candidateId] || {};
                const badge = g.recommendation?.recommended === candidateId ? 'recommended' : (review.decision === 'approved' ? 'recommended' : 'candidate');
                const selected = selectedCandidate?.candidate_id === candidateId ? ' selected' : '';
                return candidateCard(t, c, scores, badge, selected, review);
            }).join('')}</div>`;
        }).join('') + `<div id="candidateInspectorArea">${selectedCandidate ? candidateInspector(selectedCandidate) : ''}</div>`;
}

function candidateCard(typeKey, c, scores, badge, selected, review) {
    const candidateId = c.metadata?.candidate_id || (c.filename || '').replace(/\.png$/, '');
    const title = c.metadata?.generation_strategy || c.filename || typeKey;
    const bodyHtml = c.image_url ? `<img src="${c.image_url}" alt="${escapeHtml(candidateId)}">` : `<div class="img-card-placeholder"><span class="icon">🖼</span>暂无图片</div>`;
    const badgeHtml = `<div class="img-card-badge ${badge}">${badge === 'recommended' ? '推荐' : '候选'}</div>`;
    const reviewTag = review.decision ? `<span class="tag ${review.decision === 'approved' ? 'tag-green' : review.decision === 'rejected' ? 'tag-red' : 'tag-yellow'}">${review.decision}</span>` : '';
    const scoresHtml = scores ? `<div class="img-card-scores">
        <div class="score"><span class="score-label">商业</span><span class="score-val ${scoreClass(scores.c)}">${scores.c}</span></div>
        <div class="score"><span class="score-label">一致性</span><span class="score-val ${scoreClass(scores.k)}">${scores.k}</span></div>
        <div class="score"><span class="score-label">缺陷</span><span class="score-val ${scoreClass(scores.d)}">${scores.d}</span></div>
    </div>` : '';
    const payload = encodeURIComponent(JSON.stringify({ ...c, type_key: typeKey, candidate_id: candidateId }));
    return `<div class="img-card candidate-card${selected}" data-candidate-id="${escapeHtml(candidateId)}">
        <div class="img-card-head"><span class="img-card-title">${escapeHtml(candidateId)}</span><span class="img-card-size">${reviewTag}</span></div>
        <div class="img-card-body" onclick="openCandidateLightbox('${payload}')">${bodyHtml}${badgeHtml}</div>
        <div class="img-card-foot">${scoresHtml}
            <div class="candidate-meta">${escapeHtml(title)}</div>
            <div class="img-card-actions">
                <button class="btn btn-xs btn-primary" onclick="selectCandidate('${payload}')">选中</button>
                <button class="btn btn-xs btn-secondary" onclick="openCandidateLightbox('${payload}')">放大</button>
                <button class="btn btn-xs btn-secondary" onclick="selectCandidate('${payload}', true)">标记/评论</button>
            </div>
        </div>
    </div>`;
}

function decodePayload(payload) { return JSON.parse(decodeURIComponent(payload)); }

function selectCandidate(payload, focusComment = false) {
    selectedCandidate = decodePayload(payload);
    renderExploreCandidates();
    if (focusComment) setTimeout(() => document.getElementById('candidateComment')?.focus(), 0);
}

function candidateInspector(c) {
    const candidateId = c.candidate_id;
    const review = c.review || currentExploreData?.candidate_reviews?.[candidateId] || {};
    const issues = c.qa?.issues || c.metadata?.issues || [];
    return `<div class="candidate-inspector">
        <div class="candidate-inspector-img">${c.image_url ? `<img src="${c.image_url}">` : ''}</div>
        <div class="candidate-inspector-body">
            <div class="candidate-inspector-title">${escapeHtml(candidateId)}</div>
            <div class="candidate-inspector-meta">${escapeHtml(c.type_key || '')} · ${escapeHtml(c.metadata?.generation_strategy || '')}</div>
            <div class="candidate-issues">${issues.map(i => `<span class="ctx-tag">${escapeHtml(i)}</span>`).join('') || '<span class="ctx-tag">暂无问题记录</span>'}</div>
            <textarea class="form-textarea" id="candidateComment" rows="3" placeholder="写审核意见、修改要求或投放备注...">${escapeHtml(review.comment || '')}</textarea>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px;">
                <button class="btn btn-sm btn-primary" onclick="saveCandidateReview('approved')">设为选中</button>
                <button class="btn btn-sm btn-secondary" onclick="saveCandidateReview('needs_revision')">需修改</button>
                <button class="btn btn-sm btn-secondary" onclick="saveCandidateReview('rejected')">驳回</button>
                <button class="btn btn-sm btn-secondary" onclick="openCandidateLightbox('${encodeURIComponent(JSON.stringify(c))}')">放大查看</button>
            </div>
        </div>
    </div>`;
}

async function saveCandidateReview(decision) {
    if (!selectedCandidate || !currentTaskId) { toast('没有可保存的候选图', 'error'); return; }
    const comment = document.getElementById('candidateComment')?.value || '';
    const r = await fetch(`/api/tasks/${currentTaskId}/candidates/${selectedCandidate.candidate_id}/review`, {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ decision, comment, tags: [selectedCandidate.type_key || 'candidate'] }),
    });
    if (!r.ok) { toast('保存失败', 'error'); return; }
    const d = await r.json();
    currentExploreData.candidate_reviews = currentExploreData.candidate_reviews || {};
    currentExploreData.candidate_reviews[selectedCandidate.candidate_id] = d.review;
    selectedCandidate.review = d.review;
    toast('候选图反馈已保存', 'success');
    renderExploreCandidates();
}

function openCandidateLightbox(payload) {
    const c = decodePayload(payload);
    const modal = document.getElementById('candidateLightboxModal');
    document.getElementById('candidateLightboxTitle').textContent = c.candidate_id || c.filename || '候选图';
    document.getElementById('candidateLightboxBody').innerHTML = `
        <div class="lightbox-img-wrap">${c.image_url ? `<img src="${c.image_url}" alt="">` : ''}</div>
        <div class="lightbox-meta">
            <div><strong>类型：</strong>${escapeHtml(c.type_key || '')}</div>
            <div><strong>策略：</strong>${escapeHtml(c.metadata?.generation_strategy || '')}</div>
            <div><strong>QA：</strong>${escapeHtml(c.qa?.decision || 'needs_review')}</div>
            ${(c.qa?.issues || c.metadata?.issues || []).map(i => `<span class="ctx-tag">${escapeHtml(i)}</span>`).join('')}
        </div>`;
    modal.classList.add('show');
}

/* ===== Right Panel ===== */
function toggleRightPanel() {
    const r = document.getElementById('wbRight');
    r.classList.toggle('collapsed');
}

async function renderRightPanel() {
    const body = document.getElementById('wbRightBody');
    let skuAssets = [];
    if (currentSku) {
        try { const r = await fetch(`/api/products/${currentSku.product_id}/assets`); skuAssets = (await r.json()).assets || []; } catch {}
    }
    // Load knowledge docs and find matching ones
    let docs = [];
    try { const r = await fetch('/api/knowledge-docs'); docs = (await r.json()).docs || []; } catch {}
    const parsed = docs.filter(d => d.parse_status === 'parsed');
    // Load asset packs
    let packs = [];
    try { const r = await fetch('/api/asset-packs'); packs = (await r.json()).packs || []; } catch {}
    const confirmedPacks = packs.filter(p => p.parse_status === 'parsed');

    // Knowledge section
    let knowledgeHtml = '';
    if (parsed.length) {
        const doc = parsed[0];
        let k = doc.parsed_knowledge || {};
        if (!Object.keys(k).length && doc.doc_id) {
            try { const r = await fetch(`/api/knowledge-docs/${doc.doc_id}/summary`); const d = await r.json(); k = d.knowledge || {}; } catch {}
        }
        knowledgeHtml = `<div class="ctx-section"><div class="ctx-section-title">📂 品类知识 · ${doc.name}</div>
            ${k.category_path ? `<div class="ctx-item"><span class="label">品类路径</span>${k.category_path}</div>` : ''}
            ${(k.global_rules||[]).length ? `<div class="ctx-item"><span class="label">全局规则</span>${k.global_rules.map(r=>'<div>• '+r+'</div>').join('')}</div>` : ''}
            ${(k.scene_rules||[]).length ? `<div class="ctx-item"><span class="label">场景规则</span>${k.scene_rules.map(r=>'<div>• '+r+'</div>').join('')}</div>` : ''}
            ${(k.negative_prompts||[]).length ? `<div class="ctx-item"><span class="label">负面规则</span><div>${k.negative_prompts.map(r=>'<span class="ctx-tag">'+r+'</span>').join('')}</div></div>` : ''}
            ${(k.checklist||[]).length ? `<div class="ctx-item"><span class="label">检查清单</span><ul class="ctx-checklist">${k.checklist.map(c=>'<li>'+c+'</li>').join('')}</ul></div>` : ''}
        </div>`;
    } else {
        knowledgeHtml = `<div class="ctx-section"><div class="ctx-section-title">📂 品类知识</div>
            <div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">暂无已解析的知识文档<br><a href="#" onclick="showPage('knowledge');return false;">去上传文档</a></div></div>`;
    }

    // Assets section
    let assetsHtml = '';
    if (confirmedPacks.length) {
        assetsHtml = `<div class="ctx-section"><div class="ctx-section-title">🎨 素材包 (${confirmedPacks.length})</div>
            ${confirmedPacks.map(p => `<div class="ctx-item"><span class="label">${p.name}</span><span class="ctx-tag">${p.item_count} 项</span></div>`).join('')}</div>`;
    } else {
        assetsHtml = `<div class="ctx-section"><div class="ctx-section-title">🎨 素材包</div>
            <div style="padding:16px;text-align:center;color:var(--text-muted);font-size:12px;">暂无素材包<br><a href="#" onclick="showPage('assets');return false;">去上传素材</a></div></div>`;
    }

    const skuAssetsHtml = `<div class="ctx-section"><div class="ctx-section-title">🧩 当前 SKU 素材</div>
        ${skuAssets.length ? skuAssets.slice(0, 6).map(a => `<div class="sku-asset-mini">
            ${a.url ? `<img src="${a.url}">` : '<div class="sku-asset-mini-empty">素材</div>'}
            <div><strong>${escapeHtml(a.type)}</strong><br><span>${escapeHtml(a.name)}</span></div>
        </div>`).join('') : '<div style="padding:12px;color:var(--text-muted);font-size:12px;">暂无 SKU 素材</div>'}
        <button class="btn btn-secondary btn-sm" style="width:100%;margin-top:8px" onclick="openSkuAssetModal()">上传/管理 SKU 素材</button>
    </div>`;

    body.innerHTML = skuAssetsHtml + knowledgeHtml + assetsHtml + `
    <div class="ctx-section">
        <div class="ctx-section-title">⚙️ Agent 设置</div>
        <div class="agent-mini-form">
            <div class="row"><span class="label">生成模式</span><span class="value">Explore</span></div>
            <div class="row"><span class="label">候选数量</span><span class="value">4</span></div>
            <div class="row"><span class="label">尺寸</span><span class="value">2000×2000</span></div>
        </div>
    </div>`;
}

/* ===== Product Form ===== */
async function handleProductSubmit(e) {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
        const productId = (fd.get('product_id') || '').toString().trim();
        const data = {
            product_id: productId,
            name: (fd.get('name') || '').toString(),
            description: (fd.get('description') || '').toString(),
            target_audience: (fd.get('target_audience') || '').toString(),
            positioning: (fd.get('positioning') || '').toString(),
            selling_points: (fd.get('selling_points') || '').toString().split('\n').map(x => x.trim()).filter(Boolean),
            keywords: [],
            image_plan: [],
        };
        await fetch('/api/products', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        const image = fd.get('product_image');
        if (image && image.size) {
            const imgFd = new FormData();
            imgFd.append('file', image);
            await fetch(`/api/products/${productId}/image`, { method: 'POST', body: imgFd });
        }
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

function handleFileSelect(e) {
    const input = e.target;
    const files = Array.from(input.files || []);
    const zone = input.closest('.upload-zone');
    if (!zone) return;
    zone.classList.toggle('has-file', files.length > 0);
    zone.querySelector('.upload-selected')?.remove();
    if (!files.length) return;

    const total = files.reduce((sum, f) => sum + (f.size || 0), 0);
    const label = files.length === 1
        ? files[0].name
        : `${files.length} 个文件：${files.slice(0, 3).map(f => f.name).join('、')}${files.length > 3 ? '...' : ''}`;
    const selected = document.createElement('div');
    selected.className = 'upload-selected';
    selected.innerHTML = `<strong>已选择</strong><span title="${escapeHtml(label)}">${escapeHtml(label)}</span><em>${formatBytes(total)}</em>`;
    zone.appendChild(selected);
}

function clearUploadSelection(form) {
    form.querySelectorAll('.upload-zone').forEach(zone => {
        zone.classList.remove('has-file');
        zone.querySelector('.upload-selected')?.remove();
    });
}

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let size = bytes;
    let idx = 0;
    while (size >= 1024 && idx < units.length - 1) {
        size /= 1024;
        idx++;
    }
    return `${size.toFixed(size >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`;
}

async function renderSkuAssetList() {
    const area = document.getElementById('skuAssetList');
    if (!area || !currentSku) return;
    try {
        const r = await fetch(`/api/products/${currentSku.product_id}/assets`);
        const d = await r.json();
        const assets = d.assets || [];
        area.innerHTML = assets.length ? `<div class="sku-asset-grid">${assets.map(a => `
            <div class="sku-asset-card">
                <div class="sku-asset-preview">${a.url ? `<img src="${a.url}">` : '素材'}</div>
                <div class="sku-asset-name">${escapeHtml(a.name)}</div>
                <div class="sku-asset-type">${escapeHtml(a.type)}</div>
            </div>`).join('')}</div>` : '<div style="padding:20px;text-align:center;color:var(--text-muted)">暂无素材</div>';
    } catch {
        area.innerHTML = '<div style="padding:20px;color:var(--danger)">素材加载失败</div>';
    }
}

async function handleSkuAssetUpload(e) {
    e.preventDefault();
    if (!currentSku) return;
    const form = e.target;
    const file = form.querySelector('input[type=file]')?.files?.[0];
    if (!file) { toast('请选择图片', 'info'); return; }
    const fd = new FormData();
    fd.append('file', file);
    const btn = form.querySelector('button[type=submit]');
    const orig = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '上传中...';
    try {
        await uploadWithProgress(`/api/products/${currentSku.product_id}/image`, fd, () => {});
        toast('SKU 原始图已更新', 'success');
        form.reset();
        clearUploadSelection(form);
        await loadProducts();
        currentSku = products.find(p => p.product_id === currentSku.product_id) || currentSku;
        renderWorkbench();
        renderSkuAssetList();
    } catch (err) {
        toast('上传失败: ' + err.message, 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = orig;
    }
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
let assetPacks = [];
async function renderAssets() {
    const area = document.getElementById('assetLibraryArea');
    try { const r = await fetch('/api/asset-packs'); assetPacks = (await r.json()).packs || []; } catch { assetPacks = []; }
    area.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
        <div style="font-size:15px;font-weight:600">素材包管理</div>
        <div style="display:flex;gap:8px"><button class="btn btn-primary btn-sm" onclick="openModal('uploadPackModal')">📎 上传素材包</button></div>
    </div>
    ${uploadStatusHtml('asset')}
    <table class="data-table"><thead><tr><th>素材包名称</th><th>类型</th><th>品类</th><th>页数</th><th>素材项</th><th>状态</th><th>操作</th></tr></thead><tbody>
    ${assetPacks.map(p => `<tr>
        <td><strong>${p.name}</strong></td>
        <td><span class="tag tag-gray">${p.type}</span></td>
        <td>${(p.category||[]).map(c=>'<span class="tag tag-blue" style="margin:1px">'+c+'</span>').join('')}</td>
        <td>${p.page_count}</td><td>${p.item_count}</td>
        <td><span class="tag ${p.parse_status==='parsed'?'tag-green':p.parse_status==='parsing'?'tag-blue':p.parse_status==='error'?'tag-red':'tag-yellow'}">${statusLabel(p.parse_status)}</span>${p.error?'<br><span class="inline-error">'+escapeHtml(p.error)+'</span>':''}</td>
        <td><button class="btn btn-xs btn-secondary" onclick="viewPackItems('${p.asset_pack_id}')">查看素材项</button>
        ${p.parse_status!=='parsed'?'<button class="btn btn-xs btn-primary" onclick="triggerParse(\x27'+p.asset_pack_id+'\x27)">解析</button>':''}</td>
    </tr>`).join('')}
    </tbody></table>
    <div id="packItemsArea" style="margin-top:20px"></div>`;
}
async function triggerParse(packId) {
    await fetch('/api/asset-packs/'+packId+'/parse',{method:'POST'});
    uploadOps['asset:'+packId] = { scope: 'asset', name: packId, phase: '解析中', pct: 60, status: 'running' };
    toast('开始解析素材包...','info');
    pollPackStatus(packId);
}
async function viewPackItems(packId) {
    const r = await fetch('/api/asset-packs/'+packId+'/items');
    const items = (await r.json()).items || [];
    const area = document.getElementById('packItemsArea');
    area.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
        <div style="font-size:14px;font-weight:600">素材项 (${items.length})</div>
        <div style="display:flex;gap:6px">
            <button class="btn btn-xs btn-primary" onclick="batchConfirmItems('${packId}')">✓ 批量确认</button>
            <button class="btn btn-xs btn-secondary" onclick="batchDisableItems('${packId}')">✕ 批量禁用</button>
        </div>
    </div>
    <div class="asset-grid">${items.map(it => `<div class="asset-thumb" data-item-id="${it.asset_item_id}" onclick="this.classList.toggle('selected')" style="border:2px solid ${it.status==='confirmed'?'var(--success)':it.status==='disabled'?'var(--danger)':'var(--border)'}">
        <div class="asset-thumb-img">${it.preview_url ? '<img src="'+it.preview_url+'" style="width:100%;height:100%;object-fit:contain;">' : (it.type==='icon'?'🏷':'🎨')}</div>
        <div class="asset-thumb-label"><strong>${it.name}</strong><br><span style="font-size:10px;color:var(--text-muted)">${(it.tags||[]).join(', ')}</span><br><span class="tag ${it.status==='confirmed'?'tag-green':it.status==='disabled'?'tag-red':'tag-yellow'}" style="margin-top:2px">${it.status}</span></div>
    </div>`).join('')}</div>`;
}
async function batchConfirmItems(packId) {
    const ids = [...document.querySelectorAll('#packItemsArea .asset-thumb.selected')].map(e=>e.dataset.itemId).filter(Boolean);
    if(!ids.length){toast('请先点击选择素材项','info');return;}
    await fetch('/api/asset-items/batch-confirm',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_item_ids:ids,status:'confirmed'})});
    toast(`已确认 ${ids.length} 个素材项`,'success'); viewPackItems(packId);
}
async function batchDisableItems(packId) {
    const ids = [...document.querySelectorAll('#packItemsArea .asset-thumb.selected')].map(e=>e.dataset.itemId).filter(Boolean);
    if(!ids.length){toast('请先点击选择素材项','info');return;}
    await fetch('/api/asset-items/batch-disable',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_item_ids:ids})});
    toast(`已禁用 ${ids.length} 个素材项`,'success'); viewPackItems(packId);
}
async function handlePackUpload(e) {
    e.preventDefault();
    const form = e.target;
    const files = form.querySelector('input[type=file]').files;
    if (!files.length) { toast('请选择文件','info'); return; }
    const fd = new FormData();
    for (const f of files) fd.append('file', f);
    fd.append('name', form.querySelector('input[name=name]')?.value || '');
    fd.append('category', form.querySelector('input[name=category]')?.value || '');
    fd.append('usage', form.querySelector('input[name=usage]')?.value || '');

    // Show progress bar
    const btn = form.querySelector('button[type=submit]');
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="upload-progress-text">上传中... 0%</span><div class="upload-progress-bar"><div class="upload-progress-fill" style="width:0%"></div></div>`;

    try {
        const opId = 'asset:' + Date.now();
        uploadOps[opId] = { scope: 'asset', name: files.length > 1 ? `${files.length} 个文件` : files[0].name, phase: '上传中', pct: 0, status: 'running' };
        renderAssets();
        const result = await uploadWithProgress('/api/asset-packs/upload', fd, (pct) => {
            btn.querySelector('.upload-progress-text').textContent = `上传中... ${pct}%`;
            btn.querySelector('.upload-progress-fill').style.width = pct + '%';
            uploadOps[opId].pct = pct;
            renderAssets();
        });
        const d = JSON.parse(result);
        uploadOps[opId].phase = '解析中';
        uploadOps[opId].pct = 100;
        uploadOps[opId].packId = d.pack.asset_pack_id;
        btn.innerHTML = '解析中...';
        toast('素材包上传成功，开始解析...','success');
        await fetch('/api/asset-packs/'+d.pack.asset_pack_id+'/parse',{method:'POST'});
        closeModal('uploadPackModal');
        form.reset();
        clearUploadSelection(form);
        btn.disabled = false;
        btn.innerHTML = origText;
        pollPackStatus(d.pack.asset_pack_id, 40, opId);
    } catch(err) {
        toast('上传失败: '+err.message,'error');
        btn.disabled = false;
        btn.innerHTML = origText;
    }
}

function uploadWithProgress(url, formData, onProgress) {
    return new Promise((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.upload.addEventListener('progress', (e) => {
            if (e.lengthComputable) onProgress(Math.round(e.loaded / e.total * 100));
        });
        xhr.addEventListener('load', () => {
            if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.responseText);
            else reject(new Error(xhr.statusText || `HTTP ${xhr.status}`));
        });
        xhr.addEventListener('error', () => reject(new Error('网络错误')));
        xhr.open('POST', url);
        xhr.send(formData);
    });
}

function uploadStatusHtml(scope) {
    const ops = Object.entries(uploadOps).filter(([, op]) => op.scope === scope && op.status !== 'hidden');
    if (!ops.length) return '';
    return `<div class="upload-status-list">${ops.map(([id, op]) => `
        <div class="upload-status-card ${op.status || 'running'}">
            <div class="upload-status-main">
                <strong>${escapeHtml(op.name || '上传任务')}</strong>
                <span>${escapeHtml(op.phase || '处理中')}</span>
            </div>
            <div class="progress-bar"><div class="progress-bar-fill" style="width:${Math.max(0, Math.min(100, op.pct || 0))}%"></div></div>
            <button class="btn-ghost btn-xs" onclick="uploadOps['${id}'].status='hidden'; renderAssets(); renderKb();">隐藏</button>
        </div>`).join('')}</div>`;
}

function pollPackStatus(packId, maxRetries = 40, opId = 'asset:' + packId) {
    let retries = 0;
    renderAssets();
    const interval = setInterval(async () => {
        retries++;
        try {
            const r = await fetch('/api/asset-packs/' + packId);
            const p = await r.json();
            uploadOps[opId] = uploadOps[opId] || { scope: 'asset', name: p.name || packId, status: 'running' };
            uploadOps[opId].name = p.name || uploadOps[opId].name;
            uploadOps[opId].phase = statusLabel(p.parse_status);
            uploadOps[opId].pct = p.parse_status === 'parsed' ? 100 : p.parse_status === 'error' ? 100 : Math.min(95, 55 + retries * 3);
            uploadOps[opId].status = p.parse_status === 'error' ? 'error' : p.parse_status === 'parsed' ? 'done' : 'running';
            if (p.parse_status === 'parsed' || p.parse_status === 'error' || retries >= maxRetries) {
                clearInterval(interval);
                renderAssets();
                if (p.parse_status === 'parsed') toast(`解析完成：${p.item_count} 个素材项`, 'success');
                else if (p.parse_status === 'error') toast('解析失败: ' + (p.error||''), 'error');
            } else {
                renderAssets();
            }
        } catch { if (retries >= maxRetries) clearInterval(interval); }
    }, 3000);
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

let kbDocs = [];
async function renderKbCategory(el) {
    try { const r = await fetch('/api/knowledge-docs'); kbDocs = (await r.json()).docs || []; } catch { kbDocs = []; }
    el.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <div style="font-size:15px;font-weight:600;">品类知识库</div>
        <button class="btn btn-primary btn-sm" onclick="openModal('uploadDocModal')">📄 上传文档</button>
    </div>
    ${uploadStatusHtml('knowledge')}
    <table class="data-table"><thead><tr>
        <th>文档名称</th><th>适用品类</th><th>上传时间</th><th>解析状态</th><th>规则数</th><th>检查清单</th><th>关联SKU</th><th>操作</th>
    </tr></thead><tbody>
    ${kbDocs.map(d => `<tr>
        <td><strong>${d.name}</strong>${d.name_en?'<br><span style="font-size:11px;color:var(--text-muted)">'+d.name_en+'</span>':''}</td>
        <td>${(d.category||[]).map(c=>'<span class="tag tag-blue">'+c+'</span>').join(' ')}</td>
        <td>${(d.upload_time||'').slice(0,10)}</td>
        <td><span class="tag ${d.parse_status==='parsed'?'tag-green':d.parse_status==='parsing'?'tag-blue':d.parse_status==='error'?'tag-red':'tag-yellow'}">${statusLabel(d.parse_status)}</span>
            ${docParseModeBadge(d)}
            ${d.error?'<br><span class="inline-error">'+escapeHtml(d.error)+'</span>':''}</td>
        <td>${d.rule_count||'-'}</td><td>${d.checklist_count||'-'}</td><td>${d.linked_sku_count||0}</td>
        <td>${d.parse_status!=='parsed'
            ? '<button class="btn btn-xs btn-primary" onclick="analyzeDoc(\x27'+d.doc_id+'\x27)">解析</button>'
            : '<button class="btn btn-xs btn-secondary" onclick="viewDocSummary(\x27'+d.doc_id+'\x27)">查看</button><button class="btn btn-xs btn-primary" onclick="analyzeDoc(\x27'+d.doc_id+'\x27)">重新解析</button>'}</td>
    </tr>`).join('')}
    </tbody></table>
    <div id="docSummaryArea" style="margin-top:16px"></div>`;
}

function docParseModeBadge(doc) {
    const k = doc.parsed_knowledge || {};
    if (!k.parse_mode) return '';
    if (k.parse_mode === 'llm_chunked') {
        return `<br><span class="tag tag-blue" style="margin-top:4px">LLM: ${escapeHtml(k.llm_model || '')}</span>`;
    }
    if (k.parse_mode === 'local_heuristic_fallback') {
        return `<br><span class="tag tag-yellow" style="margin-top:4px">本地兜底</span>`;
    }
    return `<br><span class="tag tag-gray" style="margin-top:4px">${escapeHtml(k.parse_mode)}</span>`;
}

function renderKbInspiration(el) {
    el.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <div style="font-size:15px;font-weight:600;">素材灵感库</div>
    </div>
    <div style="text-align:center;padding:40px;color:var(--text-muted);font-size:13px;"><div style="font-size:28px;margin-bottom:8px;">🎨</div>暂无灵感素材<br>后续版本支持上传竞品参考图</div>`;
}

async function renderKbStandard(el) {
    let packs = [];
    try { const r = await fetch('/api/asset-packs'); packs = (await r.json()).packs || []; } catch {}
    if (!packs.length) {
        el.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
            <div style="font-size:15px;font-weight:600;">标准素材库</div>
            <button class="btn btn-primary btn-sm" onclick="showPage('assets')">📎 管理素材包</button>
        </div>
        <div style="text-align:center;padding:40px;color:var(--text-muted);font-size:13px;"><div style="font-size:28px;margin-bottom:8px;">📦</div>暂无素材包<br>请到「图片资产库」上传 PDF 素材包</div>`;
        return;
    }
    el.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
        <div style="font-size:15px;font-weight:600;">标准素材库</div>
        <button class="btn btn-primary btn-sm" onclick="showPage('assets')">📎 管理素材包</button>
    </div>
    <table class="data-table"><thead><tr><th>素材包</th><th>类型</th><th>素材项</th><th>状态</th></tr></thead><tbody>
    ${packs.map(p => `<tr><td><strong>${p.name}</strong></td><td><span class="tag tag-gray">${p.type||'pdf'}</span></td><td>${p.item_count}</td>
        <td><span class="tag ${p.parse_status==='parsed'?'tag-green':'tag-yellow'}">${p.parse_status==='parsed'?'已解析':'待解析'}</span></td></tr>`).join('')}
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

/* ===== Knowledge Doc Actions ===== */
async function analyzeDoc(docId) {
    await fetch('/api/knowledge-docs/'+docId+'/analyze',{method:'POST'});
    uploadOps['knowledge:'+docId] = { scope: 'knowledge', name: docId, phase: '解析中', pct: 60, status: 'running' };
    toast('开始解析文档...','info');
    pollDocStatus(docId);
}
async function viewDocSummary(docId) {
    const r = await fetch('/api/knowledge-docs/'+docId+'/summary');
    const d = await r.json();
    const k = d.knowledge || {};
    const area = document.getElementById('docSummaryArea');
    area.innerHTML = `<div class="settings-card"><h3>📋 ${d.summary||docId}</h3>
        <div class="ctx-item"><span class="label">解析模式</span>${k.parse_mode === 'llm_chunked' ? 'LLM 分块提取' : k.parse_mode === 'local_heuristic_fallback' ? '本地兜底（LLM 未成功）' : (k.parse_mode || '-')}</div>
        ${k.llm_model ? `<div class="ctx-item"><span class="label">LLM 模型</span>${escapeHtml(k.llm_model)}</div>` : ''}
        ${k.fallback_reason ? `<div class="ctx-item"><span class="label">兜底原因</span><span class="inline-error">${escapeHtml(k.fallback_reason)}</span></div>` : ''}
        <div class="ctx-item"><span class="label">品类路径</span>${k.category_path||'-'}</div>
        <div class="ctx-item"><span class="label">全局规则</span>${(k.global_rules||[]).map(r=>'<div>• '+r+'</div>').join('')}</div>
        <div class="ctx-item"><span class="label">场景规则</span>${(k.scene_rules||[]).map(r=>'<div>• '+r+'</div>').join('')}</div>
        <div class="ctx-item"><span class="label">负面提示词</span>${(k.negative_prompts||[]).map(r=>'<span class="ctx-tag">'+r+'</span>').join('')}</div>
        <div class="ctx-item"><span class="label">检查清单</span><ul class="ctx-checklist">${(k.checklist||[]).map(c=>'<li>'+c+'</li>').join('')}</ul></div>
    </div>`;
}
async function handleDocUpload(e) {
    e.preventDefault();
    const form = e.target;
    const fd = new FormData(form);
    const btn = form.querySelector('button[type=submit]');
    const origText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span class="upload-progress-text">上传中... 0%</span><div class="upload-progress-bar"><div class="upload-progress-fill" style="width:0%"></div></div>`;

    try {
        const file = form.querySelector('input[type=file]')?.files?.[0];
        const opId = 'knowledge:' + Date.now();
        uploadOps[opId] = { scope: 'knowledge', name: file?.name || '知识文档', phase: '上传中', pct: 0, status: 'running' };
        renderKb();
        const result = await uploadWithProgress('/api/knowledge-docs/upload', fd, (pct) => {
            btn.querySelector('.upload-progress-text').textContent = `上传中... ${pct}%`;
            btn.querySelector('.upload-progress-fill').style.width = pct + '%';
            uploadOps[opId].pct = pct;
            renderKb();
        });
        const d = JSON.parse(result);
        uploadOps[opId].phase = '解析中';
        uploadOps[opId].pct = 100;
        uploadOps[opId].docId = d.doc.doc_id;
        btn.innerHTML = '解析中...';
        toast('文档上传成功，开始解析...','success');
        await fetch('/api/knowledge-docs/'+d.doc.doc_id+'/analyze',{method:'POST'});
        closeModal('uploadDocModal');
        form.reset();
        clearUploadSelection(form);
        btn.disabled = false;
        btn.innerHTML = origText;
        pollDocStatus(d.doc.doc_id, 40, opId);
    } catch(err) {
        toast('上传失败: '+err.message,'error');
        btn.disabled = false;
        btn.innerHTML = origText;
    }
}

function pollDocStatus(docId, maxRetries = 40, opId = 'knowledge:' + docId) {
    let retries = 0;
    renderKb();
    const interval = setInterval(async () => {
        retries++;
        try {
            const r = await fetch('/api/knowledge-docs/' + docId);
            const d = await r.json();
            uploadOps[opId] = uploadOps[opId] || { scope: 'knowledge', name: d.name || docId, status: 'running' };
            uploadOps[opId].name = d.name || uploadOps[opId].name;
            uploadOps[opId].phase = statusLabel(d.parse_status);
            uploadOps[opId].pct = d.parse_status === 'parsed' ? 100 : d.parse_status === 'error' ? 100 : Math.min(95, 55 + retries * 3);
            uploadOps[opId].status = d.parse_status === 'error' ? 'error' : d.parse_status === 'parsed' ? 'done' : 'running';
            if (d.parse_status === 'parsed' || d.parse_status === 'error' || retries >= maxRetries) {
                clearInterval(interval);
                renderKb();
                if (d.parse_status === 'parsed') toast(`解析完成：${d.rule_count} 条规则，${d.checklist_count} 条检查项`, 'success');
                else if (d.parse_status === 'error') toast('解析失败', 'error');
            } else {
                renderKb();
            }
        } catch { if (retries >= maxRetries) clearInterval(interval); }
    }, 3000);
}

/* ===== Init ===== */
document.addEventListener('DOMContentLoaded', () => { loadProducts(); });

document.addEventListener('change', (e) => {
    const target = e.target;
    if (target && target.matches && target.matches('.upload-zone input[type="file"]')) {
        handleFileSelect(e);
    }
});
