"""
ExploreGenerationService — the new default entry point.

Flow:
1. SKUBriefAgent → product identity
2. CreativeDirectorAgent → creative briefs
3. ImageGenerationAgent → N candidates per brief
4. VisualQAAgent → multi-dimensional scoring
5. Output: explore/ directory with candidates, briefs, qa_summary

Does NOT output img01-img09 formal files.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image
from rich.console import Console

from config import MODELS, OUTPUT_DIR, PRODUCTS_DIR
from core.agents.batch_orchestrator_agent import BatchOrchestratorAgent
from core.agents.creative_director_agent import CreativeDirectorAgent
from core.agents.image_generation_agent import ImageGenerationAgent
from core.agents.sku_brief_agent import SKUBriefAgent
from core.agents.visual_qa_agent import VisualQAAgent
from core.schemas.candidate import QAScore
from core.schemas.sku import SKU
from core.services.creative_service import CreativeService
from core.services.sku_service import SKUService
from core.tracing.trace import TraceRecorder
from pipeline.step1_extract import remove_background

console = Console()
ProgressCallback = Callable[[str, int], None]


class ExploreGenerationService:
    """Explore mode: generate multi-candidate images for core types, score and recommend."""

    def __init__(self, products_dir: Path = PRODUCTS_DIR, output_dir: Path = OUTPUT_DIR):
        self.products_dir = products_dir
        self.output_dir = output_dir
        self.sku_service = SKUService(products_dir)

    def execute_explore(
        self,
        product_id: str,
        product_image_path: str | Path,
        model: str | None = None,
        run_id: str | None = None,
        progress: ProgressCallback | None = None,
        knowledge_doc_ids: list[str] | None = None,
        asset_pack_ids: list[str] | None = None,
        asset_item_ids: list[str] | None = None,
        inspiration_asset_ids: list[str] | None = None,
        standard_asset_ids: list[str] | None = None,
        size: str = "2000x2000",
        candidate_count: int = 4,
    ) -> dict:
        sku = self.sku_service.load(product_id)
        knowledge_doc_ids = self._merge_ids(knowledge_doc_ids, getattr(sku, "knowledge_doc_ids", []))
        asset_pack_ids = self._merge_ids(asset_pack_ids, getattr(sku, "asset_pack_ids", []))
        standard_asset_ids = self._merge_ids(standard_asset_ids, getattr(sku, "standard_asset_item_ids", []))
        inspiration_asset_ids = self._merge_ids(inspiration_asset_ids, getattr(sku, "inspiration_asset_ids", []))
        asset_item_ids = self._merge_ids(asset_item_ids, standard_asset_ids)
        model = model or MODELS.get("image_primary", "gpt-image-2")
        run_id = run_id or f"explore_{product_id}_{datetime.now().strftime('%H%M%S')}"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        run_dir = self.output_dir / f"{product_id}_{timestamp}"
        explore_dir = run_dir / "explore"
        explore_dir.mkdir(parents=True, exist_ok=True)
        trace = TraceRecorder(run_id)
        knowledge_context = self._load_knowledge_context(knowledge_doc_ids)
        asset_context = self._load_asset_context(asset_pack_ids, asset_item_ids, inspiration_asset_ids)
        trace.add(
            step="context.load_knowledge_and_assets",
            status="warning" if knowledge_context["warnings"] or asset_context["excluded_unconfirmed_asset_item_ids"] or asset_context["missing_asset_item_ids"] else "success",
            input={
                "knowledge_doc_ids": knowledge_doc_ids,
                "asset_pack_ids": asset_pack_ids,
                "asset_item_ids": asset_item_ids,
                "requested_asset_item_ids": asset_item_ids,
                "inspiration_asset_ids": inspiration_asset_ids,
                "standard_asset_ids": standard_asset_ids,
                "knowledge_source": knowledge_context["knowledge_source"],
                "knowledge_summary_used": knowledge_context["knowledge_summary_used"],
                "standard_assets_used": [item["asset_item_id"] for item in asset_context["confirmed_items"]],
                "confirmed_asset_item_ids": [item["asset_item_id"] for item in asset_context["confirmed_items"]],
                "excluded_unconfirmed_asset_item_ids": asset_context["excluded_unconfirmed_asset_item_ids"],
                "missing_asset_item_ids": asset_context["missing_asset_item_ids"],
            },
            issues=knowledge_context["warnings"],
        )

        image_path = Path(product_image_path)
        product_image = Image.open(image_path).copy().convert("RGB")

        # Save original
        shutil.copy(image_path, run_dir / "original.png")

        # ---- Step 1: Asset extraction (for reference only) ----
        self._progress(progress, "AssetAgent: 主体标准化 (reference)", 5)
        extracted = remove_background(product_image, model=model)
        extracted["transparent"].save(run_dir / "01_transparent.png", "PNG")
        extracted["white_bg"].save(run_dir / "01_white_bg.png", "PNG")
        trace.add(step="asset_agent.extract", status="success",
                  input={"sku_id": product_id, "note": "white_bg is reference only, not compositing base"})

        # ---- Step 2: SKU Brief ----
        self._progress(progress, "SKUBriefAgent: 商品身份提取", 10)
        brief_agent = SKUBriefAgent()
        sku_brief = brief_agent.generate_brief(sku, product_image)
        self._inject_context_into_sku_brief(sku_brief, knowledge_context, asset_context)
        sku_brief_path = explore_dir / "sku_brief.json"
        sku_brief_path.write_text(sku_brief.model_dump_json(indent=2), encoding="utf-8")
        trace.add(step="sku_brief_agent", status="success",
                  input={"core_identity_count": len(sku_brief.core_identity)},
                  output_artifact=str(sku_brief_path))

        # ---- Step 3: Creative Director ----
        self._progress(progress, "CreativeDirector: 视觉方案规划", 15)
        director = CreativeDirectorAgent()
        brief_set = director.plan(sku_brief)
        briefs_path = explore_dir / "creative_briefs.json"
        briefs_path.write_text(brief_set.model_dump_json(indent=2), encoding="utf-8")
        trace.add(step="creative_director", status="success",
                  input={"brief_count": len(brief_set.briefs)},
                  output_artifact=str(briefs_path))

        console.print(f"  📋 {len(brief_set.briefs)} creative briefs planned")
        for b in brief_set.briefs:
            console.print(f"    • {b.image_type} ({b.material_focus or 'main'}) — {b.visual_goal[:60]}...")

        # ---- Step 4: Multi-candidate generation ----
        gen_agent = ImageGenerationAgent(model=model, candidates_per_brief=max(1, min(int(candidate_count or 4), 8)))
        all_candidates = {}
        all_qa_input = {}
        total_briefs = len(brief_set.briefs)

        for i, brief in enumerate(brief_set.briefs):
            pct = 20 + int(i / total_briefs * 50)
            self._progress(progress, f"ImageGen: {brief.image_type} ({brief.material_focus or 'main'})", pct)

            candidates = gen_agent.generate_candidates(
                brief=brief,
                sku_brief=sku_brief,
                original_image=product_image,
                white_bg_image=extracted["white_bg"],
                output_dir=explore_dir,
            )
            self._resize_candidate_images(candidates, size)

            # Save candidates
            type_key = self._type_key_for_brief(brief)
            gen_agent.save_candidates(candidates, explore_dir, type_key)

            all_candidates[type_key] = candidates

            # Prepare QA input
            qa_input = []
            for c in candidates:
                img = getattr(c, '_image', None)
                if img is None and c.image_path:
                    try:
                        img = Image.open(c.image_path)
                    except OSError:
                        pass
                qa_input.append({
                    "candidate_id": c.candidate_id,
                    "image": img,
                    "image_path": c.image_path,
                    "brief": brief,
                })
            all_qa_input[type_key] = qa_input

            trace.add(
                step=f"image_gen.{type_key}",
                status="success" if any(c.status != "failed" for c in candidates) else "warning",
                input={
                    "image_type": type_key,
                    "candidates_generated": len(candidates),
                    "size": size,
                    "knowledge_doc_ids": knowledge_doc_ids,
                    "asset_pack_ids": asset_pack_ids,
                    "asset_item_ids": asset_item_ids,
                    "standard_assets_used": [item["asset_item_id"] for item in asset_context["confirmed_items"]],
                },
                issues=[c.issues[0] for c in candidates if c.issues],
            )

        # ---- Step 5: Visual QA ----
        self._progress(progress, "VisualQA: 候选图质量评审", 75)
        qa_agent = VisualQAAgent()
        all_scores: dict[str, list[QAScore]] = {}

        for type_key, qa_input in all_qa_input.items():
            scores = qa_agent.evaluate_batch(qa_input, sku_brief)
            all_scores[type_key] = scores

            # Save individual scores
            type_dir = explore_dir / type_key
            type_dir.mkdir(parents=True, exist_ok=True)
            for score in scores:
                score_path = type_dir / f"{score.candidate_id}_qa.json"
                score_path.write_text(score.model_dump_json(indent=2), encoding="utf-8")

            trace.add(
                step=f"visual_qa.{type_key}",
                status="success",
                input={"candidates_evaluated": len(scores)},
                issues=[s.issues[0] for s in scores if s.issues],
            )

        context_summary = {
            "knowledge_doc_ids": knowledge_doc_ids,
            "asset_pack_ids": asset_pack_ids,
            "asset_item_ids": asset_item_ids,
            "inspiration_asset_ids": inspiration_asset_ids,
            "standard_asset_ids": standard_asset_ids,
            "knowledge_summary_used": knowledge_context["knowledge_summary_used"],
            "knowledge_source": knowledge_context["knowledge_source"],
            "standard_assets_used": [item["asset_item_id"] for item in asset_context["confirmed_items"]],
            "confirmed_asset_item_ids": [item["asset_item_id"] for item in asset_context["confirmed_items"]],
            "excluded_unconfirmed_asset_item_ids": asset_context["excluded_unconfirmed_asset_item_ids"],
            "missing_asset_item_ids": asset_context["missing_asset_item_ids"],
        }

        # Build QA summary
        qa_summary = qa_agent.build_summary(product_id, run_id, all_scores)
        qa_summary_data = qa_summary.model_dump()
        qa_summary_data["context"] = context_summary
        qa_summary_path = explore_dir / "qa_summary.json"
        qa_summary_path.write_text(json.dumps(qa_summary_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # Build recommendation.json per type
        for type_key, scores in all_scores.items():
            type_dir = explore_dir / type_key
            rec = {
                "image_type": type_key,
                "recommended": qa_summary.recommendations.get(type_key),
                "scores": [s.model_dump() for s in sorted(scores, key=lambda x: -(
                    x.commercial_score * 0.3 + x.sku_consistency_score * 0.25
                    + x.scene_score * 0.2 + x.defect_score * 0.15 + x.selling_point_score * 0.1
                ))],
            }
            (type_dir / "recommendation.json").write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")

        # ---- Save trace ----
        trace_path = explore_dir / "trace.json"
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace.records, f, ensure_ascii=False, indent=2)

        # ---- Import explore outputs into the creative feedback loop ----
        artifacts = self._build_creative_artifacts(all_candidates, all_scores, trace_path)
        creative_version = None
        try:
            creative_version = CreativeService(output_dir=self.output_dir).record_generation_result({
                "run_id": run_id,
                "sku_id": product_id,
                "mode": "explore",
                "output_dir": str(run_dir),
                "artifacts": artifacts,
            })
            trace.add(
                step="creative_loop.import_explore_result",
                status="success",
                input={"artifact_count": len(artifacts)},
                output_artifact=creative_version.version_id,
            )
        except Exception as exc:
            trace.add(
                step="creative_loop.import_explore_result",
                status="warning",
                input={"artifact_count": len(artifacts)},
                issues=[f"creative_loop_import_failed: {exc}"],
            )
        with open(trace_path, "w", encoding="utf-8") as f:
            json.dump(trace.records, f, ensure_ascii=False, indent=2)

        self._progress(progress, "完成", 100)

        # Summary
        console.print(f"\n[bold green]✅ Explore 完成[/]")
        console.print(f"  📁 输出: {explore_dir}")
        console.print(f"  📋 Briefs: {len(brief_set.briefs)}")
        total_gen = sum(sum(1 for c in cl if c.status != "failed") for cl in all_candidates.values())
        console.print(f"  🎨 候选图: {total_gen}")
        console.print(f"  ⭐ 推荐: {qa_summary.recommendations}")
        console.print(f"  🔍 QA 来源: {qa_summary.visual_qa_source}")
        console.print(f"  📊 就绪度: {qa_summary.overall_readiness}")

        return {
            "run_id": run_id,
            "sku_id": product_id,
            "mode": "explore",
            "output_dir": str(run_dir),
            "explore_dir": str(explore_dir),
            "sku_brief": sku_brief.model_dump(),
            "creative_briefs": [b.model_dump() for b in brief_set.briefs],
            "candidates": {k: [c.model_dump() for c in v] for k, v in all_candidates.items()},
            "qa_summary": qa_summary_data,
            "creative_version": creative_version.model_dump() if creative_version else None,
            "artifacts": artifacts,
            "context": context_summary,
            "traces": trace.records,
        }

    def _progress(self, callback: ProgressCallback | None, message: str, value: int):
        if callback:
            callback(message, value)

    def _merge_ids(self, explicit: list[str] | None, bound: list[str] | None) -> list[str]:
        result: list[str] = []
        for value in [*(explicit or []), *(bound or [])]:
            if value and value not in result:
                result.append(value)
        return result

    def _load_knowledge_context(self, doc_ids: list[str]) -> dict:
        context = {
            "docs": [],
            "knowledge_summary_used": "",
            "knowledge_source": "none",
            "warnings": [],
        }
        if not doc_ids:
            return context
        try:
            from core.services.asset_service import analyze_doc, get_doc
        except Exception as exc:
            context["knowledge_source"] = "failed"
            context["warnings"].append(f"knowledge_service_unavailable: {exc}")
            return context

        summaries = []
        source_states = []
        for doc_id in doc_ids:
            doc = get_doc(doc_id)
            if not doc:
                context["warnings"].append(f"knowledge_doc_not_found: {doc_id}")
                source_states.append("failed")
                continue
            if doc.parse_status != "parsed":
                try:
                    doc = analyze_doc(doc_id)
                except Exception as exc:
                    context["warnings"].append(f"knowledge_doc_parse_failed: {doc_id}: {exc}")
            if doc.parse_status == "parsed" and doc.parsed_knowledge:
                source_states.append("parsed")
                knowledge = doc.parsed_knowledge
                summaries.append(knowledge.get("summary") or doc.summary or doc.name)
                context["docs"].append(doc.model_dump())
            elif doc.parse_status == "failed":
                source_states.append("failed")
                context["warnings"].append(f"knowledge_doc_failed: {doc_id}: {doc.error or doc.status_message}")
            else:
                source_states.append("pending")
                context["warnings"].append(f"knowledge_doc_pending: {doc_id}")
        if "parsed" in source_states:
            context["knowledge_source"] = "parsed"
        elif "failed" in source_states:
            context["knowledge_source"] = "failed"
        elif source_states:
            context["knowledge_source"] = "pending"
        context["knowledge_summary_used"] = " / ".join(summaries)[:1200]
        return context

    def _load_asset_context(
        self,
        pack_ids: list[str],
        item_ids: list[str],
        inspiration_ids: list[str],
    ) -> dict:
        context = {
            "packs": [],
            "confirmed_items": [],
            "inspiration_items": [],
            "excluded_unconfirmed_asset_item_ids": [],
            "missing_asset_item_ids": [],
        }
        try:
            from core.services.asset_service import get_item, get_pack, list_pack_items
        except Exception:
            return context
        for pack_id in pack_ids:
            pack = get_pack(pack_id)
            if pack:
                context["packs"].append(pack.model_dump())
                for item in list_pack_items(pack_id):
                    if item.get("status") == "confirmed" and item.get("asset_item_id") not in item_ids:
                        context["confirmed_items"].append(item)
        for item_id in item_ids:
            item = get_item(item_id)
            if not item:
                context["missing_asset_item_ids"].append(item_id)
                continue
            data = item.model_dump()
            if item.status == "confirmed":
                context["confirmed_items"].append(data)
            else:
                context["excluded_unconfirmed_asset_item_ids"].append(item_id)
        for item_id in inspiration_ids:
            item = get_item(item_id)
            if item:
                context["inspiration_items"].append(item.model_dump())
        seen = set()
        deduped = []
        for item in context["confirmed_items"]:
            iid = item.get("asset_item_id")
            if iid in seen:
                continue
            seen.add(iid)
            deduped.append(item)
        context["confirmed_items"] = deduped
        return context

    def _inject_context_into_sku_brief(self, sku_brief, knowledge_context: dict, asset_context: dict):
        for doc in knowledge_context.get("docs", []):
            knowledge = doc.get("parsed_knowledge") or {}
            for rule in (knowledge.get("global_rules") or [])[:6]:
                if isinstance(rule, str) and rule not in sku_brief.must_show:
                    sku_brief.must_show.append(rule)
            for negative in (knowledge.get("negative_prompts") or [])[:8]:
                if isinstance(negative, str) and negative not in sku_brief.sku_consistency_rules["strict"]:
                    sku_brief.sku_consistency_rules["strict"].append(negative)
            for keyword in (knowledge.get("keyword_bank") or [])[:12]:
                if isinstance(keyword, str) and keyword not in sku_brief.core_identity:
                    sku_brief.core_identity.append(keyword)
        for item in asset_context.get("confirmed_items", [])[:20]:
            label = f"approved visual asset: {item.get('name')} ({item.get('group')})"
            if label not in sku_brief.core_identity:
                sku_brief.core_identity.append(label)

    def _resize_candidate_images(self, candidates: list, size: str):
        try:
            width, height = [int(part) for part in size.lower().split("x", 1)]
        except Exception:
            width, height = 2000, 2000
        for candidate in candidates:
            img = getattr(candidate, "_image", None)
            if img is None:
                continue
            if img.size != (width, height):
                candidate._image = img.resize((width, height), Image.LANCZOS)

    def _type_key_for_brief(self, brief) -> str:
        if not brief.material_focus:
            return brief.image_type
        source = "|".join([
            brief.image_type,
            brief.material_focus or "",
            brief.visual_goal or "",
            brief.scene or "",
        ])
        digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:6]
        return f"{brief.image_type}_{brief.material_focus}_{digest}"

    def _build_creative_artifacts(
        self,
        all_candidates: dict[str, list],
        all_scores: dict[str, list[QAScore]],
        trace_path: Path,
    ) -> list[dict]:
        artifacts: list[dict] = [{
            "artifact_id": f"{trace_path.parent.name}_trace",
            "type": "trace",
            "name": "trace.json",
            "path": str(trace_path),
            "metadata": {"generation_strategy": "agent_trace"},
        }]
        score_index = {
            score.candidate_id: score
            for scores in all_scores.values()
            for score in scores
        }
        for type_key, candidates in all_candidates.items():
            for cand in candidates:
                path = Path(cand.image_path) if cand.image_path else None
                if not path or not path.exists():
                    continue
                score = score_index.get(cand.candidate_id)
                quality_level = "needs_review"
                if score and score.decision in {"recommended", "candidate"} and score.visual_qa_source == "vlm":
                    quality_level = "commercial_scene_pass" if "scene" in cand.image_type else "info_graph_pass"
                artifacts.append({
                    "artifact_id": cand.candidate_id,
                    "job_id": type_key,
                    "type": cand.image_type,
                    "name": path.name,
                    "path": str(path),
                    "metadata": {
                        **cand.model_dump(),
                        "generation_strategy": cand.generation_strategy,
                        "commercial_quality_level": quality_level,
                        "reference_assets_used": cand.reference_assets_used,
                        "visual_qa": score.model_dump() if score else None,
                    },
                })
        return artifacts
