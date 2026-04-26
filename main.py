"""
CLI entry for the SKU visual Agent platform.

The CLI is intentionally thin. It validates SKU config, builds ImageJobs from
SKU.image_plan, then delegates execution to GenerationService.
"""
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core.services.generation_service import GenerationService

console = Console()


def run_pipeline(product_id: str, product_image_path: str):
    console.print(Panel.fit(
        f"[bold white]SKU Visual Agent Run[/]\n"
        f"SKU: {product_id}\n"
        f"Image: {product_image_path}",
        border_style="cyan",
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
    if len(sys.argv) < 3:
        console.print("[bold red]用法:[/] python main.py <product_id> <image_path>")
        console.print("示例: python main.py pct020 ./products/images/pct020.jpeg")
        sys.exit(1)

    run_pipeline(sys.argv[1], sys.argv[2])
