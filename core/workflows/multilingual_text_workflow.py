from __future__ import annotations

from core.workflows.detail_workflow import DetailWorkflow
from core.workflows.registry import register_workflow


@register_workflow("multilingual_text")
class MultilingualTextWorkflow(DetailWorkflow):
    """PoC fallback: use the detail-card workflow until text-layer detection lands."""

