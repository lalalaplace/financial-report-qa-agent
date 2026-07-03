"""V0.4.0 多公司对比 10 个场景端到端测试。"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from unittest import mock
from agent.nodes.slot_nodes import resolve_company_node, map_metric_node, check_slots_node
from agent.routing import route_by_intent
from agent.nodes.sql_nodes.compare_sql import generate_compare_sql_node
from agent.nodes.sql_nodes.derived_sql import generate_derived_compare_sql_node
from agent.nodes.analyze_nodes.compare_analysis import analyze_compare_node, analyze_derived_compare_node
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.schemas.query_plan import validate_plan

# ═══════════════════ Mock 数据 ═══════════════════

COMPANY_DB = {
    "华润三九": [{"stock_code": "000999", "stock_abbr": "华润三九", "company_name": "华润三九医药股份有限公司"}],
    "白云山":   [{"stock_code": "600332", "stock_abbr": "白云山", "company_name": "广州白云山医药集团股份有限公司"}],
    "贵州茅台": [{"stock_code": "600519", "stock_abbr": "贵州茅台", "company_name": "贵州茅台酒股份有限公司"}],
    "五粮液":   [{"stock_code": "000858", "stock_abbr": "五粮液", "company_name": "宜宾五粮液股份有限公司"}],
    "茅台": [  # 歧义 mention
        {"stock_code": "600519", "stock_abbr": "贵州茅台", "company_name": "贵州茅台酒股份有限公司"},
        {"stock_code": "999999", "stock_abbr": "茅台B", "company_name": "其他茅台公司"},
    ],
}

METRIC_DB = {
    "营业收入":  [{"metric_key": "total_operating_revenue", "metric_name": "营业收入", "metric_type": "base",
                   "table": "income_sheet", "field": "total_operating_revenue", "unit": "yuan",
                   "aliases": ["营业收入", "营收"]}],
    "总资产":    [{"metric_key": "asset_total_assets", "metric_name": "总资产", "metric_type": "base",
                   "table": "balance_sheet", "field": "asset_total_assets", "unit": "yuan",
                   "aliases": ["总资产", "资产总计"]}],
    "净利润":    [{"metric_key": "net_profit", "metric_name": "净利润", "metric_type": "base",
                   "table": "income_sheet", "field": "net_profit", "unit": "yuan",
                   "aliases": ["净利润"]}],
    "净利率":    [{"metric_key": "net_profit_margin", "metric_name": "净利率", "metric_type": "derived",
                   "unit": "percent", "scale": 100, "precision": 2,
                   "aliases": ["净利率", "销售净利率"],
                   "formula": {"numerator": "net_profit", "denominator": "total_operating_revenue"}}],
    "资产负债率": [{"metric_key": "debt_to_asset_ratio", "metric_name": "资产负债率", "metric_type": "derived",
                   "unit": "percent", "scale": 100, "precision": 2,
                   "aliases": ["资产负债率", "负债率"],
                   "formula": {"numerator": "liability_total_liabilities", "denominator": "asset_total_assets"}}],
}

SQL_RESULTS = {
    "income_sheet": {
        "000999": {"income_sheet__total_operating_revenue": 24500000000.0, "income_sheet__net_profit": 3100000000.0},
        "600332": {"income_sheet__total_operating_revenue": 64000000000.0, "income_sheet__net_profit": 4200000000.0},
        "600519": {"income_sheet__total_operating_revenue": 173000000000.0, "income_sheet__net_profit": 8700000000.0},
        "000858": {"income_sheet__total_operating_revenue": 83000000000.0, "income_sheet__net_profit": 3200000000.0},
    },
    "balance_sheet": {
        "000999": {"balance_sheet__asset_total_assets": 40000000000.0, "balance_sheet__liability_total_liabilities": 18000000000.0},
        "600332": {"balance_sheet__asset_total_assets": 78000000000.0, "balance_sheet__liability_total_liabilities": 42000000000.0},
        "600519": {"balance_sheet__asset_total_assets": 270000000000.0, "balance_sheet__liability_total_liabilities": 50000000000.0},
        "000858": {"balance_sheet__asset_total_assets": 120000000000.0, "balance_sheet__liability_total_liabilities": 30000000000.0},
    },
}


def mock_resolve_company(query_text):
    candidates = COMPANY_DB.get(query_text, [])
    return {"matched": len(candidates) == 1, "need_clarification": len(candidates) > 1,
            "candidates": candidates}


def mock_map_metrics(question):
    for alias, metrics in METRIC_DB.items():
        if alias in question:
            return {"matched": True, "metrics": [dict(m) for m in metrics],
                    "need_clarification": False, "clarification_question": None}
    return {"matched": False, "metrics": [], "need_clarification": True,
            "clarification_question": "请说明你要查询的财务指标"}


def mock_review_sql(sql):
    return {"is_safe": True, "reason": "", "corrected_sql": None}


# stock_code → company info lookup
CODE_TO_COMPANY = {
    "000999": {"stock_code": "000999", "stock_abbr": "华润三九", "company_name": "华润三九医药股份有限公司"},
    "600332": {"stock_code": "600332", "stock_abbr": "白云山", "company_name": "广州白云山医药集团股份有限公司"},
    "600519": {"stock_code": "600519", "stock_abbr": "贵州茅台", "company_name": "贵州茅台酒股份有限公司"},
    "000858": {"stock_code": "000858", "stock_abbr": "五粮液", "company_name": "宜宾五粮液股份有限公司"},
}


def mock_execute_sql(sql):
    for table in ["income_sheet", "balance_sheet"]:
        if table not in sql:
            continue
        rows = []
        all_fields = set()
        for code, fields in SQL_RESULTS.get(table, {}).items():
            if code in sql:
                info = CODE_TO_COMPANY.get(code, {"stock_code": code, "stock_abbr": code, "company_name": code})
                row = [code, info["stock_abbr"], info["company_name"], 2024, "FY"]
                for col, val in fields.items():
                    row.append(val)
                    all_fields.add(col)
                rows.append(row)
        if rows:
            columns = ["stock_code", "stock_abbr", "company_name", "report_year", "report_period"] + sorted(all_fields)
            return {"success": True, "columns": columns, "rows": rows, "row_count": len(rows), "error": None}
    return {"success": True, "columns": [], "rows": [], "row_count": 0, "error": None}


# ═══════════════════ 公共 helper ═══════════════════

def _run_pipeline(state, *, execute=False):
    """运行 resolve → map → check_slots → route → sql 链路。"""
    with mock.patch("agent.nodes.slot_nodes.resolve_company", side_effect=mock_resolve_company):
        state.update(resolve_company_node(state))
    with mock.patch("agent.nodes.slot_nodes.map_metrics", side_effect=mock_map_metrics):
        state.update(map_metric_node(state))
    state.update(check_slots_node(state))

    if state.get("need_clarification"):
        return state

    next_node = route_by_intent(state)
    if next_node == "generate_compare_sql":
        state.update(generate_compare_sql_node(state))
    elif next_node == "generate_derived_compare_sql":
        state.update(generate_derived_compare_sql_node(state))

    if execute:
        with mock.patch("agent.nodes.execute_sql_handlers.review_sql", side_effect=mock_review_sql):
            with mock.patch("agent.nodes.execute_sql_handlers._invoke_execute_financial_sql", side_effect=mock_execute_sql):
                from agent.nodes.execute_sql_node import review_and_execute_sql_node
                state.update(review_and_execute_sql_node(state))
        if state.get("compare_query_results"):
            state.update(analyze_compare_node(state))
        if state.get("derived_compare_query_results"):
            state.update(analyze_derived_compare_node(state))
        state.update(generate_answer_node(state))

    return state


# ═══════════════════ 测试场景 ═══════════════════


def test_01_two_companies_one_base_metric():
    """华润三九和贵州茅台 2024 年营业收入谁更高？→ compare, base, 2 companies"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "intent_type": "company_compare_query",
        "report_year": 2024,
    }, execute=True)

    assert len(state["compare_sqls"]) == 1
    assert state["compare_sqls"][0]["table"] == "income_sheet"
    assert len(state["compare_result"]) == 1
    assert state["compare_result"][0]["status"] == "ok"
    assert state["compare_result"][0]["winner_company"] is not None
    assert "更高" in state["final_answer"]


