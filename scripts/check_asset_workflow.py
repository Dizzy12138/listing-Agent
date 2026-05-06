#!/usr/bin/env python3
"""Self-check for knowledge docs, asset packs, and health routes.

By default this uses FastAPI's in-process TestClient, so it does not require a
running server. Pass --base-url http://host:port to check a live deployment.
"""
from __future__ import annotations

import argparse
import json
import time
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _client_request(method: str, path: str, **kwargs):
    from fastapi.testclient import TestClient
    from server import app

    client = TestClient(app)
    return client.request(method, path, **kwargs)


def _http_request(base_url: str, method: str, path: str, **kwargs):
    import httpx

    return httpx.request(method, base_url.rstrip("/") + path, timeout=30, **kwargs)


def _ok(label: str):
    print(f"PASS {label}")


def _fail(label: str, detail: Any):
    print(f"FAIL {label}: {detail}")
    return False


def _asset_items_quality(items: list[dict], pack_type: str = "icon_pack_pdf") -> tuple[bool, str]:
    if pack_type == "icon_pack_pdf" and len(items) <= 2:
        return False, f"icon pack returned only {len(items)} items"
    required = {"group", "item_type", "status", "source", "preview_url", "applicable_categories", "transparent_png_url", "confidence"}
    missing = [
        item.get("asset_item_id") or item.get("name") or "<unknown>"
        for item in items
        if any(field not in item for field in required)
    ]
    if missing:
        return False, f"items missing required fields: {missing[:5]}"
    if any(item.get("status") == "available" for item in items):
        return False, "found deprecated status=available"
    page_like = [
        item for item in items
        if item.get("source") == "text_preview"
        or "pdf_page" in (item.get("tags") or [])
        or str(item.get("name", "")).startswith("页面_")
    ]
    if items and len(page_like) == len(items):
        return False, "all items are page previews"
    if pack_type == "icon_pack_pdf":
        names = {str(item.get("name", "")) for item in items}
        expected = {"猫树", "猫抓板", "防倾倒", "承重"}
        if not expected.issubset(names) or not any("箭头" in name for name in names):
            return False, f"missing expected Feandrea items; got sample={sorted(names)[:12]}"
    return True, f"{len(items)} items"


def _confirm_items_flow(request, pack_id: str, items: list[dict]) -> tuple[bool, list[str], str]:
    candidates = [item for item in items if item.get("status") in {"needs_review", "auto_detected"}]
    if len(candidates) < 4:
        return False, [], f"need at least 4 unconfirmed items, got {len(candidates)}"
    confirm_ids = [item["asset_item_id"] for item in candidates[:3]]
    response = request(
        "POST",
        "/api/asset-items/batch-confirm",
        json={
            "asset_item_ids": confirm_ids,
            "status": "confirmed",
            "tags": ["self_check_confirmed"],
            "applicable_categories": ["Self Check"],
            "applicable_image_types": ["feature_icon"],
        },
    )
    if response.status_code != 200:
        return False, [], f"HTTP {response.status_code}: {response.text[:200]}"
    data = response.json()
    updated = data.get("items", data if isinstance(data, list) else [])
    if len(updated) != len(confirm_ids):
        return False, [], f"expected {len(confirm_ids)} updated items, got {len(updated)}; skipped={data.get('skipped')}"

    items_response = request("GET", f"/api/asset-packs/{pack_id}/items")
    if items_response.status_code != 200:
        return False, [], f"reload HTTP {items_response.status_code}: {items_response.text[:200]}"
    reloaded = items_response.json()
    index = {item.get("asset_item_id"): item for item in reloaded}
    if not all(index.get(item_id, {}).get("status") == "confirmed" for item_id in confirm_ids):
        return False, [], "confirmed items did not persist"
    return True, confirm_ids, f"{len(confirm_ids)} items confirmed"


