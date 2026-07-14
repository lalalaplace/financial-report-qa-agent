"""V0.5.2 排名查询 SQL 生成测试。

覆盖 build_base_ranking_sql、build_derived_ranking_sql、SQL Guard、安全防护。
V0.5.2：二级排序、NULLIF、_guard_ranking_params、guard 拦截无 LIMIT 查询。
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.sql_nodes.ranking_sql import (
    build_base_ranking_sql,
    build_derived_ranking_sql,
    generate_ranking_sql_node,
    _guard_ranking_params,
)
from agent.tools.sql_tools import review_sql


BASE_METRIC = {
    "table": "income_sheet",
    "field": "operating_revenue",
    "metric_key": "operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "unit": "yuan",
}


# ── SQL 结构 ──

def test_desc_sql_contains_order_desc_and_secondary_sort():
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert "ORDER BY i.operating_revenue DESC, c.stock_code ASC" in sql


def test_asc_sql_contains_order_asc_and_secondary_sort():
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="asc",
        limit=5,
    )
    assert "ORDER BY i.operating_revenue ASC, c.stock_code ASC" in sql


def test_limit_in_sql():
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=3,
    )
    assert "LIMIT 3" in sql


def test_limit_1_in_sql():
    """V0.5.2：limit=1 正常生成 SQL。"""
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=1,
    )
    assert "LIMIT 1" in sql


def test_contains_where_not_null():
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert "IS NOT NULL" in sql


def test_no_company_filter():
    """排名 SQL 的 WHERE 子句不筛选特定公司（只过滤 NULL）。"""
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    sql_upper = sql.upper()
    where_idx = sql_upper.find("WHERE")
    after_where = sql_upper[where_idx:] if where_idx != -1 else ""
    assert "C.STOCK_CODE = '" not in after_where
    assert "STOCK_CODE IN (" not in after_where


def test_balance_sheet_uses_correct_alias():
    metric = {**BASE_METRIC, "table": "balance_sheet", "field": "total_assets"}
    sql = build_base_ranking_sql(
        metric=metric,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert "b.total_assets" in sql


def test_cash_flow_sheet_uses_correct_alias():
    metric = {**BASE_METRIC, "table": "cash_flow_sheet", "field": "operating_cf"}
    sql = build_base_ranking_sql(
        metric=metric,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert "cf.operating_cf" in sql


# ── 派生指标 SQL ──

def test_derived_ranking_sql_uses_nullif():
    """V0.5.2：派生排名 SQL 使用 NULLIF 处理分母为零。"""
    num_info = {"field": "net_profit", "metric_key": "net_profit", "metric_name": "净利润"}
    den_info = {"field": "operating_revenue", "metric_key": "operating_revenue", "metric_name": "营业收入"}
    sql = build_derived_ranking_sql(
        metric={"metric_key": "net_profit_margin", "metric_name": "净利率", "precision": 2},
        num_info=num_info,
        den_info=den_info,
        num_table="income_sheet",
        den_table="income_sheet",
        num_alias="i1",
        den_alias="i2",
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert "NULLIF(CAST(i2.operating_revenue AS NUMERIC), 0)" in sql
    assert "NUMERIC" in sql


def test_derived_ranking_sql_has_secondary_sort():
    """V0.5.2：派生排名 SQL 也包含二级排序。"""
    num_info = {"field": "net_profit", "metric_key": "net_profit", "metric_name": "净利润"}
    den_info = {"field": "operating_revenue", "metric_key": "operating_revenue", "metric_name": "营业收入"}
    sql = build_derived_ranking_sql(
        metric={"metric_key": "net_profit_margin", "metric_name": "净利率", "precision": 2},
        num_info=num_info,
        den_info=den_info,
        num_table="income_sheet",
        den_table="income_sheet",
        num_alias="i1",
        den_alias="i2",
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert "ORDER BY net_profit_margin DESC, c.stock_code ASC" in sql


def test_derived_ranking_den_not_null_filter():
    """派生排名 SQL 的 WHERE 过滤分母 IS NOT NULL 和 != 0。"""
    num_info = {"field": "net_profit", "metric_key": "net_profit", "metric_name": "净利润"}
    den_info = {"field": "operating_revenue", "metric_key": "operating_revenue", "metric_name": "营业收入"}
    sql = build_derived_ranking_sql(
        metric={"metric_key": "net_profit_margin", "metric_name": "净利率"},
        num_info=num_info,
        den_info=den_info,
        num_table="income_sheet",
        den_table="income_sheet",
        num_alias="i1",
        den_alias="i2",
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    # 同表场景：分子分母在同一张表，WHERE 过滤使用 num_alias (i1)
    assert "i1.operating_revenue IS NOT NULL" in sql
    assert "i1.operating_revenue != 0" in sql


# ── SQL Guard ──

def test_ranking_sql_passes_guard():
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    review = review_sql(sql)
    assert review["is_safe"], f"SQL guard 应通过，原因: {review.get('reason')}"


def test_ranking_sql_is_select():
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=10,
    )
    assert sql.strip().upper().startswith("SELECT")


def test_guard_rejects_order_by_without_limit():
    """V0.5.2：无公司过滤 + ORDER BY + 无 LIMIT → 被 guard 拦截。"""
    sql = """SELECT c.stock_code, i.operating_revenue
    FROM company_dim c
    LEFT JOIN income_sheet i ON c.stock_code = i.stock_code
    WHERE i.operating_revenue IS NOT NULL
    ORDER BY i.operating_revenue DESC"""
    review = review_sql(sql)
    assert review["is_safe"] is False
    assert "LIMIT" in review["reason"]


def test_guard_rejects_limit_over_50():
    """V0.5.2：LIMIT > 50 被 guard 拦截。"""
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=100,
    )
    review = review_sql(sql)
    assert review["is_safe"] is False


def test_guard_allows_order_by_with_company_filter():
    """有 stock_code 过滤的 ORDER BY 查询不受 LIMIT 规则约束。"""
    sql = """SELECT c.stock_code, i.operating_revenue
    FROM company_dim c
    JOIN income_sheet i ON c.stock_code = i.stock_code
    WHERE c.stock_code = '000999'
    ORDER BY i.report_year DESC"""
    review = review_sql(sql)
    assert review["is_safe"], f"公司过滤查询应通过 guard，原因: {review.get('reason')}"


# ── _guard_ranking_params 安全防护 ──

def test_guard_params_raises_on_none_limit():
    with pytest.raises(ValueError, match="requires limit"):
        _guard_ranking_params(None, "desc")


def test_guard_params_raises_on_invalid_limit():
    with pytest.raises(ValueError, match="invalid ranking limit"):
        _guard_ranking_params(0, "desc")


def test_guard_params_raises_on_limit_over_50():
    with pytest.raises(ValueError, match="invalid ranking limit"):
        _guard_ranking_params(51, "desc")


def test_guard_params_raises_on_invalid_direction():
    with pytest.raises(ValueError, match="invalid rank_direction"):
        _guard_ranking_params(10, "up")


def test_guard_params_passes_valid():
    """正常参数不抛异常。"""
    _guard_ranking_params(1, "desc")
    _guard_ranking_params(50, "asc")


# ── generate_ranking_sql_node ──

def test_node_rejects_empty_metrics():
    state = {"metrics": [], "need_clarification": False}
    result = generate_ranking_sql_node(state)
    assert result["need_clarification"] is True


def test_node_rejects_missing_limit():
    """V0.5.2：limit 缺失时被 _guard_ranking_params 拦截。"""
    state = {
        "metrics": [BASE_METRIC],
        "need_clarification": False,
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
    }
    result = generate_ranking_sql_node(state)
    assert result["need_clarification"] is True


def test_node_generates_sql_for_base_metric():
    state = {
        "metrics": [BASE_METRIC],
        "need_clarification": False,
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "limit": 10,
    }
    result = generate_ranking_sql_node(state)
    assert result.get("sql") is not None
    assert "LIMIT 10" in result["sql"]
    assert result.get("sql_metadata") is not None
    assert result["sql_metadata"]["rank_direction"] == "desc"


def test_node_generates_sql_for_limit_1():
    """V0.5.2：limit=1 正常生成 SQL。"""
    state = {
        "metrics": [BASE_METRIC],
        "need_clarification": False,
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "desc",
        "limit": 1,
    }
    result = generate_ranking_sql_node(state)
    assert result.get("sql") is not None
    assert "LIMIT 1" in result["sql"]


# ── 路由验证 ──

def test_route_analysis_ranking():
    from agent.routing import route_analysis
    result = route_analysis({"intent_type": "ranking_query"})
    assert result == "analyze_ranking"


def test_route_by_intent_ranking():
    from agent.routing import route_by_intent
    result = route_by_intent({"intent_type": "ranking_query"})
    assert result == "generate_ranking_sql"


if __name__ == "__main__":
    tests = [
        test_desc_sql_contains_order_desc_and_secondary_sort,
        test_asc_sql_contains_order_asc_and_secondary_sort,
        test_limit_in_sql,
        test_limit_1_in_sql,
        test_contains_where_not_null,
        test_no_company_filter,
        test_balance_sheet_uses_correct_alias,
        test_cash_flow_sheet_uses_correct_alias,
        test_derived_ranking_sql_uses_nullif,
        test_derived_ranking_sql_has_secondary_sort,
        test_derived_ranking_den_not_null_filter,
        test_ranking_sql_passes_guard,
        test_ranking_sql_is_select,
        test_guard_rejects_order_by_without_limit,
        test_guard_rejects_limit_over_50,
        test_guard_allows_order_by_with_company_filter,
        test_guard_params_raises_on_none_limit,
        test_guard_params_raises_on_invalid_limit,
        test_guard_params_raises_on_limit_over_50,
        test_guard_params_raises_on_invalid_direction,
        test_guard_params_passes_valid,
        test_node_rejects_empty_metrics,
        test_node_rejects_missing_limit,
        test_node_generates_sql_for_base_metric,
        test_node_generates_sql_for_limit_1,
        test_route_analysis_ranking,
        test_route_by_intent_ranking,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAIL {test.__name__}: {e}")
    print(f"V0.5.2 ranking SQL: {passed}/{len(tests)} 通过")
    if passed != len(tests):
        raise SystemExit(1)
