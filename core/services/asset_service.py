"""
Asset management service — PDF parsing, icon extraction, pack/item CRUD.
PoC: uses in-memory store + filesystem. Production: switch to DB.
"""
import json
import uuid
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.schemas.asset_pack import AssetPack, AssetItem, KnowledgeDoc


ASSET_DIR = Path("assets")
ASSET_DIR.mkdir(exist_ok=True)

# ── In-memory stores (PoC) ──
_packs: dict[str, AssetPack] = {}
_items: dict[str, AssetItem] = {}
_docs: dict[str, KnowledgeDoc] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Asset Packs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_pack(name: str, file_path: str, category: list[str],
                usage: list[str], file_type: str = "pdf") -> AssetPack:
    pack_id = f"pack_{uuid.uuid4().hex[:8]}"
    pack = AssetPack(
        asset_pack_id=pack_id,
        name=name,
        file_type=file_type,
        category=category,
        usage=usage,
        source_file=file_path,
        source_file_url=f"/assets/packs/{pack_id}/{Path(file_path).name}",
        parse_status="pending",
        created_at=_now(),
        updated_at=_now(),
    )
    # Store file
    pack_dir = ASSET_DIR / "packs" / pack_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    if Path(file_path).exists():
        shutil.copy2(file_path, pack_dir / Path(file_path).name)

    _packs[pack_id] = pack
    _save_pack_meta(pack)
    return pack


def list_packs() -> list[dict]:
    _load_all_packs()
    return [p.model_dump() for p in _packs.values()]


def get_pack(pack_id: str) -> Optional[AssetPack]:
    _load_all_packs()
    return _packs.get(pack_id)


def parse_pack(pack_id: str) -> AssetPack:
    """Parse a PDF pack into individual asset items (mock/OCR)."""
    pack = get_pack(pack_id)
    if not pack:
        raise ValueError(f"Pack {pack_id} not found")

    pack.parse_status = "parsing"
    pack.updated_at = _now()
    _save_pack_meta(pack)

    try:
        items = _extract_items_from_pdf(pack)
        pack.item_count = len(items)
        pack.parse_status = "parsed"
        pack.updated_at = _now()
    except Exception as e:
        pack.parse_status = "error"
        pack.error = str(e)
        pack.updated_at = _now()

    _save_pack_meta(pack)
    return pack


