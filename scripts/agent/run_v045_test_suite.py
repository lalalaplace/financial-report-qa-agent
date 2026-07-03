"""V0.4.5 分组测试总入口。

默认只运行本地可重复的单元/场景测试。
V0.3 旧端到端回归依赖实际 Agent 运行环境，需显式加 --include-live。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


TEST_GROUPS: dict[str, list[str]] = {
    "v040_company_compare": [
        "scripts/agent/test_v040_scenarios.py",
    ],
    "v041_stability": [
        "scripts/agent/test_v045_query_type_routing.py",
        "scripts/agent/test_v045_query_plan_schema.py",
        "scripts/agent/test_v045_agent_state_schema.py",
    ],
    "v042_compare_trend": [
        "scripts/agent/test_v042_compare_trend_scenarios.py",
    ],
    "v043_compare_yoy": [
        "scripts/agent/test_v043_company_compare_yoy_schema.py",
        "scripts/agent/test_v043_company_compare_yoy_slots.py",
        "scripts/agent/test_v043_company_compare_yoy_scenarios.py",
    ],
    "v044_semantics": [
        "scripts/test_agent_20.py",
    ],
    "v045_contracts": [
        "scripts/agent/test_v045_compare_result_schema.py",
        "scripts/agent/test_v045_error_type_schema.py",
        "scripts/agent/test_v045_node_responsibility.py",
        "scripts/agent/test_v045_logger_observability.py",
    ],
    "unsupported_clarify": [
        "scripts/agent/test_v045_query_type_routing.py",
        "scripts/agent/test_v045_error_type_schema.py",
        "scripts/agent/test_v045_node_responsibility.py",
    ],
}

LIVE_TEST_GROUPS: dict[str, list[str]] = {
    "v03_regression": [
        "scripts/agent/test_agent.py",
    ],
}


def _run_script(script_path: str) -> bool:
    display_path = script_path.replace("/", "\\")
    print(f"\n=== RUN {display_path} ===")
    completed = subprocess.run(
        [sys.executable, script_path],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if completed.returncode == 0:
        print(f"=== PASS {display_path} ===")
        return True
    print(f"=== FAIL {display_path}，退出码 {completed.returncode} ===")
    return False


def _select_groups(names: list[str], include_live: bool) -> dict[str, list[str]]:
    groups = dict(TEST_GROUPS)
    if include_live:
        groups.update(LIVE_TEST_GROUPS)
    if not names:
        return groups

    unknown = [name for name in names if name not in groups]
    if unknown:
        available = ", ".join(sorted(groups))
        raise SystemExit(f"未知测试分组：{', '.join(unknown)}。可用分组：{available}")
    return {name: groups[name] for name in names}


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 V0.4.5 分组测试。")
    parser.add_argument(
        "groups",
        nargs="*",
        help="指定要运行的分组；为空时运行默认全部本地测试。",
    )
    parser.add_argument(
        "--include-live",
        action="store_true",
        help="包含依赖实际 Agent/外部环境的 V0.3 旧端到端回归。",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出测试分组后退出。",
    )
    args = parser.parse_args()

    all_groups = dict(TEST_GROUPS)
    if args.include_live:
        all_groups.update(LIVE_TEST_GROUPS)

    if args.list:
        for name, scripts in all_groups.items():
            print(f"{name}:")
            for script in scripts:
                print(f"  - {script}")
        return 0

    selected_groups = _select_groups(args.groups, args.include_live)
    failed: list[tuple[str, str]] = []

    for group_name, scripts in selected_groups.items():
        print(f"\n\n######## {group_name} ########")
        for script in scripts:
            if not _run_script(script):
                failed.append((group_name, script))

    print("\n\n======== 测试汇总 ========")
    if not failed:
        print("全部通过")
        return 0

    for group_name, script in failed:
        print(f"失败：{group_name} / {script}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
