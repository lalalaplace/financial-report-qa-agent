"""Agent 运行日志记录。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOG_PATH = PROJECT_ROOT / "logs" / "agent_runs.jsonl"


def _metric_keys(metrics: list[dict[str, Any]]) -> list[str]:
    """提取指标主键，便于后续评测统计。"""
    return [metric["metric_key"] for metric in metrics if metric.get("metric_key")]


def _company_names(companies: list[dict[str, Any]]) -> list[str]:
    """提取公司简称，简称缺失时退回公司全称。"""
    names: list[str] = []
    for company in companies:
        name = company.get("stock_abbr") or company.get("company_name")
        if name:
            names.append(name)
    return names


def _compact_query_result(result: dict[str, Any]) -> dict[str, Any]:
    """压缩执行结果，日志中保留定位问题所需字段。"""
    return {
        "sql_id": result.get("sql_id"),
        "table": result.get("table"),
        "metric_key": result.get("metric_key"),
        "metric_keys": result.get("metric_keys"),
        "years": result.get("years"),
        "guard_passed": result.get("guard_passed"),
        "success": result.get("success", result.get("sql_success")),
        "row_count": result.get("row_count"),
        "error": result.get("error"),
    }


def _collect_sqls(state: dict[str, Any]) -> list[dict[str, Any]]:
    """汇总所有 SQL 字段，形成统一可观测列表。"""
    sqls: list[dict[str, Any]] = []
    if state.get("sql"):
        sqls.append({"sql_id": "single_sql", "sql": state.get("sql")})

    for index, sql in enumerate(state.get("yoy_sqls") or [], start=1):
        sqls.append({"sql_id": f"yoy_sql_{index:03d}", "sql": sql})
    for index, sql in enumerate(state.get("derived_sqls") or [], start=1):
        sqls.append({"sql_id": f"derived_sql_{index:03d}", "sql": sql})

    sql_list_fields = [
        "compare_sqls",
        "compare_trend_sqls",
        "compare_yoy_sqls",
        "derived_compare_sqls",
        "derived_compare_trend_sqls",
        "derived_compare_yoy_sqls",
        "derived_trend_sqls",
        "derived_yoy_sqls",
    ]
    for field_name in sql_list_fields:
        for index, entry in enumerate(state.get(field_name) or [], start=1):
            if isinstance(entry, dict):
                compact = {
                    "sql_id": entry.get("sql_id") or f"{field_name}_{index:03d}",
                    "source": field_name,
                    "table": entry.get("table"),
                    "metric_key": entry.get("metric_key"),
                    "metric_keys": entry.get("metric_keys"),
                    "years": entry.get("years"),
                    "guard_passed": entry.get("guard_passed"),
                    "sql": entry.get("sql"),
                }
                sqls.append(compact)
    return sqls


def _collect_query_results(state: dict[str, Any]) -> list[dict[str, Any]]:
    """汇总所有执行结果，形成统一可观测列表。"""
    query_results: list[dict[str, Any]] = []
    if state.get("query_result") is not None:
        query_results.append({
            "source": "query_result",
            **_compact_query_result(state.get("query_result") or {}),
        })

    list_result_fields = [
        "derived_query_results",
        "compare_query_results",
        "compare_trend_query_results",
        "compare_yoy_query_results",
    ]
    for field_name in list_result_fields:
        for result in state.get(field_name) or []:
            if isinstance(result, dict):
                query_results.append({
                    "source": field_name,
                    **_compact_query_result(result),
                })

    dict_result_fields = [
        "derived_trend_query_results",
        "derived_yoy_query_results",
        "derived_compare_query_results",
        "derived_compare_trend_query_results",
        "derived_compare_yoy_query_results",
    ]
    for field_name in dict_result_fields:
        for metric_key, result in (state.get(field_name) or {}).items():
            if isinstance(result, dict):
                query_results.append({
                    "source": field_name,
                    "metric_key": metric_key,
                    **_compact_query_result(result),
                })
    return query_results


def _collect_analysis_result(state: dict[str, Any]) -> dict[str, Any]:
    """汇总分析结果入口，保留原 analysis_result 及 compare 专项结果。"""
    fields = [
        "analysis_result",
        "yoy_result",
        "derived_result",
        "derived_trend_result",
        "derived_yoy_result",
        "compare_result",
        "derived_compare_result",
        "compare_trend_result",
        "derived_compare_trend_result",
        "compare_yoy_result",
        "derived_compare_yoy_result",
    ]
    return {
        field_name: state.get(field_name)
        for field_name in fields
        if state.get(field_name) is not None
    }


def _primary_metric_type(metrics: list[dict[str, Any]]) -> str | None:
    """返回主指标类型；多指标时用 mixed 标识。"""
    metric_types = sorted({metric.get("metric_type", "base") for metric in metrics})
    if not metric_types:
        return None
    if len(metric_types) == 1:
        return metric_types[0]
    return "mixed"


def _analysis_result_summary(state: dict[str, Any]) -> dict[str, Any] | None:
    """提取轻量分析摘要，避免日志消费者反复解析完整 analysis_result。"""
    analysis = state.get("analysis_result")
    if not isinstance(analysis, dict):
        return None

    summary: dict[str, Any] = {
        "analysis_type": analysis.get("analysis_type"),
        "row_count": analysis.get("row_count"),
        "is_empty": analysis.get("is_empty"),
        "result_summary": analysis.get("result_summary"),
    }
    rows = analysis.get("rows")
    if isinstance(rows, list) and rows:
        first = rows[0]
        if isinstance(first, dict):
            summary["first_row"] = {
                key: first.get(key)
                for key in (
                    "rank",
                    "company_name",
                    "metric_value",
                    "display_value",
                    "yoy_rate",
                    "display_yoy_rate",
                    "growth_rate",
                    "display_growth_rate",
                )
                if key in first
            }
    for key in ("rank_no", "total_count", "metric_value", "display_value"):
        if key in analysis:
            summary[key] = analysis.get(key)
    return summary


def _normalize_error_type(error_type: Any) -> Any:
    """日志层统一 error_type 命名，兼容旧节点返回值。"""
    mapping = {
        "sql_guard_failed": "sql_guard_rejected",
        "sql_execution_error": "sql_execution_failed",
        "derived_yoy_ranking_not_supported_v053": "unsupported_metric_type",
        "derived_trend_ranking_not_supported_v054": "unsupported_metric_type",
        "unsupported_rank_position_metric_type": "unsupported_metric_type",
        "scoped_company_ranking_not_supported": "multiple_companies_not_supported",
        "scoped_company_yoy_ranking_not_supported": "multiple_companies_not_supported",
        "scoped_company_trend_ranking_not_supported": "multiple_companies_not_supported",
        "unsupported_yoy_ranking_time_mode": "unsupported_time_mode",
        "invalid_yoy_ranking_params": "invalid_limit",
        "invalid_trend_ranking_params": "invalid_limit",
        "rank_position_param_error": "missing_company",
    }
    return mapping.get(error_type, error_type)


def _ranking_mode(intent_type: str | None) -> str | None:
    """ranking 系列 intent 到日志 ranking_mode 的稳定映射。"""
    return {
        "ranking_query": "value_ranking",
        "yoy_ranking_query": "yoy_rate_ranking",
        "trend_ranking_query": "growth_rate_ranking",
        "rank_position_query": "rank_position",
    }.get(intent_type or "")


def _ranking_log_fields(state: dict[str, Any]) -> dict[str, Any]:
    """构造 ranking 系列专用日志字段。"""
    intent_type = state.get("intent_type")
    ranking_mode = _ranking_mode(intent_type)
    if ranking_mode is None:
        return {}

    analysis = state.get("analysis_result") if isinstance(state.get("analysis_result"), dict) else {}
    report_year = state.get("report_year") or analysis.get("report_year")
    fields: dict[str, Any] = {
        "ranking_mode": ranking_mode,
        "rank_direction": state.get("rank_direction") or analysis.get("rank_direction"),
        "limit": state.get("limit") or analysis.get("limit"),
        "change_metric": state.get("change_metric") or analysis.get("change_metric"),
    }

    if intent_type == "ranking_query":
        fields["metric_value_field"] = "metric_value"
    elif intent_type == "yoy_ranking_query":
        fields["current_year"] = report_year
        fields["previous_year"] = analysis.get("previous_year") or (
            report_year - 1 if isinstance(report_year, int) else None
        )
        fields["change_metric"] = "yoy_rate"
    elif intent_type == "trend_ranking_query":
        fields["start_year"] = state.get("start_year") or analysis.get("start_year")
        fields["end_year"] = state.get("end_year") or analysis.get("end_year")
        fields["change_metric"] = "growth_rate"
    elif intent_type == "rank_position_query":
        fields["rank_no"] = analysis.get("rank_no")
        fields["total_count"] = analysis.get("total_count")

    return fields


def _infer_failure_stage(state: dict[str, Any]) -> str | None:
    """根据状态和错误类型推断失败阶段，便于日志排障。"""
    error_type = _normalize_error_type(state.get("error_type"))
    if error_type == "planner_parse_error":
        return "planner"
    if error_type == "schema_validation_error":
        return "planner"
    if error_type == "clarify_company":
        return "company_normalization"
    if error_type == "clarify_metric":
        return "metric_mapping"
    if error_type in {"clarify_year", "clarify_compare_reference"}:
        return "slot_check"
    if error_type and str(error_type).startswith("unsupported_"):
        return "route"
    if error_type == "route_error":
        return "route"
    if error_type == "sql_guard_rejected":
        return "sql_guard"
    if error_type == "sql_execution_failed":
        return "sql_execution"
    if error_type and "unavailable" in str(error_type):
        return "analyze"
    if state.get("need_clarification"):
        return "slot_check"
    if state.get("final_answer") is None and state.get("business_success") is False:
        return "answer"
    return None


def build_agent_run_log(state: dict[str, Any]) -> dict[str, Any]:
    """从最终 Agent 状态构造 JSONL 日志记录。"""
    companies = state.get("companies") or []
    metrics = state.get("metrics") or []
    sql_review = state.get("sql_review") or {}
    query_result = state.get("query_result")
    error_type = _normalize_error_type(state.get("error_type"))
    analysis = state.get("analysis_result") if isinstance(state.get("analysis_result"), dict) else {}
    row_count = query_result.get("row_count") if query_result else analysis.get("row_count", 0)

    record: dict[str, Any] = {
        "logged_at": datetime.now().isoformat(timespec="seconds"),
        "query": state.get("user_question"),
        "question": state.get("user_question"),
        "intent_type": state.get("intent_type"),
        "query_plan": state.get("query_plan"),
        "metric_type": _primary_metric_type(metrics),
        "metric_types": sorted({m.get("metric_type", "base") for m in metrics}),
        "companies": _company_names(companies),
        "metrics": _metric_keys(metrics),
        "report_year": state.get("report_year"),
        "report_years": state.get("report_years") or [],
        "report_period": state.get("report_period"),
        "time_mode": state.get("time_mode"),
        "start_year": state.get("start_year"),
        "end_year": state.get("end_year"),
        "recent_n_years": state.get("recent_n_years"),
        "sql": state.get("sql"),
        "sqls": _collect_sqls(state),
        "sql_review": sql_review,
        "sql_safe": sql_review.get("is_safe"),
        "row_count": row_count,
        "query_results": _collect_query_results(state),
        "sql_success": state.get("sql_success"),
        "business_success": state.get("business_success"),
        "error_type": error_type,
        "failure_stage": _infer_failure_stage(state),
        "empty_fields": state.get("empty_fields") or [],
        "pending_query_plan": state.get("pending_query_plan"),
        "pending_clarification_type": state.get("pending_clarification_type"),
        "pending_empty_fields": state.get("pending_empty_fields") or [],
        "pending_candidates": state.get("pending_candidates") or [],
        "slot_patch": state.get("slot_patch"),
        "merged_query_plan": state.get("merged_query_plan"),
        "route_type": state.get("route_type"),
        "target_context": state.get("target_context"),
        "last_successful_query_plan": state.get("last_successful_query_plan"),
        "final_answer": state.get("final_answer"),
        "compare_spec": state.get("compare_spec"),
        "analysis_result": _collect_analysis_result(state),
        "analysis_result_summary": _analysis_result_summary(state),
        "llm_analysis": state.get("llm_analysis"),
        "llm_analysis_success": state.get("llm_analysis_success"),
        "llm_analysis_error": state.get("llm_analysis_error"),
    }
    record.update(_ranking_log_fields(state))

    # yoy 专项字段
    yoy_sqls = state.get("yoy_sqls")
    if yoy_sqls:
        record["yoy_sqls"] = yoy_sqls
    yoy_result = state.get("yoy_result")
    if yoy_result is not None:
        record["yoy_result"] = yoy_result

    # derived 单年专项字段
    derived_sqls = state.get("derived_sqls")
    if derived_sqls:
        record["derived_sqls"] = derived_sqls
    derived_query_results = state.get("derived_query_results")
    if derived_query_results is not None:
        record["derived_query_results"] = derived_query_results
    derived_result = state.get("derived_result")
    if derived_result is not None:
        record["derived_result"] = derived_result

    # derived 趋势专项字段
    derived_trend_sqls = state.get("derived_trend_sqls")
    if derived_trend_sqls:
        record["derived_trend_sqls"] = derived_trend_sqls
    derived_trend_result = state.get("derived_trend_result")
    if derived_trend_result is not None:
        record["derived_trend_result"] = derived_trend_result

    # derived yoy 专项字段（V0.3.5）
    derived_yoy_sqls = state.get("derived_yoy_sqls")
    if derived_yoy_sqls:
        record["derived_yoy_sqls"] = derived_yoy_sqls
    derived_yoy_result = state.get("derived_yoy_result")
    if derived_yoy_result is not None:
        record["derived_yoy_result"] = derived_yoy_result

    # ── V0.4.0 多公司对比专项字段 ──
    compare_sqls = state.get("compare_sqls")
    if compare_sqls:
        record["compare_sqls"] = [
            {"table": e["table"], "metric_keys": e["metric_keys"], "sql": e["sql"]}
            for e in compare_sqls
        ]

    derived_compare_sqls = state.get("derived_compare_sqls")
    if derived_compare_sqls:
        record["derived_compare_sqls"] = derived_compare_sqls

    compare_result = state.get("compare_result")
    if compare_result is not None:
        record["compare_result"] = compare_result

    derived_compare_result = state.get("derived_compare_result")
    if derived_compare_result is not None:
        record["derived_compare_result"] = derived_compare_result

    compare_query_results = state.get("compare_query_results")
    if compare_query_results:
        record["compare_query_results"] = [
            {"table": r.get("table"), "metric_keys": r.get("metric_keys"),
             "success": r.get("success"), "row_count": r.get("row_count"),
             "error": r.get("error")}
            for r in compare_query_results
        ]

    derived_compare_query_results = state.get("derived_compare_query_results")
    if derived_compare_query_results:
        record["derived_compare_query_results"] = derived_compare_query_results

    # ── V0.4.2 公司趋势对比专项字段 ──
    compare_trend_sqls = state.get("compare_trend_sqls")
    if compare_trend_sqls:
        record["compare_trend_sqls"] = compare_trend_sqls

    compare_trend_query_results = state.get("compare_trend_query_results")
    if compare_trend_query_results:
        record["compare_trend_query_results"] = [
            {"table": r.get("table"), "metric_keys": r.get("metric_keys"),
             "success": r.get("success"), "row_count": r.get("row_count"),
             "error": r.get("error")}
            for r in compare_trend_query_results
        ]

    compare_trend_result = state.get("compare_trend_result")
    if compare_trend_result is not None:
        record["compare_trend_result"] = compare_trend_result

    derived_compare_trend_sqls = state.get("derived_compare_trend_sqls")
    if derived_compare_trend_sqls:
        record["derived_compare_trend_sqls"] = derived_compare_trend_sqls

    derived_compare_trend_query_results = state.get("derived_compare_trend_query_results")
    if derived_compare_trend_query_results:
        record["derived_compare_trend_query_results"] = derived_compare_trend_query_results

    derived_compare_trend_result = state.get("derived_compare_trend_result")
    if derived_compare_trend_result is not None:
        record["derived_compare_trend_result"] = derived_compare_trend_result

    # ── V0.4.3 公司同比对比专项字段 ──
    compare_yoy_sqls = state.get("compare_yoy_sqls")
    if compare_yoy_sqls:
        record["compare_yoy_sqls"] = [
            {"sql_id": e.get("sql_id"), "table": e.get("table"),
             "metric_keys": e["metric_keys"], "years": e.get("years", []),
             "guard_passed": e.get("guard_passed"), "sql": e["sql"]}
            for e in compare_yoy_sqls
        ]

    compare_yoy_query_results = state.get("compare_yoy_query_results")
    if compare_yoy_query_results:
        record["compare_yoy_query_results"] = [
            {"sql_id": r.get("sql_id"), "table": r.get("table"),
             "metric_keys": r.get("metric_keys"), "years": r.get("years", []),
             "guard_passed": r.get("guard_passed"),
             "success": r.get("success"), "row_count": r.get("row_count"),
             "error": r.get("error")}
            for r in compare_yoy_query_results
        ]

    compare_yoy_result = state.get("compare_yoy_result")
    if compare_yoy_result is not None:
        record["compare_yoy_result"] = compare_yoy_result

    derived_compare_yoy_sqls = state.get("derived_compare_yoy_sqls")
    if derived_compare_yoy_sqls:
        record["derived_compare_yoy_sqls"] = [
            {"sql_id": e.get("sql_id"), "metric_key": e.get("metric_key"),
             "years": e.get("years", []), "numerator": e.get("numerator"),
             "denominator": e.get("denominator"), "guard_passed": e.get("guard_passed"),
             "sql": e["sql"]}
            for e in derived_compare_yoy_sqls
        ]

    derived_compare_yoy_query_results = state.get("derived_compare_yoy_query_results")
    if derived_compare_yoy_query_results:
        record["derived_compare_yoy_query_results"] = derived_compare_yoy_query_results

    derived_compare_yoy_result = state.get("derived_compare_yoy_result")
    if derived_compare_yoy_result is not None:
        record["derived_compare_yoy_result"] = derived_compare_yoy_result

    # yoy 年份诊断字段
    report_years = state.get("report_years")
    if report_years:
        record["report_years"] = report_years

    # 路由信息
    intent_type = state.get("intent_type")
    if intent_type == "company_compare_query":
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            record["compare_route"] = "derived"
        elif metric_types <= {"base"}:
            record["compare_route"] = "base"
        else:
            record["compare_route"] = "unsupported_mixed"
    if intent_type == "company_compare_trend_query":
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            record["compare_trend_route"] = "derived"
        elif metric_types <= {"base"}:
            record["compare_trend_route"] = "base"
        else:
            record["compare_trend_route"] = "unsupported_mixed"
    if intent_type == "company_compare_yoy_query":
        metric_types = {m.get("metric_type", "base") for m in metrics}
        if metric_types == {"derived"}:
            record["compare_yoy_route"] = "derived"
        elif metric_types <= {"base"}:
            record["compare_yoy_route"] = "base"
        else:
            record["compare_yoy_route"] = "unsupported_mixed"
    record["metric_type_route"] = sorted(
        m.get("metric_type", "base") for m in metrics
    )

    return record


def safe_log_run(record: dict[str, Any], log_path: Path | None = None) -> None:
    """安全写入运行日志，失败时不影响 Agent 主链路。"""
    target_path = log_path or DEFAULT_LOG_PATH
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        print(f"[WARN] Failed to write agent log: {exc}")


def log_agent_run(state: dict[str, Any], log_path: Path | None = None) -> None:
    """追加写入单次 Agent 运行日志。"""
    record = build_agent_run_log(state)
    safe_log_run(record, log_path)
