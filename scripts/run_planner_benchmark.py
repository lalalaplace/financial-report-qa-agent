"""独立验证 Flexible SQL Planner 的真实 QuerySpec 输出与阶段耗时。"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "dual_channel_e2e"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.nodes.llm_plan_query import llm_plan_query_node
from agent.utils.stage_trace import traced_node
CASES = [
    ("f_intersection", "找出 2024 年营业收入和净利润都进入前 20 的公司，并按净利率排序。", "set_intersection_ranking"),
    ("f_cross_filter", "找出 2024 年净利润同比超过 50%，但营业收入同比低于 10% 的公司。", "multi_metric_yoy_filter"),
    ("f_opposite", "找出 2024 年营业收入下降但净利润上升的公司，并按净利润同比排序。", "yoy_direction_filter_sort"),
    ("f_subset_rank", "在 2024 年营业收入前 30 的公司中，找出净利率最高的 10 家。", "nested_top_n"),
    ("f_cross_table_ratio", "在 2024 年营业收入前 30 的公司中，找出资产负债率最低的 10 家。", "nested_top_n"),
    ("f_multi_sort", "找出 2024 年营业收入同比和净利润同比均为正的公司，先按净利润同比、再按营业收入同比降序。", "yoy_direction_filter_sort"),
]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    planner = traced_node("query_planner", llm_plan_query_node)
    records: list[dict] = []
    for case_id, question, expected_operation in CASES:
        result = planner({"user_question": question})
        query_spec = result.get("query_spec") if isinstance(result.get("query_spec"), dict) else {}
        trace = (result.get("stage_traces") or [{}])[-1]
        passed = (
            query_spec.get("operation") == expected_operation
            and query_spec.get("execution_mode") == "flexible_sql"
            and trace.get("status") == "completed"
        )
        records.append({
            "case_id": case_id,
            "passed": passed,
            "expected_operation": expected_operation,
            "query_spec": query_spec,
            "error_type": result.get("error_type"),
            "stage_trace": trace,
        })
    path = OUTPUT_DIR / f"planner_benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(records, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"passed": sum(record["passed"] for record in records), "total": len(records), "path": str(path)}, ensure_ascii=False))
    return 0 if all(record["passed"] for record in records) else 1


if __name__ == "__main__":
    raise SystemExit(main())
