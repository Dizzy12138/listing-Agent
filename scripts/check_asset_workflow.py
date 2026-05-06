#!/usr/bin/env python3
"""Self-check for knowledge docs, asset packs, and health routes.

By default this uses FastAPI's in-process TestClient, so it does not require a
running server. Pass --base-url http://host:port to check a live deployment.
"""
from __future__ import annotations

import argparse
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Check listing-Agent asset workflow APIs.")
    parser.add_argument("--base-url", default="", help="Optional live server base URL.")
    parser.add_argument("--doc-file", default="", help="Optional docx/pdf/txt/md file to upload.")
    parser.add_argument("--pack-file", default="", help="Optional pdf/zip/image file to upload.")
    args = parser.parse_args()

    def request(method: str, path: str, **kwargs):
        if args.base_url:
            return _http_request(args.base_url, method, path, **kwargs)
        return _client_request(method, path, **kwargs)

    checks: list[bool] = []
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

    if all(checks):
        print("PASS asset workflow self-check")
        return 0
    print("FAIL asset workflow self-check")
    return 1


if __name__ == "__main__":
    sys.exit(main())
