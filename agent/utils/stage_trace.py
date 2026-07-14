"""正式主图的节点级与 LLM 调用级追踪。"""

from __future__ import annotations

from contextvars import ContextVar
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Callable


_active_events: ContextVar[list[dict[str, Any]] | None] = ContextVar("active_stage_trace_events", default=None)


def merge_stage_traces(left: list[dict[str, Any]] | None, right: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """合并并行节点的追踪，保留共同前缀且避免重复记录。"""
    merged: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any, Any]] = set()
    for trace in [*(left or []), *(right or [])]:
        key = (trace.get("stage"), trace.get("stage_started_at") or trace.get("started_at"), trace.get("attempt"))
        if key not in seen:
            seen.add(key)
            merged.append(trace)
    return merged


def record_llm_event(event: dict[str, Any]) -> None:
    events = _active_events.get()
    if events is not None:
        events.append(event)


def traced_node(stage: str, node: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """为 LangGraph 节点追加稳定的开始、结束和异常追踪记录。"""
    def wrapped(state: dict[str, Any]) -> dict[str, Any]:
        started_at = datetime.now(timezone.utc).isoformat()
        started = perf_counter()
        events: list[dict[str, Any]] = []
        token = _active_events.set(events)
        try:
            result = node(state)
            error = result.get("error") if isinstance(result, dict) and isinstance(result.get("error"), dict) else {}
            error_code = error.get("error_type")
            event_timeout = next((event for event in reversed(events) if event.get("timeout_type")), None)
            if event_timeout:
                status = "timeout"
                error_code = error_code or event_timeout.get("error_code")
            else:
                status = "timeout" if isinstance(error_code, str) and error_code.endswith("_TIMEOUT") else "failed" if error_code else "completed"
        except Exception as exc:
            status = "failed"
            error_code = getattr(exc, "error_code", type(exc).__name__)
            raise
        finally:
            _active_events.reset(token)
        trace = {
            "stage": stage,
            "stage_started_at": started_at,
            "started_at": started_at,
            "stage_completed_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_ms": round((perf_counter() - started) * 1000, 3),
            "status": status,
            "attempt": len(state.get("stage_traces") or []) + 1,
            "finish_reason": next((event.get("finish_reason") for event in reversed(events) if event.get("finish_reason")), None),
            "error_code": error_code,
            "timeout_scope": next((event.get("timeout_type") for event in reversed(events) if event.get("timeout_type")), None),
            "llm_events": events,
        }
        return {**(result or {}), "stage_traces": [*(state.get("stage_traces") or []), trace]}

    return wrapped


__all__ = ["merge_stage_traces", "record_llm_event", "traced_node"]
