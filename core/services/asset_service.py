"""
Asset management service — PDF parsing, icon extraction, pack/item CRUD.
Uses PyMuPDF for real PDF image extraction and LLM for document analysis.
"""
import json
import uuid
import shutil
import traceback
from pathlib import Path
from datetime import datetime
from typing import Optional

from core.schemas.asset_pack import AssetPack, AssetItem, KnowledgeDoc


ASSET_DIR = Path("assets")
ASSET_DIR.mkdir(exist_ok=True)

# ── In-memory stores ──
_packs: dict[str, AssetPack] = {}
_items: dict[str, AssetItem] = {}
_docs: dict[str, KnowledgeDoc] = {}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Asset Packs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_pack(name: str, file_paths, category: list[str],
                usage: list[str], file_type: str = "pdf") -> AssetPack:
    """Create a new asset pack from uploaded files (list or single path)."""
    if isinstance(file_paths, str):
        file_paths = [file_paths]
    pack_id = f"pack_{uuid.uuid4().hex[:8]}"
    pack = AssetPack(
        asset_pack_id=pack_id,
        name=name,
        file_type=file_type,
        category=category,
        usage=usage,
        source_file=file_paths[0] if file_paths else "",
        source_file_url=f"/assets/packs/{pack_id}/",
        parse_status="pending",
        created_at=_now(),
        updated_at=_now(),
    )
    pack_dir = ASSET_DIR / "packs" / pack_id
    pack_dir.mkdir(parents=True, exist_ok=True)
    for fp in file_paths:
        p = Path(fp)
        if p.exists():
            shutil.copy2(fp, pack_dir / p.name)

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
    """Parse a pack into individual asset items (PDF or images)."""
    pack = get_pack(pack_id)
    if not pack:
        raise ValueError(f"Pack {pack_id} not found")

    pack.parse_status = "parsing"
    pack.updated_at = _now()
    _save_pack_meta(pack)

    try:
        if pack.file_type == "image":
            items = _extract_items_from_images(pack)
        else:
            items = _extract_items_from_pdf(pack)
        pack.item_count = len(items)
        pack.parse_status = "parsed"
        pack.updated_at = _now()
    except Exception as e:
        pack.parse_status = "error"
        pack.error = str(e)
        pack.updated_at = _now()
        traceback.print_exc()

    _save_pack_meta(pack)
    return pack


