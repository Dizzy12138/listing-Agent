from __future__ import annotations

from pipeline.step4_enhance import generate_detail_crops

from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("detail")
class DetailWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        with context.trace.timed("workflow.detail"):
            details = generate_detail_crops(
                context.base_assets["white_bg"],
                [context.job.description],
            )
            artifacts = []
            if details:
                artifact = self.save_image(details[0]["crop"], context, context.job.image_type, "detail")
                artifacts.append(artifact)
                context.trace.add(
                    step="workflow.detail.output",
                    status="success",
                    input={
                        "job_id": context.job.job_id,
                        "selling_point": context.job.description,
                        "view_type": context.job.view_type or "detail_closeup",
                    },
                    output_artifact=artifact.path,
                )
            return self.ok_result(context, artifacts, context.trace.records[-2:])
