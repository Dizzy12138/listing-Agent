from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from core.schemas.creative import LayeredAsset
from pipeline.step4_enhance import _load_font


class LayerRenderer:
    def render(self, asset: LayeredAsset, output_path: Path) -> Path:
        width = int(asset.canvas.get("width", 1500))
        height = int(asset.canvas.get("height", 1500))
        canvas = Image.new("RGBA", (width, height), (255, 255, 255, 255))
        draw = ImageDraw.Draw(canvas)

        for layer in asset.layers:
            if layer.layer_type == "image" and layer.source_path:
                self._draw_image(canvas, layer)
            elif layer.layer_type == "text" and layer.text:
                self._draw_text(draw, layer)
            elif layer.layer_type in {"shape", "dimension"}:
                self._draw_shape(draw, layer)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, "PNG")
        return output_path

    def _draw_image(self, canvas: Image.Image, layer):
        path = Path(layer.source_path or "")
        if not path.exists():
            return
        image = Image.open(path).convert("RGBA")
        target_w = int(layer.width or image.width)
        target_h = int(layer.height or image.height)
        image.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
        if layer.opacity < 1:
            alpha = image.getchannel("A").point(lambda p: int(p * layer.opacity))
            image.putalpha(alpha)
        canvas.alpha_composite(image, (int(layer.x), int(layer.y)))

    def _draw_text(self, draw: ImageDraw.ImageDraw, layer):
        style = layer.style
        font_size = int(style.get("font_size", 42))
        font = _load_font(font_size, bold=bool(style.get("bold", False)))
        fill = style.get("fill", "#172033")
        draw.text((layer.x, layer.y), layer.text or "", font=font, fill=fill)

    def _draw_shape(self, draw: ImageDraw.ImageDraw, layer):
        style = layer.style
        fill = style.get("fill")
        outline = style.get("outline", "#2563eb")
        width = int(style.get("width", 4))
        x1 = int(layer.x)
        y1 = int(layer.y)
        x2 = int(layer.x + (layer.width or 0))
        y2 = int(layer.y + (layer.height or 0))
        shape = style.get("shape", "rect")
        if shape == "line":
            points = layer.data.get("points", [(x1, y1), (x2, y2)])
            draw.line([tuple(point) for point in points], fill=outline, width=width)
        elif shape == "ellipse":
            draw.ellipse((x1, y1, x2, y2), fill=fill, outline=outline, width=width)
        else:
            radius = int(style.get("radius", 0))
            if radius:
                draw.rounded_rectangle((x1, y1, x2, y2), radius=radius, fill=fill, outline=outline, width=width)
            else:
                draw.rectangle((x1, y1, x2, y2), fill=fill, outline=outline, width=width)