def _run_explore_smoke(
    request,
    product_id: str,
    confirmed_ids: list[str],
    unconfirmed_id: str = "",
    knowledge_doc_ids: list[str] | None = None,
) -> tuple[bool, str]:
    knowledge_doc_ids = knowledge_doc_ids or []
    response = request(
        "POST",
        "/api/explore-tasks",
        data={
            "product_id": product_id,
            "knowledge_doc_ids": ",".join(knowledge_doc_ids),
            "asset_item_ids": ",".join([item_id for item_id in [*confirmed_ids, unconfirmed_id] if item_id]),
            "standard_asset_ids": ",".join(confirmed_ids),
            "size": "2000x2000",
            "candidate_count": "1",
        },
    )
    if response.status_code != 200:
        return False, f"create HTTP {response.status_code}: {response.text[:300]}"
    task_id = response.json().get("task_id")
    if not task_id:
        return False, f"missing task_id: {response.text[:300]}"
    _ok("explore context created")

    task = {}
    for _ in range(90):
        task_response = request("GET", f"/api/tasks/{task_id}")
        if task_response.status_code != 200:
            return False, f"task HTTP {task_response.status_code}: {task_response.text[:300]}"
        task = task_response.json()
        if task.get("status") in {"done", "error"}:
            break
        time.sleep(2)
    if task.get("status") != "done":
        return False, f"task did not finish: status={task.get('status')} error={task.get('error')}"

    context = task.get("context") or (task.get("qa_summary") or {}).get("context") or {}
    used = set(context.get("standard_assets_used") or context.get("confirmed_asset_item_ids") or [])
    excluded = set(context.get("excluded_unconfirmed_asset_item_ids") or [])
    requested = set(context.get("asset_item_ids") or [])
    if confirmed_ids and not set(confirmed_ids).issubset(used):
        return False, f"confirmed assets missing from standard_assets_used: used={sorted(used)}"
    if confirmed_ids:
        _ok("confirmed assets used")
    if unconfirmed_id and unconfirmed_id not in excluded:
        return False, f"unconfirmed asset not excluded: excluded={sorted(excluded)}"
    if unconfirmed_id:
        _ok("unconfirmed assets excluded")
    if (confirmed_ids or unconfirmed_id) and not requested:
        return False, "qa summary context missing asset_item_ids"
    if confirmed_ids or unconfirmed_id:
        _ok("qa summary context")
    if knowledge_doc_ids:
        ok, detail = _check_explore_knowledge_outputs(task, knowledge_doc_ids)
        if not ok:
            return False, detail
    return True, f"task_id={task_id}"


