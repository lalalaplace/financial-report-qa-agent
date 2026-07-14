from agent.utils.stage_trace import traced_node


def test_traced_node_records_stage_timing_and_status() -> None:
    node = traced_node("sql_guard", lambda _state: {"sql_guard_status": "passed"})

    result = node({})

    trace = result["stage_traces"][0]
    assert trace["stage"] == "sql_guard"
    assert trace["status"] == "completed"
    assert trace["duration_ms"] >= 0
