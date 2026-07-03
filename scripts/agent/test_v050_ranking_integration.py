"""V0.5.2 排名查询集成测试。

端到端验证：schema → validator → SQL → guard → analysis → answer 全链路。
V0.5.2：新 analysis_result 结构（rows / is_empty / analysis_type）、limit=1 话术。
不依赖数据库连接，使用 mock query_result。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.schemas.query_plan import validate_plan
from agent.nodes.slot_validators.ranking_validator import validate as validate_slots
from agent.nodes.sql_nodes.ranking_sql import build_base_ranking_sql
from agent.tools.sql_tools import review_sql
from agent.nodes.analyze_nodes.ranking_analysis import analyze_ranking_node
from agent.nodes.answer_nodes.ranking_answer import generate_ranking_answer_node


BASE_METRIC = {
    "metric_key": "operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "table": "income_sheet",
    "field": "operating_revenue",
    "unit": "yuan",
}


def _mock_query_result(rows):
    return {
        "success": True,
        "row_count": len(rows),
        "columns": [
            "stock_code", "stock_abbr", "company_name",
            "report_year", "report_period", "income_sheet__operating_revenue",
        ],
        "rows": rows,
    }


# ── E2E: plan → SQL → guard → analysis → answer (desc + limit>1) ──

def test_e2e_desc_top3():
    # 1. plan
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
        "limit": 3,
    })
    assert plan["rank_direction"] == "desc"
    assert plan["limit"] == 3

    # 2. validator
    val_result = validate_slots({
        "metrics": [BASE_METRIC],
        "metric_candidates": [],
        "rank_direction": plan["rank_direction"],
        "limit": plan["limit"],
        "report_year": plan["time_range"]["report_year"],
        "report_period": "FY",
        "time_range": plan["time_range"],
        "companies": [],
        "company_mentions": [],
    })
    assert val_result["need_clarification"] is False

    # 3. SQL
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="desc",
        limit=3,
    )
    assert "ORDER BY i.operating_revenue DESC, c.stock_code ASC" in sql
    assert "LIMIT 3" in sql

    # 4. guard
    guard = review_sql(sql)
    assert guard["is_safe"]

    # 5. analysis
    qr = _mock_query_result([
        ["000001", "公司A", "公司A全称", 2024, "FY", 100_000_000_000],
        ["000002", "公司B", "公司B全称", 2024, "FY", 80_000_000_000],
        ["000003", "公司C", "公司C全称", 2024, "FY", 60_000_000_000],
    ])
    analysis = analyze_ranking_node({
        "query_result": qr,
        "metrics": [BASE_METRIC],
        "rank_direction": "desc",
        "limit": 3,
        "report_year": 2024,
        "report_period": "FY",
    })
    ar = analysis["analysis_result"]
    assert ar["analysis_type"] == "ranking"
    assert ar["is_empty"] is False
    assert ar["row_count"] == 3
    rows = ar["rows"]
    assert len(rows) == 3
    assert rows[0]["rank"] == 1
    assert rows[0]["metric_value"] == 100_000_000_000
    assert rows[2]["rank"] == 3

    # 6. answer
    ans = generate_ranking_answer_node({
        "analysis_result": ar,
    })
    assert "排名前 3" in ans["final_answer"]
    assert "公司A全称" in ans["final_answer"]
    assert "平均营业收入" in ans["final_answer"]
    assert "公司A全称比第二名公司B全称高" in ans["final_answer"]
    assert ans["business_success"] is True


# ── E2E: asc + limit>1 ──

def test_e2e_asc_bottom3():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "asc",
        "limit": 3,
    })
    sql = build_base_ranking_sql(
        metric=BASE_METRIC,
        report_year=2024,
        report_period="FY",
        rank_direction="asc",
        limit=3,
    )
    assert "ORDER BY i.operating_revenue ASC, c.stock_code ASC" in sql

    qr = _mock_query_result([
        ["000001", "小A", "小A公司", 2024, "FY", 1_000_000_000],
        ["000002", "小B", "小B公司", 2024, "FY", 2_000_000_000],
        ["000003", "小C", "小C公司", 2024, "FY", 3_000_000_000],
    ])
    analysis = analyze_ranking_node({
        "query_result": qr,
        "metrics": [BASE_METRIC],
        "rank_direction": "asc",
        "limit": 3,
        "report_year": 2024,
        "report_period": "FY",
    })
    ar = analysis["analysis_result"]
    assert ar["is_empty"] is False
    assert ar["rows"][0]["metric_value"] == 1_000_000_000


def test_answer_percent_metric_asc_summary_uses_percentage_points():
    ar = {
        "analysis_type": "ranking",
        "metric_name": "资产负债率",
        "metric_type": "derived",
        "report_year": 2024,
        "report_period": "FY",
        "rank_direction": "asc",
        "limit": 10,
        "row_count": 2,
        "is_empty": False,
        "rows": [
            {
                "rank": 1,
                "company_name": "A公司",
                "metric_value": 20.0,
                "display_value": "20.00%",
            },
            {
                "rank": 2,
                "company_name": "B公司",
                "metric_value": 25.0,
                "display_value": "25.00%",
            },
        ],
        "result_summary": {
            "first_company_name": "A公司",
            "first_display_value": "20.00%",
            "first_rank_label": "排名第一（数值最低）",
            "average_label": "平均资产负债率",
            "average_display_value": "22.50%",
            "topn_count": 2,
            "gap_compare_word": "低",
            "gap_display_value": "5.00 个百分点",
            "gap_ratio_display": None,
        },
    }

    ans = generate_ranking_answer_node({"analysis_result": ar})

    assert "资产负债率最低的 2 家公司如下" in ans["final_answer"]
    assert "A公司排名第一（数值最低）" in ans["final_answer"]
    assert "平均资产负债率为22.50%" in ans["final_answer"]
    assert "A公司比第二名低5.00 个百分点" in ans["final_answer"]


def test_analysis_builds_ranking_result_summary():
    qr = {
        "success": True,
        "row_count": 2,
        "columns": [
            "stock_code", "stock_abbr", "company_name",
            "report_year", "report_period", "asset_liability_ratio",
        ],
        "rows": [
            ["000001", "A", "A公司", 2024, "FY", 0.20],
            ["000002", "B", "B公司", 2024, "FY", 0.25],
        ],
    }
    metric = {
        "metric_key": "asset_liability_ratio",
        "metric_name": "资产负债率",
        "metric_type": "derived",
        "unit": "percent",
        "scale": 100,
        "precision": 2,
    }

    analysis = analyze_ranking_node({
        "query_result": qr,
        "metrics": [metric],
        "rank_direction": "asc",
        "limit": 10,
        "report_year": 2024,
        "report_period": "FY",
        "sql_metadata": {
            "column_alias": "asset_liability_ratio",
            "scale": 100,
            "precision": 2,
        },
    })
    summary = analysis["analysis_result"]["result_summary"]

    assert summary["average_display_value"] == "22.50%"
    assert summary["gap_display_value"] == "5.00 个百分点"
    assert summary["gap_compare_word"] == "低"


# ── E2E: limit=1 单行内联 ──

def test_e2e_limit_1_desc():
    """V0.5.2：limit=1 使用单行内联话术。"""
    qr = _mock_query_result([
        ["000001", "茅台", "贵州茅台酒股份有限公司", 2024, "FY", 150_000_000_000],
    ])
    analysis = analyze_ranking_node({
        "query_result": qr,
        "metrics": [BASE_METRIC],
        "rank_direction": "desc",
        "limit": 1,
        "report_year": 2024,
        "report_period": "FY",
    })
    ar = analysis["analysis_result"]
    assert ar["is_empty"] is False
    assert ar["row_count"] == 1
    assert ar["rows"][0]["rank"] == 1

    ans = generate_ranking_answer_node({
        "analysis_result": ar,
    })
    assert "最高的是贵州茅台酒股份有限公司" in ans["final_answer"]
    assert "营业收入为" in ans["final_answer"]
    assert "1. 贵州茅台酒股份有限公司：1,500.00 亿元" in ans["final_answer"]


def test_e2e_limit_1_asc():
    """V0.5.2：limit=1 asc 使用单行内联话术。"""
    qr = _mock_query_result([
        ["000001", "某司", "某公司", 2024, "FY", -50_000_000],
    ])
    analysis = analyze_ranking_node({
        "query_result": qr,
        "metrics": [BASE_METRIC],
        "rank_direction": "asc",
        "limit": 1,
        "report_year": 2024,
        "report_period": "FY",
    })
    ar = analysis["analysis_result"]
    ans = generate_ranking_answer_node({
        "analysis_result": ar,
    })
    assert "最低的是某公司" in ans["final_answer"]


# ── 空结果 ──

def test_empty_result():
    qr = {"success": True, "row_count": 0, "columns": [], "rows": []}
    analysis = analyze_ranking_node({
        "query_result": qr,
        "metrics": [BASE_METRIC],
        "rank_direction": "desc",
        "limit": 10,
        "report_year": 2024,
        "report_period": "FY",
    })
    ar = analysis["analysis_result"]
    assert ar["is_empty"] is True
    assert ar["row_count"] == 0
    assert ar["rows"] == []
    assert analysis["business_success"] is False
    assert analysis["error_type"] == "empty_ranking_result"

    ans = generate_ranking_answer_node({
        "analysis_result": ar,
    })
    assert "未查询到满足条件的数据" in ans["final_answer"]
    assert "查询条件" in ans["final_answer"]


# ── 查询失败 ──

def test_query_failed():
    qr = {"success": False, "error": "连接超时", "columns": [], "rows": [], "row_count": 0}
    analysis = analyze_ranking_node({
        "query_result": qr,
        "metrics": [BASE_METRIC],
    })
    ar = analysis["analysis_result"]
    assert ar["is_empty"] is True
    assert ar["error"] == "连接超时"

    ans = generate_ranking_answer_node({
        "analysis_result": ar,
    })
    assert "失败" in ans["final_answer"]


# ── 派生指标回答含口径说明 ──

def test_e2e_derived_limit_1_with_formula():
    """V0.5.2：派生指标 limit=1 时附带口径说明。"""
    derived_metric = {
        "metric_key": "net_profit_margin",
        "metric_name": "净利率",
        "metric_type": "derived",
        "unit": "percent",
        "scale": 100,
        "precision": 2,
    }
    qr = {
        "success": True,
        "row_count": 1,
        "columns": [
            "stock_code", "stock_abbr", "company_name",
            "report_year", "report_period", "net_profit_margin",
        ],
        "rows": [["000001", "测试", "测试公司", 2024, "FY", 0.2356]],
    }
    analysis = analyze_ranking_node({
        "query_result": qr,
        "metrics": [derived_metric],
        "rank_direction": "desc",
        "limit": 1,
        "report_year": 2024,
        "report_period": "FY",
        "sql_metadata": {
            "metric_type": "derived",
            "column_alias": "net_profit_margin",
            "scale": 100,
            "precision": 2,
            "formula_display": "净利润 / 营业收入",
        },
    })
    ar = analysis["analysis_result"]
    assert ar["is_empty"] is False
    assert ar["metric_type"] == "derived"

    ans = generate_ranking_answer_node({
        "analysis_result": ar,
        "sql_metadata": {"metric_type": "derived", "formula_display": "净利润 / 营业收入"},
    })
    assert "净利率最高的是测试公司" in ans["final_answer"]
    assert "23.56%" in ans["final_answer"]
    assert "口径：" in ans["final_answer"]
    assert "净利润 / 营业收入" in ans["final_answer"]


# ── 粗粒度 regression: V0.4.6 路径不受影响 ──

def test_v046_regression_plan_schema():
    """非 ranking 路径不受排名字段影响。"""
    plan = validate_plan({
        "intent_type": "company_compare_query",
        "company_mentions": ["贵州茅台", "五粮液"],
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
    })
    assert plan["compare_spec"] is not None
    assert plan["compare_spec"]["operator"] == "general"
    assert plan["rank_direction"] is None
    assert plan["limit"] is None


def test_v046_regression_yoy_plan():
    plan = validate_plan({
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
    })
    assert plan["time_range"]["report_years"] == [2023, 2024]
    assert plan["rank_direction"] is None
    assert plan["limit"] is None


def test_v046_regression_trend_plan():
    plan = validate_plan({
        "intent_type": "trend_query",
        "company_mentions": ["华润三九"],
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "explicit_range", "start_year": 2022, "end_year": 2024},
    })
    assert plan["time_range"]["report_years"] == [2022, 2023, 2024]
    assert plan["rank_direction"] is None


if __name__ == "__main__":
    tests = [
        test_e2e_desc_top3,
        test_e2e_asc_bottom3,
        test_e2e_limit_1_desc,
        test_e2e_limit_1_asc,
        test_empty_result,
        test_query_failed,
        test_e2e_derived_limit_1_with_formula,
        test_v046_regression_plan_schema,
        test_v046_regression_yoy_plan,
        test_v046_regression_trend_plan,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAIL {test.__name__}: {e}")
    print(f"V0.5.2 ranking integration: {passed}/{len(tests)} 通过")
    if passed != len(tests):
        raise SystemExit(1)