def _check_explore_knowledge_outputs(task: dict, knowledge_doc_ids: list[str]) -> tuple[bool, str]:
    explore_dir = Path(task.get("explore_dir") or task.get("result", {}).get("explore_dir") or "")
    if not explore_dir.exists():
        return False, f"missing explore_dir: {explore_dir}"

    briefs_path = explore_dir / "creative_briefs.json"
    qa_path = explore_dir / "qa_summary.json"
    if not briefs_path.exists() or not qa_path.exists():
        return False, "missing creative_briefs.json or qa_summary.json"

    briefs_data = json.loads(briefs_path.read_text(encoding="utf-8"))
    briefs = briefs_data.get("briefs", []) if isinstance(briefs_data, dict) else []
    if not briefs or not any(b.get("knowledge_doc_ids") for b in briefs):
        return False, "creative_briefs missing knowledge_doc_ids"
    if not any(b.get("knowledge_rules_used") for b in briefs):
        return False, "creative_briefs missing knowledge_rules_used"
    _ok("creative briefs knowledge refs")

    candidate_files = [p for p in explore_dir.glob("*/*.json") if not p.name.endswith("_qa.json") and p.name != "recommendation.json"]
    if not candidate_files:
        return False, "missing candidate metadata json"
    candidate = json.loads(candidate_files[0].read_text(encoding="utf-8"))
    if not set(knowledge_doc_ids).intersection(candidate.get("knowledge_doc_ids") or []):
        return False, "candidate missing knowledge_doc_ids"
    if not candidate.get("knowledge_rules_used"):
        return False, "candidate missing knowledge_rules_used"
    _ok("candidate knowledge refs")

    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    context = qa.get("context") or {}
    if not set(knowledge_doc_ids).intersection(context.get("knowledge_doc_ids") or []):
        return False, "qa_summary.context missing knowledge_doc_ids"
    if not context.get("knowledge_rules_used"):
        return False, "qa_summary.context missing knowledge_rules_used"
    _ok("qa summary knowledge refs")
    return True, "knowledge refs ok"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check listing-Agent asset workflow APIs.")
    parser.add_argument("--base-url", default="", help="Optional live server base URL.")
    parser.add_argument("--doc-file", default="", help="Optional docx/pdf/txt/md file to upload.")
    parser.add_argument("--pack-file", default="", help="Optional pdf/zip/image file to upload.")
    parser.add_argument("--confirm-items", action="store_true", help="Confirm three parsed asset items and verify persistence.")
    parser.add_argument("--run-explore-smoke", action="store_true", help="Create an Explore task with confirmed and unconfirmed asset ids.")
    parser.add_argument("--product-id", default="PCT020", help="SKU id for --run-explore-smoke.")
    args = parser.parse_args()

    def request(method: str, path: str, **kwargs):
        if args.base_url:
            return _http_request(args.base_url, method, path, **kwargs)
        return _client_request(method, path, **kwargs)

    checks: list[bool] = []
    knowledge_doc_ids: list[str] = []
    for label, method, path in [
        ("health", "GET", "/api/health"),
        ("knowledge-docs list", "GET", "/api/knowledge-docs"),
        ("asset-packs list", "GET", "/api/asset-packs"),
    ]:
        try:
            response = request(method, path)
            if response.status_code == 200:
                _ok(label)
                checks.append(True)
            else:
                checks.append(_fail(label, f"HTTP {response.status_code}: {response.text[:200]}"))
        except Exception as exc:
            checks.append(_fail(label, exc))

    if args.doc_file:
        path = Path(args.doc_file)
        if not path.exists():
            checks.append(_fail("knowledge doc upload", f"missing file: {path}"))
        else:
            with path.open("rb") as fh:
                response = request(
                    "POST",
                    "/api/knowledge-docs/upload",
                    files={"file": (path.name, fh, "application/octet-stream")},
                    data={"name": path.stem, "category": "Self Check"},
                )
            if response.status_code == 200 and response.json().get("doc_id"):
                _ok("knowledge doc upload")
                checks.append(True)
                doc_id = response.json().get("doc_id")
                analyze_response = request("POST", f"/api/knowledge-docs/{doc_id}/analyze")
                analyzed = analyze_response.json() if analyze_response.status_code == 200 else {}
                if analyze_response.status_code == 200 and analyzed.get("parsed_knowledge"):
                    _ok("knowledge doc analyze")
                    checks.append(True)
                    knowledge_doc_ids.append(doc_id)
                else:
                    checks.append(_fail("knowledge doc analyze", f"HTTP {analyze_response.status_code}: {analyze_response.text[:300]}"))
            else:
                checks.append(_fail("knowledge doc upload", f"HTTP {response.status_code}: {response.text[:200]}"))

    if args.pack_file:
        path = Path(args.pack_file)
        if not path.exists():
            checks.append(_fail("asset pack upload", f"missing file: {path}"))
        else:
            with path.open("rb") as fh:
                response = request(
                    "POST",
                    "/api/asset-packs/upload",
                    files=[("file", (path.name, fh, "application/octet-stream"))],
                    data={
                        "name": path.stem,
                        "pack_type": "icon_pack_pdf",
                        "category": "Self Check",
                        "usage": "feature_icon",
                    },
                )
            pack = response.json() if response.status_code == 200 else {}
            pack_id = pack.get("asset_pack_id")
            if response.status_code == 200 and pack_id:
                _ok("asset pack upload")
                checks.append(True)
            else:
                checks.append(_fail("asset pack upload", f"HTTP {response.status_code}: {response.text[:200]}"))
                pack_id = ""
            if pack_id:
                parse_response = request("POST", f"/api/asset-packs/{pack_id}/parse")
                parsed_pack = parse_response.json() if parse_response.status_code == 200 else {}
                if parse_response.status_code == 200 and parsed_pack.get("parse_status") in {"parsed", "needs_review"}:
                    _ok("asset pack parse")
                    checks.append(True)
                else:
                    checks.append(_fail("asset pack parse", f"HTTP {parse_response.status_code}: {parse_response.text[:200]}"))

                items_response = request("GET", f"/api/asset-packs/{pack_id}/items")
                items = items_response.json() if items_response.status_code == 200 else []
                if items_response.status_code != 200:
                    checks.append(_fail("asset items quality", f"HTTP {items_response.status_code}: {items_response.text[:200]}"))
                else:
                    ok, detail = _asset_items_quality(items, pack_type=pack.get("pack_type") or "icon_pack_pdf")
                    if ok:
                        _ok(f"asset items quality ({detail})")
                        checks.append(True)
                    else:
                        checks.append(_fail("asset items quality", detail))

                    if args.confirm_items:
                        ok, confirmed_ids, detail = _confirm_items_flow(request, pack_id, items)
                        if ok:
                            _ok("batch confirm asset items")
                            _ok("confirmed items available")
                            checks.append(True)
                        else:
                            checks.append(_fail("batch confirm asset items", detail))

                        if args.run_explore_smoke and ok:
                            refreshed = request("GET", f"/api/asset-packs/{pack_id}/items").json()
                            unconfirmed = next(
                                (
                                    item.get("asset_item_id")
                                    for item in refreshed
                                    if item.get("status") in {"needs_review", "auto_detected", "disabled"}
                                ),
                                "",
                            )
                            if not unconfirmed:
                                checks.append(_fail("unconfirmed asset fixture", "no unconfirmed item left for exclusion check"))
                            else:
                                explore_ok, explore_detail = _run_explore_smoke(
                                    request,
                                    args.product_id,
                                    confirmed_ids,
                                    unconfirmed,
                                    knowledge_doc_ids=knowledge_doc_ids,
                                )
                                if explore_ok:
                                    checks.append(True)
                                else:
                                    checks.append(_fail("explore context smoke", explore_detail))
    if args.run_explore_smoke and knowledge_doc_ids and not args.pack_file:
        explore_ok, explore_detail = _run_explore_smoke(
            request,
            args.product_id,
            [],
            "",
            knowledge_doc_ids=knowledge_doc_ids,
        )
        if explore_ok:
            checks.append(True)
        else:
            checks.append(_fail("explore knowledge smoke", explore_detail))

    if all(checks):
        print("PASS asset workflow self-check")
        return 0
    print("FAIL asset workflow self-check")
    return 1


if __name__ == "__main__":
    sys.exit(main())
