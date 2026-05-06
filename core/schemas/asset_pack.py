"""Asset Pack & Asset Item schemas for knowledge and visual asset management."""
from typing import Any, Optional

from pydantic import BaseModel, Field, model_validator


VALID_PARSE_STATUSES = {"pending", "parsing", "parsed", "needs_review", "failed"}
VALID_ITEM_STATUSES = {"auto_detected", "needs_review", "confirmed", "disabled"}


def _normalize_parse_status(value: str | None) -> str:
    if value == "error":
        return "failed"
    return value if value in VALID_PARSE_STATUSES else "pending"


def _normalize_item_status(value: str | None) -> str:
    if value == "available":
        return "auto_detected"
    return value if value in VALID_ITEM_STATUSES else "auto_detected"


class AssetPack(BaseModel):
    """A parsed asset pack (e.g. from a PDF of icons/graphics)."""
    asset_pack_id: str
    name: str
    pack_type: str = "icon_pack_pdf"  # icon_pack_pdf | style_guide | scene_ref
    type: str = "icon_pack_pdf"  # backward-compatible alias; frontend should use pack_type
    file_type: str = "pdf"
    category: list[str] = Field(default_factory=list)
    usage: list[str] = Field(default_factory=list)  # listing_info_graph, feature_icon, etc.
    parse_status: str = "pending"  # pending | parsing | parsed | needs_review | failed
    page_count: int = 0
    item_count: int = 0
    source_file: str = ""
    source_file_url: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    error: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def compat_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        data["pack_type"] = data.get("pack_type") or data.get("type") or "icon_pack_pdf"
        data["type"] = data.get("type") or data["pack_type"]
        data["parse_status"] = _normalize_parse_status(data.get("parse_status"))
        return data

    @model_validator(mode="after")
    def sync_aliases(self):
        self.type = self.pack_type
        self.parse_status = _normalize_parse_status(self.parse_status)
        return self


class AssetItem(BaseModel):
    """A single extracted asset item from a pack."""
    asset_item_id: str
    asset_pack_id: str
    name: str
    item_type: str = "icon"  # icon | graphic | background | border | decoration | logo
    type: str = "icon"  # backward-compatible alias; frontend should use item_type
    group: str = "其他"  # 产品 | 功能 | 包装 | 箭头 | 场景 | 竞品 | 其他
    tags: list[str] = Field(default_factory=list)
    bbox: list[int] = Field(default_factory=list)  # [x, y, w, h] in source
    page: int = 0
    preview_url: str = ""
    svg_url: str = ""
    png_url: str = ""
    transparent_png_url: str = ""
    description: str = ""
    applicable_categories: list[str] = Field(default_factory=list)
    applicable_image_types: list[str] = Field(default_factory=list)
    status: str = "auto_detected"  # auto_detected | needs_review | confirmed | disabled
    confidence: float = 0
    source: str = "manual"  # pdf_embedded_image | pdf_page_crop | image_upload | manual
    created_at: str = ""

    @model_validator(mode="before")
    @classmethod
    def compat_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        data["item_type"] = data.get("item_type") or data.get("type") or "icon"
        data["type"] = data.get("type") or data["item_type"]
        data["status"] = _normalize_item_status(data.get("status"))
        data.setdefault("group", "其他")
        data.setdefault("applicable_categories", [])
        data.setdefault("transparent_png_url", "")
        data.setdefault("confidence", 0)
        data.setdefault("source", "manual")
        return data

    @model_validator(mode="after")
    def sync_aliases(self):
        self.type = self.item_type
        self.status = _normalize_item_status(self.status)
        return self


class KnowledgeDoc(BaseModel):
    """A knowledge document for a product category."""
    doc_id: str
    name: str
    name_en: str = ""
    category: list[str] = Field(default_factory=list)
    category_path: str = ""
    file_type: str = "pdf"
    source_file: str = ""
    upload_time: str = ""
    parsed_at: str = ""
    parse_mode: str = ""
    parse_status: str = "pending"  # pending | parsing | parsed | needs_review | failed
    summary: str = ""
    rule_count: int = 0
    checklist_count: int = 0
    linked_sku_count: int = 0
    linked_sku_ids: list[str] = Field(default_factory=list)
    status_message: str = ""
    parsed_knowledge: Optional[dict] = None
    error: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def compat_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        data = dict(data)
        data["parse_status"] = _normalize_parse_status(data.get("parse_status"))
        data.setdefault("linked_sku_ids", [])
        data.setdefault("category_path", " > ".join(data.get("category") or []))
        data.setdefault("status_message", "")
        return data

    @model_validator(mode="after")
    def sync_status(self):
        self.parse_status = _normalize_parse_status(self.parse_status)
        if not self.category_path and self.category:
            self.category_path = " > ".join(self.category)
        self.linked_sku_count = len(self.linked_sku_ids) or self.linked_sku_count
        return self
