"""当前双通道架构的真实模型端到端验收脚本。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "output" / "dual_channel_e2e"
CASE_TIMEOUT_SECONDS = int(os.getenv("DUAL_CHANNEL_E2E_CASE_TIMEOUT_SECONDS", "360"))


CASES = [
    {"id": "d_point", "group": "deterministic", "question": "华润三九 2024 年营业收入是多少？", "mode": "deterministic", "operation": "point_query"},
    {"id": "d_yoy", "group": "deterministic", "question": "华润三九 2024 年营业收入同比是多少？", "mode": "deterministic", "operation": "yoy_query"},
    {"id": "d_trend", "group": "deterministic", "question": "华润三九 2022—2024 年营业收入趋势", "mode": "deterministic", "operation": "trend_query"},
    {"id": "d_ranking", "group": "deterministic", "question": "2024 年营业收入最高的 10 家公司", "mode": "deterministic", "operation": "ranking_query"},
    {"id": "d_position", "group": "deterministic", "question": "华润三九 2024 年营业收入排名第几？", "mode": "deterministic", "operation": "rank_position_query"},
    {"id": "d_followup", "group": "deterministic", "question": "那 2023 年呢？", "mode": "deterministic", "operation": "point_query", "previous": "华润三九 2024 年营业收入是多少？"},
    {"id": "f_intersection", "group": "flexible_sql", "question": "找出 2024 年营业收入和净利润都进入前 20 的公司，并按净利率排序。", "mode": "flexible_sql", "operation": "set_intersection_ranking", "baseline_sql": "WITH revenue AS (SELECT stock_code, total_operating_revenue, net_profit FROM income_sheet WHERE report_year=2024 AND report_period='FY' AND total_operating_revenue IS NOT NULL AND total_operating_revenue <> 0 ORDER BY total_operating_revenue DESC LIMIT 20), profit AS (SELECT stock_code FROM income_sheet WHERE report_year=2024 AND report_period='FY' AND net_profit IS NOT NULL ORDER BY net_profit DESC LIMIT 20) SELECT r.stock_code FROM revenue r JOIN profit p USING(stock_code) ORDER BY r.net_profit / NULLIF(r.total_operating_revenue, 0) DESC, r.stock_code"},
    {"id": "f_cross_filter", "group": "flexible_sql", "question": "找出 2024 年净利润同比超过 50%，但营业收入同比低于 10% 的公司。", "mode": "flexible_sql", "operation": "multi_metric_yoy_filter", "baseline_sql": "WITH c AS (SELECT stock_code, net_profit, total_operating_revenue FROM income_sheet WHERE report_year=2024 AND report_period='FY'), p AS (SELECT stock_code, net_profit, total_operating_revenue FROM income_sheet WHERE report_year=2023 AND report_period='FY') SELECT c.stock_code FROM c JOIN p USING(stock_code) WHERE (c.net_profit-p.net_profit)/NULLIF(ABS(p.net_profit),0)>0.5 AND (c.total_operating_revenue-p.total_operating_revenue)/NULLIF(ABS(p.total_operating_revenue),0)<0.1 ORDER BY c.stock_code"},
    {"id": "f_opposite", "group": "flexible_sql", "question": "找出 2024 年营业收入下降但净利润上升的公司，并按净利润同比排序。", "mode": "flexible_sql", "operation": "yoy_direction_filter_sort", "baseline_sql": "WITH c AS (SELECT stock_code, net_profit, total_operating_revenue FROM income_sheet WHERE report_year=2024 AND report_period='FY'), p AS (SELECT stock_code, net_profit, total_operating_revenue FROM income_sheet WHERE report_year=2023 AND report_period='FY') SELECT c.stock_code FROM c JOIN p USING(stock_code) WHERE (c.total_operating_revenue-p.total_operating_revenue)/NULLIF(ABS(p.total_operating_revenue),0)<0 AND (c.net_profit-p.net_profit)/NULLIF(ABS(p.net_profit),0)>0 ORDER BY (c.net_profit-p.net_profit)/NULLIF(ABS(p.net_profit),0) DESC, c.stock_code"},
    {"id": "f_subset_rank", "group": "flexible_sql", "question": "在 2024 年营业收入前 30 的公司中，找出净利率最高的 10 家。", "mode": "flexible_sql", "operation": "nested_top_n", "baseline_sql": "WITH top_revenue AS (SELECT stock_code, net_profit, total_operating_revenue FROM income_sheet WHERE report_year=2024 AND report_period='FY' AND total_operating_revenue IS NOT NULL AND total_operating_revenue<>0 ORDER BY total_operating_revenue DESC LIMIT 30) SELECT stock_code FROM top_revenue WHERE net_profit IS NOT NULL ORDER BY net_profit/NULLIF(total_operating_revenue,0) DESC, stock_code LIMIT 10"},
    {"id": "f_cross_table_ratio", "group": "flexible_sql", "question": "在 2024 年营业收入前 30 的公司中，找出资产负债率最低的 10 家。", "mode": "flexible_sql", "operation": "nested_top_n", "baseline_sql": "WITH top_revenue AS (SELECT stock_code FROM income_sheet WHERE report_year=2024 AND report_period='FY' AND total_operating_revenue IS NOT NULL ORDER BY total_operating_revenue DESC LIMIT 30) SELECT b.stock_code FROM top_revenue t JOIN balance_sheet b USING(stock_code) WHERE b.report_year=2024 AND b.report_period='FY' AND b.asset_liability_ratio IS NOT NULL ORDER BY b.asset_liability_ratio ASC, b.stock_code LIMIT 10"},
    {"id": "f_multi_sort", "group": "flexible_sql", "question": "找出 2024 年营业收入同比和净利润同比均为正的公司，先按净利润同比、再按营业收入同比降序。", "mode": "flexible_sql", "operation": "yoy_direction_filter_sort", "baseline_sql": "WITH c AS (SELECT stock_code, net_profit, total_operating_revenue FROM income_sheet WHERE report_year=2024 AND report_period='FY'), p AS (SELECT stock_code, net_profit, total_operating_revenue FROM income_sheet WHERE report_year=2023 AND report_period='FY'), rates AS (SELECT c.stock_code, (c.net_profit-p.net_profit)/NULLIF(ABS(p.net_profit),0) AS profit_yoy, (c.total_operating_revenue-p.total_operating_revenue)/NULLIF(ABS(p.total_operating_revenue),0) AS revenue_yoy FROM c JOIN p USING(stock_code)) SELECT stock_code FROM rates WHERE profit_yoy>0 AND revenue_yoy>0 ORDER BY profit_yoy DESC, revenue_yoy DESC, stock_code LIMIT 50"},
    {"id": "u_price", "group": "unsupported", "question": "分析这些公司股价未来一个月的走势。", "mode": "unsupported"},
    {"id": "u_interview", "group": "unsupported", "question": "结合管理层访谈解释利润下降原因。", "mode": "unsupported"},
    {"id": "u_missing_data", "group": "unsupported", "question": "查询 2025 年尚未入库的年报数据。", "mode": "unsupported"},
    {"id": "c_year", "group": "clarification", "question": "找出营收最高的公司。", "mode": "clarification"},
    {"id": "c_metric", "group": "clarification", "question": "比较华润三九和白云山。", "mode": "clarification"},
    {"id": "c_growth", "group": "clarification", "question": "找出增长最快的公司。", "mode": "clarification"},
]


def _trace(result: dict[str, Any]) -> dict[str, Any]:
    planning = result.get("planning") if isinstance(result.get("planning"), dict) else {}
    decision = planning.get("capability_decision") if isinstance(planning.get("capability_decision"), dict) else {}
    query_result = result.get("query_result") if isinstance(result.get("query_result"), dict) else {}
    execution = result.get("execution") if isinstance(result.get("execution"), dict) else {}
    result_state = result.get("result") if isinstance(result.get("result"), dict) else {}
    contract = result_state.get("result_contract") if isinstance(result_state.get("result_contract"), dict) else result.get("result_contract") if isinstance(result.get("result_contract"), dict) else {}
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    return {
        "route_type": result.get("route_type"),
        "query_spec": result.get("query_spec"),
        "query_spec_validation_status": result.get("query_spec_validation_status"),
        "capability_mode": decision.get("execution_mode"),
        "sql_generation_mode": result.get("sql_generation_mode"),
        "execution_mode": execution.get("execution_mode"),
        "flexible_sql_spec": execution.get("flexible_sql_spec") or result.get("flexible_sql_spec"),
        "sql": execution.get("generated_sql") or result.get("sql"),
        "sql_candidate": result.get("llm_sql_repaired_candidate") or result.get("llm_sql_candidate"),
        "sql_guard_status": result.get("sql_guard_status"),
        "dry_run_status": result.get("dry_run_status"),
        "first_sql_valid": (execution.get("guard_result") or {}).get("is_valid"),
        "semantic_validation": result.get("sql_semantic_validation"),
        "repair_used": bool(result.get("sql_repair_attempted")),
        "dry_run_result": execution.get("dry_run_result") or result.get("dry_run_result"),
        "execution_success": query_result.get("success"),
        "row_count": query_result.get("row_count"),
        "result_columns": query_result.get("columns") or [],
        "result_rows": query_result.get("rows") or [],
        "result_shape": contract.get("result_shape"),
        "table_row_count": (result.get("deterministic_table") or {}).get("row_count"),
        "answer_mode": result.get("answer_mode"),
        "answer_validation_passed": result.get("answer_validation_passed"),
        "business_success": result.get("business_success"),
        "need_clarification": result.get("need_clarification"),
        "error_type": result.get("error_type"),
        "error_stage": error.get("error_stage"),
        "final_answer": result.get("final_answer"),
        "stage_traces": result.get("stage_traces") or [],
    }


def _evaluate(case: dict[str, Any], trace: dict[str, Any]) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool) -> None:
        checks.append({"name": name, "passed": bool(passed)})

    expected = case["mode"]
    actual = trace.get("capability_mode") or (trace.get("query_spec") or {}).get("execution_mode")
    if expected == "deterministic":
        add("进入确定性通道", actual == "deterministic")
        add("QuerySpec 操作语义匹配", (trace.get("query_spec") or {}).get("operation") == case.get("operation"))
        add("未进入 Flexible SQL", trace.get("sql_generation_mode") != "llm_sql")
        add("模板 SQL 已生成", bool(trace.get("sql")))
        add("SQL 执行成功", trace.get("execution_success") is True)
        add("固定回答已生成", trace.get("answer_mode") != "llm_answer" and bool(trace.get("final_answer")))
        add("未发生 Repair", trace.get("repair_used") is False)
    elif expected == "flexible_sql":
        add("进入 Flexible SQL", actual == "flexible_sql")
        add("QuerySpec 操作语义匹配", (trace.get("query_spec") or {}).get("operation") == case.get("operation"))
        add("生成 FlexibleSQLSpec", isinstance(trace.get("flexible_sql_spec"), dict))
        add("生成 SQL", bool(trace.get("sql")))
        add("Guard 通过", trace.get("sql_guard_status") == "passed")
        add("Dry Run 通过", trace.get("dry_run_status") == "passed")
        add("SQL 执行成功", trace.get("execution_success") is True)
        add("生成 ResultContract", bool(trace.get("result_shape")))
        add("确定性表格已构建", trace.get("table_row_count") is not None)
        add("回答组装并校验", trace.get("answer_validation_passed") is True and bool(trace.get("final_answer")))
        semantic = trace.get("semantic_validation")
        add("不存在语义校验失败但继续执行", not (isinstance(semantic, dict) and semantic.get("is_valid") is False and trace.get("execution_success") is True))
        baseline = _baseline_result(case)
        expected_codes = _stock_codes(baseline.get("columns") or [], baseline.get("rows") or [])
        actual_codes = _stock_codes(trace.get("result_columns") or [], trace.get("result_rows") or [])
        add("基准 SQL 执行成功", baseline.get("success") is True)
        add("结果股票代码与基准一致", actual_codes == expected_codes)
    elif expected == "unsupported":
        add("进入 unsupported", actual == "unsupported" or trace.get("sql_generation_mode") == "unsupported")
        add("未生成 SQL", not trace.get("sql"))
        add("未伪造成功", trace.get("business_success") is not True)
    else:
        add("要求澄清", trace.get("need_clarification") is True)
        add("未生成 SQL", not trace.get("sql"))
        add("未被 Flexible SQL 接管", actual != "flexible_sql" and trace.get("sql_generation_mode") != "llm_sql")
    return checks


def _stock_codes(columns: list[Any], rows: list[Any]) -> list[str]:
    try:
        index = columns.index("stock_code")
    except ValueError:
        return []
    return [str(row[index]) for row in rows if isinstance(row, list) and len(row) > index]


def _baseline_result(case: dict[str, Any]) -> dict[str, Any]:
    sql = case.get("baseline_sql")
    if not isinstance(sql, str) or not sql:
        return {"success": False, "columns": [], "rows": [], "error": "缺少基准 SQL"}
    from db.readonly_executor import execute_readonly_sql
    return execute_readonly_sql(sql, limit=50)


def _root_cause(trace: dict[str, Any], passed: bool) -> str | None:
    if passed:
        return "sql_expression_variant_repaired" if trace.get("repair_used") else None
    stage = trace.get("error_stage")
    error_type = trace.get("error_type") or "unknown"
    if stage in {"semantic_validation", "dry_run"} or error_type == "SQL_SEMANTIC_INVALID":
        return "semantic_error"
    if stage == "sql_guard":
        return "sql_expression_variant"
    if stage == "execution":
        return "execution_error"
    if trace.get("execution_mode") not in {None, trace.get("capability_mode")}:
        return "unexpected_channel_switch"
    return f"{stage or 'unknown'}:{error_type}"


def run_case(case_id: str, run_index: int = 1) -> dict[str, Any]:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from agent.graph import app

    case = next(item for item in CASES if item["id"] == case_id)
    state: dict[str, Any] = {"user_question": case["question"]}
    if case.get("previous"):
        previous = app.invoke({"user_question": case["previous"]})
        state = {**previous, "user_question": case["question"]}
    result = app.invoke(state)
    trace = _trace(result)
    checks = _evaluate(case, trace)
    passed = all(item["passed"] for item in checks)
    return {"case": case, "run": run_index, "passed": passed, "checks": checks, "trace": trace,
            "failure_report": {"case_id": case["id"], "mode": trace.get("execution_mode") or trace.get("capability_mode"),
                               "failed_stage": None if passed else trace.get("error_stage"), "first_sql_valid": trace.get("first_sql_valid"),
                               "repair_used": trace.get("repair_used"), "final_success": passed,
                               "root_cause": _root_cause(trace, passed)}}


def _build_summary(records: list[dict[str, Any]], runs: int) -> dict[str, Any]:
    deterministic = [record for record in records if record.get("case", {}).get("group") == "deterministic"]
    flexible = [record for record in records if record.get("case", {}).get("group") == "flexible_sql"]
    return {"runs": runs, "execution_count": len(records),
            "deterministic": {"passed": sum(record.get("passed") is True for record in deterministic), "total": len(deterministic), "required": "100%"},
            "flexible_sql": {"first_sql_valid": sum(record.get("failure_report", {}).get("first_sql_valid") is True for record in flexible),
                             "final_success": sum(record.get("failure_report", {}).get("final_success") is True for record in flexible),
                             "total": len(flexible), "final_success_target": "100%"},
            "failure_report": [record.get("failure_report", {}) for record in records]}


def run_parent(selected_group: str | None, runs: int) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"result_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl"
    selected = [case for case in CASES if selected_group is None or case["group"] == selected_group]
    records: list[dict[str, Any]] = []
    for run_index in range(1, runs + 1):
      for case in selected:
        command = [sys.executable, "-u", str(Path(__file__).resolve()), "--case", case["id"], "--run-index", str(run_index)]
        try:
            completed = subprocess.run(command, cwd=PROJECT_ROOT, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace", timeout=CASE_TIMEOUT_SECONDS)
            record = json.loads(completed.stdout.strip().splitlines()[-1]) if completed.returncode == 0 else {
                "case": case, "run": run_index, "passed": False, "error": completed.stderr or completed.stdout,
            }
        except subprocess.TimeoutExpired:
            record = {"case": case, "run": run_index, "passed": False, "error": f"超过 {CASE_TIMEOUT_SECONDS} 秒"}
        records.append(record)
        case_path = OUTPUT_DIR / f"{case['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        case_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        with output_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=True, default=str) + "\n")
        print(f"[第 {run_index} 轮][{case['id']}] {'通过' if record.get('passed') else '失败'}", flush=True)
    summary = _build_summary(records, runs)
    summary_path = output_path.with_suffix(".summary.json")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    passed = sum(record.get("passed") is True for record in records)
    print(f"结果：{passed}/{len(records)}，记录：{output_path}，报告：{summary_path}")
    flexible = summary["flexible_sql"]
    return 0 if summary["deterministic"]["passed"] == summary["deterministic"]["total"] and flexible["final_success"] == flexible["total"] else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case")
    parser.add_argument("--run-index", type=int, default=1)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--group", choices=["deterministic", "flexible_sql", "unsupported", "clarification"])
    args = parser.parse_args()
    if args.case:
        record = run_case(args.case, args.run_index)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        case_path = OUTPUT_DIR / f"{args.case}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        case_path.write_text(json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        print(json.dumps(record, ensure_ascii=True, default=str))
        return 0
    if args.runs < 1:
        parser.error("--runs 必须大于 0")
    return run_parent(args.group, args.runs)


if __name__ == "__main__":
    raise SystemExit(main())
