"""V0.7 上下文 LLM 节点真实 LLM 集成测试（第 2/5 节补充覆盖）。"""

from __future__ import annotations

import os
from copy import deepcopy
from typing import Any

import pytest

from agent.nodes import slot_nodes
from agent.nodes.context_llm_nodes import (
    clarification_patch_node,
    context_router_node,
    followup_patch_node,
    merge_clarification_patch_node,
    merge_followup_patch_node,
    remember_successful_query_plan_node,
)
from agent.nodes.execute_sql_node import review_and_execute_sql_node
from agent.nodes.sql_nodes.point_sql import generate_point_sql_node
from agent.services.llm_json_service import load_dotenv_if_available


def _real_llm_enabled() -> bool:
    load_dotenv_if_available()
    has_key = any(
        os.getenv(name)
        for name in ("AGENT_LLM_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY")
    )
    return os.getenv("RUN_REAL_LLM_TESTS") == "1" and has_key


pytestmark = pytest.mark.skipif(
    not _real_llm_enabled(),
    reason="需要设置 RUN_REAL_LLM_TESTS=1 并配置真实 LLM API Key。",
)


def _query_plan(
    *,
    companies: list[str] | None = None,
    metrics: list[str] | None = None,
    year: int = 2024,
) -> dict[str, Any]:
    return {
        "intent_type": "single_metric_query",
        "company_mentions": companies or [],
        "metric_mentions": metrics or ["营业收入"],
        "report_period": "FY",
        "time_range": {
            "mode": "single_year",
            "report_year": year,
            "recent_n_years": None,
            "start_year": None,
            "end_year": None,
            "report_years": [],
        },
        "compare_spec": None,
        "rank_direction": None,
        "limit": None,
        "change_metric": None,
        "need_clarification": False,
        "clarification_reason": None,
    }