def test_02_two_companies_two_base_metrics():
    """华润三九和白云山 2024 年总资产和净利润对比 → compare, base, 2 metrics"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["华润三九", "白云山"],
        "metric_mentions": ["总资产", "净利润"],
        "intent_type": "company_compare_query",
        "report_year": 2024,
    })

    tables = {s["table"] for s in state["compare_sqls"]}
    assert tables == {"balance_sheet", "income_sheet"}
    assert len(state["compare_sqls"]) == 2


def test_03_three_companies_one_base_metric():
    """华润三九、白云山、贵州茅台 2024 年营业收入对比 → compare, 3 companies"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["华润三九", "白云山", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "intent_type": "company_compare_query",
        "report_year": 2024,
    })

    assert len(state["companies"]) == 3
    sql = state["compare_sqls"][0]["sql"]
    for code in ["000999", "600332", "600519"]:
        assert code in sql


def test_04_two_companies_derived():
    """贵州茅台和五粮液 2024 年净利率谁更高？→ compare, derived"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["贵州茅台", "五粮液"],
        "metric_mentions": ["净利率"],
        "intent_type": "company_compare_query",
        "report_year": 2024,
    })

    assert route_by_intent(state) == "generate_derived_compare_sql"
    assert len(state["derived_compare_sqls"]) == 1


def test_05_three_companies_derived():
    """华润三九、白云山、贵州茅台 2024 年资产负债率对比 → derived, 3 companies"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["华润三九", "白云山", "贵州茅台"],
        "metric_mentions": ["资产负债率"],
        "intent_type": "company_compare_query",
        "report_year": 2024,
    })

    assert len(state["companies"]) == 3
    sql = state["derived_compare_sqls"][0]["sql"]
    assert "balance_sheet" in sql
    for code in ["000999", "600332", "600519"]:
        assert code in sql


