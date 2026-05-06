"""
Candidate schemas — multi-candidate generation tracking.
"""
from __future__ import annotations
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr


class CandidateRecord(BaseModel):
    """Metadata for one generated candidate image."""
    _image: Any = PrivateAttr(default=None)

    candidate_id: str
    image_type: str
    generation_strategy: str  # reference_guided_whole_image / text_only / edit_based / crop_enhance
    reference_assets_used: list[str] = Field(default_factory=list)
    sku_consistency_level: str = "medium_high"
    prompt: str = ""
    status: str = "generated"  # generated / failed / fallback / text_only_candidate
    image_path: str = ""
    issues: list[str] = Field(default_factory=list)
    knowledge_doc_ids: list[str] = Field(default_factory=list)
    knowledge_rules_used: list[str] = Field(default_factory=list)
    negative_prompts_used: list[str] = Field(default_factory=list)
    standard_assets_used: list[str] = Field(default_factory=list)


class QAScore(BaseModel):
    """Multi-dimensional quality assessment for one candidate."""
    candidate_id: str
    commercial_score: int = 0  # 0-100
    sku_consistency_score: int = 0
    scene_score: int = 0
    defect_score: int = 0  # 100 = no defects
    selling_point_score: int = 0
    issues: list[str] = Field(default_factory=list)
    decision: str = "needs_review"  # recommended / candidate / needs_review / reject
    visual_qa_source: str = "manual_required"  # vlm / manual_required


class QASummary(BaseModel):
    """Aggregated QA results for an explore run."""
    sku_id: str
    run_id: str
    image_types: dict[str, list[QAScore]] = Field(default_factory=dict)
    recommendations: dict[str, str] = Field(default_factory=dict)  # image_type -> best candidate_id
    visual_qa_source: str = "manual_required"
    overall_readiness: str = "needs_review"  # ready_for_batch / needs_review / not_ready
