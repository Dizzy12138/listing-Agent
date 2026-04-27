"""
BatchOrchestratorAgent — controls explore vs batch mode.

explore mode: 3 core types × 4 candidates = 12 images + QA
batch mode: full 9-image plan, requires explore recommendation first
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml
from rich.console import Console

console = Console()

CONFIG_PATH = Path(__file__).parent.parent.parent / "configs" / "generation_modes.yaml"


def load_mode_config(mode: str) -> dict:
    """Load generation mode configuration."""
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, "r") as f:
            all_configs = yaml.safe_load(f)
        return all_configs.get(mode, {})
    # Hardcoded fallback
    if mode == "explore":
        return {
            "enabled_image_types": ["hero_scene", "lifestyle_scene", "material_detail"],
            "candidates_per_type": 4,
            "require_visual_qa": True,
            "allow_text_only_candidate": True,
            "allow_formal_output": False,
        }
    elif mode == "batch":
        return {
            "enabled_image_types": [
                "white_main", "hero_scene", "resting_areas_info", "scratching_demo",
                "stability_demo", "material_detail", "lifestyle_scene",
                "climbing_path_info", "size_compare",
            ],
            "require_explore_recommendation": True,
            "allow_formal_output": True,
        }
    return {}


class BatchOrchestratorAgent:
    """Controls generation mode and gating logic."""

    def __init__(self, mode: str = "explore"):
        self.mode = mode
        self.config = load_mode_config(mode)

    def can_proceed(self, output_dir: Path, force: bool = False) -> tuple[bool, str]:
        """Check if current mode can proceed."""
        if self.mode == "explore":
            return True, "explore mode always proceeds"

        if self.mode == "batch":
            if force:
                return True, "batch forced with --force-batch"

            # Check for explore recommendation
            explore_dirs = sorted(output_dir.parent.glob(f"{output_dir.name.split('_')[0]}_*/explore/"), reverse=True)
            for explore_dir in explore_dirs:
                qa_path = explore_dir / "qa_summary.json"
                if qa_path.exists():
                    with open(qa_path, "r") as f:
                        summary = json.load(f)
                    readiness = summary.get("overall_readiness", "not_ready")
                    if readiness in ("ready_for_batch", "needs_review"):
                        return True, f"explore recommendation found: {readiness}"

            return False, "no explore recommendation found — run explore mode first or use --force-batch"

        return False, f"unknown mode: {self.mode}"

    @property
    def enabled_image_types(self) -> list[str]:
        return self.config.get("enabled_image_types", [])

    @property
    def candidates_per_type(self) -> int:
        return self.config.get("candidates_per_type", 4)

    @property
    def allow_formal_output(self) -> bool:
        return self.config.get("allow_formal_output", False)
