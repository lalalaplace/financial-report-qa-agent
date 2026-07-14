"""真实端到端验证暴露问题的回归测试。"""

from __future__ import annotations

from agent.nodes.context_llm_nodes import context_router_node
from agent.nodes.target_graph_nodes import flexible_sql_spec_builder_node, query_spec_validator_node
from agent.schemas.query_spec import normalize_query_spec
from db.sql_llm_guard import validate_llm_sql_static
from agent.nodes import llm_sql_node
from agent.nodes.llm_sql_repair_node import _build_prompt as build_repair_prompt
from agent.schemas.flexible_sql_spec import flexible_sql_spec_from_query_spec
from agent.validators.sql_semantic_validator import validate_llm_sql_semantics


def test_flexible_sql_spec_builder_persists_formal_spec() -> None:
    result = flexible_sql_spec_builder_node({
        "user_question": "找出净利润同比超过 50% 的公司",
        "query_spec": {"metrics": ["净利润"], "filters": [{"metric": "净利润", "operator": ">", "value": 0.5}], "time_scope": {"year": 2024, "period": "FY"}},
        "planning": {"normalization": {"metrics": [{"metric_key": "net_profit", "metric_name": "净利润", "table": "income_sheet", "field": "net_profit"}], "companies": []}},
    })

    assert result["flexible_sql_spec"]["filters"][0]["metric"] == "净利润"
    assert result["execution"]["flexible_sql_spec"] == result["flexible_sql_spec"]
    assert result["flexible_sql_spec"]["source_tables"] == ["income_sheet"]


def test_flexible_sql_spec_preserves_query_spec_set_operations() -> None:
    set_operations = [
        {"type": "top_n", "metric": "营业收入", "n": 20, "output": "revenue_top20"},
        {"type": "top_n", "metric": "净利润", "n": 20, "output": "profit_top20"},
        {"type": "intersection", "inputs": ["revenue_top20", "profit_top20"]},
    ]
    result = flexible_sql_spec_builder_node({
        "user_question": "查询交集",
        "query_spec": {"metrics": ["营业收入", "净利润"], "set_operations": set_operations, "time_scope": {"year": 2024, "period": "FY"}},
        "metrics": [
            {"metric_key": "total_operating_revenue", "metric_name": "营业收入", "table": "income_sheet", "field": "total_operating_revenue"},
            {"metric_key": "net_profit", "metric_name": "净利润", "table": "income_sheet", "field": "net_profit"},
        ],
    })

    assert result["flexible_sql_spec"]["set_operations"] == set_operations


def test_flexible_sql_spec_compiles_normalized_entity_constraint() -> None:
    result = flexible_sql_spec_builder_node({
        "query_spec": {"metrics": ["净利润"], "time_scope": {"year": 2024, "period": "FY"}},
        "planning": {"normalization": {"metrics": [{"metric_key": "net_profit", "metric_name": "净利润", "table": "income_sheet", "field": "net_profit"}], "companies": [{"stock_code": "000999", "company_name": "华润三九"}]}},
    })

    assert result["execution"]["flexible_sql_spec"]["entity_constraints"] == [{"stock_code": "000999"}]


def test_semantic_check_rejects_sql_without_compiled_entity_constraint() -> None:
    from agent.validators.sql_semantic_validator import validate_llm_sql_semantics

    result = validate_llm_sql_semantics(
        "SELECT stock_code, net_profit FROM income_sheet WHERE report_year = 2024",
        request={"flexible_sql_spec": {"entity_constraints": [{"stock_code": "000999"}]}},
        metrics=[{"table": "income_sheet", "field": "net_profit"}],
    )

    assert result["is_valid"] is False
    assert result["error_type"] == "SQL_SEMANTIC_INVALID"