def _extract_items_from_images(pack: AssetPack) -> list[AssetItem]:
    """Handle image file uploads (PNG, JPG, etc.) — each file becomes one asset item."""
    pack_dir = ASSET_DIR / "packs" / pack.asset_pack_id
    items_dir = pack_dir / "items"
    items_dir.mkdir(exist_ok=True)

    from PIL import Image
    extracted = []
    img_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".svg"}
    img_index = 0

    for f in sorted(pack_dir.iterdir()):
        if f.suffix.lower() not in img_exts:
            continue
        try:
            # Copy to items dir as PNG
            item_id = f"item_{pack.asset_pack_id}_{img_index:03d}"
            img_filename = f"{item_id}.png"
            img_path = items_dir / img_filename

            if f.suffix.lower() == ".svg":
                # SVG: just copy as-is
                shutil.copy2(f, items_dir / f"{item_id}{f.suffix}")
                img_filename = f"{item_id}{f.suffix}"
                w, h = 0, 0
            else:
                img = Image.open(f)
                if img.mode not in ("RGB", "RGBA"):
                    img = img.convert("RGBA")
                img.save(str(img_path), "PNG")
                w, h = img.width, img.height

            item = AssetItem(
                asset_item_id=item_id,
                asset_pack_id=pack.asset_pack_id,
                name=f.stem,
                type=_guess_type_by_size(w, h) if w > 0 else "graphic",
                tags=[],
                bbox=[0, 0, w, h],
                page=0,
                preview_url=f"/assets/packs/{pack.asset_pack_id}/items/{img_filename}",
                png_url=f"/assets/packs/{pack.asset_pack_id}/items/{img_filename}",
                applicable_image_types=pack.usage,
                status="available",
                created_at=_now(),
            )
            _items[item_id] = item
            extracted.append(item)
            img_index += 1
        except Exception as e:
            print(f"  [AssetParse] 跳过文件 {f.name}: {e}")
            continue

    pack.page_count = 0
    print(f"  [AssetParse] 提取到 {len(extracted)} 个图片素材")

    # VLM auto-label
    _label_items_with_vlm(extracted, items_dir)

    # Save items metadata
    items_meta = [it.model_dump() for it in extracted]
    (pack_dir / "items.json").write_text(
        json.dumps(items_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return extracted


def _extract_items_from_pdf(pack: AssetPack) -> list[AssetItem]:
    """
    Extract images from PDF using pypdf, then use VLM to label each.
    """
    pack_dir = ASSET_DIR / "packs" / pack.asset_pack_id
    items_dir = pack_dir / "items"
    items_dir.mkdir(exist_ok=True)

    # Find the PDF file
    source = None
    for f in pack_dir.iterdir():
        if f.suffix.lower() == ".pdf":
            source = f
            break
    if source is None:
        sf = Path(pack.source_file)
        if sf.exists():
            source = sf
    if source is None:
        raise FileNotFoundError(f"No PDF found for pack {pack.asset_pack_id}")

    extracted = []
    print(f"  [AssetParse] 开始解析 PDF: {source.name}")

    from pypdf import PdfReader
    from PIL import Image
    import io

    reader = PdfReader(str(source))
    pack.page_count = len(reader.pages)
    print(f"  [AssetParse] PDF 共 {len(reader.pages)} 页")

    img_index = 0
    for page_num, page in enumerate(reader.pages):
        # Extract embedded images from each page
        if hasattr(page, 'images'):
            for img_obj in page.images:
                try:
                    img_data = img_obj.data
                    img = Image.open(io.BytesIO(img_data))
                    # Skip tiny images
                    if img.width < 20 or img.height < 20:
                        continue
                    # Convert to RGB if needed
                    if img.mode not in ("RGB", "RGBA"):
                        img = img.convert("RGBA")

                    item_id = f"item_{pack.asset_pack_id}_{img_index:03d}"
                    img_filename = f"{item_id}.png"
                    img_path = items_dir / img_filename
                    img.save(str(img_path), "PNG")

                    item = AssetItem(
                        asset_item_id=item_id,
                        asset_pack_id=pack.asset_pack_id,
                        name=f"素材_{img_index+1} (p{page_num+1})",
                        type=_guess_type_by_size(img.width, img.height),
                        tags=[],
                        bbox=[0, 0, img.width, img.height],
                        page=page_num + 1,
                        preview_url=f"/assets/packs/{pack.asset_pack_id}/items/{img_filename}",
                        png_url=f"/assets/packs/{pack.asset_pack_id}/items/{img_filename}",
                        applicable_image_types=pack.usage,
                        status="available",
                        created_at=_now(),
                    )
                    _items[item_id] = item
                    extracted.append(item)
                    img_index += 1
                except Exception as e:
                    print(f"  [AssetParse] 跳过图片: {e}")
                    continue

    # If no embedded images found, extract text per page as fallback
    if not extracted:
        print(f"  [AssetParse] 无嵌入图片，提取页面文本")
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                item_id = f"item_{pack.asset_pack_id}_{page_num:03d}"
                item = AssetItem(
                    asset_item_id=item_id,
                    asset_pack_id=pack.asset_pack_id,
                    name=f"页面_{page_num+1}",
                    type="graphic",
                    tags=[],
                    bbox=[0, 0, 0, 0],
                    page=page_num + 1,
                    description=text[:200],
                    applicable_image_types=pack.usage,
                    status="available",
                    created_at=_now(),
                )
                _items[item_id] = item
                extracted.append(item)

    print(f"  [AssetParse] 提取到 {len(extracted)} 个素材项")

    # Use VLM to auto-label items that have preview images
    _label_items_with_vlm(extracted, items_dir)

    # Save items metadata
    items_meta = [it.model_dump() for it in extracted]
    (pack_dir / "items.json").write_text(
        json.dumps(items_meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return extracted


def _guess_type_by_size(w: int, h: int) -> str:
    area = w * h
    if area < 10000:
        return "icon"
    elif area < 100000:
        return "graphic"
    else:
        return "background"


def _label_items_with_vlm(items: list[AssetItem], items_dir: Path):
    """Use VLM to auto-label extracted items with names and tags."""
    if not items:
        return
    try:
        from models.llm import chat
        from PIL import Image
    except ImportError:
        print("  [AssetParse] VLM labeling 不可用，跳过")
        return

    for item in items:
        img_path = items_dir / f"{item.asset_item_id}.png"
        if not img_path.exists():
            continue
        try:
            img = Image.open(img_path)
            if img.width > 2000 or img.height > 2000:
                img.thumbnail((1000, 1000))

            prompt = """请分析这张图片，返回JSON格式：
{
  "name": "图片的简短中文名称（如：猫图标、箭头、尺寸线、产品场景图等）",
  "type": "icon / graphic / background / decoration / logo 之一",
  "tags": ["标签1", "标签2", "标签3"],
  "description": "一句话描述图片内容"
}
只返回JSON，不要其他文本。"""
            result = chat(prompt, image=img, response_format="json")
            data = json.loads(result)
            if data.get("name"):
                item.name = data["name"]
            if data.get("type"):
                item.type = data["type"]
            if data.get("tags"):
                item.tags = data["tags"]
            if data.get("description"):
                item.description = data["description"]
            print(f"    VLM: {item.asset_item_id} → {item.name} [{item.type}]")
        except Exception as e:
            print(f"    VLM labeling 失败 {item.asset_item_id}: {e}")
            continue



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

    # Persist changes to disk
    pack_ids = set(it.get("asset_pack_id") for it in updated if it.get("asset_pack_id"))
    for pid in pack_ids:
        _persist_pack_items(pid)

    return updated


def _persist_pack_items(pack_id: str):
    """Save current item state to disk."""
    pack_dir = ASSET_DIR / "packs" / pack_id
    if not pack_dir.exists():
        return
    all_items = [it.model_dump() for it in _items.values() if it.asset_pack_id == pack_id]
    (pack_dir / "items.json").write_text(
        json.dumps(all_items, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Knowledge Docs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def create_doc(name: str, file_path: str, category: list[str],
               name_en: str = "") -> KnowledgeDoc:
    doc_id = f"doc_{uuid.uuid4().hex[:8]}"
    file_type = Path(file_path).suffix.lstrip(".").lower() or "pdf"
    doc = KnowledgeDoc(
        doc_id=doc_id,
        name=name,
        name_en=name_en,
        category=category,
        file_type=file_type,
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
    """Analyze a knowledge document: extract text, then use LLM to parse rules."""
    doc = get_doc(doc_id)
    if not doc:
        raise ValueError(f"Doc {doc_id} not found")

    doc.parse_status = "parsing"
    _save_doc_meta(doc)

    try:
        knowledge = _extract_knowledge_real(doc)
        doc.parsed_knowledge = knowledge
        doc.rule_count = (
            len(knowledge.get("global_rules", []))
            + len(knowledge.get("scene_rules", []))
            + len(knowledge.get("style_rules", []))
        )
        doc.checklist_count = len(knowledge.get("checklist", []))
        doc.parse_status = "parsed"
        doc.summary = knowledge.get("summary", "")
    except Exception as e:
        doc.parse_status = "error"
        doc.error = str(e)
        traceback.print_exc()

    _save_doc_meta(doc)
    return doc


def _extract_text_from_file(doc: KnowledgeDoc) -> str:
    """Extract text content from the uploaded file."""
    doc_dir = ASSET_DIR / "docs" / doc.doc_id
    source = None
    for f in doc_dir.iterdir():
        if f.suffix.lower() in (".pdf", ".docx", ".doc", ".txt", ".md"):
            source = f
            break
    if source is None:
        sf = Path(doc.source_file)
        if sf.exists():
            source = sf
    if source is None:
        return ""

    ext = source.suffix.lower()
    text = ""

    if ext == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(source))
            for page in reader.pages:
                text += (page.extract_text() or "") + "\n"
        except ImportError:
            text = f"[PDF文件: {source.name}, 需要安装 pypdf]"

    elif ext in (".docx",):
        try:
            from docx import Document
            doc_file = Document(str(source))
            for para in doc_file.paragraphs:
                text += para.text + "\n"
        except ImportError:
            text = f"[DOCX文件: {source.name}, 需要安装 python-docx 才能提取文本]"

    elif ext in (".txt", ".md"):
        text = source.read_text(encoding="utf-8", errors="ignore")

    return text.strip()


def _extract_knowledge_real(doc: KnowledgeDoc) -> dict:
    """Extract structured knowledge using real text extraction + LLM analysis."""
    print(f"  [KnowledgeAnalyze] 开始解析文档: {doc.name}")

    text = _extract_text_from_file(doc)
    if not text:
        print(f"  [KnowledgeAnalyze] 文档内容为空")
        return {"summary": "文档内容为空或无法提取", "global_rules": [], "checklist": []}

    # Truncate to avoid token limits (keep first ~8000 chars)
    if len(text) > 8000:
        text = text[:8000] + "\n...[截断]"

    print(f"  [KnowledgeAnalyze] 提取到 {len(text)} 字符文本，调用 LLM 分析")

    prompt = f"""请分析以下电商产品文档，提取结构化的图片生成知识。

文档内容：
---
{text}
---

请返回JSON格式，包含以下字段（每个字段为数组，如果文档中没有相关内容则返回空数组）：

{{
  "category_path": "品类路径，如 Pet Supplies > Cat Supplies > Cat Furniture > Cat Tree",
  "summary": "文档内容一句话摘要",
  "applicable_products": ["适用的产品类型"],
  "global_rules": ["全局生图规则，如：保持产品结构一致"],
  "image_plan_templates": [{{"type": "hero_scene", "name": "首图", "size": "2000x2000"}}],
  "prompt_templates": ["可复用的提示词模板"],
  "scene_rules": ["场景图拍摄/生成规则"],
  "style_rules": ["风格规则，如配色、字体、图标使用"],
  "negative_prompts": ["不要做的事情，如：不改变材质"],
  "checklist": ["质检清单项"],
  "keyword_bank": ["关键词"],
  "replaceable_variables": ["可替换变量如 ${{product_name}}"]
}}

只返回JSON，不要其他文本。"""

    try:
        from models.llm import chat
        result = chat(prompt, response_format="json")
        knowledge = json.loads(result)
        print(f"  [KnowledgeAnalyze] LLM 返回结构化知识: "
              f"{len(knowledge.get('global_rules',[]))} rules, "
              f"{len(knowledge.get('checklist',[]))} checklist items")
        return knowledge
    except Exception as e:
        print(f"  [KnowledgeAnalyze] LLM 分析失败: {e}")
        raise


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


