"""双公司同比对比不得被误判为公司歧义。"""

from agent.nodes import slot_nodes, target_graph_nodes
from agent.nodes.answer_router import route_answer_generation
from agent.nodes.llm_plan_query import _correct_explicit_operation, _state_from_query_spec
from agent.schemas.query_spec import normalize_query_spec


def test_company_compare_yoy_overrides_incorrect_flexible_mode() -> None:
    spec = normalize_query_spec(
        {
            "execution_mode": "flexible_sql",
            "operation": "company_compare_yoy_query",
            "entities": ["华润三九", "云南白药"],
            "metrics": ["净利润同比增速"],
            "time_scope": {"year": 2024, "period": "FY"},
        }
    )

    state = _state_from_query_spec(spec)

    assert spec["execution_mode"] == "deterministic"
    assert state["intent_type"] == "company_compare_yoy_query"
    assert state["company_mentions"] == ["华润三九", "云南白药"]


def test_two_unique_company_mentions_are_not_ambiguity(monkeypatch) -> None:
    resolved = {
        "华润三九": {"need_clarification": False, "candidates": [{"stock_code": "000999", "stock_abbr": "华润三九"}]},
        "云南白药": {"need_clarification": False, "candidates": [{"stock_code": "000538", "stock_abbr": "云南白药"}]},
    }
    monkeypatch.setattr(slot_nodes, "resolve_company", lambda mention: resolved[mention])

    result = slot_nodes.resolve_company_node(
        {"intent_type": "unknown", "company_mentions": ["华润三九", "云南白药"]}
    )

    assert result["company_resolution_status"] == "resolved_multiple"
    assert result["company_candidates"] == []
    assert [item["stock_code"] for item in result["companies"]] == ["000999", "000538"]


def test_compare_yoy_question_corrects_unknown_planner_operation() -> None:
    result = _correct_explicit_operation(
        "华润三九和云南白药 2024 年谁的净利润同比增速更高？",
        _state_from_query_spec(
            {
                "execution_mode": "flexible_sql",
                "operation": "unknown",
                "entities": ["华润三九", "云南白药"],
                "metrics": ["净利润"],
                "time_scope": {"year": 2024, "period": "FY"},
            }
        ),
    )

    assert result["query_spec"]["operation"] == "company_compare_yoy_query"
    assert result["intent_type"] == "company_compare_yoy_query"


def test_target_graph_keeps_compare_yoy_multi_sql_plan(monkeypatch) -> None:
    state = {
        "intent_type": "company_compare_yoy_query",
        "companies": [{"stock_code": "000999"}, {"stock_code": "000538"}],
        "metrics": [{"metric_key": "net_profit", "metric_type": "base", "table": "income_sheet", "field": "net_profit"}],
        "report_year": 2024,
        "report_years": [2023, 2024],
        "report_period": "FY",
        "planning": {"capability_decision": {"execution_mode": "deterministic"}},
    }
    built = target_graph_nodes.deterministic_sql_builder_node(state)
    guarded = target_graph_nodes.sql_guard_node({**state, **built})
    called = {"multi_sql": False}

    def fake_execute(legacy_state, *, execution):
        called["multi_sql"] = bool(legacy_state.get("compare_yoy_sqls"))
        return {"compare_yoy_query_results": [{"sql_success": True, "rows": []}], "sql_success": True}

    monkeypatch.setattr(target_graph_nodes, "review_and_execute_sql_node", fake_execute)
    executed = target_graph_nodes.execute_sql_node({**state, **built, **guarded})

    assert guarded["sql_guard_status"] == "passed"
    assert built["generated_sql"] is None
    assert called["multi_sql"] is True
    assert executed["compare_yoy_query_results"][0]["sql_success"] is True


def test_company_compare_yoy_uses_template_answer_after_deterministic_analysis() -> None:
    assert route_answer_generation(
        {
            "intent_type": "company_compare_yoy_query",
            "sql_generation_mode": "template",
            "query_type": "single",
        }
    ) == "template"


def test_company_compare_recovers_from_single_metric_planner_operation() -> None:
    result = target_graph_nodes.query_spec_validator_node(
        {
            "user_question": "华润三九和云南白药 2024 年谁的营业收入更高？",
            "query_spec": {
                "execution_mode": "deterministic",
                "operation": "point_query",
                "clarification_question": None,
            },
            "companies": [{"stock_code": "000999"}, {"stock_code": "000538"}],
            "company_candidates": [],
            "metrics": [{"metric_key": "revenue", "metric_type": "base"}],
            "metric_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
            "time_mode": "single_year",
        }
    )

    assert result["query_spec_validation_status"] == "valid"
    assert result["intent_type"] == "company_compare_query"
    assert result["query_spec"]["operation"] == "company_compare_query"


def test_recent_n_company_growth_recovers_to_compare_trend(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.nodes.slot_validators.compare_trend_validator._query_latest_fy_year",
        lambda _company, _metric: 2024,
    )
    result = target_graph_nodes.query_spec_validator_node(
        {
            "user_question": "华润三九和云南白药近三年营业收入谁增长更快？",
            "query_spec": {
                "execution_mode": "unsupported",
                "operation": "unknown",
                "unsupported_reason": "暂不支持",
                "clarification_question": None,
            },
            "companies": [{"stock_code": "000999"}, {"stock_code": "000538"}],
            "company_candidates": [],
            "metrics": [{"metric_key": "revenue", "metric_type": "base", "table": "income_sheet"}],
            "metric_candidates": [],
            "report_period": "FY",
        }
    )

    assert result["query_spec_validation_status"] == "valid"
    assert result["intent_type"] == "company_compare_trend_query"
    assert result["query_spec"]["operation"] == "company_compare_trend_query"
    assert result["recent_n_years"] == 3
    assert result["report_years"] == [2022, 2023, 2024]
    assert result["compare_spec"]["operator"] == "faster_growth"


def test_company_rank_position_recovers_from_point_query() -> None:
    result = target_graph_nodes.query_spec_validator_node(
        {
            "user_question": "华润三九 2024 年营业收入排第几？",
            "query_spec": {
                "execution_mode": "deterministic",
                "operation": "point_query",
                "clarification_question": None,
            },
            "companies": [{"stock_code": "000999"}],
            "company_candidates": [],
            "metrics": [{"metric_key": "revenue", "metric_type": "base"}],
            "metric_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
            "time_mode": "single_year",
        }
    )

    assert result["query_spec_validation_status"] == "valid"
    assert result["intent_type"] == "rank_position_query"
    assert result["query_spec"]["operation"] == "rank_position_query"
    assert result["rank_direction"] == "desc"


def test_derived_metric_uses_template_answer_after_deterministic_analysis() -> None:
    assert route_answer_generation(
        {
            "intent_type": "derived_metric_query",
            "sql_generation_mode": "template",
            "query_type": "single",
        }
    ) == "template"
