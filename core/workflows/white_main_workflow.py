from __future__ import annotations

from pipeline.step1_extract import create_main_image

from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("white_main")
class WhiteMainWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        with context.trace.timed("workflow.white_main"):
            image = create_main_image(context.base_assets["white_bg"])
            artifact = self.save_image(image, context, "white_main", "main")
            artifact.metadata.update({
                "generation_strategy": "reference_info_graph",
                "commercial_quality_level": "info_graph_pass",
                "reference_assets_used": ["white_bg"],
                "direct_white_bg_subject": True,
            })
            context.trace.add(
                step="workflow.white_main.output",
                status="success",
                input={"job_id": context.job.job_id, "workflow_key": context.job.workflow_key},
                output_artifact=artifact.path,
            )
            return self.ok_result(context, [artifact], context.trace.records[-2:])