def _extract_items_from_pdf(pack: AssetPack) -> list[AssetItem]:
    """
    Extract asset items from a PDF. 
    PoC: generates mock items. Production: use pdf2image + OCR + VLM.
    """
    pack_dir = ASSET_DIR / "packs" / pack.asset_pack_id
    items_dir = pack_dir / "items"
    items_dir.mkdir(exist_ok=True)

    # Try real PDF parsing first
    extracted = []
    source = pack_dir / Path(pack.source_file).name
    page_count = 1

    if source.exists() and source.suffix.lower() == ".pdf":
        try:
            page_count = _count_pdf_pages(source)
        except Exception:
            page_count = 1

    pack.page_count = page_count

    # For PoC: generate mock items based on common icon categories
    mock_icons = [
        ("cat_icon", "猫图标", "icon", ["cat", "pet", "animal"]),
        ("cat_tree_icon", "猫树图标", "icon", ["cat tree", "furniture", "tower"]),
        ("arrow_up", "向上箭头", "icon", ["arrow", "direction", "up"]),
        ("arrow_down", "向下箭头", "icon", ["arrow", "direction", "down"]),
        ("checkmark", "勾选图标", "icon", ["check", "confirm", "yes"]),
        ("star_rating", "星级评分", "icon", ["star", "rating", "quality"]),
        ("paw_print", "爪印图标", "icon", ["paw", "pet", "cat"]),
        ("heart_icon", "爱心图标", "icon", ["heart", "love", "care"]),
        ("sisal_rope_icon", "剑麻绳图标", "icon", ["sisal", "rope", "material"]),
        ("stability_icon", "稳定性图标", "icon", ["stability", "secure", "base"]),
        ("size_icon", "尺寸标注", "graphic", ["size", "dimension", "measure"]),
        ("hammock_icon", "吊床图标", "icon", ["hammock", "rest", "comfort"]),
        ("condo_icon", "猫窝图标", "icon", ["condo", "house", "shelter"]),
        ("scratch_board", "抓板图标", "icon", ["scratch", "board", "play"]),
        ("multi_level", "多层图标", "icon", ["level", "tier", "multi"]),
        ("decorative_line", "装饰线条", "decoration", ["line", "border", "decorative"]),
        ("info_frame", "信息框", "graphic", ["frame", "info", "layout"]),
        ("brand_badge", "品牌标志", "logo", ["brand", "badge", "logo"]),
    ]

    for i, (key, name, item_type, tags) in enumerate(mock_icons):
        item_id = f"item_{pack.asset_pack_id}_{i:03d}"
        item = AssetItem(
            asset_item_id=item_id,
            asset_pack_id=pack.asset_pack_id,
            name=name,
            type=item_type,
            tags=tags,
            bbox=[50 + (i % 5) * 120, 50 + (i // 5) * 120, 80, 80],
            page=min(i // 6 + 1, page_count),
            preview_url=f"/assets/packs/{pack.asset_pack_id}/items/{item_id}.png",
            applicable_image_types=["listing_info_graph", "feature_icon"],
            status="available",
            created_at=_now(),
        )
        _items[item_id] = item
        extracted.append(item)

    # Save items metadata
    items_meta = [it.model_dump() for it in extracted]
    (pack_dir / "items.json").write_text(
        json.dumps(items_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return extracted


def _count_pdf_pages(pdf_path: Path) -> int:
    """Count pages in a PDF file."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(pdf_path))
        count = len(doc)
        doc.close()
        return count
    except ImportError:
        # Fallback: try to count pages from PDF header
        try:
            content = pdf_path.read_bytes()
            return content.count(b"/Type /Page") - content.count(b"/Type /Pages")
        except Exception:
            return 1


def list_pack_items(pack_id: str) -> list[dict]:
    _load_pack_items(pack_id)
    return [it.model_dump() for it in _items.values() if it.asset_pack_id == pack_id]


def get_item(item_id: str) -> Optional[AssetItem]:
    return _items.get(item_id)


def batch_update_items(item_ids: list[str], status: str = None,
                       tags: list[str] = None) -> list[dict]:
    updated = []
    for iid in item_ids:
        item = _items.get(iid)
        if not item:
            continue
        if status:
            item.status = status
        if tags is not None:
            item.tags = tags
        updated.append(item.model_dump())
    return updated


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Knowledge Docs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_doc(name: str, file_path: str, category: list[str],
               name_en: str = "") -> KnowledgeDoc:
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    doc = KnowledgeDoc(
        doc_id=doc_id,
        name=name,
        name_en=name_en,
        category=category,
        source_file=file_path,
        upload_time=_now(),
        parse_status="pending",
    )
    doc_dir = ASSET_DIR / "docs" / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    if Path(file_path).exists():
        shutil.copy2(file_path, doc_dir / Path(file_path).name)

    _docs[doc_id] = doc
    _save_doc_meta(doc)
    return doc


def list_docs() -> list[dict]:
    _load_all_docs()
    return [d.model_dump() for d in _docs.values()]


def get_doc(doc_id: str) -> Optional[KnowledgeDoc]:
    _load_all_docs()
    return _docs.get(doc_id)


def analyze_doc(doc_id: str) -> KnowledgeDoc:
    """Analyze a knowledge document and extract structured rules."""
    doc = get_doc(doc_id)
    if not doc:
        raise ValueError(f"Doc {doc_id} not found")

    doc.parse_status = "parsing"
    _save_doc_meta(doc)

    try:
        knowledge = _extract_knowledge(doc)
        doc.parsed_knowledge = knowledge
        doc.rule_count = len(knowledge.get("global_rules", []))
        doc.checklist_count = len(knowledge.get("checklist", []))
        doc.parse_status = "parsed"
        doc.summary = knowledge.get("summary", "")
    except Exception as e:
        doc.parse_status = "error"
        doc.error = str(e)

    _save_doc_meta(doc)
    return doc


def _extract_knowledge(doc: KnowledgeDoc) -> dict:
    """
    Extract structured knowledge from a document.
    PoC: returns mock knowledge. Production: use VLM + LLM.
    """
    return {
        "category_path": "Pet Supplies > Cat Supplies > Cat Furniture > Cat Tree / Cat Tower / Cat Condo",
        "summary": "Amazon猫爬架品类上货图生成模板，包含全局规则、场景要求、负面提示词和检查清单。",
        "applicable_products": [],
        "global_rules": [
            "保持产品结构、比例、颜色、材质、功能部件一致",
            "不要重设计产品外观",
            "白底图需完整展示产品全貌",
            "场景图需体现产品在真实家居中的使用场景",
        ],
        "image_plan_templates": [
            {"type": "hero_scene", "name": "首图", "size": "2000x2000"},
            {"type": "lifestyle_scene", "name": "场景图", "size": "2000x2000"},
            {"type": "material_detail", "name": "材质细节图", "size": "2000x2000"},
            {"type": "selling_point", "name": "卖点图", "size": "2000x2000"},
            {"type": "size_compare", "name": "尺寸图", "size": "2000x2000"},
        ],
        "scene_rules": [
            "靠墙摆放，旁边有窗户",
            "自然光线，上午阳光",
            "现代美国住宅客厅风格",
            "可包含猫咪互动但不遮挡核心结构",
        ],
        "style_rules": [
            "橙色辅助色",
            "宠物图标轻量使用",
            "手绘元素适度点缀",
        ],
        "negative_prompts": [
            "不改变产品材质",
            "不改变产品结构",
            "不让猫遮挡核心结构",
            "不使用深色光照",
            "不加水印或文字覆盖",
        ],
        "checklist": [
            "产品主体结构完整可识别",
            "颜色和材质与原图一致",
            "底座稳固感明确",
            "无多余文字或水印",
            "光照自然、阴影合理",
            "背景干净无杂物干扰",
            "产品比例正确",
            "功能部件（猫窝、吊床、抓柱）清晰可见",
        ],
        "keyword_bank": [
            "cat tree", "cat tower", "cat condo", "scratching post",
            "sisal rope", "plush fabric", "multi-level", "hammock",
        ],
        "replaceable_variables": [
            "${product_name}", "${product_height}", "${product_color}",
            "${key_feature_1}", "${key_feature_2}",
        ],
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistence helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _save_pack_meta(pack: AssetPack):
    d = ASSET_DIR / "packs" / pack.asset_pack_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(
        json.dumps(pack.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _save_doc_meta(doc: KnowledgeDoc):
    d = ASSET_DIR / "docs" / doc.doc_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(
        json.dumps(doc.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _load_all_packs():
    packs_dir = ASSET_DIR / "packs"
    if not packs_dir.exists():
        return
    for d in packs_dir.iterdir():
        if d.is_dir() and (d / "meta.json").exists():
            pid = d.name
            if pid not in _packs:
                data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                _packs[pid] = AssetPack(**data)


def _load_pack_items(pack_id: str):
    items_file = ASSET_DIR / "packs" / pack_id / "items.json"
    if items_file.exists():
        loaded = json.loads(items_file.read_text(encoding="utf-8"))
        for it_data in loaded:
            iid = it_data["asset_item_id"]
            if iid not in _items:
                _items[iid] = AssetItem(**it_data)


def _load_all_docs():
    docs_dir = ASSET_DIR / "docs"
    if not docs_dir.exists():
        return
    for d in docs_dir.iterdir():
        if d.is_dir() and (d / "meta.json").exists():
            did = d.name
            if did not in _docs:
                data = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                _docs[did] = KnowledgeDoc(**data)


# ── Seed mock data on first import ──
def _seed_mock_data():
    """Seed demo data so the UI has something to show."""
    if list_packs():
        return

    # Mock asset pack
    pack = AssetPack(
        asset_pack_id="pack_demo01",
        name="Feandrea listing图标集",
        type="icon_pack_pdf",
        file_type="pdf",
        category=["Pet Supplies", "Cat Furniture"],
        usage=["listing_info_graph", "feature_icon"],
        parse_status="parsed",
        page_count=10,
        item_count=18,
        tags=["feandrea", "icons", "listing"],
        created_at=_now(),
        updated_at=_now(),
    )
    _packs[pack.asset_pack_id] = pack
    _save_pack_meta(pack)

    # Mock items for the pack
    mock_icons = [
        ("猫图标", "icon", ["cat", "pet"]),
        ("猫树图标", "icon", ["cat tree", "tower"]),
        ("爪印图标", "icon", ["paw", "pet"]),
        ("向上箭头", "icon", ["arrow", "up"]),
        ("勾选图标", "icon", ["check", "confirm"]),
        ("稳定性图标", "icon", ["stability", "base"]),
        ("吊床图标", "icon", ["hammock", "rest"]),
        ("剑麻绳图标", "icon", ["sisal", "rope"]),
    ]
    for i, (name, itype, tags) in enumerate(mock_icons):
        item = AssetItem(
            asset_item_id=f"item_demo_{i:03d}",
            asset_pack_id="pack_demo01",
            name=name, type=itype, tags=tags,
            bbox=[50 + i * 100, 50, 80, 80], page=1,
            status="confirmed" if i < 5 else "available",
            created_at=_now(),
        )
        _items[item.asset_item_id] = item

    # Mock knowledge doc
    doc = KnowledgeDoc(
        doc_id="doc_demo01",
        name="猫爬架 Amazon 上货图通用提示词模板",
        name_en="Cat Tree / Cat Tower Amazon Listing Image Prompt Template",
        category=["Pet Supplies", "Cat Furniture"],
        file_type="pdf",
        upload_time=_now(),
        parse_status="parsed",
        summary="Amazon猫爬架品类上货图生成模板，包含全局规则、场景要求和检查清单。",
        rule_count=12,
        checklist_count=8,
        linked_sku_count=1,
        parsed_knowledge=_extract_knowledge(doc=KnowledgeDoc(
            doc_id="", name="", category=[]
        )),
    )
    _docs[doc.doc_id] = doc
    _save_doc_meta(doc)


_seed_mock_data()
