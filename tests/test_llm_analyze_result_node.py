"""LLM 结果分析节点测试。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from agent.nodes.analyze_nodes.yoy_analysis import analyze_yoy_node
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.nodes.answer_nodes.common import assemble_final_answer_node
from agent.nodes.llm_insight import (
    llm_insight_node,
    remove_redundant_insight_fields,
    should_run_llm_insight,
    validate_llm_insight,
)


PROMPT_PATH = Path(__file__).resolve().parents[1] / "agent" / "prompts" / "result_analyzer.md"


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, content: str) -> None:
        self.content = content

    def invoke(self, _prompt: str) -> _FakeResponse:
        return _FakeResponse(self.content)


def _trend_state() -> dict[str, Any]:
    return {
        "user_question": "贵州茅台近两年营业收入趋势如何？",
        "intent_type": "trend_query",
        "query_plan": {"intent_type": "trend_query"},
        "companies": [{"company_name": "贵州茅台酒股份有限公司", "stock_abbr": "贵州茅台"}],
        "metrics": [
            {
                "metric_key": "operating_revenue",
                "metric_name": "营业收入",
                "table": "income_statement",
                "field": "operating_revenue",
                "unit": "yuan",
            }
        ],
        "query_result": {
            "success": True,
            "columns": ["company_name", "report_year", "income_statement__operating_revenue"],
            "rows": [
                ["贵州茅台酒股份有限公司", 2023, 1_000_000_000],
                ["贵州茅台酒股份有限公司", 2024, 1_200_000_000],
            ],
            "row_count": 2,
            "error": None,
        },
        "analysis_result": {
            "direction": "up",
            "metrics": {
                "operating_revenue": {
                    "metric_name": "营业收入",
                    "direction": "up",
                    "year_values": {"2023": 1_000_000_000, "2024": 1_200_000_000},
                    "first_year": 2023,
                    "first_value": 1_000_000_000,
                    "last_year": 2024,
                    "last_value": 1_200_000_000,
                    "absolute_change": 200_000_000,
                    "change_rate_pct": 20.0,
                }
            },
        },
        "sql_success": True,
        "business_success": True,
        "error_type": None,
        "empty_fields": [],
    }


def test_trend_query_can_output_trend_shape(monkeypatch):
    """趋势查询可以输出趋势形态。"""
    monkeypatch.setattr(
        "agent.nodes.llm_insight.build_llm",
        lambda: _FakeLLM(
            '{"insight":"该序列呈连续上行形态。","interpretation_boundary":"仅基于已查询年份判断趋势形态。","suggested_followup":"可继续查看利润指标是否同步变化。"}'
        ),
    )
    state = _trend_state()

    state.update(generate_answer_node(state))
    result = llm_insight_node(state)
    assert result["llm_analysis_success"] is True
    assert result["llm_analysis"]["insight"] == "该序列呈连续上行形态。"

    assembled = assemble_final_answer_node({**state, **result})
    assert "补充解读：" in assembled["final_answer"]
    assert "该序列呈连续上行形态。" in assembled["final_answer"]


def test_point_query_skips_llm_analysis():
    """point_query 默认跳过。"""
    state = _trend_state()
    state["intent_type"] = "point_query"

    state["final_answer"] = "主答案"
    assert should_run_llm_insight(state) is False
    result = llm_insight_node(state)
    assert result == {
        "llm_analysis": None,
        "llm_analysis_success": False,
        "llm_analysis_error": None,
    }


def test_business_failure_skips_llm_analysis():
    """业务失败时跳过 LLM 分析。"""
    state = _trend_state()
    state["business_success"] = False

    state["final_answer"] = "主答案"
    result = llm_insight_node(state)
    assert result["llm_analysis_success"] is False
    assert result["llm_analysis"] is None
    assert result["llm_analysis_error"] is None


def test_invalid_json_does_not_affect_final_answer(monkeypatch):
    """LLM 返回非法 JSON 时，最终答案仍由确定性节点生成。"""
    monkeypatch.setattr(
        "agent.nodes.llm_insight.build_llm",
        lambda: _FakeLLM("这不是 JSON"),
    )
    state = _trend_state()
    state.update(generate_answer_node(state))

    llm_result = llm_insight_node(state)
    assert llm_result["llm_analysis_success"] is False
    assert llm_result["llm_analysis_error"]

    assembled = assemble_final_answer_node({**state, **llm_result})
    assert assembled["final_answer"] == state["final_answer"]
    assert "补充解读：" not in assembled["final_answer"]


def test_validate_limits_insight_fields():
    """洞察字段按长度裁剪。"""
    data = validate_llm_insight(
        {
            "insight": "甲" * 200,
            "interpretation_boundary": "乙" * 200,
            "suggested_followup": "丙" * 200,
        }
    )

    assert len(data["insight"]) == 160
    assert len(data["interpretation_boundary"]) == 160
    assert len(data["suggested_followup"]) == 120


def test_redundancy_filter_keeps_year_boundary_text():
    """重复过滤不应把年份边界说明当成核心数值复述。"""
    base_answer = (
        "根据数据库查询结果，华润三九 2024 年年报中：\n\n"
        "营业收入为 12.00 亿元，2023 年为 10.00 亿元，"
        "同比增加 2.00 亿元，同比增速为 20.00%。"
    )
    analysis = {
        "insight": "该结果说明华润三九 2024 年营业收入在年度同比口径下保持增长。",
        "interpretation_boundary": "但仅基于 2023 和 2024 两个财年，不能判断中长期趋势或增速是否持续改善。",
        "suggested_followup": "可以进一步查看 2021—2024 年营业收入及同比趋势。",
    }

    cleaned = remove_redundant_insight_fields(analysis, base_answer)

    assert cleaned["insight"]
    assert cleaned["interpretation_boundary"]
    assert cleaned["suggested_followup"]


def test_node_does_not_modify_core_query_fields(monkeypatch):
    """节点不修改查询计划、查询结果、业务状态和错误类型。"""
    monkeypatch.setattr(
        "agent.nodes.llm_insight.build_llm",
        lambda: _FakeLLM(
            '{"insight":"该序列呈连续上行形态。","interpretation_boundary":"仅基于已查询年份。","suggested_followup":""}'
        ),
    )
    state = _trend_state()
    state.update(generate_answer_node(state))
    before = deepcopy(state)

    result = llm_insight_node(state)
    merged = {**state, **result}

    assert state == before
    assert merged["query_result"] == before["query_result"]
    assert merged["query_plan"] == before["query_plan"]
    assert merged["business_success"] == before["business_success"]
    assert merged["error_type"] == before["error_type"]
    assert "query_result" not in result
    assert "query_plan" not in result
    assert "business_success" not in result
    assert "error_type" not in result


def test_yoy_query_does_not_repeat_values_rates_or_changes(monkeypatch):
    """同比查询不展示重复的本期值、上期值、同比率和差额。"""
    monkeypatch.setattr(
        "agent.nodes.llm_insight.build_llm",
        lambda: _FakeLLM(
            '{"insight":"2024年营业收入为12.00亿元，同比增长20.00%，增加2.00亿元。","interpretation_boundary":"该同比仅反映两期年报口径下的变化。","suggested_followup":"可继续分析毛利率或净利润同比。"}'
        ),
    )
    state = {
        "intent_type": "yoy_query",
        "companies": [{"company_name": "华润三九医药股份有限公司", "stock_abbr": "华润三九"}],
        "metrics": [
            {
                "metric_key": "operating_revenue",
                "metric_name": "营业收入",
                "table": "income_statement",
                "field": "operating_revenue",
                "unit": "yuan",
            }
        ],
        "report_year": 2024,
        "query_result": {
            "success": True,
            "columns": ["company_name", "report_year", "income_statement__operating_revenue"],
            "rows": [
                ["华润三九医药股份有限公司", 2023, 1_000_000_000],
                ["华润三九医药股份有限公司", 2024, 1_200_000_000],
            ],
            "row_count": 2,
            "error": None,
        },
        "sql_success": True,
        "empty_fields": [],
    }

    state.update(analyze_yoy_node(state))
    assert state["business_success"] is True
    assert state["error_type"] is None
    assert state["analysis_result"] == state["yoy_result"]

    state.update(generate_answer_node(state))
    state.update(llm_insight_node(state))
    assert state["llm_analysis_success"] is True

    assembled = assemble_final_answer_node(state)
    assert "补充解读：" in assembled["final_answer"]
    appended = assembled["final_answer"].split("补充解读：", 1)[1]
    assert "12.00" not in appended
    assert "20.00%" not in appended
    assert "2.00" not in appended
    assert "该同比仅反映两期年报口径下的变化。" in appended


def test_ranking_query_outputs_scope_boundary(monkeypatch):
    """排名查询输出样本范围或排名口径限制。"""
    monkeypatch.setattr(
        "agent.nodes.llm_insight.build_llm",
        lambda: _FakeLLM(
            '{"insight":"","interpretation_boundary":"排名仅覆盖当前查询返回的样本和指标口径。","suggested_followup":"可继续查看排名公司之间的差距。"}'
        ),
    )
    state = {
        "intent_type": "ranking_query",
        "query_plan": {"intent_type": "ranking_query"},
        "query_result": {
            "success": True,
            "columns": ["company_name", "report_year", "metric_value"],
            "rows": [["甲公司", 2024, 100], ["乙公司", 2024, 80]],
            "row_count": 2,
            "error": None,
        },
        "analysis_result": {
            "analysis_type": "ranking",
            "rows": [
                {"rank": 1, "company_name": "甲公司", "metric_value": 100},
                {"rank": 2, "company_name": "乙公司", "metric_value": 80},
            ],
        },
        "final_answer": "根据数据库查询结果，甲公司排名第 1，乙公司排名第 2。",
        "business_success": True,
        "error_type": None,
    }

    state.update(llm_insight_node(state))
    assembled = assemble_final_answer_node(state)

    assert state["llm_analysis_success"] is True
    assert "排名仅覆盖当前查询返回的样本和指标口径。" in assembled["final_answer"]
    assert "可继续分析：" in assembled["final_answer"]


def test_compare_query_fallback_outputs_metric_scope(monkeypatch):
    """对比查询在 LLM 输出为空时补充指标口径边界。"""
    monkeypatch.setattr(
        "agent.nodes.llm_insight.build_llm",
        lambda: _FakeLLM(
            '{"insight":"","interpretation_boundary":"","suggested_followup":""}'
        ),
    )
    state = {
        "intent_type": "company_compare_query",
        "query_plan": {"intent_type": "company_compare_query"},
        "companies": [
            {"company_name": "甲公司", "stock_abbr": "甲公司"},
            {"company_name": "乙公司", "stock_abbr": "乙公司"},
        ],
        "metrics": [{"metric_name": "营业收入", "metric_key": "operating_revenue"}],
        "compare_query_results": [
            {
                "success": True,
                "columns": ["company_name", "report_year", "metric_value"],
                "rows": [["甲公司", 2024, 100]],
                "row_count": 1,
            },
            {
                "success": True,
                "columns": ["company_name", "report_year", "metric_value"],
                "rows": [["乙公司", 2024, 80]],
                "row_count": 1,
            },
        ],
        "analysis_result": {"analysis_type": "company_compare"},
        "final_answer": "2024 年营业收入更高的是甲公司。",
        "business_success": True,
        "error_type": None,
    }

    state.update(llm_insight_node(state))
    assembled = assemble_final_answer_node(state)

    assert state["llm_analysis_success"] is True
    assert "营业收入属于规模指标" in assembled["final_answer"]
    assert "不代表经营质量" in assembled["final_answer"]


def test_empty_llm_insight_does_not_append(monkeypatch):
    """LLM 输出为空时主答案正常返回且不追加洞察段落。"""
    monkeypatch.setattr(
        "agent.nodes.llm_insight.build_llm",
        lambda: _FakeLLM(
            '{"insight":"","interpretation_boundary":"","suggested_followup":""}'
        ),
    )
    state = _trend_state()
    state.update(generate_answer_node(state))

    state.update(llm_insight_node(state))
    assembled = assemble_final_answer_node(state)

    assert state["llm_analysis_success"] is False
    assert assembled["final_answer"] == state["final_answer"]
    assert "补充解读：" not in assembled["final_answer"]


def test_result_insight_prompt_restricts_metric_scope_generically():
    """Prompt 使用通用指标口径约束，避免单个 case 硬编码。"""
    prompt = PROMPT_PATH.read_text(encoding="utf-8")

    assert "补充解读必须与当前查询指标直接相关" in prompt
    assert "不要引入与当前指标口径不直接相关的财务概念" in prompt
    assert "不要用另一个指标解释当前指标变化" in prompt
    assert "其他指标只能作为后续对比方向" in prompt
    assert "不要提及任何输入数据中没有出现的经营原因、文本来源或拆分维度" in prompt
    assert "不要提及报表附注、公告说明、管理层解释" in prompt
    assert "不要默认建议任何结构拆分分析" in prompt
    assert "不能直接推出其他财务维度变化或变化原因" in prompt
    assert "必须包含必要限制说明" in prompt
    assert "给出 1-3 个具体相关指标名称" in prompt
    assert "近三至四年该指标及同比趋势" in prompt
