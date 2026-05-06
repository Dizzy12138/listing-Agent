#!/usr/bin/env python3
"""Run A/B Explore comparison with and without knowledge/assets.

This script is intentionally narrow: it does not parse PDFs, confirm assets, or
edit knowledge rules. It only runs two Explore jobs for the same SKU and writes a
compare_report.json showing whether knowledge rules and confirmed standard
assets changed briefs, prompts, QA context, and generation metadata.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_ids(value: str) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    return [part.strip() for part in value.split(",") if part.strip()]


def _load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe(items: list[Any]) -> list[Any]:
    result = []
    seen = set()
    for item in items:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _auto_doc_ids(limit: int = 1) -> list[str]:
    from core.services import asset_service

    docs = [
        doc for doc in asset_service.list_docs()
        if doc.get("parse_status") == "parsed" and doc.get("parsed_knowledge")
    ]
    docs.sort(key=lambda doc: doc.get("parsed_at") or doc.get("upload_time") or "", reverse=True)
    return [doc["doc_id"] for doc in docs[:limit]]


def _auto_confirmed_assets(limit: int = 3) -> tuple[list[str], list[str]]:
    from core.services import asset_service

    asset_item_ids: list[str] = []
    pack_ids: list[str] = []
    for pack in asset_service.list_packs():
        pack_id = pack.get("asset_pack_id")
        if not pack_id:
            continue
        for item in asset_service.list_pack_items(pack_id):
            if item.get("status") == "confirmed":
                asset_item_ids.append(item["asset_item_id"])
                pack_ids.append(pack_id)
            if len(asset_item_ids) >= limit:
                return _dedupe(asset_item_ids), _dedupe(pack_ids)
    return _dedupe(asset_item_ids), _dedupe(pack_ids)


def _product_image_path(product_id: str, explicit: str = "") -> Path:
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path
    lower = product_id.lower()
    for suffix in [".png", ".jpg", ".jpeg", ".webp"]:
        path = ROOT / "products" / "images" / f"{lower}{suffix}"
        if path.exists():
            return path
    raise FileNotFoundError(f"Cannot find product image for {product_id}; pass --product-image")


def _run_explore(
    label: str,
    product_id: str,
    product_image: Path,
    model: str,
    candidate_count: int,
    size: str,
    knowledge_doc_ids: list[str],
    asset_pack_ids: list[str],
    asset_item_ids: list[str],
) -> dict:
    from core.services.explore_generation_service import ExploreGenerationService

    service = ExploreGenerationService()
    result = service.execute_explore(
        product_id=product_id,
        product_image_path=product_image,
        model=model,
        run_id=f"compare_{label}_{product_id}_{datetime.now().strftime('%H%M%S')}",
        knowledge_doc_ids=knowledge_doc_ids,
        asset_pack_ids=asset_pack_ids,
        asset_item_ids=asset_item_ids,
        standard_asset_ids=asset_item_ids,
        size=size,
        candidate_count=candidate_count,
    )
    return _summarize_run(label, result)


def _candidate_files(explore_dir: Path) -> list[Path]:
    return sorted(
        path for path in explore_dir.glob("*/*.json")
        if not path.name.endswith("_qa.json") and path.name != "recommendation.json"
    )


def _summarize_run(label: str, result: dict) -> dict:
    explore_dir = Path(result["explore_dir"])
    creative = _load_json(explore_dir / "creative_briefs.json", {})
    qa = _load_json(explore_dir / "qa_summary.json", {})
    trace = _load_json(explore_dir / "trace.json", [])
    candidate_paths = _candidate_files(explore_dir)
    candidates = [_load_json(path, {}) for path in candidate_paths]
    prompts = [candidate.get("prompt", "") for candidate in candidates if candidate.get("prompt")]
    scores = _flatten_scores(qa)
    context = qa.get("context") or result.get("context") or {}
    return {
        "label": label,
        "explore_dir": str(explore_dir),
        "creative_briefs_path": str(explore_dir / "creative_briefs.json"),
        "qa_summary_path": str(explore_dir / "qa_summary.json"),
        "trace_path": str(explore_dir / "trace.json"),
        "candidate_json_paths": [str(path) for path in candidate_paths],
        "candidate_image_paths": [candidate.get("image_path") for candidate in candidates if candidate.get("image_path")],
        "creative_briefs": creative.get("briefs", []) if isinstance(creative, dict) else [],
        "qa_context": context,
        "prompts": prompts,
        "prompt_joined": "\n\n".join(prompts),
        "candidates": candidates,
        "qa_scores": scores,
        "generation_strategies": _dedupe([candidate.get("generation_strategy", "") for candidate in candidates if candidate.get("generation_strategy")]),
        "knowledge_rules_used": _dedupe(context.get("knowledge_rules_used") or []),
        "negative_prompts_used": _dedupe(context.get("negative_prompts_used") or []),
        "standard_assets_used": _dedupe(context.get("standard_assets_used") or []),
        "trace_context": next((item for item in trace if item.get("step") == "context.load_knowledge_and_assets"), {}),
        "model_unavailable": _model_unavailable(candidates, trace),
        "template_rule_presence": _template_rule_presence("\n".join(prompts)),
    }


def _flatten_scores(qa: dict) -> dict:
    result: dict[str, dict[str, float]] = {}
    for image_type, scores in (qa.get("image_types") or {}).items():
        if not scores:
            continue
        result[image_type] = {
            "commercial_score": _avg([score.get("commercial_score", 0) for score in scores]),
            "sku_consistency_score": _avg([score.get("sku_consistency_score", 0) for score in scores]),
            "scene_score": _avg([score.get("scene_score", 0) for score in scores]),
            "defect_score": _avg([score.get("defect_score", 0) for score in scores]),
            "selling_point_score": _avg([score.get("selling_point_score", 0) for score in scores]),
        }
    return result


def _avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 2) if values else 0


def _model_unavailable(candidates: list[dict], trace: list[dict]) -> bool:
    strategies = " ".join(str(candidate.get("generation_strategy", "")) for candidate in candidates).lower()
    issues = " ".join(
        [
            *(str(issue) for candidate in candidates for issue in (candidate.get("issues") or [])),
            *(str(issue) for record in trace for issue in (record.get("issues") or [])),
        ]
    ).lower()
    return "local_" in strategies or "model_unavailable" in issues or "connection error" in issues


def _template_rule_presence(text: str) -> dict[str, bool]:
    lower = text.lower()
    return {
        "wall_or_against_wall": any(term in lower for term in ["against wall", "near wall", "靠墙"]),
        "window_light": any(term in lower for term in ["window", "窗", "natural daylight", "windows"]),
        "modern_us_home": any(term in lower for term in ["modern american", "premium home", "luxury living", "美国家居"]),
        "orange_icon_assist": any(term in lower for term in ["orange icon", "橙色", "icon", "approved standard visual assets"]),
        "negative_constraints": any(term in lower for term in ["avoid:", "negative", "不要", "禁止"]),
    }


def _set_delta(with_items: list[Any], without_items: list[Any]) -> dict:
    with_set = {str(item) for item in with_items}
    without_set = {str(item) for item in without_items}
    return {
        "without_count": len(without_set),
        "with_count": len(with_set),
        "added": sorted(with_set - without_set),
        "removed": sorted(without_set - with_set),
    }


def _score_delta(with_scores: dict, without_scores: dict) -> dict:
    image_types = sorted(set(with_scores) | set(without_scores))
    delta = {}
    for image_type in image_types:
        keys = sorted(set(with_scores.get(image_type, {})) | set(without_scores.get(image_type, {})))
        delta[image_type] = {
            key: round((with_scores.get(image_type, {}).get(key, 0) - without_scores.get(image_type, {}).get(key, 0)), 2)
            for key in keys
        }
    return delta


def _prompt_diff_summary(with_run: dict, without_run: dict) -> dict:
    without_text = without_run["prompt_joined"]
    with_text = with_run["prompt_joined"]
    without_tokens = set(without_text.lower().replace(",", " ").replace(".", " ").split())
    with_tokens = set(with_text.lower().replace(",", " ").replace(".", " ").split())
    added_terms = sorted(term for term in (with_tokens - without_tokens) if len(term) > 3)[:80]
    required_markers = {
        "knowledge_rules": "Knowledge rules:" in with_text and "Knowledge rules:" not in without_text,
        "scene_rules": "Scene rules:" in with_text and "Scene rules:" not in without_text,
        "style_rules": "Style rules:" in with_text and "Style rules:" not in without_text,
        "avoid_negative": "AVOID:" in with_text,
        "standard_assets": "approved standard visual assets" in with_text,
    }
    return {
        "without_prompt_count": len(without_run["prompts"]),
        "with_prompt_count": len(with_run["prompts"]),
        "without_prompt_chars": len(without_text),
        "with_prompt_chars": len(with_text),
        "added_terms_sample": added_terms,
        "required_markers": required_markers,
        "summary": (
            "with_knowledge prompts include knowledge/asset markers"
            if any(required_markers.values())
            else "no obvious prompt marker delta detected"
        ),
    }


def _build_report(without_run: dict, with_run: dict, output_path: Path, args: argparse.Namespace) -> dict:
    model_unavailable = without_run["model_unavailable"] or with_run["model_unavailable"]
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "product_id": args.product_id,
        "model": args.model,
        "size": args.size,
        "candidate_count": args.candidate_count,
        "model_unavailable": model_unavailable,
        "without_knowledge": _compact_run(without_run),
        "with_knowledge": _compact_run(with_run),
        "prompt_diff_summary": _prompt_diff_summary(with_run, without_run),
        "knowledge_rules_delta": _set_delta(with_run["knowledge_rules_used"], without_run["knowledge_rules_used"]),
        "negative_prompts_delta": _set_delta(with_run["negative_prompts_used"], without_run["negative_prompts_used"]),
        "asset_usage_delta": _set_delta(with_run["standard_assets_used"], without_run["standard_assets_used"]),
        "qa_score_delta": _score_delta(with_run["qa_scores"], without_run["qa_scores"]),
        "generation_strategy_delta": _set_delta(with_run["generation_strategies"], without_run["generation_strategies"]),
        "cat_tree_amazon_template_checks": {
            "without_knowledge": without_run["template_rule_presence"],
            "with_knowledge": with_run["template_rule_presence"],
            "with_knowledge_matches_more_rules": (
                sum(with_run["template_rule_presence"].values())
                > sum(without_run["template_rule_presence"].values())
            ),
        },
        "notes": [
            "Image quality comparison is informational when model_unavailable=false; this report always validates prompt/brief/context deltas.",
            "No PDF parsing, asset confirmation, or knowledge rule editing is performed by this script.",
        ],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def _compact_run(run: dict) -> dict:
    return {
        "explore_dir": run["explore_dir"],
        "creative_briefs_path": run["creative_briefs_path"],
        "qa_summary_path": run["qa_summary_path"],
        "trace_path": run["trace_path"],
        "candidate_json_paths": run["candidate_json_paths"],
        "candidate_image_paths": run["candidate_image_paths"],
        "knowledge_rules_used_count": len(run["knowledge_rules_used"]),
        "negative_prompts_used_count": len(run["negative_prompts_used"]),
        "standard_assets_used": run["standard_assets_used"],
        "generation_strategies": run["generation_strategies"],
        "model_unavailable": run["model_unavailable"],
        "template_rule_presence": run["template_rule_presence"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare Explore outputs with and without knowledge/assets.")
    parser.add_argument("--product-id", default="PCT020")
    parser.add_argument("--product-image", default="")
    parser.add_argument("--knowledge-doc-ids", default="", help="Comma-separated or JSON list. Defaults to latest parsed doc.")
    parser.add_argument("--asset-item-ids", default="", help="Comma-separated or JSON list. Defaults to first confirmed items.")
    parser.add_argument("--asset-pack-ids", default="", help="Comma-separated or JSON list. Auto-derived when possible.")
    parser.add_argument("--asset-limit", type=int, default=3)
    parser.add_argument("--candidate-count", type=int, default=1)
    parser.add_argument("--size", default="2000x2000")
    parser.add_argument("--model", default="gpt-image-2")
    parser.add_argument("--output", default="", help="Report path. Defaults to output/compare_reports/<timestamp>/compare_report.json")
    args = parser.parse_args()

    product_image = _product_image_path(args.product_id, args.product_image)
    doc_ids = _parse_ids(args.knowledge_doc_ids) or _auto_doc_ids(limit=1)
    asset_item_ids = _parse_ids(args.asset_item_ids)
    asset_pack_ids = _parse_ids(args.asset_pack_ids)
    if not asset_item_ids:
        asset_item_ids, auto_pack_ids = _auto_confirmed_assets(limit=args.asset_limit)
        asset_pack_ids = asset_pack_ids or auto_pack_ids

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else ROOT / "output" / "compare_reports" / timestamp / "compare_report.json"

    print(f"Compare Explore for {args.product_id}")
    print(f"Product image: {product_image}")
    print(f"Knowledge docs: {doc_ids or 'none'}")
    print(f"Confirmed asset items: {asset_item_ids or 'none'}")

    without_run = _run_explore(
        "without_knowledge",
        args.product_id,
        product_image,
        args.model,
        args.candidate_count,
        args.size,
        knowledge_doc_ids=[],
        asset_pack_ids=[],
        asset_item_ids=[],
    )
    time.sleep(1)
    with_run = _run_explore(
        "with_knowledge",
        args.product_id,
        product_image,
        args.model,
        args.candidate_count,
        args.size,
        knowledge_doc_ids=doc_ids,
        asset_pack_ids=asset_pack_ids,
        asset_item_ids=asset_item_ids,
    )

    report = _build_report(with_run=with_run, without_run=without_run, output_path=output_path, args=args)
    print(f"PASS compare report written: {output_path}")
    print(f"model_unavailable={report['model_unavailable']}")
    print(f"knowledge_rules_delta.added={len(report['knowledge_rules_delta']['added'])}")
    print(f"negative_prompts_delta.added={len(report['negative_prompts_delta']['added'])}")
    print(f"asset_usage_delta.added={len(report['asset_usage_delta']['added'])}")
    print(f"prompt_summary={report['prompt_diff_summary']['summary']}")
    if not report["model_unavailable"]:
        print("with_knowledge candidate images:")
        for path in report["with_knowledge"]["candidate_image_paths"]:
            print(f"  {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
