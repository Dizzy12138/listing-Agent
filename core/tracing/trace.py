from __future__ import annotations

from datetime import datetime
from time import perf_counter
from typing import Any


class TraceRecorder:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.records: list[dict[str, Any]] = []

    def add(
        self,
        step: str,
        status: str,
        input: dict[str, Any] | None = None,
        output_artifact: str | None = None,
        model: str | None = None,
        cost: float | None = None,
        duration_ms: int | None = None,
        issues: list[str] | None = None,
    ) -> dict[str, Any]:
        record = {
            "run_id": self.run_id,
            "step": step,
            "status": status,
            "input": input or {},
            "model": model,
            "output_artifact": output_artifact,
            "cost": cost,
            "duration_ms": duration_ms,
            "issues": issues or [],
            "created_at": datetime.now().isoformat(timespec="seconds"),
        }
        self.records.append(record)
        return record

    def timed(self, step: str):
        return _TraceTimer(self, step)


class _TraceTimer:
    def __init__(self, recorder: TraceRecorder, step: str):
        self.recorder = recorder
        self.step = step
        self.start = 0.0

    def __enter__(self):
        self.start = perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        duration_ms = int((perf_counter() - self.start) * 1000)
        self.recorder.add(
            step=self.step,
            status="error" if exc else "success",
            duration_ms=duration_ms,
            issues=[str(exc)] if exc else [],
        )
        return False
