"""
VisualQAAgent — multi-dimensional quality scoring for candidates.

Scoring dimensions:
- commercial_score: looks like real commercial photography
- sku_consistency_score: still recognizable as the same SKU
- scene_score: scene realism, lighting, actors present
- defect_score: no artifacts, no floating, no cutout edges
- selling_point_score: conveys the intended selling point
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from PIL import Image
from rich.console import Console

from core.schemas.candidate import QAScore, QASummary
from core.schemas.creative_brief import CreativeBrief, SKUBrief
from models.llm import chat

console = Console()

VLM_QA_PROMPT = """You are a senior e-commerce image quality reviewer.

Product Identity:
- Type: {product_type}
- Core features: {core_identity}
- Must show: {must_show}

Image Purpose: {image_type}
Visual Goal: {visual_goal}

Evaluate this image on these dimensions (0-100 each):

1. commercial_score: Does it look like a real premium e-commerce product photo?
2. sku_consistency_score: Is this clearly the same product described above?
3. scene_score: Is the scene realistic, well-lit, with requested actors/elements?
4. defect_score: Are there NO defects? (100=perfect, 0=severe defects like checkerboard, floating, cutout edges)
5. selling_point_score: Does it effectively convey the visual goal?

Also provide:
- issues: list of specific problems found
- decision: one of "recommended" / "candidate" / "needs_review" / "reject"

Decision criteria:
- recommended: all scores >= 70, no critical issues
- candidate: most scores >= 50, minor issues only
- needs_review: some scores < 50 or moderate issues
- reject: any score < 30 or critical defects

Return JSON:
{{
  "commercial_score": 0-100,
  "sku_consistency_score": 0-100,
  "scene_score": 0-100,
  "defect_score": 0-100,
  "selling_point_score": 0-100,
  "issues": [],
  "decision": "recommended/candidate/needs_review/reject"
}}

Output ONLY the JSON, no markdown code blocks."""


class VisualQAAgent:
    """Multi-dimensional quality assessment for generated candidates."""

    def __init__(self, model: str | None = None):
        import config
        self.model = model or config.MODELS.get("quality", "gpt-5.2")

    def evaluate_candidate(
        self,
        image: Image.Image,
        brief: CreativeBrief,
        sku_brief: SKUBrief,
        candidate_id: str,
    ) -> QAScore:
        """Evaluate a single candidate image."""
        console.print(f"    [QA] {candidate_id}")

        try:
            result = self._vlm_evaluate(image, brief, sku_brief)
            if result:
                score = QAScore(
                    candidate_id=candidate_id,
                    commercial_score=result.get("commercial_score", 0),
                    sku_consistency_score=result.get("sku_consistency_score", 0),
                    scene_score=result.get("scene_score", 0),
                    defect_score=result.get("defect_score", 0),
                    selling_point_score=result.get("selling_point_score", 0),
                    issues=result.get("issues", []),
                    decision=result.get("decision", "needs_review"),
                    visual_qa_source="vlm",
                )
                console.print(f"      VLM: {score.decision} (commercial={score.commercial_score}, "
                              f"consistency={score.sku_consistency_score}, defect={score.defect_score})")
                return score
        except Exception as exc:
            console.print(f"      ⚠️ VLM QA failed: {exc}", style="yellow")

        return self._fallback_evaluate(candidate_id, brief)

    def evaluate_batch(
        self,
        candidates: list[dict],  # [{candidate_id, image, brief}]
        sku_brief: SKUBrief,
    ) -> list[QAScore]:
        """Evaluate multiple candidates."""
        scores = []
        for c in candidates:
            img = c.get("image")
            if img is None and c.get("image_path"):
                try:
                    img = Image.open(c["image_path"])
                except OSError:
                    scores.append(QAScore(
                        candidate_id=c["candidate_id"],
                        decision="reject",
                        issues=["cannot open image file"],
                    ))
                    continue

            if img is None:
                scores.append(QAScore(
                    candidate_id=c["candidate_id"],
                    decision="reject",
                    issues=["no image available"],
                ))
                continue

            score = self.evaluate_candidate(img, c["brief"], sku_brief, c["candidate_id"])
            scores.append(score)
        return scores

    def build_summary(
        self,
        sku_id: str,
        run_id: str,
        all_scores: dict[str, list[QAScore]],
    ) -> QASummary:
        """Build QA summary with recommendations per image type."""
        recommendations = {}
        has_vlm = False

        for image_type, scores in all_scores.items():
            # Sort by weighted composite score
            scored = []
            for s in scores:
                composite = (
                    s.commercial_score * 0.3
                    + s.sku_consistency_score * 0.25
                    + s.scene_score * 0.2
                    + s.defect_score * 0.15
                    + s.selling_point_score * 0.1
                )
                scored.append((composite, s))
                if s.visual_qa_source == "vlm":
                    has_vlm = True

            scored.sort(key=lambda x: x[0], reverse=True)

            # Recommend best if it's "recommended" or "candidate". In no-VLM
            # environments, still surface the least-risky candidate for manual
            # review so the exploration loop is not a dead end.
            for composite, s in scored:
                if s.decision in ("recommended", "candidate"):
                    recommendations[image_type] = s.candidate_id
                    break
            if image_type not in recommendations:
                reviewable = [s for _, s in scored if s.decision == "needs_review"]
                if reviewable:
                    recommendations[image_type] = reviewable[0].candidate_id

        # Overall readiness
        qa_source = "vlm" if has_vlm else "manual_required"
        if recommendations and len(recommendations) >= len(all_scores):
            readiness = "ready_for_batch" if qa_source == "vlm" else "needs_review"
        elif recommendations:
            readiness = "needs_review"
        else:
            readiness = "not_ready"

        return QASummary(
            sku_id=sku_id,
            run_id=run_id,
            image_types=all_scores,
            recommendations=recommendations,
            visual_qa_source=qa_source,
            overall_readiness=readiness,
        )

    def _vlm_evaluate(self, image: Image.Image, brief: CreativeBrief, sku_brief: SKUBrief) -> dict | None:
        prompt = VLM_QA_PROMPT.format(
            product_type=sku_brief.product_type,
            core_identity=", ".join(sku_brief.core_identity[:6]),
            must_show=", ".join(sku_brief.must_show[:5]),
            image_type=brief.image_type,
            visual_goal=brief.visual_goal,
        )
        response = chat(prompt=prompt, model=self.model, image=image, response_format="json")
        return self._parse_json(response)

    def _fallback_evaluate(self, candidate_id: str, brief: CreativeBrief) -> QAScore:
        """Without VLM, assign default scores — never auto-recommend."""
        base = 50 if brief.image_type == "material_detail" else 45

        return QAScore(
            candidate_id=candidate_id,
            commercial_score=base,
            sku_consistency_score=base,
            scene_score=base,
            defect_score=60,
            selling_point_score=base,
            issues=["visual_qa_source=manual_required: no VLM available for automated review"],
            decision="needs_review",
            visual_qa_source="manual_required",
        )

    def _parse_json(self, text: str) -> dict | None:
        text = text.strip()
        match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            start = text.find('{')
            end = text.rfind('}')
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    pass
        return None
