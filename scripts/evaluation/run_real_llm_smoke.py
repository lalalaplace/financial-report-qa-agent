"""真实 LLM 链路 smoke 测试。

父进程逐条启动子进程执行问题，避免单个 LLM 请求卡住整批测试。
"""

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
OUTPUT_PATH = PROJECT_ROOT / "output" / "real_llm_smoke_results.jsonl"
CASE_TIMEOUT_SECONDS = 90


CASES = [
    {
        "id": 1,
        "question": "\u534e\u6da6\u4e09\u4e5d 2024 \u5e74\u8425\u4e1a\u6536\u5165\u662f\u591a\u5c11\uff1f",
        "expectation": "point_query 跳过 LLM",
    },
    {
        "id": 2,
        "question": "\u534e\u6da6\u4e09\u4e5d 2024 \u5e74\u8425\u4e1a\u6536\u5165\u540c\u6bd4",
        "expectation": "yoy_query 不复述数值，不引入外部原因",
    },
    {
        "id": 3,
        "question": "\u534e\u6da6\u4e09\u4e5d 2021 \u5230 2024 \u5e74\u8425\u4e1a\u6536\u5165\u8d8b\u52bf\u600e\u4e48\u6837\uff1f",
        "expectation": "trend_query 输出趋势形态",
    },
    {
        "id": 4,
        "question": "\u534e\u6da6\u4e09\u4e5d\u548c\u8d35\u5dde\u8305\u53f0 2024 \u5e74\u8425\u4e1a\u6536\u5165\u8c01\u66f4\u9ad8\uff1f",
        "expectation": "compare_query 强调收入规模，不扩展为经营质量",
    },
    {
        "id": 5,
        "question": "\u534e\u6da6\u4e09\u4e5d\u548c\u8d35\u5dde\u8305\u53f0 2024 \u5e74\u51c0\u5229\u7387\u5bf9\u6bd4",
        "expectation": "派生指标解释含义，不给投资判断",
    },
    {
        "id": 6,
        "question": "2024 \u5e74\u8425\u4e1a\u6536\u5165\u6700\u9ad8\u7684\u524d 5 \u5bb6\u516c\u53f8\u662f\u8c01\uff1f",
        "expectation": "ranking_query 强调数据库样本范围",
    },
    {
        "id": 7,
        "question": "\u534e\u6da6\u4e09\u4e5d 2099 \u5e74\u8425\u4e1a\u6536\u5165\u662f\u591a\u5c11\uff1f",
        "expectation": "空结果不调用 LLM",
    },
    {
        "id": 8,
        "question": "\u534e\u6da6\u4e09\u4e5d 2024 \u5e74\u8425\u4e1a\u6536\u5165\u4e3a\u4ec0\u4e48\u589e\u957f\uff1f",
        "expectation": "不支持原因分析时，不让 LLM 编原因",
    },
]


FORBIDDEN_EXTERNAL_TERMS = [
    "并购",
    "内生增长",
    "外部",
    "政策",
    "市场需求",
    "产品销量",
    "价格变化",
    "渠道",
    "公告",
    "附注",
    "管理层",
    "经营原因",
    "业务范围变化",
]


def _compact(text: str | None) -> str:
    return " ".join((text or "").split())


def _llm_section(answer: str) -> str:
    if "补充解读：" not in answer and "可继续分析：" not in answer:
        return ""
    if "补充解读：" in answer:
        return answer.split("补充解读：", 1)[1]
    return answer.split("可继续分析：", 1)[1]


