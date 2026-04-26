from __future__ import annotations

from pipeline.step4_enhance import generate_detail_crops

from core.agents.detail_target_agent import DetailTargetAgent
from core.workflows.base import BaseWorkflow, WorkflowContext
from core.workflows.registry import register_workflow


@register_workflow("detail")
@register_workflow("detail_material")
class DetailWorkflow(BaseWorkflow):
    def run(self, context: WorkflowContext):
        target_agent = DetailTargetAgent()
        target = target_agent.resolve(context.job.description)
        view_asset = context.view_agent.get_or_generate_view(
            sku=context.sku,
            base_subject=context.base_assets["white_bg"],
            image_type=context.job.image_type,
            requested_view=context.job.view_type,
        )
        view_path = context.view_agent.save_view_asset(context.sku.product_id, context.job.image_index, view_asset)
        detail_source = target_agent.crop_by_strategy(
            view_asset.image,
            target["crop_strategy"],
            variant=context.job.image_index,
        )
        with context.trace.timed("workflow.detail"):
            details = generate_detail_crops(
                detail_source,
                [context.job.description],
            )
            artifacts = []
            if details:
                artifact = self.save_image(details[0]["crop"], context, context.job.image_type, "detail")
                artifact.metadata.update({
                    "view_generation_mode": view_asset.mode,
                    "view_issues": view_asset.issues or [],
                    "view_asset_path": str(view_path),
                    "target_region": target["target_region"],
                    "crop_strategy": target["crop_strategy"],
                    "annotation_title": target["annotation_title"],
                    "crop_variant": context.job.image_index % 3,
                })
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
