from core.tracing.trace import TraceRecorder


def test_trace_record_contains_run_metadata():
    trace = TraceRecorder("run_123")

    record = trace.add(
        step="workflow.node",
        status="success",
        input={"sku_id": "P1"},
        model="test-model",
    )

    assert record["run_id"] == "run_123"
    assert record["step"] == "workflow.node"
    assert record["input"] == {"sku_id": "P1"}
    assert record["model"] == "test-model"
    assert record["issues"] == []
    assert trace.records == [record]
