"""Asset Pack & Asset Item schemas for PDF-based asset management."""
from typing import Optional
from pydantic import BaseModel, Field


class AssetPack(BaseModel):
    """A parsed asset pack (e.g. from a PDF of icons/graphics)."""
    asset_pack_id: str
    name: str
    type: str = "icon_pack_pdf"  # icon_pack_pdf | style_guide | scene_ref
    file_type: str = "pdf"
    category: list[str] = Field(default_factory=list)
    usage: list[str] = Field(default_factory=list)  # listing_info_graph, feature_icon, etc.
    parse_status: str = "pending"  # pending | parsing | parsed | error
    page_count: int = 0
    item_count: int = 0
    source_file: str = ""
    source_file_url: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    error: Optional[str] = None


class AssetItem(BaseModel):
    """A single extracted asset item from a pack."""
    asset_item_id: str
    asset_pack_id: str
    name: str
    type: str = "icon"  # icon | graphic | background | border | decoration | logo
    tags: list[str] = Field(default_factory=list)
    bbox: list[int] = Field(default_factory=list)  # [x, y, w, h] in source
    page: int = 0
    preview_url: str = ""
    svg_url: str = ""
    png_url: str = ""
    description: str = ""
    applicable_image_types: list[str] = Field(default_factory=list)
    status: str = "available"  # available | confirmed | disabled
    created_at: str = ""


class KnowledgeDoc(BaseModel):
    """A knowledge document for a product category."""
    doc_id: str
    name: str
    name_en: str = ""
    category: list[str] = Field(default_factory=list)
    file_type: str = "pdf"
    source_file: str = ""
    upload_time: str = ""
    parse_status: str = "pending"  # pending | parsing | parsed | error
    summary: str = ""
    rule_count: int = 0
    checklist_count: int = 0
    linked_sku_count: int = 0
    parsed_knowledge: Optional[dict] = None
    error: Optional[str] = None
