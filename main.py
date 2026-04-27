"""
CLI entry for the SKU visual Agent platform.

Modes:
  --mode explore  (default) Generate multi-candidate images for 3 core types
  --mode batch    Generate full 9-image set (requires explore recommendation)
  --force-batch   Skip explore requirement check for batch mode
"""
import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def run_explore(product_id: str, product_image_path: str):
    """Explore mode: 3 types × 4 candidates → QA scoring → recommendations."""
    from core.services.explore_generation_service import ExploreGenerationService

    console.print(Panel.fit(
        f"[bold white]SKU Visual Agent — Explore Mode[/]\n"
        f"SKU: {product_id}\n"
        f"Image: {product_image_path}\n"
        f"Mode: [bold yellow]explore[/] (multi-candidate, no formal output)",
        border_style="cyan",
    ))

    def progress(message: str, value: int):
        console.print(f"[cyan]{value:>3}%[/] {message}")

    result = ExploreGenerationService().execute_explore(
        product_id=product_id,
        product_image_path=product_image_path,
        progress=progress,
    )

    # Summary table
    table = Table(title="Explore 候选结果")
    table.add_column("Image Type", style="cyan")
    table.add_column("Candidates", justify="center")
    table.add_column("Recommended", style="green")
    table.add_column("QA Source")

    qa = result.get("qa_summary", {})
    recs = qa.get("recommendations", {})
    for type_key, candidates in result.get("candidates", {}).items():
        success = sum(1 for c in candidates if c.get("status") != "failed")
        rec = recs.get(type_key, "-")
        table.add_row(type_key, str(success), rec, qa.get("visual_qa_source", "?"))

    console.print(table)
    console.print(f"\n📁 输出: [bold]{result.get('explore_dir', '')}[/]")
    console.print(f"📊 就绪度: [bold]{qa.get('overall_readiness', '?')}[/]")
    return result


def run_batch(product_id: str, product_image_path: str, force: bool = False):
    """Batch mode: full 9-image generation (requires explore recommendation)."""
    from core.agents.batch_orchestrator_agent import BatchOrchestratorAgent
    from core.services.generation_service import GenerationService
    from config import OUTPUT_DIR
    from pathlib import Path

    orchestrator = BatchOrchestratorAgent(mode="batch")
    run_dir = OUTPUT_DIR / product_id
    can_proceed, reason = orchestrator.can_proceed(run_dir, force=force)

    if not can_proceed:
        console.print(f"[bold red]❌ Batch 模式被阻止:[/] {reason}")
        console.print("[yellow]请先运行 explore 模式: python main.py <sku> <image> --mode explore[/]")
        sys.exit(1)

    console.print(Panel.fit(
        f"[bold white]SKU Visual Agent — Batch Mode[/]\n"
        f"SKU: {product_id}\n"
        f"Image: {product_image_path}\n"
        f"Mode: [bold green]batch[/] (formal 9-image output)\n"
        f"Gate: {reason}",
        border_style="green",
    ))

    def progress(message: str, value: int):
        console.print(f"[cyan]{value:>3}%[/] {message}")

    result = GenerationService().execute_run(
        product_id=product_id,
        product_image_path=product_image_path,
        progress=progress,
    )

    table = Table(title="ImageJob 执行结果")
    table.add_column("Index", style="cyan")
    table.add_column("Type")
    table.add_column("Workflow")
    table.add_column("View")
    table.add_column("Artifacts", style="green")

    artifacts_by_job = {}
    for artifact in result["artifacts"]:
        job_id = artifact.get("job_id")
        if job_id:
            artifacts_by_job.setdefault(job_id, []).append(artifact["name"])

    for job in result["jobs"]:
        table.add_row(
            str(job["image_index"]),
            job["image_type"],
            job["workflow_key"],
            job.get("view_type") or "-",
            ", ".join(artifacts_by_job.get(job["job_id"], [])) or "-",
        )

    console.print(table)
    console.print(f"\n📁 输出目录: [bold]{result['output_dir']}[/]")
    console.print(f"🧭 Trace: [bold]{result['output_dir']}/trace.json[/]")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SKU Visual Agent Platform")
    parser.add_argument("product_id", help="SKU product ID (e.g. pct020)")
    parser.add_argument("image_path", help="Path to product image")
    parser.add_argument("--mode", choices=["explore", "batch"], default="explore",
                        help="Generation mode: explore (default) or batch")
    parser.add_argument("--force-batch", action="store_true",
                        help="Force batch mode without explore recommendation")

    args = parser.parse_args()

    if args.mode == "explore":
        run_explore(args.product_id, args.image_path)
    elif args.mode == "batch":
        run_batch(args.product_id, args.image_path, force=args.force_batch)