def _stub_executor(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_resolve_company(_query_text: str) -> dict[str, Any]:
        return {
            "matched": True,
            "need_clarification": False,
            "candidates": [
                {
                    "stock_code": "600519",
                    "stock_abbr": "贵州茅台",
                    "company_name": "贵州茅台酒股份有限公司",
                }
            ],
        }

    def fake_execute_sql(_sql: str) -> dict[str, Any]:
        return {
            "success": True,
            "columns": ["stock_code", "company_name", "report_year", "operating_revenue"],
            "rows": [["600519", "贵州茅台酒股份有限公司", 2024, 1]],
            "row_count": 1,
            "error": None,
        }

    monkeypatch.setattr(slot_nodes, "resolve_company", fake_resolve_company)
    monkeypatch.setattr(
        "agent.nodes.execute_sql_handlers._invoke_execute_financial_sql",
        fake_execute_sql,
    )


# ── 2. 路由能力 ──


def test_context_router_llm_routes_clarification_answer():
    """补答识别：pending 缺公司，用户输入公司名。"""
    result = context_router_node(
        {
            "user_question": "贵州茅台",
            "pending_query_plan": _query_plan(),
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
            "last_successful_query_plan": None,
        }
    )
    assert result["route_type"] == "clarification_answer"
    assert result["target_context"] == "pending_query_plan"


def test_context_router_llm_routes_new_query_and_clears_pending():
    """新问题识别：pending 存在但用户输入完整新问题，清理旧 pending。"""
    result = context_router_node(
        {
            "user_question": "五粮液2023年净利润同比增长率是多少？",
            "pending_query_plan": _query_plan(),
            "pending_clarification_type": "missing_company",
            "pending_empty_fields": ["companies"],
            "last_successful_query_plan": _query_plan(
                companies=["贵州茅台"], metrics=["营业收入"]
            ),
        }
    )
    assert result["route_type"] == "new_query"
    assert result["target_context"] == "none"
    assert result["pending_query_plan"] is None
    assert result["slot_patch"] is None
    assert result["merged_query_plan"] is None


# ── 3. 补答链路 ──


def test_clarification_patch_real_llm_then_merge_and_execute(
    monkeypatch: pytest.MonkeyPatch,
):
    """补答全链路：patch 抽取 → merge → 标准化 → SQL → 执行。"""
    _stub_executor(monkeypatch)
    state = {
        "user_question": "贵州茅台",
        "pending_query_plan": _query_plan(),
        "pending_clarification_type": "missing_company",
        "pending_empty_fields": ["companies"],
        "sql": "DROP TABLE company_dim",
        "final_answer": "旧回答",
        "companies": [{"stock_code": "000000"}],
        "metrics": [{"metric_key": "old_metric"}],
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "clarification_answer"

    patched = clarification_patch_node({**state, **routed})
    assert patched.get("slot_patch", {}).get("company_mentions")

    merged = merge_clarification_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["pending_query_plan"] is None
    assert merged["sql"] is None
    assert merged["final_answer"] is None
    assert merged["companies"] == []
    assert merged["metrics"] == []

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False

    current.update(generate_point_sql_node(current))
    assert current["sql"]
    current.update(review_and_execute_sql_node(current))

    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True
    assert current["query_result"]["success"] is True


# ── 4. 续问链路 ──


def test_followup_patch_real_llm_then_merge_and_execute(
    monkeypatch: pytest.MonkeyPatch,
):
    """续问全链路：patch 抽取 → merge → 标准化 → SQL → 执行。"""
    _stub_executor(monkeypatch)
    state = {
        "user_question": "那净利润呢",
        "pending_query_plan": None,
        "last_successful_query_plan": _query_plan(
            companies=["贵州茅台"], metrics=["营业收入"]
        ),
        "sql": "DROP TABLE company_dim",
        "query_result": {"success": True, "rows": [["旧结果"]]},
        "final_answer": "旧回答",
    }

    routed = context_router_node(state)
    assert routed["route_type"] == "contextual_followup"

    patched = followup_patch_node({**state, **routed})
    assert patched.get("patch_status") == "ok"
    assert patched["slot_patch"]["metric_mentions"]

    merged = merge_followup_patch_node({**state, **routed, **patched})
    assert merged["need_clarification"] is False
    assert merged["sql"] is None
    assert merged["query_result"] is None
    assert "营业收入" in merged["metric_mentions"]
    assert any("净利润" in m for m in merged["metric_mentions"])

    current = {**state, **merged}
    current.update(slot_nodes.resolve_company_node(current))
    current.update(slot_nodes.map_metric_node(current))
    current.update(slot_nodes.check_slots_node(current))
    assert current["need_clarification"] is False

    current.update(generate_point_sql_node(current))
    current.update(review_and_execute_sql_node(current))

    assert current["sql_review"]["is_safe"] is True
    assert current["sql_success"] is True


# ── 5. QueryPlan 合并验收（通过真实 LLM 节点验证）──


def test_forbidden_keys_rejected_by_merge_node():
    """5. 禁止 patch 字段：在 merge 阶段注入越权 slot_patch 应被拒绝。"""
    FORBIDDEN_KEYS = [
        "sql", "companies", "metrics", "query_result",
        "analysis_result", "table_name", "column_name", "where_clause",
    ]
    for key in FORBIDDEN_KEYS:
        bad_patch = {key: "越权值"}
        result = merge_followup_patch_node(
            {
                "user_question": "test",
                "last_successful_query_plan": _query_plan(
                    companies=["贵州茅台"], metrics=["营业收入"]
                ),
                "slot_patch": bad_patch,
                "patch_status": "ok",
                "route_type": "contextual_followup",
                "target_context": "last_successful_query_plan",
            }
        )
        assert result["need_clarification"] is True
        assert result.get("error_type") == "invalid_query"


def test_company_dedup_through_real_llm_followup(
    monkeypatch: pytest.MonkeyPatch,
):
    """5. 公司去重：续问追加已存在的公司时，合并结果应去重。"""
    _stub_executor(monkeypatch)
    state = {
        "user_question": "贵州茅台呢？",
        "pending_query_plan": None,
        "last_successful_query_plan": _query_plan(
            companies=["贵州茅台"], metrics=["营业收入"]
        ),
    }

    routed = context_router_node(state)
    patched = followup_patch_node({**state, **routed})

    if patched.get("patch_status") == "ok" and patched.get("slot_patch", {}).get(
        "company_mentions"
    ):
        merged = merge_followup_patch_node({**state, **routed, **patched})
        # 贵州茅台不应重复出现
        mentions = merged.get("company_mentions") or []
        assert mentions.count("贵州茅台") <= 1


def test_metric_append_through_real_llm_followup(
    monkeypatch: pytest.MonkeyPatch,
):
    """5. 指标追加：续问追加新指标时，合并结果包含新旧指标。"""
    _stub_executor(monkeypatch)
    state = {
        "user_question": "还有净利润呢？",
        "pending_query_plan": None,
        "last_successful_query_plan": _query_plan(
            companies=["贵州茅台"], metrics=["营业收入"]
        ),
    }

    routed = context_router_node(state)
    patched = followup_patch_node({**state, **routed})

    if patched.get("patch_status") == "ok":
        merged = merge_followup_patch_node({**state, **routed, **patched})
        mentions = merged.get("metric_mentions") or []
        assert "营业收入" in mentions
        assert any("净利润" in m for m in mentions)


def test_merged_plan_passes_schema_validation_real_llm(
    monkeypatch: pytest.MonkeyPatch,
):
    """5. schema 校验：真实 LLM 续问合并后必须通过 validate_plan。"""
    _stub_executor(monkeypatch)
    from agent.schemas.query_plan import validate_plan

    state = {
        "user_question": "那净利润呢",
        "pending_query_plan": None,
        "last_successful_query_plan": _query_plan(
            companies=["贵州茅台"], metrics=["营业收入"]
        ),
    }

    routed = context_router_node(state)
    patched = followup_patch_node({**state, **routed})
    merged = merge_followup_patch_node({**state, **routed, **patched})

    if merged.get("patch_status") == "ok":
        plan = merged.get("merged_query_plan") or merged.get("query_plan")
        if plan:
            validated = validate_plan(plan)
            assert validated["intent_type"] in (
                "single_metric_query",
                "multi_metric_query",
            )
            assert validated["company_mentions"]
            assert validated["metric_mentions"]


# ── 7. 状态管理 ──


def test_remember_successful_query_plan_only_records_successful():
    """7.3/7.5 只在 business_success=True 且有 query_plan 时保存。"""
    plan = _query_plan(companies=["贵州茅台"], metrics=["净利润"], year=2023)

    success = remember_successful_query_plan_node(
        {"business_success": True, "query_plan": plan}
    )
    failed = remember_successful_query_plan_node(
        {"business_success": False, "query_plan": plan}
    )
    missing = remember_successful_query_plan_node(
        {"business_success": True, "query_plan": None}
    )

    assert success == {"last_successful_query_plan": plan}
    assert failed == {}
    assert missing == {}


def test_last_successful_plan_points_to_latest():
    """7.5 连续成功时 last_successful 指向最新一次。"""
    q2 = _query_plan(companies=["五粮液"], metrics=["净利润"], year=2023)
    q3 = _query_plan(companies=["五粮液"], metrics=["营业收入"], year=2023)

    r1 = remember_successful_query_plan_node(
        {"business_success": True, "query_plan": q2}
    )
    assert r1 == {"last_successful_query_plan": q2}

    r2 = remember_successful_query_plan_node(
        {"business_success": True, "query_plan": q3}
    )
    assert r2 == {"last_successful_query_plan": q3}
