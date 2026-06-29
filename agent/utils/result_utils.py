"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

from typing import Any

from agent.services.trend_service import _summarize_trend_series


def _company_name_matches(company_name: str, query_name: str | None) -> bool:
    if not query_name:
        return False
    return query_name in company_name or company_name in query_name

def _find_named_item(items: list[dict[str, Any]], query_name: str | None) -> dict[str, Any] | None:
    for item in items:
        if _company_name_matches(str(item.get("company_name", "")), query_name):
            return item
    return None

def _select_extreme_item(
    items: list[dict[str, Any]],
    field: str,
    *,
    choose_max: bool,
    abs_value: bool = False,
) -> dict[str, Any] | None:
    candidates = [
        item for item in items
        if item.get("status") == "ok" and item.get(field) is not None
    ]
    if not candidates:
        return None
    key = (
        (lambda item: abs(float(item[field])))
        if abs_value
        else (lambda item: float(item[field]))
    )
    return max(candidates, key=key) if choose_max else min(candidates, key=key)

def _merge_query_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """合并多条 SQL 的查询结果，按 report_year 对齐列。"""
    if len(results) == 1:
        return results[0]

    merged_by_year: dict[int, dict[str, Any]] = {}
    for result in results:
        if not result.get("success"):
            return result
        columns = result["columns"]
        for row in result["rows"]:
            data = dict(zip(columns, row))
            year = data.get("report_year")
            if year is not None:
                merged_by_year.setdefault(year, {}).update(data)

    seen_columns: set[str] = set()
    merged_columns: list[str] = []
    for result in results:
        for col in result["columns"]:
            if col not in seen_columns:
                seen_columns.add(col)
                merged_columns.append(col)

    merged_rows = [
        [merged_by_year[year].get(col) for col in merged_columns]
        for year in sorted(merged_by_year.keys())
    ]

    return {
        "success": True,
        "columns": merged_columns,
        "rows": merged_rows,
        "row_count": len(merged_rows),
        "error": None,
    }

def _build_compare_trend_item(
    *,
    company_id: str,
    company_name: str,
    series: list[dict[str, Any]],
    precision: int,
) -> dict[str, Any]:
    summary = _summarize_trend_series(series, precision=precision)
    return {
        "company_id": company_id,
        "company_name": company_name,
        "series": series,
        "first_value": summary["first_value"],
        "last_value": summary["last_value"],
        "absolute_change": summary["absolute_change"],
        "change_rate": summary["change_rate"],
        "trend_direction": summary["trend_direction"],
        "status": "ok" if summary["status"] == "ok" else summary["status"],
    }

def _latest_year_winner_company(items: list[dict[str, Any]], years: list[int]) -> str | None:
    latest_year = years[-1] if years else None
    if latest_year is None:
        return None
    candidates: list[dict[str, Any]] = []
    for item in items:
        point = next(
            (
                p for p in item.get("series", [])
                if p.get("year") == latest_year and p.get("status") == "ok" and p.get("value") is not None
            ),
            None,
        )
        if point:
            candidates.append({"company_name": item["company_name"], "value": point["value"]})
    if not candidates:
        return None
    return max(candidates, key=lambda row: row["value"])["company_name"]

def _largest_absolute_change_company(items: list[dict[str, Any]]) -> str | None:
    candidates = [
        item for item in items
        if item.get("absolute_change") is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: abs(item["absolute_change"]))["company_name"]

def _latest_year_loser_company(items: list[dict[str, Any]], years: list[int]) -> str | None:
    latest_year = years[-1] if years else None
    if latest_year is None:
        return None
    candidates: list[dict[str, Any]] = []
    for item in items:
        point = next(
            (
                p for p in item.get("series", [])
                if p.get("year") == latest_year and p.get("status") == "ok" and p.get("value") is not None
            ),
            None,
        )
        if point:
            candidates.append({"company_name": item["company_name"], "value": point["value"]})
    if not candidates:
        return None
    return min(candidates, key=lambda row: row["value"])["company_name"]

def _largest_increase_company(items: list[dict[str, Any]]) -> str | None:
    candidates = [
        item for item in items
        if item.get("absolute_change") is not None and item["absolute_change"] > 0
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: item["absolute_change"])["company_name"]

def _largest_decline_company(items: list[dict[str, Any]]) -> str | None:
    candidates = [
        item for item in items
        if item.get("absolute_change") is not None and item["absolute_change"] < 0
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item["absolute_change"])["company_name"]

__all__ = ['_company_name_matches', '_find_named_item', '_select_extreme_item', '_merge_query_results', '_build_compare_trend_item', '_latest_year_winner_company', '_largest_absolute_change_company', '_latest_year_loser_company', '_largest_increase_company', '_largest_decline_company']