def test_guard_allows_lag_and_row_number_window_functions() -> None:
    sql = """
    WITH ranked AS (
      SELECT i.stock_code, i.report_year,
             LAG(i.net_profit) OVER (PARTITION BY i.stock_code ORDER BY i.report_year) AS previous_value,
             ROW_NUMBER() OVER (ORDER BY i.net_profit DESC) AS row_num
      FROM income_sheet i
      WHERE i.report_year IN (2023, 2024)
    )
    SELECT r.stock_code, r.report_year, r.previous_value, r.row_num
    FROM ranked r
    WHERE r.report_year = 2024
    ORDER BY r.row_num
    LIMIT 20
    """
    result = validate_llm_sql_static(
        sql,
        allowed_tables=["income_sheet"],
        allowed_columns={"income_sheet": ["stock_code", "report_year", "net_profit"]},
    )

    assert result["is_valid"] is True, result


def test_guard_applies_max_rows_to_final_limit_only() -> None:
    sql = """
    WITH top30 AS (
      SELECT i.stock_code, i.report_year, i.net_profit
      FROM income_sheet i
      WHERE i.report_year = 2024 AND i.report_period = 'FY'
      ORDER BY i.net_profit DESC
      LIMIT 30
    )
    SELECT t.stock_code, t.report_year, t.net_profit
    FROM top30 t
    ORDER BY t.net_profit DESC
    LIMIT 10
    """
    result = validate_llm_sql_static(
        sql, allowed_tables=["income_sheet"],
        allowed_columns={"income_sheet": ["stock_code", "report_year", "report_period", "net_profit"]},
        max_rows=10,
    )

    assert result["is_valid"] is True, result


def test_guard_parses_join_alias_after_cte_source() -> None:
    sql = """
    WITH calc AS (
      SELECT i.stock_code, i.report_year, i.net_profit
      FROM income_sheet i
      WHERE i.report_year = 2024 AND i.report_period = 'FY'
    )
    SELECT c.stock_code, d.stock_abbr, d.company_name, c.report_year, c.net_profit
    FROM calc c
    JOIN company_dim d ON c.stock_code = d.stock_code
    ORDER BY c.net_profit DESC
    LIMIT 10
    """
    result = validate_llm_sql_static(
        sql, allowed_tables=["income_sheet", "company_dim"],
        allowed_columns={
            "income_sheet": ["stock_code", "report_year", "report_period", "net_profit"],
            "company_dim": ["stock_code", "stock_abbr", "company_name"],
        },
    )

    assert result["is_valid"] is True, result


def test_guard_handles_alias_reuse_across_cte_scopes() -> None:
    sql = """
    WITH current_year AS (
      SELECT i.stock_code, i.report_year, i.net_profit
      FROM income_sheet i
      WHERE i.report_year = 2024 AND i.report_period = 'FY'
    ), combined AS (
      SELECT c.stock_code, c.report_year, c.net_profit
      FROM current_year c
    )
    SELECT c.stock_code, c.stock_abbr, m.report_year, m.net_profit
    FROM combined m
    JOIN company_dim c ON m.stock_code = c.stock_code
    ORDER BY m.net_profit DESC
    LIMIT 10
    """
    result = validate_llm_sql_static(
        sql, allowed_tables=["income_sheet", "company_dim"],
        allowed_columns={
            "income_sheet": ["stock_code", "report_year", "report_period", "net_profit"],
            "company_dim": ["stock_code", "stock_abbr", "company_name"],
        },
    )

    assert result["is_valid"] is True, result


def test_entity_ranking_without_top_n_normalizes_to_rank_position() -> None:
    spec = normalize_query_spec({
        "execution_mode": "deterministic", "operation": "ranking_query",
        "entities": ["华润三九"], "metrics": ["营业收入"], "limit": None,
    })

    assert spec["operation"] == "rank_position_query"


def test_point_ranking_variant_normalizes_to_rank_position() -> None:
    spec = normalize_query_spec({
        "execution_mode": "deterministic", "operation": "point_ranking",
        "entities": ["华润三九"], "metrics": ["营业收入"],
    })

    assert spec["operation"] == "rank_position_query"


def test_rank_query_variant_normalizes_to_rank_position() -> None:
    spec = normalize_query_spec({
        "execution_mode": "deterministic", "operation": "rank_query",
        "entities": ["华润三九"], "metrics": ["营业收入"],
    })

    assert spec["operation"] == "rank_position_query"


