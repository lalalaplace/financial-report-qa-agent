"""Flexible SQL 语义合同与支持边界回归测试。"""

from agent.schemas.flexible_sql_spec import compile_flexible_sql_spec
from agent.nodes.capability_router import route_query_capability
from agent.nodes.target_graph_nodes import query_spec_validator_node
from agent.tools.metric_tools import load_metric_dictionary
from agent.validators.sql_semantic_validator import validate_llm_sql_semantics


def _derived_metric() -> dict:
    return {
        "metric_key": "debt_to_asset_ratio",
        "metric_name": "资产负债率",
        "metric_type": "derived",
        "unit": "percent",
        "formula": {"numerator": "liability_total_liabilities", "denominator": "asset_total_assets"},
    }


def test_contract_registers_formula_dependencies_and_normalizes_percentage() -> None:
    spec = compile_flexible_sql_spec(
        {
            "metrics": ["资产负债率"],
            "filters": [{"metric": "资产负债率", "operator": ">", "value": 50}],
            "time_scope": {"year": 2024, "period": "FY"},
        },
        [], [_derived_metric()], {"balance_sheet": ["stock_code", "report_year", "report_period", "total_liabilities", "total_assets"]},
    )

    contract = spec["semantic_contract"]
    assert contract["formula_dependencies"] == ["balance_sheet.liability_total_liabilities", "balance_sheet.asset_total_assets"]
    assert contract["normalized_thresholds"][0]["normalized_value"] == 0.5


def test_contract_rejects_null_derived_metric_placeholder() -> None:
    spec = compile_flexible_sql_spec(
        {"metrics": ["资产负债率"], "time_scope": {"year": 2024, "period": "FY"}},
        [], [_derived_metric()], {"balance_sheet": ["stock_code", "report_year", "report_period", "total_liabilities", "total_assets"]},
    )
    result = validate_llm_sql_semantics(
        "SELECT stock_code, total_liabilities, total_assets, NULL AS debt_to_asset_ratio "
        "FROM balance_sheet WHERE report_year = 2024 AND report_period = 'FY' LIMIT 10",
        request={"flexible_sql_spec": spec}, metrics=[],
    )

    assert result["error_type"] == "SQL_CONTRACT_FORMULA_INVALID"


def test_nested_top_n_is_rejected_before_sql_generation() -> None:
    try:
        compile_flexible_sql_spec(
            {
                "operation": "nested_top_n", "metrics": ["营业收入"],
                "set_operations": [{"type": "top_n", "metric": "营业收入", "n": 20, "output": "a"}, {"type": "top_n", "metric": "营业收入", "n": 10, "input": "a", "output": "b"}],
            },
            [], [{"metric_key": "revenue", "metric_name": "营业收入", "table": "income_sheet", "field": "total_operating_revenue"}],
            {"income_sheet": ["stock_code", "report_year", "report_period", "total_operating_revenue"]},
        )
    except ValueError as exc:
        assert str(exc).startswith("UNSUPPORTED_FLEXIBLE_SQL:")
    else:
        raise AssertionError("嵌套 Top N 不应进入 SQL 生成")


def test_yoy_percentage_thresholds_are_normalized_once_in_contract() -> None:
    metrics = [
        {"metric_key": "revenue", "metric_name": "营业收入", "table": "income_sheet", "field": "total_operating_revenue", "unit": "yuan"},
        {"metric_key": "net_profit", "metric_name": "净利润", "table": "income_sheet", "field": "net_profit", "unit": "yuan"},
    ]
    spec = compile_flexible_sql_spec(
        {
            "operation": "multi_metric_yoy_filter",
            "metrics": ["营业收入", "净利润"],
            "filters": [
                {"metric": "营业收入同比", "operator": ">", "value": 5},
                {"metric": "净利润同比", "operator": ">", "value": 10},
            ],
            "sort": [{"metric": "净利润同比", "direction": "desc"}],
            "time_scope": {"year": 2024, "period": "FY"},
            "limit": 50,
        },
        [], metrics, {"income_sheet": ["stock_code", "report_year", "report_period", "total_operating_revenue", "net_profit"]},
    )

    thresholds = spec["semantic_contract"]["normalized_thresholds"]
    assert [item["normalized_value"] for item in thresholds] == [0.05, 0.1]


def test_intersection_stage_has_stable_contract_name() -> None:
    spec = compile_flexible_sql_spec(
        {
            "metrics": ["营业收入", "净利润"],
            "set_operations": [
                {"type": "top_n", "metric": "营业收入", "n": 20, "output": "revenue_top20"},
                {"type": "top_n", "metric": "净利润", "n": 20, "output": "profit_top20"},
                {"type": "intersection", "inputs": ["revenue_top20", "profit_top20"]},
            ],
            "time_scope": {"year": 2024, "period": "FY"},
        },
        [],
        [
            {"metric_key": "revenue", "metric_name": "营业收入", "table": "income_sheet", "field": "total_operating_revenue"},
            {"metric_key": "net_profit", "metric_name": "净利润", "table": "income_sheet", "field": "net_profit"},
        ],
        {"income_sheet": ["stock_code", "report_year", "report_period", "total_operating_revenue", "net_profit"]},
    )

    assert spec["semantic_contract"]["stages"][-1]["stage_id"] == "intersection_stage"


