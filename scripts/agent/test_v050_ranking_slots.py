"""V0.5.2 排名查询 slot validator 测试。

覆盖 ranking_validator 的所有错误类型和正常路径。
V0.5.2：统一错误类型、limit 1-50、derived 放行、仅 single_year。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.slot_validators.ranking_validator import validate


def _base_state(**overrides):
    s = {
        "metrics": [{
            "metric_key": "operating_revenue",
            "metric_name": "营业收入",
            "metric_type": "base",
            "table": "income_sheet",
            "field": "operating_revenue",
            "unit": "yuan",
        }],
        "metric_candidates": [],
        "rank_direction": "desc",
        "limit": 10,
        "report_year": 2024,
        "report_period": "FY",
        "time_range": {"mode": "single_year", "report_year": 2024},
        "companies": [],
        "company_mentions": [],
    }
    s.update(overrides)
    return s


# ── 正常路径 ──

def test_valid_ranking_desc():
    result = validate(_base_state())
    assert result["need_clarification"] is False
    assert result["rank_direction"] == "desc"
    assert result["limit"] == 10


def test_valid_ranking_asc():
    result = validate(_base_state(rank_direction="asc", limit=5))
    assert result["need_clarification"] is False
    assert result["rank_direction"] == "asc"
    assert result["limit"] == 5


def test_valid_ranking_limit_1():
    """V0.5.2：limit=1 正常通过。"""
    result = validate(_base_state(limit=1))
    assert result["need_clarification"] is False
    assert result["limit"] == 1


def test_valid_derived_ranking():
    """V0.5.2：derived 指标排名正常通过。"""
    result = validate(_base_state(metrics=[{
        "metric_key": "net_profit_margin",
        "metric_name": "净利率",
        "metric_type": "derived",
    }]))
    assert result["need_clarification"] is False


# ── missing_metric ──

def test_missing_metric():
    result = validate(_base_state(metrics=[], metric_candidates=[]))
    assert result["need_clarification"] is True
    assert result["error_type"] == "missing_metric"


# ── multiple_metrics_not_supported ──

def test_multiple_metrics():
    result = validate(_base_state(metrics=[
        {"metric_key": "a", "metric_name": "营收", "metric_type": "base"},
        {"metric_key": "b", "metric_name": "净利", "metric_type": "base"},
    ]))
    assert result["need_clarification"] is True
    assert result["error_type"] == "multiple_metrics_not_supported"


# ── multiple_companies_not_supported ──

def test_company_scoped_ranking_rejected():
    result = validate(_base_state(companies=[
        {"company_name": "贵州茅台", "stock_code": "600519"},
    ]))
    assert result["need_clarification"] is True
    assert result["error_type"] == "multiple_companies_not_supported"


def test_company_mentions_ranking_rejected():
    result = validate(_base_state(company_mentions=["贵州茅台"]))
    assert result["need_clarification"] is True
    assert result["error_type"] == "multiple_companies_not_supported"


# ── unsupported_ranking_time_mode ──

def test_trend_time_mode_rejected():
    result = validate(_base_state(time_range={"mode": "recent_n", "recent_n_years": 3}))
    assert result["need_clarification"] is True
    assert result["error_type"] == "unsupported_ranking_time_mode"


def test_explicit_range_time_mode_rejected():
    result = validate(_base_state(time_range={"mode": "explicit_range", "start_year": 2022, "end_year": 2024}))
    assert result["need_clarification"] is True
    assert result["error_type"] == "unsupported_ranking_time_mode"


def test_unspecified_time_mode_rejected():
    """V0.5.2：unspecified 时间模式也被拦截。"""
    result = validate(_base_state(time_range={"mode": "unspecified"}, report_year=None))
    assert result["need_clarification"] is True


# ── missing_year ──

def test_missing_report_year():
    result = validate(_base_state(report_year=None, time_range={"mode": "single_year", "report_year": None}))
    assert result["need_clarification"] is True
    assert result["error_type"] == "missing_year"


# ── missing_rank_direction ──

def test_missing_rank_direction():
    result = validate(_base_state(rank_direction=None))
    assert result["need_clarification"] is True
    assert result["error_type"] == "missing_rank_direction"


# ── missing_limit ──

def test_missing_limit():
    result = validate(_base_state(limit=None))
    assert result["need_clarification"] is True
    assert result["error_type"] == "missing_limit"


# ── invalid_limit ──

def test_limit_below_min():
    result = validate(_base_state(limit=0))
    assert result["need_clarification"] is True
    assert result["error_type"] == "invalid_limit"


def test_limit_above_max():
    """V0.5.2：上限从 100 改为 50。"""
    result = validate(_base_state(limit=200))
    assert result["need_clarification"] is True
    assert result["error_type"] == "invalid_limit"


def test_limit_51_rejected():
    """V0.5.2：51 超过新上限 50。"""
    result = validate(_base_state(limit=51))
    assert result["need_clarification"] is True
    assert result["error_type"] == "invalid_limit"


if __name__ == "__main__":
    tests = [
        test_valid_ranking_desc,
        test_valid_ranking_asc,
        test_valid_ranking_limit_1,
        test_valid_derived_ranking,
        test_missing_metric,
        test_multiple_metrics,
        test_company_scoped_ranking_rejected,
        test_company_mentions_ranking_rejected,
        test_trend_time_mode_rejected,
        test_explicit_range_time_mode_rejected,
        test_unspecified_time_mode_rejected,
        test_missing_report_year,
        test_missing_rank_direction,
        test_missing_limit,
        test_limit_below_min,
        test_limit_above_max,
        test_limit_51_rejected,
    ]
    passed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"FAIL {test.__name__}: {e}")
    print(f"V0.5.2 ranking validator: {passed}/{len(tests)} 通过")
    if passed != len(tests):
        raise SystemExit(1)
