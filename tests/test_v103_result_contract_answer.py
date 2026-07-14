"""ResultContract 驱动回答测试。"""

from __future__ import annotations

from agent.nodes.deterministic_table_renderer import render_deterministic_table
from agent.nodes.final_answer_formatter import format_llm_answer_response
from agent.nodes.llm_answer_synthesis_node import llm_answer_synthesis_node
from agent.nodes.result_contract_builder import build_result_contract
from agent.nodes.target_graph_nodes import result_contract_builder_node


def _state() -> dict:
    rows = [
        {"rank": 1, "stock_code": "000999", "company_name": "华润三九", "net_profit_margin": 0.1368}
    ]
    return {
        "user_question": "找出净利率最高的公司",
        "query_type": "single",
        "intent_type": "unknown",
        "sql_generation_mode": "llm_sql",
        "execution": {"execution_result": {
            "success": True,
            "columns": list(rows[0]),
            "rows": [[row[column] for column in rows[0]] for row in rows],
            "row_count": 1,
            "error": None,
        }},
    }


def test_result_contract_requires_table_for_non_empty_rows() -> None:
    contract = build_result_contract(_state())
    table = render_deterministic_table(contract)

    assert contract["must_render_table"] is True
    assert contract["result_shape"] == "ranking"
    assert table["rows"][0]["stock_code"] == "000999"


def test_flexible_sql_percent_metric_does_not_apply_scale_twice() -> None:
    state = _state()
    state["metrics"] = [
        {"metric_key": "net_profit_margin", "metric_name": "净利率", "unit": "percent", "storage_scale": "percent"}
    ]
    state["execution"] = {
        "execution_mode": "flexible_sql",
        "execution_result": {
            "success": True,
            "columns": ["stock_code", "净利率"],
            "rows": [["000999", 28.35]],
            "row_count": 1,
            "error": None,
        },
    }

    table = render_deterministic_table(build_result_contract(state))

    assert table["rows"][0]["净利率"] == "28.35%"


def test_flexible_sql_percent_metric_converts_raw_ratio() -> None:
    state = _state()
    state["metrics"] = [
        {"metric_key": "net_profit_margin", "metric_name": "净利率", "unit": "percent"}
    ]
    state["execution"] = {
        "execution_mode": "flexible_sql",
        "execution_result": {
            "success": True,
            "columns": ["stock_code", "净利率"],
            "rows": [["000999", 0.2835]],
            "row_count": 1,
            "error": None,
        },
    }

    table = render_deterministic_table(build_result_contract(state))

    assert table["rows"][0]["净利率"] == "28.35%"


def test_derived_ratio_forces_fraction_storage_scale() -> None:
    state = _state()
    state["metrics"] = [{
        "metric_key": "net_profit_margin", "metric_name": "净利率", "unit": "percent",
        "metric_type": "derived", "scale": 100,
        "formula": {"numerator": "net_profit", "denominator": "total_operating_revenue"},
    }]
    state["execution"] = {"execution_result": {
        "success": True, "columns": ["stock_code", "净利率"],
        "rows": [["000999", 0.2835]], "row_count": 1,
    }}

    table = render_deterministic_table(build_result_contract(state))

    assert table["rows"][0]["净利率"] == "28.35%"


def test_percent_storage_scale_never_uses_value_size_heuristic() -> None:
    state = _state()
    state["metrics"] = [
        {"metric_key": "yoy_rate", "metric_name": "净利润同比", "unit": "percent", "storage_scale": "percent"}
    ]
    state["execution"] = {
        "execution_result": {
            "success": True,
            "columns": ["stock_code", "净利润同比"],
            "rows": [["000999", 25.98]],
            "row_count": 1,
            "error": None,
        }
    }

    table = render_deterministic_table(build_result_contract(state))

    assert table["rows"][0]["净利润同比"] == "25.98%"


def test_numeric_semantic_representative_categories_are_rendered_from_contract() -> None:
    rows = [{
        "营业收入": 123_456_789,
        "公司数量": 49,
        "净利率": 0.2598,
        "利润率差": 3.25,
        "rank": 3,
        "增长差": 25.98,
    }]
    state = {
        "metrics": [
            {"metric_name": "营业收入", "unit": "yuan", "display_unit": "hundred_million_yuan", "precision": 2},
            {"metric_name": "公司数量", "unit": "count"},
            {"metric_name": "净利率", "unit": "percent", "storage_scale": "fraction", "precision": 2},
            {"metric_name": "利润率差", "value_kind": "percentage_point", "unit": "raw"},
            {"metric_name": "增长差", "unit": "percent", "storage_scale": "percent", "precision": 2},
        ],
        "execution": {"execution_result": {"success": True, "columns": list(rows[0]), "rows": [[row[column] for column in rows[0]] for row in rows], "row_count": 1}},
    }

    contract = build_result_contract(state)
    table = render_deterministic_table(contract)

    assert contract["evidence_rows"][0]["净利率"] == 0.2598
    assert contract["numeric_semantics"]["净利率"]["storage_scale"] == "fraction"
    assert table["rows"][0] == {
        "rank": 3,
        "营业收入": "1.23 亿元",
        "公司数量": 49,
        "净利率": "25.98%",
        "利润率差": "3.25 个百分点",
        "增长差": "25.98%",
    }


def test_llm_narrative_cannot_remove_deterministic_table(monkeypatch) -> None:
    monkeypatch.setattr(
        "agent.nodes.llm_answer_synthesis_node.invoke_json_prompt",
        lambda _prompt: {
            "answer_type": "table_with_summary",
            "title": "查询结果",
            "summary": "符合条件的公司如下。",
            "table": {"columns": [], "rows": []},
            "key_findings": [],
            "method_note": "按净利率降序排序。",
            "data_note": "表格由系统渲染。",
            "warnings": [],
        },
    )

    result = llm_answer_synthesis_node(_state())

    assert result["result_contract"]["must_render_table"] is True
    assert result["deterministic_table"]["rows"]
    assert "000999" in result["final_answer"]
    assert result["answer_validation"]["is_valid"] is True


def test_formal_answer_context_only_uses_result_contract_evidence() -> None:
    state = _state()
    state["query_result"] = {
        "success": True,
        "columns": ["stock_code"],
        "rows": [["stale"]],
        "row_count": 1,
    }

    result = result_contract_builder_node(state)

    assert result["answer_context"]["result_rows"] == result["result_contract"]["evidence_rows"]
    assert result["answer_context"]["result_rows"][0]["stock_code"] == "000999"


def test_report_year_is_rendered_as_year_label_not_decimal_number() -> None:
    answer = format_llm_answer_response(
        {
            "table": {
                "columns": ["stock_code", "report_year"],
                "rows": [{"stock_code": "002773", "report_year": 2024.0}],
            }
        }
    )

    assert "| 002773 | 2024 |" in answer
    assert "2,024.00" not in answer
