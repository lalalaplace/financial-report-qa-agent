"""SQL 执行分支 handler：各 SQL family 的执行逻辑。"""

from __future__ import annotations

from typing import Any

from agent.tools.sql_tools import execute_financial_sql, review_sql
from agent.utils.result_utils import _merge_query_results


def _invoke_execute_financial_sql(sql: str) -> dict[str, Any]:
    invoke = getattr(execute_financial_sql, "invoke", None)
    if callable(invoke):
        return invoke({"sql": sql})
    return execute_financial_sql(sql)


def _review_and_execute_one(sql: str) -> dict[str, Any]:
    """Review + execute 单条 SQL。返回统一的 result dict。"""
    review = review_sql(sql)
    if not review["is_safe"]:
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "row_count": 0,
            "error": review["reason"],
        }
    return _invoke_execute_financial_sql(sql)


# ── 1. yoy_sqls：多 SQL 合并 ──


def handle_yoy_sqls(sqls: list[str]) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for sql in sqls:
        result = _review_and_execute_one(sql)
        if not result.get("success"):
            return {
                "sql_review": {"is_safe": False, "reason": result.get("error", "")},
                "query_result": result,
                "sql_success": False,
                "business_success": False,
                "error_type": "sql_execution_error",
                "empty_fields": [],
            }
        results.append(result)

    merged = _merge_query_results(results)
    return {
        "sql_review": {"is_safe": True, "reason": "", "corrected_sql": None},
        "query_result": merged,
        "sql_success": True,
        "error_type": None,
    }


# ── 2. derived_sqls：多 SQL 逐条存储 ──


def handle_derived_sqls(sqls: list[str]) -> dict[str, Any]:
    d_results: list[dict[str, Any]] = []
    for dsql in sqls:
        result = _review_and_execute_one(dsql)
        if not result.get("success"):
            return {
                "sql_review": {"is_safe": False, "reason": result.get("error", "")},
                "query_result": result,
                "derived_query_results": d_results,
                "sql_success": False,
                "business_success": False,
                "error_type": "sql_execution_error",
                "empty_fields": [],
            }
        d_results.append(result)
    return {
        "sql_review": {"is_safe": True, "reason": "", "corrected_sql": None},
        "derived_query_results": d_results,
        "sql_success": True,
        "error_type": None,
    }


# ── 3/4. derived_trend_sqls / derived_yoy_sqls：按 metric_key 分组 ──


def _handle_derived_keyed_sqls(
    entries: list[dict[str, Any]],
) -> tuple[dict[str, dict], bool]:
    """通用：逐条 review+execute，返回 {metric_key: result} 字典和 all_ok。"""
    results: dict[str, dict] = {}
    all_ok = True
    for entry in entries:
        sql = entry["sql"]
        review = review_sql(sql)
        if not review["is_safe"]:
            all_ok = False
            results[entry["metric_key"]] = {
                "sql": sql,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "sql_success": False,
                "error": review["reason"],
            }
        else:
            result = _invoke_execute_financial_sql(sql)
            success = result.get("success", False)
            if not success:
                all_ok = False
            results[entry["metric_key"]] = {
                "sql": sql,
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "sql_success": success,
                "error": result.get("error"),
            }
    return results, all_ok


def handle_derived_trend_sqls(entries: list[dict[str, Any]]) -> dict[str, Any]:
    results, all_ok = _handle_derived_keyed_sqls(entries)
    return {
        "derived_trend_query_results": results,
        "sql_success": all_ok,
        "error_type": None if all_ok else "sql_execution_error",
    }


def handle_derived_yoy_sqls(entries: list[dict[str, Any]]) -> dict[str, Any]:
    results, all_ok = _handle_derived_keyed_sqls(entries)
    return {
        "derived_yoy_query_results": results,
        "sql_success": all_ok,
        "error_type": None if all_ok else "sql_execution_error",
    }


