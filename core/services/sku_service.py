from __future__ import annotations

import json
from pathlib import Path

from core.schemas.sku import SKU


class SKUService:
    def __init__(self, products_dir: Path):
        self.products_dir = products_dir

    def load(self, product_id: str) -> SKU:
        path = self.products_dir / f"{product_id.lower()}.json"
        if not path.exists():
            raise FileNotFoundError(f"SKU config not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return SKU.model_validate(json.load(f))