def test_registered_derived_metric_filter_recovers_from_planner_unsupported() -> None:
    result = query_spec_validator_node(
        {
            "user_question": "找出 2024 年资产负债率低于 50% 的公司，按资产负债率从低到高取前 10 家。",
            "query_spec": {
                "execution_mode": "unsupported",
                "operation": "unknown",
                "unsupported_reason": "Planner 未识别指标。",
                "clarification_question": None,
            },
            "metrics": [_derived_metric()],
            "metric_candidates": [],
            "companies": [],
            "company_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
            "company_source": "all_companies",
            "is_global_structured_query": True,
        }
    )

    spec = result["query_spec"]
    assert result["query_spec_validation_status"] == "valid"
    assert spec["execution_mode"] == "flexible_sql"
    assert spec["filters"] == [{"metric": "资产负债率", "operator": "<", "value": 50}]
    assert spec["sort"] == [{"metric": "资产负债率", "direction": "asc"}]
    assert spec["limit"] == 10


def test_derived_metric_point_query_uses_registered_formula_builder() -> None:
    result = query_spec_validator_node(
        {
            "user_question": "华润三九 2024 年净利率是多少？",
            "query_spec": {
                "execution_mode": "deterministic",
                "operation": "point_query",
                "clarification_question": None,
            },
            "metrics": [{
                "metric_key": "net_profit_margin",
                "metric_name": "净利率",
                "metric_type": "derived",
                "formula": {"numerator": "net_profit", "denominator": "total_operating_revenue"},
            }],
            "metric_candidates": [],
            "companies": [{"stock_code": "000999"}],
            "company_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
        }
    )

    assert result["intent_type"] == "derived_metric_query"
    assert result["query_spec"]["operation"] == "derived_metric_query"


def test_derived_metric_yoy_query_uses_registered_formula_builder() -> None:
    result = query_spec_validator_node(
        {
            "user_question": "华润三九 2024 年净利率同比变化多少？",
            "query_spec": {
                "execution_mode": "unsupported",
                "operation": "unknown",
                "unsupported_reason": "暂不支持",
                "clarification_question": None,
            },
            "metrics": [{
                "metric_key": "net_profit_margin",
                "metric_name": "净利率",
                "metric_type": "derived",
                "formula": {"numerator": "net_profit", "denominator": "total_operating_revenue"},
            }],
            "metric_candidates": [],
            "companies": [{"stock_code": "000999"}],
            "company_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
        }
    )

    assert result["query_spec_validation_status"] == "valid"
    assert result["intent_type"] == "yoy_query"
    assert result["query_spec"]["operation"] == "yoy_query"
    assert result["query_spec"]["execution_mode"] == "deterministic"


def test_single_registered_metric_filter_keeps_flexible_sql_route() -> None:
    decision = route_query_capability(
        {
            "query_spec": {
                "execution_mode": "flexible_sql",
                "operation": "metric_threshold_filter",
                "filters": [{"metric": "资产负债率", "operator": "<", "value": 50}],
                "sort": [{"metric": "资产负债率", "direction": "asc"}],
                "unsupported_reason": None,
            }
        }
    )

    assert decision["execution_mode"] == "flexible_sql"


def test_contract_accepts_derived_formula_with_table_alias_in_nullif() -> None:
    metric_dictionary = load_metric_dictionary()
    metric = {"metric_key": "debt_to_asset_ratio", **metric_dictionary["debt_to_asset_ratio"]}
    spec = compile_flexible_sql_spec(
        {
            "execution_mode": "flexible_sql",
            "operation": "metric_threshold_filter",
            "metrics": ["资产负债率"],
            "time_scope": {"year": 2024, "period": "FY"},
            "filters": [{"metric": "资产负债率", "operator": "<", "value": 50}],
            "sort": [{"metric": "资产负债率", "direction": "asc"}],
            "limit": 10,
        },
        [],
        [metric],
        {"balance_sheet": ["stock_code", "report_year", "report_period", "liability_total_liabilities", "asset_total_assets"]},
    )
    sql = (
        "SELECT b.stock_code, b.liability_total_liabilities / "
        "NULLIF(b.asset_total_assets, 0) AS debt_to_asset_ratio "
        "FROM balance_sheet b WHERE b.report_year = 2024 AND b.report_period = 'FY' "
        "AND b.liability_total_liabilities / NULLIF(b.asset_total_assets, 0) < 0.5 "
        "ORDER BY debt_to_asset_ratio ASC LIMIT 10"
    )

    result = validate_llm_sql_semantics(sql, request={"flexible_sql_spec": spec}, metrics=[metric])

    assert result["semantic_guard_passed"] is True