# ── 5/6. compare_trend_sqls / compare_yoy_sqls：含 guard_passed 列表 ──


def _handle_compare_list_sqls(
    entries: list[dict[str, Any]],
    result_key: str,
) -> dict[str, Any]:
    """通用：逐条 review+execute，返回含 guard_passed 的结果列表。"""
    ct_results: list[dict[str, Any]] = []
    reviewed_sqls: list[dict[str, Any]] = []
    sql_reviews: list[dict[str, Any]] = []
    all_ok = True
    for entry in entries:
        sql = entry["sql"]
        review = review_sql(sql)
        sql_reviews.append(review)
        reviewed_entry = dict(entry)
        reviewed_entry["guard_passed"] = bool(review["is_safe"])
        reviewed_sqls.append(reviewed_entry)
        if not review["is_safe"]:
            all_ok = False
            ct_results.append({
                "sql_id": entry.get("sql_id"),
                "table": entry["table"],
                "metric_keys": entry["metric_keys"],
                "years": entry.get("years", []),
                "guard_passed": False,
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "error": review["reason"],
            })
        else:
            result = _invoke_execute_financial_sql(sql)
            success = result.get("success", False)
            if not success:
                all_ok = False
            ct_results.append({
                "sql_id": entry.get("sql_id"),
                "table": entry["table"],
                "metric_keys": entry["metric_keys"],
                "years": entry.get("years", []),
                "guard_passed": True,
                "success": success,
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "error": result.get("error"),
            })
    return {
        "sql_review": sql_reviews[0] if sql_reviews else {"is_safe": False, "reason": "no SQL"},
        result_key: reviewed_sqls,
        f"{result_key.replace('_sqls', '_query_results')}": ct_results,
        "sql_success": all_ok,
        "error_type": None if all_ok else "sql_execution_error",
    }


