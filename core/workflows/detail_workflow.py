from __future__ import annotations

from pipeline.step4_enhance import generate_detail_crops

from core.agents.detail_target_agent import DetailTargetAgent
from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("detail")
class DetailWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        target = DetailTargetAgent().resolve(context.job.description)
        view_asset = context.view_agent.get_or_generate_view(
            sku=context.sku,
            base_subject=context.base_assets["white_bg"],
            image_type=context.job.image_type,
            requested_view=context.job.view_type,
        )
        with context.trace.timed("workflow.detail"):
            details = generate_detail_crops(
                view_asset.image,
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
                        "view_type": view_asset.view_type,
                        "generation_mode": view_asset.mode,
                        "target_region": target["target_region"],
                        "crop_strategy": target["crop_strategy"],
                        "annotation_title": target["annotation_title"],
                    },
                    output_artifact=artifact.path,
                    issues=view_asset.issues or [],
                )
            return self.ok_result(context, artifacts, context.trace.records[-2:])
