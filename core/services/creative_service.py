from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

from PIL import Image

from config import OUTPUT_DIR
from core.repositories.creative_repo import CreativeRepository
from core.schemas.creative import CreativeTask, CreativeVersion, Experiment, KnowledgeRule, Layer, LayeredAsset, PerformanceMetric, ReviewRecord
from core.tools.layer_renderer import LayerRenderer


class CreativeService:
    """Application service for the creative production feedback loop."""

    def __init__(self, db_path: Path | None = None, output_dir: Path = OUTPUT_DIR):
        self.output_dir = output_dir
        self.db_path = db_path or output_dir / "creative_loop.sqlite3"
        self.repo = CreativeRepository(self.db_path)
        self.renderer = LayerRenderer()

    def create_task(
        self,
        sku_id: str,
        objective: str = "listing_creative_production",
        marketplace: str = "US",
        target_metrics: list[str] | None = None,
        strategy_brief: dict[str, Any] | None = None,
    ) -> CreativeTask:
        task = CreativeTask(
            task_id=f"ct_{uuid.uuid4().hex[:8]}",
            sku_id=sku_id,
            objective=objective,
            marketplace=marketplace,
            target_metrics=target_metrics or [],
            strategy_brief=strategy_brief or {},
            status="active",
        )
        self.repo.upsert("creative_task", task.task_id, task.model_dump())
        return task

    def reverse_strategy_brief(
        self,
        product: dict[str, Any],
        objective: str = "提升 Amazon Listing CTR/CVR",
        marketplace: str = "US",
    ) -> dict[str, Any]:
        """Create a deterministic creative strategy brief from SKU facts."""
        selling_points = product.get("selling_points", [])
        image_plan = product.get("image_plan", [])
        keywords = product.get("keywords", [])
        title = product.get("name", "")
        text = " ".join([title, product.get("description", ""), " ".join(selling_points), " ".join(keywords)]).lower()
        primary_goal = "CTR" if any(k in objective.lower() for k in ["ctr", "点击", "主图"]) else "CVR"
        factors = [
            {
                "factor_id": "scale_clarity",
                "type": "visual",
                "hypothesis": "Large/tall product scale should be instantly readable on mobile.",
                "target_metric": "CTR",
                "evidence": ["205cm" if "205" in text else "tall positioning"],
            },
            {
                "factor_id": "trust_by_dimensions",
                "type": "dimension",
                "hypothesis": "Clear 205cm dimension line reduces size misunderstanding and return risk.",
                "target_metric": "return_rate",
                "evidence": ["SKU dimension facts"],
            },
            {
                "factor_id": "multi_cat_usage",
                "type": "scene",
                "hypothesis": "Multiple cats using different levels communicates capacity and comfort.",
                "target_metric": "CVR",
                "evidence": [sp for sp in selling_points if "猫" in sp or "cat" in sp.lower()][:3],
            },
            {
                "factor_id": "material_confidence",
                "type": "detail",
                "hypothesis": "Close-ups of plush fabric and sisal rope improve perceived quality.",
                "target_metric": "CVR",
                "evidence": [sp for sp in selling_points if any(k in sp for k in ["剑麻", "绒布", "材质"])],
            },
        ]
        recommended_images = []
        for item in image_plan:
            desc = item.get("description", "")
            image_type = item.get("type", "")
            if image_type in {"scene_main", "scene_lifestyle"}:
                route = "reference_guided_scene_generation"
            elif image_type == "size_compare":
                route = "dimension_layer_template"
            elif image_type == "detail":
                route = "material_detail_enhancement"
            else:
                route = "info_graph_or_scene_demo"
            recommended_images.append({
                "index": item.get("index"),
                "type": image_type,
                "description": desc,
                "production_route": route,
                "editable_layers_required": route in {"dimension_layer_template", "info_graph_or_scene_demo"},
            })
        return {
            "sku_id": product.get("product_id"),
            "marketplace": marketplace,
            "objective": objective,
            "primary_goal": primary_goal,
            "positioning": product.get("positioning", ""),
            "audience": product.get("target_audience", ""),
            "creative_factors": factors,
            "recommended_image_set": recommended_images,
            "prompt_brief": self._prompt_brief(product, factors),
            "risk_controls": [
                "Generate base images separately from text/dimension overlays.",
                "SKU facts override VLM guesses for hard claims such as 205cm and double base.",
                "Info graphs can pass as info_graph_pass but not commercial_scene_pass.",
                "All generated assets must preserve layered JSON for review and localization.",
            ],
        }

    def create_template_version(
        self,
        sku_id: str,
        source_image_path: str,
        asset_type: str = "dimension_infographic",
        title: str = "205cm XXL Cat Tree Tower",
        subtitle: str = "Editable layered template output",
        marketplace: str = "US",
    ) -> CreativeVersion:
        task = self.create_task(
            sku_id=sku_id,
            objective=f"template_layered_{asset_type}",
            marketplace=marketplace,
            target_metrics=["CVR", "return_rate"] if "dimension" in asset_type else ["CTR", "CVR"],
            strategy_brief={"production_route": "template_layered_asset"},
        )
        version = CreativeVersion(
            version_id=f"cv_{uuid.uuid4().hex[:8]}",
            task_id=task.task_id,
            sku_id=sku_id,
            version_name=f"{sku_id} {asset_type} template",
            generation_strategy="template_layered_asset",
            creative_factors=[{"type": "dimension" if "dimension" in asset_type else "infographic", "asset_type": asset_type}],
        )
        asset = self._template_layered_asset(version.version_id, sku_id, source_image_path, asset_type, title, subtitle)
        self._persist_layered_asset(asset)
        version.asset_ids = [asset.asset_id]
        self.repo.upsert("creative_version", version.version_id, version.model_dump())
        return version

    def record_generation_result(self, generation_result: dict[str, Any]) -> CreativeVersion:
        sku_id = generation_result["sku_id"]
        task = self.create_task(
            sku_id=sku_id,
            objective="generated_listing_creative_set",
            target_metrics=["CTR", "CVR", "return_rate"],
            strategy_brief={
                "source": "GenerationService",
                "note": "Imported generated PNG outputs as editable layered assets.",
            },
        )
        version = CreativeVersion(
            version_id=f"cv_{uuid.uuid4().hex[:8]}",
            task_id=task.task_id,
            sku_id=sku_id,
            version_name=f"{sku_id} generated set",
            trace_path=self._trace_path(generation_result),
            metadata={
                "generation_run_id": generation_result.get("run_id"),
                "output_dir": generation_result.get("output_dir"),
            },
        )

        asset_ids: list[str] = []
        for artifact in generation_result.get("artifacts", []):
            path = Path(artifact.get("path", ""))
            if path.suffix.lower() != ".png" or not path.exists():
                continue
            layered = self._layered_asset_from_artifact(version.version_id, sku_id, artifact)
            self._persist_layered_asset(layered)
            asset_ids.append(layered.asset_id)

        version.asset_ids = asset_ids
        self.repo.upsert("creative_version", version.version_id, version.model_dump())
        return version

    def add_review(
        self,
        version_id: str,
        decision: str,
        asset_id: str | None = None,
        tags: list[str] | None = None,
        comment: str = "",
        reviewer: str = "",
    ) -> ReviewRecord:
        review = ReviewRecord(
            review_id=f"rr_{uuid.uuid4().hex[:8]}",
            version_id=version_id,
            asset_id=asset_id,
            reviewer=reviewer,
            decision=decision,
            tags=tags or [],
            comment=comment,
        )
        self.repo.upsert("review_record", review.review_id, review.model_dump())
        return review

    def create_experiment(
        self,
        sku_id: str,
        objective: str,
        control_version_id: str | None = None,
        treatment_version_ids: list[str] | None = None,
        marketplace: str = "US",
        external_variables: dict[str, Any] | None = None,
    ) -> Experiment:
        experiment = Experiment(
            experiment_id=f"ex_{uuid.uuid4().hex[:8]}",
            sku_id=sku_id,
            marketplace=marketplace,
            objective=objective,
            control_version_id=control_version_id,
            treatment_version_ids=treatment_version_ids or [],
            external_variables=external_variables or {},
        )
        self.repo.upsert("experiment", experiment.experiment_id, experiment.model_dump())
        return experiment

    def add_metric(
        self,
        version_id: str,
        metric_name: str,
        value: float,
        experiment_id: str | None = None,
        sample_size: int | None = None,
        confidence: float | None = None,
        window: dict[str, str] | None = None,
    ) -> PerformanceMetric:
        metric = PerformanceMetric(
            metric_id=f"pm_{uuid.uuid4().hex[:8]}",
            experiment_id=experiment_id,
            version_id=version_id,
            metric_name=metric_name,
            value=value,
            sample_size=sample_size,
            confidence=confidence,
            window=window or {},
        )
        self.repo.upsert("performance_metric", metric.metric_id, metric.model_dump())
        return metric

    def create_knowledge_rule(
        self,
        scope: str,
        rule_type: str,
        statement: str,
        evidence: list[dict[str, Any]] | None = None,
        confidence: float = 0,
        status: str = "candidate",
    ) -> KnowledgeRule:
        rule = KnowledgeRule(
            rule_id=f"kr_{uuid.uuid4().hex[:8]}",
            scope=scope,
            rule_type=rule_type,
            statement=statement,
            evidence=evidence or [],
            confidence=confidence,
            status=status,
        )
        self.repo.upsert("knowledge_rule", rule.rule_id, rule.model_dump())
        return rule

    def list_tasks(self) -> list[dict[str, Any]]:
        return self.repo.list("creative_task")

    def list_versions(self) -> list[dict[str, Any]]:
        return self.repo.list("creative_version")

    def list_assets(self) -> list[dict[str, Any]]:
        return self.repo.list("layered_asset")

    def list_reviews(self) -> list[dict[str, Any]]:
        return self.repo.list("review_record")

    def list_experiments(self) -> list[dict[str, Any]]:
        return self.repo.list("experiment")

    def list_metrics(self) -> list[dict[str, Any]]:
        return self.repo.list("performance_metric")

    def list_rules(self) -> list[dict[str, Any]]:
        return self.repo.list("knowledge_rule")

    def get_version(self, version_id: str) -> dict[str, Any] | None:
        version = self.repo.get("creative_version", version_id)
        if not version:
            return None
        version["assets"] = [self.repo.get("layered_asset", asset_id) for asset_id in version.get("asset_ids", [])]
        return version

    def _layered_asset_from_artifact(self, version_id: str, sku_id: str, artifact: dict[str, Any]) -> LayeredAsset:
        source = Path(artifact["path"])
        metadata = artifact.get("metadata", {})
        with Image.open(source) as image:
            width, height = image.size
        asset_id = f"la_{uuid.uuid4().hex[:8]}"
        layers = [
            Layer(
                layer_id=f"ly_{uuid.uuid4().hex[:8]}",
                layer_type="image",
                name="base_rendered_image",
                source_path=str(source),
                x=0,
                y=0,
                width=width,
                height=height,
                locked=True,
                data={"role": "base_image"},
            )
        ]
        layers.extend(self._metadata_layers(metadata))
        return LayeredAsset(
            asset_id=asset_id,
            version_id=version_id,
            sku_id=sku_id,
            asset_type=artifact.get("type", "image"),
            canvas={"width": width, "height": height},
            layers=layers,
            source_path=str(source),
            metadata={
                **metadata,
                "source_artifact_id": artifact.get("artifact_id"),
                "source_job_id": artifact.get("job_id"),
                "editable_source_type": "layered_json",
            },
        )

    def _metadata_layers(self, metadata: dict[str, Any]) -> list[Layer]:
        layers: list[Layer] = []
        strategy = metadata.get("generation_strategy")
        quality = metadata.get("commercial_quality_level")
        if strategy or quality:
            layers.append(Layer(
                layer_id=f"ly_{uuid.uuid4().hex[:8]}",
                layer_type="metadata",
                name="creative_strategy_metadata",
                data={
                    "generation_strategy": strategy,
                    "commercial_quality_level": quality,
                    "reference_assets_used": metadata.get("reference_assets_used", []),
                    "direct_white_bg_subject": metadata.get("direct_white_bg_subject"),
                },
            ))
        return layers

    def _template_layered_asset(
        self,
        version_id: str,
        sku_id: str,
        source_image_path: str,
        asset_type: str,
        title: str,
        subtitle: str,
    ) -> LayeredAsset:
        source = Path(source_image_path)
        canvas = {"width": 1500, "height": 1500}
        layers = [
            Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", layer_type="shape", name="background", x=0, y=0, width=1500, height=1500, style={"fill": "#ffffff", "outline": "#ffffff"}),
            Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", layer_type="text", name="title", x=80, y=64, text=title, style={"font_size": 56, "bold": True, "fill": "#172033"}),
            Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", layer_type="text", name="subtitle", x=82, y=132, text=subtitle, style={"font_size": 30, "fill": "#536173"}),
        ]
        if source.exists():
            layers.append(Layer(
                layer_id=f"ly_{uuid.uuid4().hex[:8]}",
                layer_type="image",
                name="product_reference_image",
                source_path=str(source),
                x=390,
                y=245,
                width=820,
                height=1030,
                locked=False,
                data={"role": "product_reference"},
            ))
        if "dimension" in asset_type:
            layers.extend([
                Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", layer_type="dimension", name="height_line", x=260, y=250, width=0, height=1030, style={"shape": "line", "outline": "#2563eb", "width": 8}, data={"points": [(260, 250), (260, 1280)], "value": "205cm"}),
                Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", layer_type="shape", name="dimension_label_box", x=170, y=720, width=180, height=112, style={"fill": "#eff6ff", "outline": "#2563eb", "width": 3, "radius": 16}),
                Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", layer_type="text", name="dimension_label", x=204, y=744, text="205cm", style={"font_size": 42, "bold": True, "fill": "#1d4ed8"}),
            ])
        else:
            layers.append(Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", layer_type="shape", name="callout_box", x=1060, y=330, width=300, height=110, style={"fill": "#eff6ff", "outline": "#2563eb", "width": 3, "radius": 16}))
            layers.append(Layer(layer_id=f"ly_{uuid.uuid4().hex[:8]}", layer_type="text", name="callout_text", x=1090, y=360, text="Editable Callout", style={"font_size": 32, "bold": True, "fill": "#1d4ed8"}))
        return LayeredAsset(
            asset_id=f"la_{uuid.uuid4().hex[:8]}",
            version_id=version_id,
            sku_id=sku_id,
            asset_type=asset_type,
            canvas=canvas,
            layers=layers,
            source_path=str(source) if source.exists() else None,
            metadata={
                "generation_strategy": "template_layered_asset",
                "commercial_quality_level": "info_graph_pass",
                "reference_assets_used": ["product_reference_image"],
                "direct_white_bg_subject": True,
                "editable_source_type": "layered_json",
            },
        )

    def _persist_layered_asset(self, asset: LayeredAsset):
        asset_dir = self.output_dir / "creative_assets" / asset.version_id / asset.asset_id
        asset_dir.mkdir(parents=True, exist_ok=True)
        rendered_path = asset_dir / "rendered.png"
        layers_path = asset_dir / "layers.json"
        metadata_path = asset_dir / "metadata.json"

        if asset.source_path and Path(asset.source_path).exists():
            shutil.copy(asset.source_path, rendered_path)
        else:
            self.renderer.render(asset, rendered_path)
        asset.rendered_path = str(rendered_path)

        with open(layers_path, "w", encoding="utf-8") as f:
            json.dump(asset.model_dump(), f, ensure_ascii=False, indent=2)
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(asset.metadata, f, ensure_ascii=False, indent=2)
        self.repo.upsert("layered_asset", asset.asset_id, asset.model_dump())

    def _trace_path(self, generation_result: dict[str, Any]) -> str | None:
        for artifact in generation_result.get("artifacts", []):
            if artifact.get("type") == "trace":
                return artifact.get("path")
        output_dir = generation_result.get("output_dir")
        if output_dir and (Path(output_dir) / "trace.json").exists():
            return str(Path(output_dir) / "trace.json")
        return None

    def _prompt_brief(self, product: dict[str, Any], factors: list[dict[str, Any]]) -> dict[str, str]:
        name = product.get("name", "product")
        return {
            "base_scene": (
                f"Create a commercial Amazon listing scene for {name}. "
                "Generate the full image as a coherent scene; do not paste a cutout. "
                "Keep SKU recognition, major components, color and scale consistent with product references."
            ),
            "dimension_infographic": (
                "Use a clean editable template with product reference, dimension line, unit label, and no generated text baked into the base image."
            ),
            "localization": (
                "Text layers must remain editable. Generate English copy first, then localize with terminology and layout rules per marketplace."
            ),
            "factor_summary": "; ".join(f"{f['factor_id']}->{f['target_metric']}" for f in factors),
        }