def test_chained_top_n_is_not_normalized_as_intersection() -> None:
    spec = normalize_query_spec({
        "execution_mode": "flexible_sql", "operation": "set_intersection_ranking",
        "set_operations": [
            {"type": "top_n", "metric": "营业收入", "n": 30, "output": "top30"},
            {"type": "top_n", "metric": "净利率", "n": 10, "input": "top30"},
        ],
    })

    assert spec["operation"] == "nested_top_n"


def test_yoy_with_year_does_not_require_redundant_clarification() -> None:
    spec = normalize_query_spec({
        "execution_mode": "flexible_sql", "operation": "metric_threshold_filter",
        "metrics": ["净利润同比"], "time_scope": {"year": 2024, "period": "FY"},
        "clarification_question": "同比是否基于上一年？",
    })

    assert spec["clarification_question"] is None


def test_deterministic_yoy_semantics_normalize_operation() -> None:
    spec = normalize_query_spec({
        "execution_mode": "deterministic", "operation": "comparable_point_query",
        "entities": ["华润三九"], "metrics": ["营业收入同比"],
        "time_scope": {"year": 2024, "period": "FY"},
    })

    assert spec["operation"] == "yoy_query"


def test_generic_company_scope_is_not_an_entity() -> None:
    spec = normalize_query_spec({
        "execution_mode": "flexible_sql", "operation": "metric_threshold_filter",
        "entities": ["公司"], "metrics": ["净利润"],
    })

    assert spec["entities"] == []


def test_clarification_has_priority_over_unsupported() -> None:
    spec = normalize_query_spec({
        "execution_mode": "unsupported", "operation": "compare_entities",
        "entities": ["华润三九", "白云山"], "metrics": [],
        "unsupported_reason": "缺少指标", "clarification_question": "请补充比较指标和年份。",
    })
    result = query_spec_validator_node({"query_spec": spec, "user_question": "比较华润三九和白云山"})

    assert spec["unsupported_reason"] is None
    assert result["query_spec_validation_status"] == "need_clarification"


def test_external_capability_query_is_sent_to_planner_boundary() -> None:
    result = context_router_node({"user_question": "分析这些公司股价未来一个月的走势。"})

    assert result["route_type"] == "new_query"
    assert result["target_context"] == "none"


def test_dry_run_failure_enters_single_repair() -> None:
    from agent.target_graph_routing import route_after_dry_run

    state = {"planning": {"capability_decision": {"execution_mode": "flexible_sql"}}, "execution": {"dry_run_result": {"success": False}}}
    assert route_after_dry_run(state) == "llm_sql_repair"
    state["sql_repair_attempted"] = True
    assert route_after_dry_run(state) == "controlled_failure"


def test_guard_uses_safe_default_limit_when_request_is_incomplete() -> None:
    from agent.nodes import target_graph_nodes

    result = target_graph_nodes.sql_guard_node({
        "execution": {"execution_mode": "flexible_sql", "generated_sql": "SELECT 1 LIMIT 10"},
        "llm_sql_request": {"allowed_tables": [], "allowed_columns": {}},
        "metrics": [],
    })

    assert result["sql_guard_status"] == "passed"


def test_semantic_check_rejects_yoy_sql_scaled_as_percent() -> None:
    sql = """
    SELECT c.stock_code, (c.net_profit - p.net_profit)
      / NULLIF(ABS(p.net_profit), 0) * 100 AS yoy_rate
    FROM income_sheet c JOIN income_sheet p ON c.stock_code = p.stock_code
    WHERE c.report_year = 2024 AND p.report_year = 2023
      AND c.report_period = 'FY' AND p.report_period = 'FY'
    """
    result = validate_llm_sql_semantics(
        sql,
        request={"sql_task_type": "yoy_direction_filter_sort", "report_year": 2024},
        metrics=[{"table": "income_sheet", "field": "net_profit"}],
    )

    assert result["is_valid"] is False
    assert result["error_type"] == "YOY_SCALE_INVALID"