def _contains_any(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def _evaluate(case: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    case_id = case["id"]
    intent = result.get("intent_type")
    error_type = result.get("error_type")
    answer = result.get("final_answer") or ""
    llm_success = result.get("llm_analysis_success") is True
    llm_section = _llm_section(answer)

    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"name": name, "passed": passed, "detail": detail})

    if case_id == 1:
        add("点查跳过 LLM", not llm_success)
        add("点查主答案成功", result.get("business_success") is True and not error_type)
    elif case_id == 2:
        add("识别为同比查询", intent == "yoy_query")
        add("LLM 洞察生成", llm_success)
        add("补充解读不复述核心数值", not _contains_any(llm_section, ["276.17", "247.39", "28.78", "11.63%"]))
        add("不引入外部原因", not _contains_any(llm_section, FORBIDDEN_EXTERNAL_TERMS))
    elif case_id == 3:
        add("识别为趋势查询", intent == "trend_query")
        add("LLM 洞察生成", llm_success)
        add("包含趋势形态", _contains_any(llm_section, ["趋势", "形态", "上升", "下降", "波动", "持续"]))
    elif case_id == 4:
        add("识别为公司对比查询", intent == "company_compare_query")
        add("LLM 洞察生成", llm_success)
        add("不扩展为经营质量", "经营质量" not in llm_section and "盈利能力" not in llm_section)
    elif case_id == 5:
        add("识别为公司对比查询", intent == "company_compare_query")
        add("LLM 洞察生成", llm_success)
        add("不输出投资判断", not _contains_any(llm_section + answer, ["投资建议", "买入", "卖出", "持有评级"]))
    elif case_id == 6:
        add("识别为排名查询", intent == "ranking_query")
        add("LLM 洞察生成", llm_success)
        add("强调样本或口径范围", _contains_any(llm_section, ["样本", "范围", "口径", "数据库"]))
    elif case_id == 7:
        add("空结果不调用 LLM", not llm_success)
        add("业务未成功或有空结果错误", result.get("business_success") is not True or bool(error_type))
    elif case_id == 8:
        add("原因分析不应生成原因洞察", not llm_success or not _contains_any(llm_section, FORBIDDEN_EXTERNAL_TERMS))
        add("不编造原因", not _contains_any(answer, FORBIDDEN_EXTERNAL_TERMS))

    return {
        "checks": checks,
        "passed": all(item["passed"] for item in checks),
    }


def run_case(case_id: int) -> dict[str, Any]:
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))

    from agent.graph import app

    case = next(item for item in CASES if item["id"] == case_id)
    result = app.invoke({"user_question": case["question"]})
    evaluation = _evaluate(case, result)
    return {
        "case_id": case_id,
        "question": case["question"],
        "expectation": case["expectation"],
        "intent_type": result.get("intent_type"),
        "business_success": result.get("business_success"),
        "error_type": result.get("error_type"),
        "sql_success": result.get("sql_success"),
        "row_count": (result.get("query_result") or {}).get("row_count"),
        "llm_analysis_success": result.get("llm_analysis_success"),
        "llm_analysis": result.get("llm_analysis"),
        "llm_analysis_error": result.get("llm_analysis_error"),
        "final_answer": result.get("final_answer"),
        **evaluation,
    }


def run_parent() -> int:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_PATH
    if output_path.exists():
        try:
            output_path.unlink()
        except PermissionError:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = OUTPUT_PATH.with_name(
                f"{OUTPUT_PATH.stem}_{timestamp}{OUTPUT_PATH.suffix}"
            )

    overall_passed = True
    for case in CASES:
        case_id = case["id"]
        print(f"[RUN] case {case_id}: {case['question']}", flush=True)
        command = [
            sys.executable,
            "-u",
            str(Path(__file__).resolve()),
            "--case",
            str(case_id),
        ]
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        try:
            completed = subprocess.run(
                command,
                cwd=str(PROJECT_ROOT),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=CASE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            record = {
                "case_id": case_id,
                "question": case["question"],
                "expectation": case["expectation"],
                "passed": False,
                "timeout": True,
                "error": f"单条超时：{CASE_TIMEOUT_SECONDS} 秒",
            }
        else:
            if completed.returncode != 0:
                record = {
                    "case_id": case_id,
                    "question": case["question"],
                    "expectation": case["expectation"],
                    "passed": False,
                    "returncode": completed.returncode,
                    "stdout": completed.stdout,
                    "stderr": completed.stderr,
                }
            else:
                stdout_lines = [
                    line.strip()
                    for line in (completed.stdout or "").splitlines()
                    if line.strip()
                ]
                if not stdout_lines:
                    record = {
                        "case_id": case_id,
                        "question": case["question"],
                        "expectation": case["expectation"],
                        "passed": False,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                        "error": "子进程未输出 JSON",
                    }
                else:
                    record = json.loads(stdout_lines[-1])

        overall_passed = overall_passed and bool(record.get("passed"))
        with output_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        print(
            f"[DONE] case {case_id}: passed={record.get('passed')} "
            f"intent={record.get('intent_type')} error={record.get('error_type')} "
            f"llm={record.get('llm_analysis_success')}",
            flush=True,
        )

    print(f"[OUTPUT] {output_path}", flush=True)
    return 0 if overall_passed else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", type=int)
    args = parser.parse_args()
    if args.case:
        print(json.dumps(run_case(args.case), ensure_ascii=False), flush=True)
        return 0
    return run_parent()


if __name__ == "__main__":
    raise SystemExit(main())
