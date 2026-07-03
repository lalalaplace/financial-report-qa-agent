"""V0.4.3 公司同比对比场景测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.analyze_nodes.compare_yoy_analysis import analyze_compare_yoy_node, analyze_derived_compare_yoy_node
from agent.nodes.slot_nodes import check_slots_node
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.nodes.answer_nodes.clarify_answer import generate_unsupported_answer_node
from agent.nodes.sql_nodes.compare_yoy_sql import generate_compare_yoy_sql_node
from agent.nodes.sql_nodes.derived_sql import generate_derived_compare_yoy_sql_node
from agent.routing import route_by_intent, route_compare_yoy_metric_type
from agent.schemas.query_plan import validate_plan
from agent.utils.logger import build_agent_run_log


COMPANIES = [
    {"stock_code": "000999", "stock_abbr": "华润三九", "company_name": "华润三九医药股份有限公司"},
    {"stock_code": "600519", "stock_abbr": "贵州茅台", "company_name": "贵州茅台酒股份有限公司"},
]

REVENUE_METRIC = {
    "metric_key": "total_operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "table": "income_sheet",
    "field": "total_operating_revenue",
    "unit": "yuan",
}

NET_PROFIT_METRIC = {
    "metric_key": "net_profit",
    "metric_name": "净利润",
    "metric_type": "base",
    "table": "income_sheet",
    "field": "net_profit",
    "unit": "yuan",
}

TOTAL_ASSETS_METRIC = {
    "metric_key": "asset_total_assets",
    "metric_name": "总资产",
    "metric_type": "base",
    "table": "balance_sheet",
    "field": "asset_total_assets",
    "unit": "yuan",
}

NET_MARGIN_METRIC = {
    "metric_key": "net_profit_margin",
    "metric_name": "净利率",
    "metric_type": "derived",
    "unit": "percent",
    "scale": 100,
    "precision": 2,
    "formula": {"numerator": "net_profit", "denominator": "total_operating_revenue"},
}


def _base_state(**overrides):
    state = {
        "intent_type": "company_compare_yoy_query",
        "companies": COMPANIES,
        "metrics": [REVENUE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "report_years": [2023, 2024],
        "warnings": [],
    }
    state.update(overrides)
    return state


# ── 1. base 多指标同比对比，完整链路 ──

def test_base_compare_yoy_sql_and_answer():
    """base 多指标同比对比：SQL 生成、分析、回答生成完整链路。"""
    state = _base_state(metrics=[REVENUE_METRIC, NET_PROFIT_METRIC])

    # SQL 生成
    sql_state = generate_compare_yoy_sql_node(state)
    entries = sql_state["compare_yoy_sqls"]
    assert len(entries) == 1  # 两个指标都在 income_sheet
    assert entries[0]["table"] == "income_sheet"
    assert "total_operating_revenue" in entries[0]["metric_keys"]
    assert "net_profit" in entries[0]["metric_keys"]
    assert not entries[0]["guard_passed"]

    # 模拟 SQL 执行结果
    mock_columns = [
        "stock_code", "stock_abbr", "company_name", "report_year",
        "report_period", "income_sheet__total_operating_revenue",
        "income_sheet__net_profit",
    ]
    mock_rows = [
        ("000999", "华润三九", "华润三九医药股份有限公司", 2023, "FY", 247.39e8, 28.53e8),
        ("000999", "华润三九", "华润三九医药股份有限公司", 2024, "FY", 276.17e8, 33.68e8),
        ("600519", "贵州茅台", "贵州茅台酒股份有限公司", 2023, "FY", 1505.60e8, 747.34e8),
        ("600519", "贵州茅台", "贵州茅台酒股份有限公司", 2024, "FY", 1741.44e8, 893.30e8),
    ]

    # 分析
    yoy_state = analyze_compare_yoy_node({
        **_base_state(metrics=[REVENUE_METRIC, NET_PROFIT_METRIC]),
        "compare_yoy_query_results": [{
            "sql_id": "compare_yoy_base_income_sheet_001",
            "table": "income_sheet",
            "metric_keys": ["total_operating_revenue", "net_profit"],
            "years": [2023, 2024],
            "guard_passed": True,
            "success": True,
            "columns": mock_columns,
            "rows": mock_rows,
            "row_count": 4,
        }],
    })

    result = yoy_state["compare_yoy_result"]
    assert len(result) == 2

    # 营业收入
    rev = result[0]
    assert rev["metric_name"] == "营业收入"
    assert rev["metric_type"] == "base"
    assert rev["current_year"] == 2024
    assert rev["previous_year"] == 2023
    assert rev["status"] == "ok"
    assert rev["winner_company"] is not None
    assert rev["max_yoy_rate"] is not None
    assert rev["min_yoy_rate"] is not None
    assert rev["diff_yoy_rate"] is not None
    # 华润三九 yoy_rate ≈ 0.1163
    hualun = rev["items"][0]
    assert hualun["company_name"] == "华润三九医药股份有限公司"
    assert hualun["status"] == "ok"
    assert abs(hualun["yoy_rate"] - 0.1163) < 0.01

    # 净利润
    profit = result[1]
    assert profit["metric_name"] == "净利润"
    assert profit["winner_company"] == "贵州茅台酒股份有限公司"

    # 回答生成
    ans = generate_answer_node({
        "intent_type": "company_compare_yoy_query",
        "report_year": 2024,
        "warnings": [],
        "compare_yoy_result": result,
        "derived_compare_yoy_result": [],
    })

    answer = ans["final_answer"]
    assert "2024 年" in answer
    assert "营业收入" in answer
    assert "净利润" in answer
    assert "247.39 亿元" in answer
    assert "276.17 亿元" in answer
    assert "+11.63%" in answer or "+11.64%" in answer
    assert "高出" in answer
    assert ans["business_success"] is True


# ── 2. derived 同比对比 ──

def test_derived_compare_yoy_sql_and_answer():
    """派生指标公司同比对比：SQL 生成、分析、回答。"""
    state = _base_state(metrics=[NET_MARGIN_METRIC])

    sql_state = generate_derived_compare_yoy_sql_node(state)
    entries = sql_state["derived_compare_yoy_sqls"]
    assert len(entries) == 1
    assert entries[0]["metric_key"] == "net_profit_margin"
    assert entries[0]["numerator"] == "net_profit"
    assert entries[0]["denominator"] == "total_operating_revenue"

    mock_columns = ["stock_code", "stock_abbr", "company_name", "report_year",
                    "report_period", "numerator_value", "denominator_value"]
    mock_rows = [
        ("000999", "华润三九", "华润三九", 2023, "FY", 28.53e8, 247.39e8),
        ("000999", "华润三九", "华润三九", 2024, "FY", 33.68e8, 276.17e8),
        ("600519", "贵州茅台", "贵州茅台", 2023, "FY", 747.34e8, 1505.60e8),
        ("600519", "贵州茅台", "贵州茅台", 2024, "FY", 893.30e8, 1741.44e8),
    ]

    yoy_state = analyze_derived_compare_yoy_node({
        **_base_state(metrics=[NET_MARGIN_METRIC]),
        "derived_compare_yoy_query_results": {
            "net_profit_margin": {
                "sql_id": "derived_compare_yoy_net_profit_margin_001",
                "sql_success": True,
                "columns": mock_columns,
                "rows": mock_rows,
                "row_count": 4,
            },
        },
    })

    result = yoy_state["derived_compare_yoy_result"]
    assert len(result) == 1
    nm = result[0]
    assert nm["metric_name"] == "净利率"
    assert nm["metric_type"] == "derived"
    assert nm["current_year"] == 2024
    assert nm["previous_year"] == 2023
    assert nm["diff_unit"] == "百分点"
    assert nm["status"] == "ok"
    assert nm["winner_company"] is not None

    # 华润三九: 11.53% → 12.20%, change=0.67
    hualun = nm["items"][0]
    assert hualun["status"] == "ok"
    assert hualun["change_unit"] == "百分点"
    assert abs(hualun["previous_value"] - 11.53) < 0.1
    assert abs(hualun["current_value"] - 12.20) < 0.1
    assert abs(hualun["absolute_change"] - 0.67) < 0.1

    # 回答
    ans = generate_answer_node({
        "intent_type": "company_compare_yoy_query",
        "report_year": 2024,
        "warnings": [],
        "compare_yoy_result": [],
        "derived_compare_yoy_result": result,
    })

    answer = ans["final_answer"]
    assert "百分点" in answer
    assert "11.53%" in answer
    assert "12.20%" in answer
    # 不应出现 "同比增长" — derived 指标使用"变化"
    assert "变化" in answer


# ── 3. 混合不支持 ──

def test_mixed_compare_yoy_unsupported():
    """混合同比对比应路由到 unsupported。"""
    state = _base_state(metrics=[REVENUE_METRIC, NET_MARGIN_METRIC])

    # 准入检查
    slot_state = check_slots_node(state)
    assert slot_state["need_clarification"] is True
    assert slot_state["error_type"] == "unsupported_query"
    assert slot_state["clarification_type"] == "unsupported_metric_for_intent"
    assert slot_state["empty_fields"] == ["metrics"]

    # 路由
    route = route_compare_yoy_metric_type(state)
    assert route == "generate_unsupported_answer"

    # 回答
    ans = generate_unsupported_answer_node(slot_state)
    assert "混合" in ans["final_answer"]


# ── 4. 部分缺失 ──

def test_base_compare_yoy_partial_missing():
    """部分公司缺少年份数据时不输出误导性 winner。"""
    mock_columns = ["stock_code", "stock_abbr", "company_name", "report_year",
                    "report_period", "income_sheet__total_operating_revenue"]
    # 贵州茅台缺少2023年
    mock_rows = [
        ("000999", "华润三九", "华润三九", 2023, "FY", 247.39e8),
        ("000999", "华润三九", "华润三九", 2024, "FY", 276.17e8),
        ("600519", "贵州茅台", "贵州茅台", 2024, "FY", 1741.44e8),
    ]

    yoy_state = analyze_compare_yoy_node({
        **_base_state(),
        "compare_yoy_query_results": [{
            "sql_id": "test", "table": "income_sheet",
            "metric_keys": ["total_operating_revenue"],
            "success": True, "columns": mock_columns,
            "rows": mock_rows, "row_count": 3,
        }],
    })

    result = yoy_state["compare_yoy_result"]
    assert len(result) == 1
    assert result[0]["status"] == "partial_compare_yoy_unavailable"
    assert result[0]["winner_company"] is None  # 部分缺失不产生winner

    maotai = result[0]["items"][1]
    assert maotai["status"] == "missing_previous"

    # 回答不应有"结论"行（避免误导）
    ans = generate_answer_node({
        "intent_type": "company_compare_yoy_query",
        "report_year": 2024,
        "warnings": [],
        "compare_yoy_result": result,
        "derived_compare_yoy_result": [],
    })
    assert "缺少 2023 年数据" in ans["final_answer"]
    # 部分缺失：不输出 winner 结论
    lines = ans["final_answer"].split("\n")
    conclusion_lines = [l for l in lines if l.startswith("结论")]
    assert len(conclusion_lines) == 0


# ── 5. 零基数 ──

def test_base_compare_yoy_zero_previous():
    """上年基数为零时不计算同比率。"""
    mock_columns = ["stock_code", "stock_abbr", "company_name", "report_year",
                    "report_period", "income_sheet__total_operating_revenue"]
    mock_rows = [
        ("000999", "华润三九", "华润三九", 2023, "FY", 0),
        ("000999", "华润三九", "华润三九", 2024, "FY", 276.17e8),
        ("600519", "贵州茅台", "贵州茅台", 2023, "FY", 1505.60e8),
        ("600519", "贵州茅台", "贵州茅台", 2024, "FY", 1741.44e8),
    ]

    yoy_state = analyze_compare_yoy_node({
        **_base_state(),
        "compare_yoy_query_results": [{
            "sql_id": "test", "table": "income_sheet",
            "metric_keys": ["total_operating_revenue"],
            "success": True, "columns": mock_columns,
            "rows": mock_rows, "row_count": 4,
        }],
    })

    result = yoy_state["compare_yoy_result"]
    hualun = result[0]["items"][0]
    assert hualun["status"] == "zero_previous"
    assert hualun["yoy_rate"] is None
    assert hualun["absolute_change"] is not None  # 仍记录当年值

    # 回答
    ans = generate_answer_node({
        "intent_type": "company_compare_yoy_query",
        "report_year": 2024,
        "warnings": [],
        "compare_yoy_result": result,
        "derived_compare_yoy_result": [],
    })
    assert "基数为零" in ans["final_answer"]
    assert "无法计算同比率" in ans["final_answer"]


# ── 6. 负基数 ──

def test_base_compare_yoy_negative_previous():
    """上年值为负时仍计算同比率，但标记 warning。"""
    mock_columns = ["stock_code", "stock_abbr", "company_name", "report_year",
                    "report_period", "income_sheet__net_profit"]
    mock_rows = [
        ("000999", "华润三九", "华润三九", 2023, "FY", -10e8),
        ("000999", "华润三九", "华润三九", 2024, "FY", 5e8),
        ("600519", "贵州茅台", "贵州茅台", 2023, "FY", 100e8),
        ("600519", "贵州茅台", "贵州茅台", 2024, "FY", 120e8),
    ]

    yoy_state = analyze_compare_yoy_node({
        **_base_state(metrics=[NET_PROFIT_METRIC]),
        "compare_yoy_query_results": [{
            "sql_id": "test", "table": "income_sheet",
            "metric_keys": ["net_profit"],
            "success": True, "columns": mock_columns,
            "rows": mock_rows, "row_count": 4,
        }],
    })

    hualun = yoy_state["compare_yoy_result"][0]["items"][0]
    assert hualun["status"] == "ok"
    assert hualun["warning"] == "negative_previous_value"
    # yoy_rate = (5 - (-10)) / 10 = 1.5
    assert abs(hualun["yoy_rate"] - 1.5) < 0.01

    # 回答中应有警告
    ans = generate_answer_node({
        "intent_type": "company_compare_yoy_query",
        "report_year": 2024,
        "warnings": [],
        "compare_yoy_result": yoy_state["compare_yoy_result"],
        "derived_compare_yoy_result": [],
    })
    assert "上年值为负" in ans["final_answer"]


# ── 7. derived 分母为零 ──

def test_derived_compare_yoy_zero_denominator():
    """分母为零时标记状态，当前年值仍可计算。"""
    mock_columns = ["stock_code", "stock_abbr", "company_name", "report_year",
                    "report_period", "numerator_value", "denominator_value"]
    mock_rows = [
        ("000999", "华润三九", "华润三九", 2023, "FY", 10e8, 0),
        ("000999", "华润三九", "华润三九", 2024, "FY", 12e8, 100e8),
        ("600519", "贵州茅台", "贵州茅台", 2023, "FY", 100e8, 200e8),
        ("600519", "贵州茅台", "贵州茅台", 2024, "FY", 120e8, 220e8),
    ]

    yoy_state = analyze_derived_compare_yoy_node({
        **_base_state(metrics=[NET_MARGIN_METRIC]),
        "derived_compare_yoy_query_results": {
            "net_profit_margin": {
                "sql_id": "test", "sql_success": True,
                "columns": mock_columns, "rows": mock_rows, "row_count": 4,
            },
        },
    })

    hualun = yoy_state["derived_compare_yoy_result"][0]["items"][0]
    assert hualun["status"] == "zero_previous_denominator"
    # 当年值仍可计算: 12/100*100 = 12.0
    assert hualun["current_value"] == 12.0
    # previous_value 未计算
    assert hualun["previous_value"] is None


# ── 8. 单公司被拒 ──

def test_compare_yoy_single_company_rejected():
    """单公司同比对比应提示需要两家公司。"""
    state = {
        "intent_type": "company_compare_yoy_query",
        "companies": COMPANIES[:1],
        "metrics": [REVENUE_METRIC],
        "report_year": 2024,
    }
    result = check_slots_node(state)
    assert result["need_clarification"] is True
    assert result["error_type"] == "clarification_required"
    assert result["clarification_type"] == "missing_company"
    assert result["empty_fields"] == ["companies"]


# ── 9. 缺少年份 ──

def test_compare_yoy_missing_year_rejected():
    """缺少报告年份应提示。"""
    state = {
        "intent_type": "company_compare_yoy_query",
        "companies": COMPANIES,
        "metrics": [REVENUE_METRIC],
    }
    result = check_slots_node(state)
    assert result["need_clarification"] is True
    assert result["error_type"] == "clarification_required"
    assert result["clarification_type"] == "missing_year"
    assert result["empty_fields"] == ["report_year"]


# ── 10. 日志记录 ──

def test_logger_records_compare_yoy_fields():
    """日志应包含 V0.4.3 诊断字段。"""
    state = {
        "intent_type": "company_compare_yoy_query",
        "companies": COMPANIES,
        "metrics": [REVENUE_METRIC],
        "report_year": 2024,
        "report_period": "FY",
        "report_years": [2023, 2024],
        "compare_yoy_sqls": [{
            "sql_id": "compare_yoy_base_income_sheet_001",
            "table": "income_sheet",
            "metric_keys": ["total_operating_revenue"],
            "years": [2023, 2024],
            "guard_passed": True,
            "sql": "SELECT 1",
        }],
        "compare_yoy_query_results": [{
            "sql_id": "compare_yoy_base_income_sheet_001",
            "table": "income_sheet",
            "metric_keys": ["total_operating_revenue"],
            "years": [2023, 2024],
            "guard_passed": True,
            "success": True,
            "row_count": 4,
        }],
        "compare_yoy_result": [{
            "metric_key": "total_operating_revenue",
            "metric_name": "营业收入",
            "metric_type": "base",
            "unit": "yuan",
            "current_year": 2024,
            "previous_year": 2023,
            "status": "ok",
            "winner_company": "贵州茅台酒股份有限公司",
        }],
        "derived_compare_yoy_sqls": [{
            "sql_id": "derived_compare_yoy_net_profit_margin_001",
            "metric_key": "net_profit_margin",
            "years": [2023, 2024],
            "numerator": "net_profit",
            "denominator": "total_operating_revenue",
            "guard_passed": True,
            "sql": "SELECT 1",
        }],
        "derived_compare_yoy_query_results": {"net_profit_margin": {"sql_success": True}},
        "derived_compare_yoy_result": [{
            "metric_key": "net_profit_margin",
            "status": "ok",
            "winner_company": "贵州茅台酒股份有限公司",
        }],
    }

    record = build_agent_run_log(state)

    assert record["compare_yoy_route"] == "base"
    assert record["report_years"] == [2023, 2024]
    assert "compare_yoy_sqls" in record
    assert "compare_yoy_query_results" in record
    assert "compare_yoy_result" in record
    assert "derived_compare_yoy_sqls" in record
    assert "derived_compare_yoy_query_results" in record
    assert "derived_compare_yoy_result" in record


# ── 11. QueryPlan 补齐两年 ──

def test_query_plan_yoy_generates_report_years():
    """QueryPlan 校验时自动补齐上一年和当年。"""
    plan = validate_plan({
        "intent_type": "company_compare_yoy_query",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "single_year",
            "report_year": 2024,
            "recent_n_years": None,
            "start_year": None,
            "end_year": None,
            "report_years": [],
        },
        "need_clarification": False,
        "clarification_reason": None,
    })

    assert plan["intent_type"] == "company_compare_yoy_query"
    assert plan["time_range"]["report_years"] == [2023, 2024]
    assert plan["need_clarification"] is False


# ── 12. 跨表 base 指标分表生成 SQL ──

def test_base_compare_yoy_multi_table_sql():
    """跨表 base 指标应按表分组生成多条 SQL。"""
    state = _base_state(metrics=[REVENUE_METRIC, TOTAL_ASSETS_METRIC])

    sql_state = generate_compare_yoy_sql_node(state)
    entries = sql_state["compare_yoy_sqls"]
    assert len(entries) == 2

    income_entry = next(e for e in entries if e["table"] == "income_sheet")
    balance_entry = next(e for e in entries if e["table"] == "balance_sheet")
    assert income_entry["metric_keys"] == ["total_operating_revenue"]
    assert balance_entry["metric_keys"] == ["asset_total_assets"]


# ── 13. 跨表 derived 指标 SQL ──

def test_derived_compare_yoy_cross_table_sql():
    """跨表派生指标（ROE）SQL 应包含双 LEFT JOIN。"""
    roe_metric = {
        "metric_key": "roe",
        "metric_name": "净资产收益率",
        "metric_type": "derived",
        "unit": "percent",
        "scale": 100,
        "precision": 2,
        "formula": {"numerator": "net_profit", "denominator": "asset_total_assets"},
    }
    state = _base_state(metrics=[roe_metric])

    sql_state = generate_derived_compare_yoy_sql_node(state)
    entries = sql_state["derived_compare_yoy_sqls"]
    assert len(entries) == 1
    sql = entries[0]["sql"]
    # 跨表应有两个 LEFT JOIN
    assert sql.count("LEFT JOIN") == 2


# ── 14. 路由完整性 ──

def test_routing_integrity():
    """验证所有意图类型路由正确。"""
    # base yoy 对比
    assert route_by_intent({"intent_type": "company_compare_yoy_query",
                            "metrics": [REVENUE_METRIC]}) == "generate_compare_yoy_sql"
    # derived yoy 对比
    assert route_by_intent({"intent_type": "company_compare_yoy_query",
                            "metrics": [NET_MARGIN_METRIC]}) == "generate_derived_compare_yoy_sql"
    # 混合
    assert route_by_intent({"intent_type": "company_compare_yoy_query",
                            "metrics": [REVENUE_METRIC, NET_MARGIN_METRIC]}) == "generate_unsupported_answer"
    # 其他意图不受影响
    assert "generate_ranking_sql" == route_by_intent({"intent_type": "ranking_query"})
    assert "generate_point_sql" == route_by_intent({"intent_type": "single_metric_query"})


if __name__ == "__main__":
    tests = [
        test_base_compare_yoy_sql_and_answer,
        test_derived_compare_yoy_sql_and_answer,
        test_mixed_compare_yoy_unsupported,
        test_base_compare_yoy_partial_missing,
        test_base_compare_yoy_zero_previous,
        test_base_compare_yoy_negative_previous,
        test_derived_compare_yoy_zero_denominator,
        test_compare_yoy_single_company_rejected,
        test_compare_yoy_missing_year_rejected,
        test_logger_records_compare_yoy_fields,
        test_query_plan_yoy_generates_report_years,
        test_base_compare_yoy_multi_table_sql,
        test_derived_compare_yoy_cross_table_sql,
        test_routing_integrity,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            print(f"OK  {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"FAIL {test.__name__}: {exc}")
    print(f"\n{passed}/{len(tests)} passed")
