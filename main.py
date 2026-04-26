"""
批量生图平台 - 主入口
以 PCT020 猫爬架为基准，运行完整 Pipeline
"""
import json
import sys
from pathlib import Path
from datetime import datetime

from PIL import Image
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config import OUTPUT_DIR, PRODUCTS_DIR, MODELS, PIPELINE
from pipeline.step1_extract import remove_background, create_main_image
from pipeline.step2_scene import generate_scene_descriptions
from pipeline.step3_compose import generate_scene_with_product
from pipeline.step4_enhance import add_lighting_and_shadow, generate_detail_crops
from pipeline.step5_text import translate_text, add_text_overlay
from pipeline.quality import check_quality

console = Console()


def load_product(product_id: str) -> dict:
    """加载产品配置"""
    path = PRODUCTS_DIR / f"{product_id.lower()}.json"
    if not path.exists():
        raise FileNotFoundError(f"产品配置不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_image(image: Image.Image, output_dir: Path, name: str) -> Path:
    """保存图片"""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.png"
    image.save(path, "PNG", quality=95)
    console.print(f"  💾 保存: {path}")
    return path


def run_pipeline(product_id: str, product_image_path: str):
    """
    运行完整 Pipeline

    Args:
        product_id: 产品ID (如 PCT020)
        product_image_path: 产品原图路径
    """
    # --- 初始化 ---
    console.print(Panel.fit(
        f"[bold white]批量生图 Pipeline[/]\n"
        f"产品: {product_id}\n"
        f"图片: {product_image_path}",
        border_style="cyan",
    ))

    product = load_product(product_id)
    product_image = Image.open(product_image_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = OUTPUT_DIR / f"{product_id}_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"\n📦 产品: {product['name']}")
    console.print(f"📁 输出: {output_dir}\n")

    results = {}

    # === Step 1: 白图修复 ===
    console.rule("[bold cyan]Step 1: 白图修复")
    extracted = remove_background(product_image)
    save_image(extracted["transparent"], output_dir, "01_transparent")
    save_image(extracted["white_bg"], output_dir, "01_white_bg")

    # 生成白底首图 (图1)
    main_white = create_main_image(extracted["white_bg"])
    save_image(main_white, output_dir, "img01_white_main")
    results["img01"] = main_white

    # === Step 2: 场景描述生成 ===
    console.rule("[bold cyan]Step 2: 场景描述生成")
    user_req = product.get("scene_requirements", {}).get("main_scene", "")
    scenes = generate_scene_descriptions(
        product_info=product,
        user_requirements=user_req,
        scene_count=3,
        product_image=product_image,
    )

    # 保存场景描述
    with open(output_dir / "scenes.json", "w", encoding="utf-8") as f:
        json.dump(scenes, f, ensure_ascii=False, indent=2)

    # === Step 3: 场景图合成 ===
    console.rule("[bold cyan]Step 3: 场景图合成")
    if scenes:
        # 场景首图 (图2): 使用第一个场景
        scene_en = scenes[0].get("description_en", "")
        scene_images = generate_scene_with_product(
            product_transparent=extracted["transparent"],
            scene_description=scene_en,
            model="gpt-image-2",
            candidates=2,
            scale_factor=0.75,  # 猫爬架要显大
        )
        for i, img in enumerate(scene_images):
            save_image(img, output_dir, f"img02_scene_main_v{i+1}")
        if scene_images:
            results["img02"] = scene_images[0]

        # 场景图 (图7): 亲子互动场景
        if len(scenes) > 1:
            lifestyle_en = scenes[1].get("description_en", "")
            lifestyle_images = generate_scene_with_product(
                product_transparent=extracted["transparent"],
                scene_description=lifestyle_en,
                model="gpt-image-2",
                candidates=1,
                scale_factor=0.65,
            )
            if lifestyle_images:
                save_image(lifestyle_images[0], output_dir, "img07_scene_lifestyle")
                results["img07"] = lifestyle_images[0]

    # === Step 4: 光影 + 细节 ===
    console.rule("[bold cyan]Step 4: 光影渲染 + 细节图")

    # 光影增强场景首图
    if "img02" in results:
        enhanced = add_lighting_and_shadow(results["img02"])
        save_image(enhanced, output_dir, "img02_scene_main_enhanced")
        results["img02"] = enhanced

    # 生成细节图 (图6)
    details = generate_detail_crops(
        extracted["white_bg"],
        product.get("selling_points", [])[:3],
    )
    for i, detail in enumerate(details):
        save_image(detail["crop"], output_dir, f"img06_detail_{i+1}")

    # === Step 5: 质量检测 ===
    console.rule("[bold cyan]质量检测")
    quality_results = {}
    for img_name, img in results.items():
        qr = check_quality(img)
        quality_results[img_name] = qr

    # === 输出汇总 ===
    console.rule("[bold green]Pipeline 完成")

    table = Table(title="生成结果汇总")
    table.add_column("图片", style="cyan")
    table.add_column("类型", style="white")
    table.add_column("质量", style="green")
    table.add_column("状态", style="bold")

    for img_name, qr in quality_results.items():
        score = qr.get("scores", {}).get("overall", 0)
        status = "✅" if qr.get("pass") else "❌"
        table.add_row(img_name, "场景/主图", f"{score:.2f}", status)

    console.print(table)
    console.print(f"\n📁 所有结果保存在: [bold]{output_dir}[/]")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        console.print("[bold red]用法:[/] python main.py <product_id> <image_path>")
        console.print("示例: python main.py pct020 ./products/pct020_white.png")
        sys.exit(1)

    product_id = sys.argv[1]
    image_path = sys.argv[2]
    run_pipeline(product_id, image_path)