def handle_compare_trend_sqls(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return _handle_compare_list_sqls(entries, "compare_trend_sqls")


def handle_compare_yoy_sqls(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return _handle_compare_list_sqls(entries, "compare_yoy_sqls")


# ── 7/8. derived_compare_yoy_sqls / derived_compare_trend_sqls：含 guard_passed 字典 ──


def _handle_derived_compare_keyed_sqls(
    entries: list[dict[str, Any]],
    result_key: str,
) -> dict[str, Any]:
    """通用：逐条 review+execute，返回 {metric_key: result} 字典。"""
    d_results: dict[str, dict] = {}
    reviewed_sqls: list[dict[str, Any]] = []
    all_ok = True
    for entry in entries:
        sql = entry["sql"]
        review = review_sql(sql)
        reviewed_entry = dict(entry)
        reviewed_entry["guard_passed"] = bool(review["is_safe"])
        reviewed_sqls.append(reviewed_entry)
        if not review["is_safe"]:
            all_ok = False
            d_results[entry["metric_key"]] = {
                "sql_id": entry.get("sql_id"),
                "sql": sql,
                "years": entry.get("years", []),
                "guard_passed": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "sql_success": False,
                "error": review["reason"],
            }
        else:
            result = _invoke_execute_financial_sql(sql)
            success = result.get("success", False)
            if not success:
                all_ok = False
            d_results[entry["metric_key"]] = {
                "sql_id": entry.get("sql_id"),
                "sql": sql,
                "years": entry.get("years", []),
                "guard_passed": True,
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "sql_success": success,
                "error": result.get("error"),
            }
    return {
        result_key: reviewed_sqls,
        f"{result_key.replace('_sqls', '_query_results')}": d_results,
        "sql_success": all_ok,
        "error_type": None if all_ok else "sql_execution_error",
    }


def handle_derived_compare_yoy_sqls(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return _handle_derived_compare_keyed_sqls(entries, "derived_compare_yoy_sqls")


def handle_derived_compare_trend_sqls(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return _handle_derived_compare_keyed_sqls(entries, "derived_compare_trend_sqls")


# ── 9. compare_sqls：无 guard_passed 列表 ──


def handle_compare_sqls(entries: list[dict[str, Any]]) -> dict[str, Any]:
    compare_results: list[dict[str, Any]] = []
    sql_reviews: list[dict[str, Any]] = []
    all_ok = True
    for entry in entries:
        sql = entry["sql"]
        review = review_sql(sql)
        sql_reviews.append(review)
        if not review["is_safe"]:
            all_ok = False
            compare_results.append({
                "table": entry["table"],
                "metric_keys": entry["metric_keys"],
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "error": review["reason"],
            })
        else:
            result = _invoke_execute_financial_sql(sql)
            success = result.get("success", False)
            if not success:
                all_ok = False
            compare_results.append({
                "table": entry["table"],
                "metric_keys": entry["metric_keys"],
                "success": success,
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "error": result.get("error"),
            })
    return {
        "sql_review": sql_reviews[0] if sql_reviews else {"is_safe": False, "reason": "no SQL"},
        "compare_query_results": compare_results,
        "sql_success": all_ok,
        "error_type": None if all_ok else "sql_execution_error",
    }


# ── 10. derived_compare_sqls：无 guard_passed 字典 ──


def handle_derived_compare_sqls(entries: list[dict[str, Any]]) -> dict[str, Any]:
    dc_results: dict[str, dict] = {}
    all_ok = True
    for entry in entries:
        sql = entry["sql"]
        review = review_sql(sql)
        if not review["is_safe"]:
            all_ok = False
            dc_results[entry["metric_key"]] = {
                "sql": sql,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "sql_success": False,
                "error": review["reason"],
            }
        else:
            result = _invoke_execute_financial_sql(sql)
            success = result.get("success", False)
            if not success:
                all_ok = False
            dc_results[entry["metric_key"]] = {
                "sql": sql,
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "row_count": result.get("row_count", 0),
                "sql_success": success,
                "error": result.get("error"),
            }
    return {
        "derived_compare_query_results": dc_results,
        "sql_success": all_ok,
        "error_type": None if all_ok else "sql_execution_error",
    }


# ── 11. 单 SQL ──


def handle_single_sql(sql: str | None) -> dict[str, Any]:
    if not sql:
        return {
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
            "query_result": {
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "error": "SQL is empty.",
            },
        }

    review = review_sql(sql)
    if not review["is_safe"]:
        return {
            "sql_review": review,
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_guard_failed",
            "empty_fields": [],
            "query_result": {
                "success": False,
                "columns": [],
                "rows": [],
                "row_count": 0,
                "error": review["reason"],
            },
        }

    result = _invoke_execute_financial_sql(sql)
    sql_success = bool(result.get("success"))
    return {
        "sql_review": review,
        "query_result": result,
        "sql_success": sql_success,
        "error_type": None if sql_success else "sql_execution_error",
    }


def execute_approved_sql(sql: str | None) -> dict[str, Any]:
    """执行已由正式 Guard 节点批准的单条 SQL。"""
    if not sql:
        return {
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
            "query_result": {"success": False, "columns": [], "rows": [], "row_count": 0, "error": "SQL is empty."},
        }
    result = _invoke_execute_financial_sql(sql)
    sql_success = bool(result.get("success"))
    return {"query_result": result, "sql_success": sql_success, "error_type": None if sql_success else "sql_execution_error"}


__all__ = [
    "_invoke_execute_financial_sql",
    "handle_yoy_sqls",
    "handle_derived_sqls",
    "handle_derived_trend_sqls",
    "handle_derived_yoy_sqls",
    "handle_compare_trend_sqls",
    "handle_compare_yoy_sqls",
    "handle_derived_compare_yoy_sqls",
    "handle_derived_compare_trend_sqls",
    "handle_compare_sqls",
    "handle_derived_compare_sqls",
    "execute_approved_sql",
    "handle_single_sql",
]