def test_06_mixed_base_derived_unsupported():
    """华润三九和贵州茅台 2024 年营业收入和净利率对比 → unsupported_mixed_compare"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入", "净利率"],
        "intent_type": "company_compare_query",
        "report_year": 2024,
    })

    assert state["need_clarification"]
    assert state["error_type"] == "unsupported_query"
    assert state["clarification_type"] == "unsupported_metric_for_intent"
    assert state["empty_fields"] == ["metrics"]


def test_07_missing_year_clarify():
    """华润三九和贵州茅台 营业收入谁更高？→ clarify_year"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "intent_type": "company_compare_query",
        # 不传 report_year
    })

    assert state["need_clarification"]
    assert state["error_type"] == "clarification_required"
    assert state["clarification_type"] == "missing_year"
    assert state["empty_fields"] == ["report_year"]


def test_08_ambiguous_company_clarify():
    """茅台和五粮液 2024 年净利润谁更高？→ clarify_company（茅台歧义）"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["茅台", "五粮液"],
        "metric_mentions": ["净利润"],
        "intent_type": "company_compare_query",
        "report_year": 2024,
    })

    assert state["need_clarification"]
    assert state["error_type"] == "clarification_required"
    assert state["clarification_type"] == "ambiguous_company"
    assert state["empty_fields"] == ["companies"]
    assert "茅台" in state["clarification_question"]


def test_09_ranking_supported_v050():
    """2024 年营业收入最高的前 10 家公司是谁？→ V0.5.0 起 ranking_query 已支持"""
    plan = validate_plan({
        "intent_type": "ranking_query",
        "company_mentions": [],
        "metric_mentions": ["营业收入"],
        "report_period": "FY",
        "time_range": {"mode": "single_year", "report_year": 2024},
    })
    assert plan["intent_type"] == "ranking_query"
    assert not plan["need_clarification"]

    state = {
        "user_question": "", "company_mentions": [], "metric_mentions": ["营业收入"],
        "intent_type": "ranking_query", "report_year": 2024, "report_period": "FY",
        "companies": [], "metrics": METRIC_DB["营业收入"], "metric_candidates": [],
        "rank_direction": "desc", "limit": 10,
        "time_range": {"mode": "single_year", "report_year": 2024},
    }
    state.update(check_slots_node(state))
    assert state["need_clarification"] is False
    assert state["error_type"] is None


def test_10_compare_trend_unsupported():
    """华润三九和贵州茅台 营业收入趋势对比 → 暂不支持公司趋势对比"""
    state = _run_pipeline({
        "user_question": "",
        "company_mentions": ["华润三九", "贵州茅台"],
        "metric_mentions": ["营业收入"],
        "intent_type": "trend_query",
        "time_mode": "recent_n",
        "recent_n_years": 5,
    })

    # trend_query + 多公司：resolve_company_node 返回 candidates（非 compare 不自动确认）
    # check_slots_node 展示候选列表要求选择一家
    assert state.get("need_clarification"), "多公司趋势查询应被拦截"
    assert "哪家公司" in state.get("clarification_question", "") or \
           "单公司" in state.get("clarification_question", ""), \
           f"unexpected msg: {state.get('clarification_question', '')}"


# ═══════════════════ 运行 ═══════════════════

if __name__ == "__main__":
    tests = [
        test_01_two_companies_one_base_metric,
        test_02_two_companies_two_base_metrics,
        test_03_three_companies_one_base_metric,
        test_04_two_companies_derived,
        test_05_three_companies_derived,
        test_06_mixed_base_derived_unsupported,
        test_07_missing_year_clarify,
        test_08_ambiguous_company_clarify,
        test_09_ranking_supported_v050,
        test_10_compare_trend_unsupported,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            print(f"OK  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"FAIL {test.__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
