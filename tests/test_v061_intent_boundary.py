"""V0.6.1 intent 边界回归测试。

测试目标：
- 固化 Planner 输出 QueryPlan 后，schema 归一化不能改坏 intent。
- route_by_intent 按既有 intent 分发到既有 SQL 节点，不新增 intent 或 SQL 类型。
- V0.6.0 统一澄清出口保持不变。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent.nodes import llm_plan_query
from agent.nodes.slot_nodes import check_slots_node
from agent.routing import route_by_intent
from agent.schemas.query_plan import validate_plan


BASE_METRIC = {
    "metric_key": "operating_revenue",
    "metric_name": "营业收入",
    "metric_type": "base",
    "table": "income_sheet",
    "field": "operating_revenue",
    "unit": "yuan",
}


def _plan(
    intent_type: str,
    *,
    companies: list[str] | None = None,
    metrics: list[str] | None = None,
    time_range: dict[str, Any] | None = None,
    compare_spec: dict[str, Any] | None = None,
    rank_direction: str | None = None,
    limit: int | None = None,
    change_metric: str | None = None,
    need_clarification: bool = False,
) -> dict[str, Any]:
    return {
        "intent_type": intent_type,
        "company_mentions": companies or [],
        "metric_mentions": metrics or [],
        "report_period": "FY",
        "time_range": time_range or _single_year(),
        "compare_spec": compare_spec,
        "rank_direction": rank_direction,
        "limit": limit,
        "change_metric": change_metric,
        "need_clarification": need_clarification,
        "clarification_reason": None,
    }


def _single_year(year: int = 2024) -> dict[str, Any]:
    return {
        "mode": "single_year",
        "report_year": year,
        "recent_n_years": None,
        "start_year": None,
        "end_year": None,
        "report_years": [],
    }


def _explicit_range(start_year: int = 2020, end_year: int = 2024) -> dict[str, Any]:
    return {
        "mode": "explicit_range",
        "report_year": None,
        "recent_n_years": None,
        "start_year": start_year,
        "end_year": end_year,
        "report_years": list(range(start_year, end_year + 1)),
    }


def _recent_n(years: int = 5) -> dict[str, Any]:
    return {
        "mode": "recent_n",
        "report_year": None,
        "recent_n_years": years,
        "start_year": None,
        "end_year": None,
        "report_years": [],
    }


class _FakeLLM:
    def __init__(self, plan: dict[str, Any]):
        self.plan = plan

    def invoke(self, _prompt: str) -> SimpleNamespace:
        import json

        return SimpleNamespace(content=json.dumps(self.plan, ensure_ascii=False))


def _run_planner(monkeypatch: pytest.MonkeyPatch, question: str, plan: dict[str, Any]) -> dict[str, Any]:
    monkeypatch.setattr(llm_plan_query, "_build_llm", lambda: _FakeLLM(plan))
    result = llm_plan_query.llm_plan_query_node({"user_question": question})
    assert result["need_clarification"] is plan.get("need_clarification", False)
    return result


@pytest.mark.parametrize(
    ("question", "plan", "expected_intent", "expected_route"),
    [
        (
            "贵州茅台 2024 年营业收入是多少？",
            _plan("single_metric_query", companies=["贵州茅台"], metrics=["营业收入"]),
            "single_metric_query",
            "generate_point_sql",
        ),
        (
            "贵州茅台 2024 年净利润情况如何？",
            _plan("single_metric_query", companies=["贵州茅台"], metrics=["净利润"]),
            "single_metric_query",
            "generate_point_sql",
        ),
        (
            "贵州茅台 2020 到 2024 年营业收入变化趋势",
            _plan("trend_query", companies=["贵州茅台"], metrics=["营业收入"], time_range=_explicit_range()),
            "trend_query",
            "generate_trend_sql",
        ),
        (
            "贵州茅台近五年营业收入趋势",
            _plan("trend_query", companies=["贵州茅台"], metrics=["营业收入"], time_range=_recent_n()),
            "trend_query",
            "generate_trend_sql",
        ),
        (
            "贵州茅台 2024 年营业收入同比增长率是多少？",
            _plan("yoy_query", companies=["贵州茅台"], metrics=["营业收入"]),
            "yoy_query",
            "generate_yoy_sql",
        ),
        (
            "贵州茅台 2024 年净利润较上年增长多少？",
            _plan("yoy_query", companies=["贵州茅台"], metrics=["净利润"]),
            "yoy_query",
            "generate_yoy_sql",
        ),
        (
            "贵州茅台和五粮液 2024 年营业收入谁更高？",
            _plan(
                "company_compare_query",
                companies=["贵州茅台", "五粮液"],
                metrics=["营业收入"],
                compare_spec={"operator": "higher", "target": "metric_value"},
            ),
            "company_compare_query",
            "generate_compare_sql",
        ),
        (
            "贵州茅台、五粮液和泸州老窖 2024 年净利润对比",
            _plan(
                "company_compare_query",
                companies=["贵州茅台", "五粮液", "泸州老窖"],
                metrics=["净利润"],
                compare_spec={"operator": "general", "target": None},
            ),
            "company_compare_query",
            "generate_compare_sql",
        ),
        (
            "贵州茅台和五粮液 2020 到 2024 年营业收入趋势对比",
            _plan(
                "company_compare_trend_query",
                companies=["贵州茅台", "五粮液"],
                metrics=["营业收入"],
                time_range=_explicit_range(),
                compare_spec={"operator": "general", "target": None},
            ),
            "company_compare_trend_query",
            "generate_compare_trend_sql",
        ),
        (
            "贵州茅台和五粮液 2024 年营业收入同比增长率谁更高？",
            _plan(
                "company_compare_yoy_query",
                companies=["贵州茅台", "五粮液"],
                metrics=["营业收入"],
                compare_spec={"operator": "faster_growth", "target": "yoy_rate"},
            ),
            "company_compare_yoy_query",
            "generate_compare_yoy_sql",
        ),
        (
            "2024 年营业收入前 5 的公司有哪些？",
            _plan("ranking_query", metrics=["营业收入"], rank_direction="desc", limit=5),
            "ranking_query",
            "generate_ranking_sql",
        ),
        (
            "2024 年资产负债率最低的 5 家公司",
            _plan("ranking_query", metrics=["资产负债率"], rank_direction="asc", limit=5),
            "ranking_query",
            "generate_ranking_sql",
        ),
        (
            "2024 年营业收入同比增长率前 5 的公司",
            _plan(
                "yoy_ranking_query",
                metrics=["营业收入"],
                rank_direction="desc",
                limit=5,
                change_metric="yoy_rate",
            ),
            "yoy_ranking_query",
            "generate_yoy_ranking_sql",
        ),
        (
            "2024 年净利润同比下降最多的 5 家公司",
            _plan(
                "yoy_ranking_query",
                metrics=["净利润"],
                rank_direction="asc",
                limit=5,
                change_metric="yoy_rate",
            ),
            "yoy_ranking_query",
            "generate_yoy_ranking_sql",
        ),
        (
            "近五年营业收入增长最快的 5 家公司",
            _plan(
                "trend_ranking_query",
                metrics=["营业收入"],
                time_range=_recent_n(),
                rank_direction="desc",
                limit=5,
                change_metric="growth_rate",
            ),
            "trend_ranking_query",
            "generate_trend_ranking_sql",
        ),
        (
            "2020 到 2024 年净利润趋势最好的 10 家公司",
            _plan(
                "trend_ranking_query",
                metrics=["净利润"],
                time_range=_explicit_range(),
                rank_direction="desc",
                limit=10,
                change_metric="growth_rate",
            ),
            "trend_ranking_query",
            "generate_trend_ranking_sql",
        ),
        (
            "贵州茅台 2024 年营业收入排名第几？",
            _plan(
                "rank_position_query",
                companies=["贵州茅台"],
                metrics=["营业收入"],
                rank_direction="desc",
            ),
            "rank_position_query",
            "generate_rank_position_sql",
        ),
        (
            "贵州茅台 2024 年净利润在所有公司中位列第几？",
            _plan(
                "rank_position_query",
                companies=["贵州茅台"],
                metrics=["净利润"],
                rank_direction="desc",
            ),
            "rank_position_query",
            "generate_rank_position_sql",
        ),
    ],
)
def test_v061_planner_intent_boundaries_keep_routes(
    monkeypatch: pytest.MonkeyPatch,
    question: str,
    plan: dict[str, Any],
    expected_intent: str,
    expected_route: str,
):
    result = _run_planner(monkeypatch, question, plan)

    assert result["intent_type"] == expected_intent
    assert result["query_plan"]["intent_type"] == expected_intent
    assert route_by_intent(result) == expected_route


def test_v061_ranking_intents_keep_exclusive_fields():
    cases = [
        (_plan("ranking_query", metrics=["营业收入"], rank_direction="desc", limit=5), None, 5),
        (
            _plan(
                "yoy_ranking_query",
                metrics=["营业收入"],
                rank_direction="desc",
                limit=5,
                change_metric="yoy_rate",
            ),
            "yoy_rate",
            5,
        ),
        (
            _plan(
                "trend_ranking_query",
                metrics=["营业收入"],
                time_range=_explicit_range(),
                rank_direction="desc",
                limit=5,
                change_metric="growth_rate",
            ),
            "growth_rate",
            5,
        ),
        (
            _plan(
                "rank_position_query",
                companies=["贵州茅台"],
                metrics=["营业收入"],
                rank_direction="desc",
                limit=5,
                change_metric="growth_rate",
            ),
            None,
            None,
        ),
    ]

    for raw_plan, expected_change_metric, expected_limit in cases:
        plan = validate_plan(raw_plan)
        assert plan["change_metric"] == expected_change_metric
        assert plan["limit"] == expected_limit


def test_v061_missing_ranking_limit_still_uses_v060_clarification_payload():
    result = check_slots_node(
        {
            "intent_type": "ranking_query",
            "companies": [],
            "company_mentions": [],
            "metrics": [BASE_METRIC],
            "metric_candidates": [],
            "report_year": 2024,
            "report_period": "FY",
            "rank_direction": "desc",
            "limit": None,
            "time_range": _single_year(),
        }
    )

    assert result["need_clarification"] is True
    assert result["clarification_type"] == "missing_ranking_limit"
    assert result["error_type"] == "clarification_required"
    assert result["empty_fields"] == ["ranking_limit"]
    assert result["clarification_payload"]["clarification_type"] == "missing_ranking_limit"