def test_semantic_check_accepts_percentage_threshold_as_decimal_ratio() -> None:
    sql = """
    SELECT c.stock_code, (c.net_profit - p.net_profit)
      / NULLIF(ABS(p.net_profit), 0) AS yoy_rate
    FROM income_sheet c JOIN income_sheet p ON c.stock_code = p.stock_code
    WHERE c.report_year = 2024 AND p.report_year = 2023
      AND c.report_period = 'FY' AND p.report_period = 'FY'
      AND (c.net_profit - p.net_profit) / NULLIF(ABS(p.net_profit), 0) > 0.5
    """
    result = validate_llm_sql_semantics(
        sql,
        request={
            "sql_task_type": "multi_metric_yoy_filter", "report_year": 2024,
            "flexible_sql_spec": {"filters": [{"metric": "净利润同比", "operator": ">", "value": 50}]},
        },
        metrics=[{"table": "income_sheet", "field": "net_profit"}],
    )

    assert result["is_valid"] is True, result


def test_nested_top_n_is_compiled_into_ordered_stages() -> None:
    spec = flexible_sql_spec_from_query_spec(
        {
            "operation": "nested_top_n",
            "metrics": ["营业收入", "净利率"],
            "set_operations": [
                {"type": "top_n", "metric": "营业收入", "n": 30, "output": "revenue_top30", "direction": "desc"},
                {"type": "top_n", "metric": "净利率", "n": 10, "input": "revenue_top30", "output": "margin_top10", "direction": "desc"},
            ],
            "sort": [{"metric": "净利率", "direction": "desc"}],
        },
        [],
        ["income_sheet"],
    )

    assert spec["operation"] == "nested_top_n"
    assert spec["stages"] == [
        {"stage_id": "revenue_top30", "operation": "top_n", "metric": "营业收入", "limit": 30, "partition": [], "order": "desc", "exclude_null_metric": True},
        {"stage_id": "margin_top10", "operation": "top_n", "input_stage": "revenue_top30", "metric": "净利率", "limit": 10, "partition": [], "order": "desc", "exclude_null_metric": True},
    ]
    assert spec["final_order"] == [{"metric": "净利率", "direction": "desc"}]
    assert spec["display_limit"] == 10


def test_sql_generator_request_contains_only_compiled_sql_contract() -> None:
    request = llm_sql_node._build_request({
        "user_question": "很长的原始问题，不应发送到 SQL Generator",
        "query_plan": {"legacy": True},
        "llm_sql_requirement": {"legacy": True},
        "execution": {"flexible_sql_spec": {"limit": 10, "question": ""}},
        "metrics": [{"metric_key": "net_profit", "metric_name": "净利润", "table": "income_sheet", "field": "net_profit"}],
    })

    assert set(request) == {
        "flexible_sql_spec", "allowed_tables", "allowed_columns", "metric_bindings",
        "max_rows", "required_output_fields", "sql_dialect", "sql_constraints",
    }
    assert "user_question" not in str(request)
    assert "legacy" not in str(request)


def test_sql_repair_prompt_excludes_old_semantic_inputs() -> None:
    prompt = build_repair_prompt({
        "original_question": "不应进入修复器",
        "llm_sql_requirement": {"legacy": True},
        "flexible_sql_spec": {"operation": "nested_top_n"},
        "allowed_tables": ["income_sheet"],
        "allowed_columns": {"income_sheet": ["stock_code"]},
        "metric_bindings": [],
        "candidate_sql": "SELECT stock_code FROM income_sheet LIMIT 1",
        "validation_error": {"error_type": "SQL_PARSE_ERROR"},
        "max_rows": 10,
    })

    assert "不应进入修复器" not in prompt
    assert '"legacy"' not in prompt


def test_semantic_check_enforces_compiled_top_n_null_filter() -> None:
    from agent.validators.sql_semantic_validator import validate_llm_sql_semantics

    result = validate_llm_sql_semantics(
        "SELECT stock_code, total_operating_revenue FROM income_sheet ORDER BY total_operating_revenue DESC LIMIT 30",
        request={
            "flexible_sql_spec": {
                "stages": [{"operation": "top_n", "metric": "营业收入", "exclude_null_metric": True}],
            },
            "metric_bindings": [{"metric_name": "营业收入", "field": "total_operating_revenue"}],
        },
        metrics=[{"table": "income_sheet", "field": "total_operating_revenue"}],
    )

    assert result["is_valid"] is False
    assert result["error_type"] == "SQL_SEMANTIC_INVALID"
