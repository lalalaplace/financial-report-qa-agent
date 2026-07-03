"""V0.5.2 排名查询 schema 测试。

覆盖 QueryPlan 的 rank_direction / limit 字段结构校验。
V0.5.2：schema 只做结构校验，不设默认值、不做 clamp。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.schemas.query_plan import (
    validate_plan,
    VALID_RANK_DIRECTIONS,
    DEFAULT_RANK_LIMIT,
    MIN_RANK_LIMIT,
    MAX_RANK_LIMIT,
)


# ── rank_direction 结构校验 ──

def test_ranking_query_desc_direction():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
        "limit": 10,
    })
    assert plan["rank_direction"] == "desc"


def test_ranking_query_asc_direction():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["净利率"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "asc",
        "limit": 5,
    })
    assert plan["rank_direction"] == "asc"


def test_ranking_query_invalid_direction_defaults_to_desc():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "top",
    })
    assert plan["rank_direction"] == "desc"


def test_ranking_query_missing_direction_defaults_to_desc():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
    })
    assert plan["rank_direction"] == "desc"


# ── limit 结构校验 ──

def test_ranking_query_explicit_limit():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
        "limit": 3,
    })
    assert plan["limit"] == 3


def test_ranking_query_limit_1():
    """V0.5.2：隐式单条 limit=1 正常通过。"""
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
        "limit": 1,
    })
    assert plan["limit"] == 1


def test_ranking_query_missing_limit_is_none():
    """V0.5.2：schema 不设默认值，缺失时透传 None。"""
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
    })
    assert plan["limit"] is None


def test_ranking_query_limit_passthrough():
    """V0.5.2：schema 不做 clamp，原值透传。"""
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
        "limit": 200,
    })
    assert plan["limit"] == 200


def test_ranking_query_limit_zero_passthrough():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
        "limit": 0,
    })
    assert plan["limit"] == 0


# ── 非 ranking_query 排名字段为 null ──

def test_non_ranking_query_rank_fields_null():
    for intent in ["single_metric_query", "trend_query", "company_compare_query"]:
        plan = validate_plan({
            "intent_type": intent,
            "company_mentions": ["贵州茅台"],
            "metric_mentions": ["营业收入"],
            "time_range": {"mode": "single_year", "report_year": 2024},
        })
        assert plan["rank_direction"] is None, f"{intent} rank_direction 应为 null"
        assert plan["limit"] is None, f"{intent} limit 应为 null"


# ── ranking_query compare_spec 为 null ──

def test_ranking_query_compare_spec_null():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
        "limit": 10,
    })
    assert plan["compare_spec"] is None


# ── ranking_query company_mentions 可为空 ──

def test_ranking_query_allows_empty_company_mentions():
    plan = validate_plan({
        "intent_type": "ranking_query",
        "company_mentions": [],
        "metric_mentions": ["营业收入"],
        "time_range": {"mode": "single_year", "report_year": 2024},
        "rank_direction": "desc",
        "limit": 10,
    })
    assert plan["company_mentions"] == []
    assert plan["need_clarification"] is False


# ── 常量校验 ──

def test_rank_direction_constants():
    assert VALID_RANK_DIRECTIONS == {"desc", "asc"}


def test_rank_limit_constants():
    assert DEFAULT_RANK_LIMIT == 10
    assert MIN_RANK_LIMIT == 1
    assert MAX_RANK_LIMIT == 100


if __name__ == "__main__":
    tests = [
        test_ranking_query_desc_direction,
        test_ranking_query_asc_direction,
        test_ranking_query_invalid_direction_defaults_to_desc,
        test_ranking_query_missing_direction_defaults_to_desc,
        test_ranking_query_explicit_limit,
        test_ranking_query_limit_1,
        test_ranking_query_missing_limit_is_none,
        test_ranking_query_limit_passthrough,
        test_ranking_query_limit_zero_passthrough,
        test_non_ranking_query_rank_fields_null,
        test_ranking_query_compare_spec_null,
        test_ranking_query_allows_empty_company_mentions,
        test_rank_direction_constants,
        test_rank_limit_constants,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAIL {test.__name__}: {e}")
    print(f"V0.5.2 ranking schema: {passed}/{len(tests)} 通过")
    if passed != len(tests):
        raise SystemExit(1)
