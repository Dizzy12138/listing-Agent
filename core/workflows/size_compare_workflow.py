from __future__ import annotations

from PIL import ImageDraw

from pipeline.step4_enhance import _load_font

from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("size_compare")
class SizeCompareWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        with context.trace.timed("workflow.size_compare"):
            canvas = context.base_assets["white_bg"].copy().convert("RGB").resize((1500, 1500))
            draw = ImageDraw.Draw(canvas)
            title_font = _load_font(64, bold=True)
            body_font = _load_font(38)
            draw.rounded_rectangle((80, 80, 1420, 220), radius=24, fill="#ffffff", outline="#d8dee6", width=3)
            draw.text((120, 110), "205cm XXL HEIGHT", font=title_font, fill="#172033")
            draw.text((120, 185), "Front view for scale comparison", font=body_font, fill="#536173")
            artifact = self.save_image(canvas, context, "size_compare", "size_compare")
            context.trace.add(
                step="workflow.size_compare.output",
                status="success",
                input={"job_id": context.job.job_id, "view_type": context.job.view_type or "front_open"},
                output_artifact=artifact.path,
            )
            return self.ok_result(context, [artifact], context.trace.records[-2:])
