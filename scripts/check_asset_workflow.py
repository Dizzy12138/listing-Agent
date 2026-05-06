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
            if response.status_code == 200 and response.json().get("asset_pack_id"):
                _ok("asset pack upload")
                checks.append(True)
            else:
                checks.append(_fail("asset pack upload", f"HTTP {response.status_code}: {response.text[:200]}"))

    if all(checks):
        print("PASS asset workflow self-check")
        return 0
    print("FAIL asset workflow self-check")
    return 1


if __name__ == "__main__":
    sys.exit(main())
