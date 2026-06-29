"""V0.6 系列回归测试入口。

默认运行：
- V0.6.1 intent 边界测试
- V0.6.0 统一澄清测试
- V0.6.2 多轮补问 pending 状态与 QueryPlan 合并预留测试
- V0.6.3 error_type、澄清出口与 SimpleCompiledGraph 链路稳定性测试
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

TEST_GROUPS: dict[str, list[str]] = {
    "v061_intent_boundary": [
        "tests/test_v061_intent_boundary.py",
    ],
    "v060_clarification": [
        "tests/test_v060_clarification.py",
    ],
    "v062_clarification_context": [
        "tests/test_v062_pending_state.py",
        "tests/test_v062_clarification_context.py",
        "tests/test_v062_query_plan_merge.py",
    ],
    "v063_error_type_clarification": [
        "tests/test_v063_error_type_clarification.py",
    ],
}


def _run_pytest(group_name: str, targets: list[str]) -> bool:
    print(f"\n\n######## {group_name} ########")
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", *targets],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if completed.returncode == 0:
        print(f"######## PASS {group_name} ########")
        return True
    print(f"######## FAIL {group_name}，退出码 {completed.returncode} ########")
    return False


def _run_script(group_name: str, command: list[str]) -> bool:
    print(f"\n\n######## {group_name} ########")
    completed = subprocess.run(
        [sys.executable, *command],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if completed.returncode == 0:
        print(f"######## PASS {group_name} ########")
        return True
    print(f"######## FAIL {group_name}，退出码 {completed.returncode} ########")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 V0.6 系列回归测试。")
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出测试分组后退出。",
    )
    args = parser.parse_args()

    if args.list:
        for group_name, targets in TEST_GROUPS.items():
            print(f"{group_name}:")
            for target in targets:
                print(f"  - {target}")
        return 0

    failed: list[str] = []

    for group_name, targets in TEST_GROUPS.items():
        if not _run_pytest(group_name, targets):
            failed.append(group_name)

    print("\n\n======== V0.6 测试汇总 ========")
    if not failed:
        print("全部通过")
        return 0

    for group_name in failed:
        print(f"失败：{group_name}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
