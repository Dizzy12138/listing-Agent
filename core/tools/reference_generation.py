from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from models.gpt_image import edit_image, generate_image
from pipeline.step3_compose import has_checkerboard_artifact


def reference_guided_scene_generation(
    original_photo: Image.Image,
    white_bg_reference: Image.Image,
    product_analysis: dict[str, Any],
    scene_prompt: str,
    model: str = "gpt-image-2",
    image_type: str = "scene_main",
) -> tuple[Image.Image, list[str], str]:
    """
    Generate a complete scene image using the original product photo as reference.

    white_bg_reference is intentionally not used as the rendered subject. It is
    only part of the reference contract and trace metadata.
    """
    del white_bg_reference
    structure_summary = _structure_summary(product_analysis)
    prompt = (
        f"{scene_prompt}\n\n"
        "Generate a complete commercial ecommerce scene image using the product in the reference photo as the SKU subject. "
        "Keep the cat tree recognizably the same SKU: light grey color, tall multi-level vertical tower, platforms, condo, hammock, sisal posts, ramp and wide base. "
        f"Product analysis reference: {structure_summary}. "
        "You may redraw lighting, edges, perspective, contact shadows and natural occlusion so the result does NOT look like a cutout or mechanical paste. "
        "The product must stand naturally on the floor, with no transparent checkerboard, no white background residue, no floating base and no hard pasted edges. "
        "Include cats, child/family interaction, furniture and room elements when requested by the scene prompt. "
        "Do not require pixel-level identity, but preserve SKU recognition and core structure."
    )
    try:
        results = edit_image(original_photo, prompt=prompt, model=model, size="1536x1024", quality="high")
        if results:
            image = results[0].convert("RGB")
            issues = _scene_output_issues(image)
            return image, issues, "reference_guided_edit"
    except Exception as exc:  # pragma: no cover - external service dependent
        edit_issue = f"reference_guided_edit_failed: {exc}"
    else:
        edit_issue = "reference_guided_edit_returned_no_image"

    try:
        results = generate_image(prompt=prompt, model=model, size="1536x1024", quality="high", n=1)
        if results:
            image = results[0].convert("RGB")
            issues = [edit_issue, "text_generation_no_image_reference"] + _scene_output_issues(image)
            return image, issues, "reference_guided_text_fallback"
    except Exception as exc:  # pragma: no cover - external service dependent
        gen_issue = f"reference_guided_text_failed: {exc}"
    else:
        gen_issue = "reference_guided_text_returned_no_image"

    return _local_reference_scene_card(original_photo, image_type), [edit_issue, gen_issue, "reference_based_fallback"], "reference_based_fallback"


def material_detail_enhancement(
    original_photo: Image.Image,
    crop_box: tuple[int, int, int, int],
    material_type: str,
    model: str = "gpt-image-2",
) -> tuple[Image.Image, list[str], str]:
    """Create a commercial material close-up from an original-photo crop."""
    crop = original_photo.convert("RGB").crop(crop_box)
    prompt = (
        f"Create a realistic ecommerce macro close-up of the cat tree {material_type}. "
        "Use this crop only as product reference. Preserve the real material, color and texture. "
        "Make it look like a sharp commercial detail photo with natural light, no white background screenshot, no annotation boxes and no checkerboard."
    )
    try:
        results = edit_image(crop, prompt=prompt, model=model, size="1024x1024", quality="high")
        if results:
            image = results[0].convert("RGB")
            issues = []
            if has_checkerboard_artifact(image):
                issues.append("material_detail_checkerboard_artifact")
            return image, issues, "material_detail_edit"
    except Exception as exc:  # pragma: no cover
        return _local_material_card(crop, material_type), [f"material_detail_edit_failed: {exc}", "reference_based_fallback"], "reference_based_fallback"

    return _local_material_card(crop, material_type), ["material_detail_edit_returned_no_image", "reference_based_fallback"], "reference_based_fallback"


def _structure_summary(product_analysis: dict[str, Any]) -> str:
    visible = product_analysis.get("visible_parts", {})
    counts = {
        "platforms": len(visible.get("platforms", [])),
        "sisal_posts": len(visible.get("sisal_posts", [])),
        "scratch_boards": len(visible.get("scratch_boards", [])),
        "hammocks": len(visible.get("hammock_area", [])),
        "condos": len(visible.get("condo_area", [])),
    }
    base = visible.get("base_area", {})
    return f"{counts}; base={base}; source_priority=SKU facts > ProductVisionAgent > heuristic fallback"


def _scene_output_issues(image: Image.Image) -> list[str]:
    issues: list[str] = []
    if has_checkerboard_artifact(image):
        issues.append("final_scene_checkerboard_artifact")
    return issues


def _local_reference_scene_card(original_photo: Image.Image, image_type: str) -> Image.Image:
    canvas = Image.new("RGB", (1536, 1024), "#eee4d6")
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 1536, 640), fill="#ead7c1")
    draw.rectangle((0, 640, 1536, 1024), fill="#d7bea3")
    draw.rounded_rectangle((90, 90, 1446, 934), radius=28, fill="#f8fafc", outline="#cbd5e1", width=3)
    ref = original_photo.convert("RGB")
    ref.thumbnail((880, 760), Image.Resampling.LANCZOS)
    canvas.paste(ref, ((1536 - ref.width) // 2, 150))
    draw.text((120, 805), f"{image_type}: reference-based fallback candidate", fill="#172033")
    draw.text((120, 845), "Model generation unavailable. This is not a commercial scene pass.", fill="#536173")
    return canvas


def _local_material_card(crop: Image.Image, material_type: str) -> Image.Image:
    canvas = Image.new("RGB", (1500, 1500), "#f8fafc")
    draw = ImageDraw.Draw(canvas)
    crop = crop.convert("RGB")
    crop.thumbnail((1280, 1120), Image.Resampling.LANCZOS)
    canvas.paste(crop, ((1500 - crop.width) // 2, 210))
    draw.rectangle((0, 0, 1500, 150), fill="#ffffff")
    draw.text((80, 52), f"Material detail candidate: {material_type}", fill="#172033")
    draw.text((80, 112), "Enhancement model unavailable; manual review required.", fill="#536173")
    return canvas
