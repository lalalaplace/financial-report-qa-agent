"""财报问数 Agent CLI Demo。

该脚本只提供展示入口，不修改 Agent 核心链路。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.graph import app


CONTEXT_KEYS = [
    "last_successful_query_plan",
    "pending_query_plan",
    "pending_clarification_type",
    "pending_empty_fields",
    "pending_candidates",
    "target_context",
]

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="财报问数 Agent CLI Demo。")
    parser.add_argument(
        "--trace",
        "--debug",
        action="store_true",
        dest="trace",
        help="显示 route、intent、公司、指标、SQL guard 等关键中间状态。",
    )
    return parser.parse_args()


def _first_text(values: list[Any]) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _display_intent(intent_type: Any) -> str:
    if not isinstance(intent_type, str):
        return "unknown"
    return intent_type


def _format_company_line(state: dict[str, Any]) -> str | None:
    companies = state.get("companies") or []
    if not companies:
        return None

    mentions = state.get("company_mentions") or []
    parts: list[str] = []
    for index, company in enumerate(companies):
        if not isinstance(company, dict):
            continue
        source = mentions[index] if index < len(mentions) else None
        source = source or company.get("stock_abbr") or company.get("company_name")
        target = company.get("company_name") or company.get("stock_abbr") or company.get("stock_code")
        if source and target:
            parts.append(f"{source} -> {target}")
    return "；".join(parts) if parts else None


def _format_metric_line(state: dict[str, Any]) -> str | None:
    metrics = state.get("metrics") or []
    if not metrics:
        return None

    mentions = state.get("metric_mentions") or []
    parts: list[str] = []
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            continue
        source = mentions[index] if index < len(mentions) else None
        source = source or metric.get("metric_name") or metric.get("metric_key")
        target = metric.get("metric_key") or metric.get("field") or metric.get("metric_name")
        if source and target:
            parts.append(f"{source} -> {target}")
    return "；".join(parts) if parts else None


def _iter_sql_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    if state.get("sql"):
        entries.append({"sql": state.get("sql"), "guard_passed": _sql_review_passed(state)})

    list_fields = [
        "compare_sqls",
        "compare_trend_sqls",
        "compare_yoy_sqls",
        "derived_compare_sqls",
        "derived_compare_trend_sqls",
        "derived_compare_yoy_sqls",
        "derived_trend_sqls",
        "derived_yoy_sqls",
    ]
    for field_name in list_fields:
        for entry in state.get(field_name) or []:
            if isinstance(entry, dict):
                entries.append(entry)

    for sql in state.get("yoy_sqls") or []:
        entries.append({"sql": sql})
    for sql in state.get("derived_sqls") or []:
        entries.append({"sql": sql})
    return entries


def _sql_review_passed(state: dict[str, Any]) -> bool | None:
    sql_review = state.get("sql_review")
    if isinstance(sql_review, dict) and "is_safe" in sql_review:
        return bool(sql_review.get("is_safe"))

    for entry in _iter_sql_entries_without_review(state):
        if "guard_passed" in entry:
            return bool(entry.get("guard_passed"))

    if state.get("sql_success") is True:
        return True
    if state.get("error_type") == "sql_guard_rejected":
        return False
    return None


def _iter_sql_entries_without_review(state: dict[str, Any]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for field_name in [
        "compare_sqls",
        "compare_trend_sqls",
        "compare_yoy_sqls",
        "derived_compare_sqls",
        "derived_compare_trend_sqls",
        "derived_compare_yoy_sqls",
        "derived_trend_sqls",
        "derived_yoy_sqls",
    ]:
        for entry in state.get(field_name) or []:
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _format_sql_guard_line(state: dict[str, Any]) -> str:
    passed = _sql_review_passed(state)
    if passed is True:
        return "passed"
    if passed is False:
        return "rejected"
    if state.get("need_clarification"):
        return "skipped"
    return "unknown"


def _format_sql_preview(state: dict[str, Any]) -> str | None:
    entry = next((item for item in _iter_sql_entries(state) if item.get("sql")), None)
    if not entry:
        return None
    sql = " ".join(str(entry["sql"]).split())
    if len(sql) > 180:
        return sql[:177] + "..."
    return sql


def print_trace(state: dict[str, Any]) -> None:
    route_type = state.get("route_type") or "new_query"
    print(f"[route] {route_type}")
    print(f"[intent] {_display_intent(state.get('intent_type'))}")

    company_line = _format_company_line(state)
    if company_line:
        print(f"[company] {company_line}")

    report_year = state.get("report_year")
    report_years = state.get("report_years") or []
    if report_year:
        print(f"[time] {report_year} {state.get('report_period') or ''}".strip())
    elif report_years:
        print(f"[time] {', '.join(str(year) for year in report_years)}")

    print(f"[sql_guard] {_format_sql_guard_line(state)}")

    sql_preview = _format_sql_preview(state)
    if sql_preview:
        print(f"[sql] {sql_preview}")

    error_type = state.get("error_type")
    if error_type:
        print(f"[error] {error_type}")

    answer = _first_text([
        state.get("final_answer"),
        state.get("clarification_question"),
    ]) or "本轮没有生成回答。"
    print(f"[answer] {answer}")


def update_context(context: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    next_context = dict(context)
    for key in CONTEXT_KEYS:
        if key in result:
            value = result.get(key)
            if value is None:
                next_context.pop(key, None)
            else:
                next_context[key] = value
    return next_context


def run_cli(trace: bool) -> int:
    print("财报问数 Agent Demo")
    print("输入 exit 退出")
    if trace:
        print("当前模式：Debug / Trace")
    else:
        print("当前模式：普通")
    print()

    context: dict[str, Any] = {}
    while True:
        try:
            question = input("用户：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if question.lower() in {"exit", "quit", "q"}:
            return 0
        if not question:
            continue

        state = {"user_question": question, **context}
        try:
            result = app.invoke(state)
        except Exception as exc:
            print(f"Agent：运行失败：{exc}")
            continue

        if trace:
            print_trace(result)
        else:
            answer = _first_text([
                result.get("final_answer"),
                result.get("clarification_question"),
            ]) or "本轮没有生成回答。"
            print(f"Agent：{answer}")

        context = update_context(context, result)
        print()


def main() -> int:
    args = parse_args()
    return run_cli(trace=args.trace)


if __name__ == "__main__":
    raise SystemExit(main())
