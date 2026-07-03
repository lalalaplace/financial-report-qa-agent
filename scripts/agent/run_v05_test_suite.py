"""V0.5 ranking 系列测试总入口。

默认运行 V0.5 全部 ranking 能力测试。分组保持稳定命名，便于 CI
或人工按职责定位失败范围。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]

TEST_GROUPS: dict[str, list[str]] = {
    "ranking_base_tests": [
        "scripts/agent/test_v050_ranking_schema.py",
        "scripts/agent/test_v050_ranking_slots.py",
        "scripts/agent/test_v050_ranking_sql.py::test_desc_sql_contains_order_desc_and_secondary_sort",
        "scripts/agent/test_v050_ranking_sql.py::test_asc_sql_contains_order_asc_and_secondary_sort",
        "scripts/agent/test_v050_ranking_sql.py::test_limit_in_sql",
        "scripts/agent/test_v050_ranking_sql.py::test_limit_1_in_sql",
        "scripts/agent/test_v050_ranking_sql.py::test_contains_where_not_null",
        "scripts/agent/test_v050_ranking_sql.py::test_no_company_filter",
        "scripts/agent/test_v050_ranking_sql.py::test_balance_sheet_uses_correct_alias",
        "scripts/agent/test_v050_ranking_sql.py::test_cash_flow_sheet_uses_correct_alias",
        "scripts/agent/test_v050_ranking_sql.py::test_node_generates_sql_for_base_metric",
        "scripts/agent/test_v050_ranking_sql.py::test_node_generates_sql_for_limit_1",
    ],
    "ranking_derived_tests": [
        "scripts/agent/test_v050_ranking_slots.py::test_valid_derived_ranking",
        "scripts/agent/test_v050_ranking_sql.py::test_derived_ranking_sql_uses_nullif",
        "scripts/agent/test_v050_ranking_sql.py::test_derived_ranking_sql_has_secondary_sort",
        "scripts/agent/test_v050_ranking_sql.py::test_derived_ranking_den_not_null_filter",
        "scripts/agent/test_v050_ranking_integration.py::test_answer_percent_metric_asc_summary_uses_percentage_points",
        "scripts/agent/test_v050_ranking_integration.py::test_analysis_builds_ranking_result_summary",
        "scripts/agent/test_v050_ranking_integration.py::test_e2e_derived_limit_1_with_formula",
    ],
    "ranking_stability_tests": [
        "scripts/agent/test_v057_ranking_intent_registration.py",
        "scripts/agent/test_v057_ranking_logger_schema.py",
        "scripts/agent/test_v045_query_type_routing.py::test_query_type_list_is_stable",
        "scripts/agent/test_v045_query_type_routing.py::test_ranking_query_routing_and_validation_v050",
    ],
    "yoy_ranking_tests": [
        "scripts/agent/test_v053_yoy_ranking.py",
    ],
    "trend_ranking_tests": [
        "scripts/agent/test_v054_trend_ranking.py",
    ],
    "rank_position_tests": [
        "scripts/agent/test_v055_rank_position.py",
    ],
    "ranking_result_analysis_tests": [
        "scripts/agent/test_v057_ranking_answer_format.py",
        "scripts/agent/test_v050_ranking_integration.py::test_e2e_desc_top3",
        "scripts/agent/test_v050_ranking_integration.py::test_e2e_asc_bottom3",
        "scripts/agent/test_v050_ranking_integration.py::test_e2e_limit_1_desc",
        "scripts/agent/test_v050_ranking_integration.py::test_e2e_limit_1_asc",
        "scripts/agent/test_v050_ranking_integration.py::test_empty_result",
        "scripts/agent/test_v050_ranking_integration.py::test_query_failed",
        "scripts/agent/test_v053_yoy_ranking.py::test_analysis_and_answer",
        "scripts/agent/test_v053_yoy_ranking.py::test_answer_includes_yoy_ranking_summary_for_topn",
        "scripts/agent/test_v053_yoy_ranking.py::test_answer_includes_yoy_decline_summary_for_topn",
        "scripts/agent/test_v054_trend_ranking.py::test_analysis_and_answer",
        "scripts/agent/test_v054_trend_ranking.py::test_answer_includes_trend_ranking_summary_for_topn",
        "scripts/agent/test_v054_trend_ranking.py::test_answer_includes_trend_decline_summary_for_topn",
        "scripts/agent/test_v055_rank_position.py::test_analysis_and_answer",
    ],
    "intent_boundary_tests": [
        "scripts/agent/test_v050_ranking_integration.py::test_v046_regression_plan_schema",
        "scripts/agent/test_v050_ranking_integration.py::test_v046_regression_yoy_plan",
        "scripts/agent/test_v050_ranking_integration.py::test_v046_regression_trend_plan",
        "scripts/agent/test_v045_query_type_routing.py::test_validate_plan_keeps_compare_trend_yoy_intents_with_derived_metric_names",
        "scripts/agent/test_v045_query_type_routing.py::test_route_by_intent_does_not_mix_compare_trend_yoy",
        "scripts/agent/test_v045_query_type_routing.py::test_derived_metrics_do_not_steal_compare_trend_yoy_intents",
    ],
    "sql_guard_ranking_tests": [
        "scripts/agent/test_v050_ranking_sql.py::test_ranking_sql_passes_guard",
        "scripts/agent/test_v050_ranking_sql.py::test_ranking_sql_is_select",
        "scripts/agent/test_v050_ranking_sql.py::test_guard_rejects_order_by_without_limit",
        "scripts/agent/test_v050_ranking_sql.py::test_guard_rejects_limit_over_50",
        "scripts/agent/test_v050_ranking_sql.py::test_guard_allows_order_by_with_company_filter",
        "scripts/agent/test_v050_ranking_sql.py::test_guard_params_raises_on_none_limit",
        "scripts/agent/test_v050_ranking_sql.py::test_guard_params_raises_on_invalid_limit",
        "scripts/agent/test_v050_ranking_sql.py::test_guard_params_raises_on_limit_over_50",
        "scripts/agent/test_v050_ranking_sql.py::test_guard_params_raises_on_invalid_direction",
        "scripts/agent/test_v050_ranking_sql.py::test_guard_params_passes_valid",
        "scripts/agent/test_v050_ranking_sql.py::test_node_rejects_empty_metrics",
        "scripts/agent/test_v050_ranking_sql.py::test_node_rejects_missing_limit",
        "scripts/agent/test_v050_ranking_sql.py::test_route_analysis_ranking",
        "scripts/agent/test_v050_ranking_sql.py::test_route_by_intent_ranking",
        "scripts/agent/test_v053_yoy_ranking.py::test_yoy_ranking_sql_passes_guard",
        "scripts/agent/test_v053_yoy_ranking.py::test_guard_rejects_invalid_limit",
        "scripts/agent/test_v054_trend_ranking.py::test_trend_ranking_sql_passes_guard",
        "scripts/agent/test_v054_trend_ranking.py::test_guard_rejects_invalid_limit",
        "scripts/agent/test_v055_rank_position.py::test_rank_position_sql_passes_guard",
        "scripts/agent/test_v055_rank_position.py::test_guard_rejects_invalid_inputs",
    ],
    "regression_tests": [
        "scripts/agent/test_v045_query_plan_schema.py",
        "scripts/agent/test_v045_query_type_routing.py",
        "scripts/agent/test_v045_error_type_schema.py",
        "scripts/agent/test_v045_node_responsibility.py",
        "scripts/agent/test_v045_compare_result_schema.py",
        "scripts/agent/test_v045_agent_state_schema.py",
    ],
}


def _run_pytest(group_name: str, test_targets: list[str]) -> bool:
    print(f"\n\n######## {group_name} ########")
    for target in test_targets:
        print(f"  - {target}")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *test_targets],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if completed.returncode == 0:
        print(f"######## PASS {group_name} ########")
        return True
    print(f"######## FAIL {group_name}，退出码 {completed.returncode} ########")
    return False


def _select_groups(names: list[str]) -> dict[str, list[str]]:
    if not names:
        return TEST_GROUPS

    unknown = [name for name in names if name not in TEST_GROUPS]
    if unknown:
        available = ", ".join(sorted(TEST_GROUPS))
        raise SystemExit(f"未知测试分组：{', '.join(unknown)}。可用分组：{available}")
    return {name: TEST_GROUPS[name] for name in names}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 V0.5 ranking 系列分组测试。")
    parser.add_argument(
        "groups",
        nargs="*",
        help="指定要运行的分组；为空时运行 V0.5 全部 ranking 测试。",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出测试分组后退出。",
    )
    args = parser.parse_args()

    if args.list:
        for name, targets in TEST_GROUPS.items():
            print(f"{name}:")
            for target in targets:
                print(f"  - {target}")
        return 0

    selected = _select_groups(args.groups)
    failed: list[str] = []

    for group_name, targets in selected.items():
        if not _run_pytest(group_name, targets):
            failed.append(group_name)

    print("\n\n======== V0.5 ranking 测试汇总 ========")
    if not failed:
        print("全部通过")
        return 0

    for group_name in failed:
        print(f"失败：{group_name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
