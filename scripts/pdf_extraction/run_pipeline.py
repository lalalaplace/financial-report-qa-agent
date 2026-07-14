import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Deque, Dict, List, Optional, TextIO


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = Path(__file__).resolve().parent
LOG_DIR = PROJECT_ROOT / "output" / "runtime" / "logs"
RUN_HISTORY_PATH = PROJECT_ROOT / "output" / "runtime" / "run_history.csv"
DEFAULT_SCAN_MODE = "all"
ERROR_TAIL_LIMIT = 20
DIVIDER = "=" * 50
INNER_DIVIDER = "-" * 50
 

def configure_console_encoding() -> None:
    """配置控制台编码，避免 Windows 输出异常。"""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def safe_text(value: object, stream: Optional[TextIO] = None) -> str:
    """将任意对象转换为可安全输出的文本。"""
    text = str(value)
    target_stream = stream if stream is not None else sys.stdout
    encoding = getattr(target_stream, "encoding", None) or "utf-8"
    try:
        return text.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except Exception:
        return text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")


def safe_print(
    *args,
    sep: str = " ",
    end: str = "\n",
    file: Optional[TextIO] = None,
    flush: bool = False,
) -> None:
    """安全打印，防止编码问题中断主流程。"""
    target_stream = file if file is not None else sys.stdout
    message = safe_text(sep, target_stream).join(safe_text(arg, target_stream) for arg in args)
    final_end = safe_text(end, target_stream)
    try:
        print(message, end=final_end, file=target_stream, flush=flush)
    except UnicodeEncodeError:
        fallback_message = message.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        fallback_end = final_end.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
        print(fallback_message, end=fallback_end, file=target_stream, flush=flush)


configure_console_encoding()


@dataclass(frozen=True)
class StepConfig:
    """定义单个流水线步骤。"""

    key: str
    script_name: str
    description: str
    supports_file_id: bool = False
    supports_limit: bool = False
    supports_statement_type: bool = False
    supports_target_table: bool = False
    extra_args: tuple[str, ...] = ()


STEP_CONFIGS: List[StepConfig] = [
    StepConfig(
        key="scan_reports",
        script_name="scan_reports.py",
        description="扫描 PDF 并写入 report_file_index",
        extra_args=("--mode", DEFAULT_SCAN_MODE),
    ),
    StepConfig(
        key="import_company",
        script_name="import_company.py",
        description="导入公司维表和别名表",
    ),
    StepConfig(
        key="import_attachment3_dict",
        script_name="import_attachment3_dict.py",
        description="导入附件3字段字典",
    ),
    StepConfig(
        key="parse_pdf_pages",
        script_name="parse_pdf_pages.py",
        description="逐页解析 PDF 并生成页面级缓存",
        supports_file_id=True,
        supports_limit=True,
    ),
    StepConfig(
        key="locate_financial_statements",
        script_name="locate_financial_statements.py",
        description="定位三大财务报表起始页",
        supports_file_id=True,
        supports_limit=True,
    ),
    StepConfig(
        key="extract_statement_blocks",
        script_name="extract_statement_blocks.py",
        description="提取报表定向文本 JSON",
        supports_file_id=True,
        supports_limit=True,
        supports_statement_type=True,
    ),
    StepConfig(
        key="extract_attachment3_rule_based",
        script_name="extract_attachment3_rule_based.py",
        description="基于规则抽取报表字段",
        supports_file_id=True,
        supports_limit=True,
        supports_statement_type=True,
    ),
    StepConfig(
        key="load_attachment3_results_to_sql",
        script_name="load_attachment3_results_to_sql.py",
        description="将抽取结果清洗并写入最终 SQL 表",
        supports_file_id=True,
        supports_limit=True,
        supports_target_table=True,
    ),
]


STEP_LOOKUP: Dict[str, int] = {}
for index, step in enumerate(STEP_CONFIGS, start=1):
    STEP_LOOKUP[str(index)] = index - 1
    STEP_LOOKUP[step.key] = index - 1
    STEP_LOOKUP[step.script_name] = index - 1
    STEP_LOOKUP[step.script_name.removesuffix(".py")] = index - 1


def parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(description="串行执行财报导入与规则抽取主流水线。")
    parser.add_argument("--file-id", type=int, nargs="*", help="仅传递给支持 --file-id 的子脚本，可传多个。")
    parser.add_argument("--limit", type=int, help="仅传递给支持 --limit 的子脚本。")
    parser.add_argument("--statement-type", nargs="*", help="仅传递给支持 --statement-type 的子脚本。")
    parser.add_argument("--target-table", nargs="*", help="仅传递给支持 --target-table 的子脚本。")
    parser.add_argument("--from-step", help="从指定步骤开始执行，支持序号、脚本名或步骤名。")
    parser.add_argument("--to-step", help="执行到指定步骤为止，支持序号、脚本名或步骤名。")
    parser.add_argument("--continue-on-error", action="store_true", help="某一步失败后继续执行后续步骤。")
    parser.add_argument(
        "--python-executable",
        default=sys.executable,
        help="指定用于执行子脚本的 Python 解释器路径，默认使用当前解释器。",
    )
    return parser.parse_args()


def resolve_step_index(raw_value: Optional[str], arg_name: str, default: int) -> int:
    """将步骤参数解析为索引。"""
    if not raw_value:
        return default
    normalized = raw_value.strip()
    if normalized not in STEP_LOOKUP:
        supported = ", ".join(step.script_name for step in STEP_CONFIGS)
        raise SystemExit(f"{arg_name} 无效：{raw_value}。可选步骤：{supported}")
    return STEP_LOOKUP[normalized]


def format_command(command: List[str]) -> str:
    """格式化命令文本。"""
    if os.name == "nt":
        return subprocess.list2cmdline(command)
    return " ".join(shlex.quote(part) for part in command)


def format_seconds(seconds: float) -> str:
    """格式化耗时。"""
    return f"{seconds:.1f} 秒"


def format_ratio_text(value: object) -> str:
    """将比例值格式化为百分比文本。"""
    try:
        numeric_value = float(value or 0.0)
    except (TypeError, ValueError):
        numeric_value = 0.0
    return f"{numeric_value * 100:.2f}%"


def build_command(
    step: StepConfig,
    python_executable: str,
    file_ids: Optional[List[int]],
    limit: Optional[int],
    statement_types: Optional[List[str]],
    target_tables: Optional[List[str]],
    run_id: str,
) -> List[str]:
    """构造子进程命令。"""
    script_path = SCRIPTS_DIR / step.script_name
    command = [python_executable, str(script_path)]
    if step.extra_args:
        command.extend(step.extra_args)
    if step.supports_file_id and file_ids:
        command.append("--file-id")
        command.extend(str(file_id) for file_id in file_ids)
    if step.supports_limit and limit is not None:
        command.extend(["--limit", str(limit)])
    if step.supports_statement_type and statement_types:
        command.append("--statement-type")
        command.extend(statement_types)
    if step.supports_target_table and target_tables:
        command.append("--target-table")
        command.extend(target_tables)
    if step.key == "parse_pdf_pages":
        command.extend(["--run-id", run_id])
    if step.key == "extract_attachment3_rule_based":
        command.extend(["--run-id", run_id, "--run-history-path", str(RUN_HISTORY_PATH)])
    if step.key == "load_attachment3_results_to_sql":
        command.extend(["--run-id", run_id])
    return command


def load_run_metrics(run_id: str) -> Dict:
    """读取规则抽取阶段生成的结构化运行指标。"""
    metrics_path = LOG_DIR / f"run_metrics_{run_id}.json"
    if not metrics_path.exists():
        return {}
    try:
        with metrics_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def load_page_cache_metrics(run_id: str) -> Dict:
    """读取页面缓存阶段生成的指标。"""
    metrics_path = LOG_DIR / f"page_cache_metrics_{run_id}.json"
    if not metrics_path.exists():
        return {}
    try:
        with metrics_path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return {}


def merge_page_cache_metrics(run_id: str, metrics_payload: Dict) -> Dict:
    """将页面缓存指标合并到统一 run_metrics。"""
    page_cache_metrics = load_page_cache_metrics(run_id)
    if not page_cache_metrics:
        return metrics_payload
    metrics_payload["page_cache_summary"] = page_cache_metrics
    metrics_path = LOG_DIR / f"run_metrics_{run_id}.json"
    try:
        with metrics_path.open("w", encoding="utf-8", newline="\n") as file:
            json.dump(metrics_payload, file, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return metrics_payload


def build_counter_lines(counter_map: Dict[str, int]) -> List[str]:
    """将计数字典转为 markdown 列表。"""
    lines = [f"- {key}: {value}" for key, value in sorted(counter_map.items(), key=lambda item: (-item[1], item[0]))]
    return lines or ["- 无"]


def build_issue_sample_lines(issue_samples: List[Dict]) -> List[str]:
    """将典型问题样本转为 markdown 列表。"""
    if not issue_samples:
        return ["- 无"]
    lines: List[str] = []
    for sample in issue_samples[:8]:
        lines.extend(
            [
                f"report_id={sample.get('report_id', '')}",
                f"- table={sample.get('table', '')}",
                f"- field={sample.get('field', '')}",
                f"- reason={sample.get('reason', '')}",
                f"- preview={sample.get('preview', '')}",
                "",
            ]
        )
    if lines and not lines[-1]:
        lines.pop()
    return lines


def write_pipeline_summary(
    run_id: str,
    log_path: Path,
    results: List[Dict],
    skipped_steps: List[StepConfig],
    total_duration: float,
) -> Optional[Path]:
    """在 pipeline 结束后写出统一的 markdown 摘要。"""
    metrics_payload = load_run_metrics(run_id)
    if not metrics_payload:
        return None
    metrics_payload = merge_page_cache_metrics(run_id, metrics_payload)

    run_history_row = {
        "run_id": run_id,
        "run_time": metrics_payload.get("run_time", ""),
        "git_commit": "",
        "branch": "",
        "test_files_count": "",
        "changed_files": "",
        "success_count": 0,
        "failed_count": 0,
        "empty_count": 0,
        "inserted_rows": 0,
        "total_target_fields": 0,
        "non_empty_fields": 0,
        "non_empty_rate": 0,
        "key_field_total": 0,
        "key_field_hit": 0,
        "key_field_hit_rate": 0,
        "high_risk_fill_count": 0,
        "high_risk_fill_suspect_count": 0,
        "not_found_count": 0,
        "alias_missing_count": 0,
        "entry_missing_count": 0,
        "semantic_unstable_count": 0,
        "unexpected_error_count": 0,
        "final_judgement": "",
        "notes": "",
    }
    if RUN_HISTORY_PATH.exists():
        try:
            import csv

            with RUN_HISTORY_PATH.open("r", encoding="utf-8-sig", newline="") as file:
                for row in csv.DictReader(file):
                    if row.get("run_id") == run_id:
                        run_history_row.update(row)
        except Exception:
            pass

    changed_files = [item.strip() for item in str(run_history_row.get("changed_files", "")).split(";") if item.strip()]
    if not changed_files:
        changed_files = ["-"]

    step_lines = [
        f"- {item['step'].script_name}: status={item['status']}, duration={format_seconds(item['duration'])}"
        for item in results
    ]
    step_lines.extend(f"- {step.script_name}: status=SKIPPED, duration=0.0 秒" for step in skipped_steps)
    if not step_lines:
        step_lines = ["- 无"]
    page_cache_summary = metrics_payload.get("page_cache_summary", {})

    summary_lines = [
        f"# Run Summary: {run_id}",
        "",
        "## 1. 基本信息",
        f"- git_commit: {run_history_row.get('git_commit', '')}",
        f"- branch: {run_history_row.get('branch', '')}",
        "- test_scope: pipeline",
        f"- test_files_count: {run_history_row.get('test_files_count', '')}",
        f"- run_time: {run_history_row.get('run_time', '')}",
        "",
        "## 2. 本轮修改文件",
        *[f"- {item}" for item in changed_files],
        "",
        "## 3. Pipeline 级统计",
        f"- success_count: {run_history_row.get('success_count', 0)}",
        f"- failed_count: {run_history_row.get('failed_count', 0)}",
        f"- empty_count: {run_history_row.get('empty_count', 0)}",
        f"- inserted_rows: {run_history_row.get('inserted_rows', 0)}",
        f"- pipeline_duration: {format_seconds(total_duration)}",
        f"- log_path: {log_path}",
        f"- page_cache_hit_count: {page_cache_summary.get('cache_hit_count', 0)}",
        f"- page_cache_miss_count: {page_cache_summary.get('cache_miss_count', 0)}",
        f"- page_cache_stale_count: {page_cache_summary.get('cache_stale_count', 0)}",
        f"- page_cache_parsed_page_count: {page_cache_summary.get('parsed_page_count', 0)}",
        f"- page_cache_reused_page_count: {page_cache_summary.get('reused_page_count', 0)}",
        "",
        "## 4. 字段覆盖统计",
        f"- total_target_fields: {run_history_row.get('total_target_fields', 0)}",
        f"- non_empty_fields: {run_history_row.get('non_empty_fields', 0)}",
        f"- non_empty_rate: {format_ratio_text(run_history_row.get('non_empty_rate', 0))}",
        "",
        "## 5. 关键字段统计",
        f"- key_field_total: {run_history_row.get('key_field_total', 0)}",
        f"- key_field_hit: {run_history_row.get('key_field_hit', 0)}",
        f"- key_field_hit_rate: {format_ratio_text(run_history_row.get('key_field_hit_rate', 0))}",
        "",
        "## 6. 高风险统计",
        f"- high_risk_fill_count: {run_history_row.get('high_risk_fill_count', 0)}",
        f"- high_risk_fill_suspect_count: {run_history_row.get('high_risk_fill_suspect_count', 0)}",
        "",
        "## 7. 诊断拆分",
        f"- not_found_count: {run_history_row.get('not_found_count', 0)}",
        f"- alias_missing_count: {run_history_row.get('alias_missing_count', 0)}",
        f"- entry_missing_count: {run_history_row.get('entry_missing_count', 0)}",
        f"- semantic_unstable_count: {run_history_row.get('semantic_unstable_count', 0)}",
        f"- unexpected_error_count: {run_history_row.get('unexpected_error_count', 0)}",
        "",
        "## 8. 结构化结果",
        "- pipeline_steps:",
        *step_lines,
        "- statement_type_summary:",
        *build_counter_lines(metrics_payload.get("statement_type_summary", {})),
        "- zero_reason_summary:",
        *build_counter_lines(metrics_payload.get("zero_reason_summary", {})),
        "- upstream_issue_stage_summary:",
        *build_counter_lines(metrics_payload.get("upstream_issue_stage_summary", {})),
        "- decision_summary:",
        *build_counter_lines(metrics_payload.get("decision_summary", {})),
        "",
        "## 9. 典型错误样本",
        *build_issue_sample_lines(metrics_payload.get("issue_samples", [])),
        "",
        "## 10. 本轮结论",
        f"- final_judgement: {run_history_row.get('final_judgement', '')}",
        f"- notes: {run_history_row.get('notes', '')}",
    ]

    summary_path = LOG_DIR / f"run_summary_{run_id}.md"
    with summary_path.open("w", encoding="utf-8", newline="\n") as file:
        file.write("\n".join(summary_lines) + "\n")
    return summary_path


def stream_pipe(pipe, is_stderr: bool, error_tail: Deque[str], log_file: TextIO) -> None:
    """实时转发子进程输出，并同步落盘。"""
    try:
        for line in iter(pipe.readline, ""):
            safe_print(line, end="")
            log_file.write(line)
            log_file.flush()
            if is_stderr:
                error_tail.append(line.rstrip("\r\n"))
    finally:
        pipe.close()


def run_step(step: StepConfig, index: int, total: int, command: List[str], log_file: TextIO) -> Dict:
    """执行单个步骤。"""
    started_at = datetime.now()
    command_text = format_command(command)

    for line in [
        DIVIDER,
        f"[{index}/{total}] 开始：{step.script_name}",
        f"说明：{step.description}",
        f"命令：{command_text}",
        f"开始时间：{started_at.strftime('%Y-%m-%d %H:%M:%S')}",
        INNER_DIVIDER,
    ]:
        safe_print(line)
        log_file.write(line + "\n")
    log_file.flush()

    error_tail: Deque[str] = deque(maxlen=ERROR_TAIL_LIMIT)
    process = subprocess.Popen(
        command,
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )

    stdout_thread = threading.Thread(target=stream_pipe, args=(process.stdout, False, error_tail, log_file), daemon=True)
    stderr_thread = threading.Thread(target=stream_pipe, args=(process.stderr, True, error_tail, log_file), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    return_code = process.wait()
    stdout_thread.join()
    stderr_thread.join()

    finished_at = datetime.now()
    duration = (finished_at - started_at).total_seconds()
    status = "SUCCESS" if return_code == 0 else "FAILED"

    summary_lines = [
        INNER_DIVIDER,
        f"[{index}/{total}] 完成：{step.script_name}",
        f"状态：{status}",
        f"耗时：{format_seconds(duration)}",
    ]
    if return_code != 0:
        summary_lines.append(f"return code：{return_code}")
        summary_lines.append(f"失败命令：{command_text}")
        if error_tail:
            summary_lines.append("错误尾部：")
            summary_lines.extend(error_tail)
        else:
            summary_lines.append("错误尾部：无 stderr 输出，请检查上方日志。")
    summary_lines.append(DIVIDER)

    for line in summary_lines:
        safe_print(line)
        log_file.write(line + "\n")
    log_file.flush()

    return {
        "step": step,
        "status": status,
        "return_code": return_code,
        "duration": duration,
        "started_at": started_at,
        "finished_at": finished_at,
        "command": command_text,
        "error_tail": list(error_tail),
    }


def print_selected_steps(selected_steps: List[StepConfig], log_file: TextIO) -> None:
    """打印本次执行步骤。"""
    safe_print("本次执行步骤：")
    log_file.write("本次执行步骤：\n")
    for index, step in enumerate(selected_steps, start=1):
        line = f"{index}. {step.script_name} - {step.description}"
        safe_print(line)
        log_file.write(line + "\n")
    safe_print(DIVIDER)
    log_file.write(DIVIDER + "\n")
    log_file.flush()


def print_summary(results: List[Dict], skipped_steps: List[StepConfig], total_duration: float, log_file: TextIO) -> None:
    """打印最终汇总。"""
    success_count = sum(1 for item in results if item["status"] == "SUCCESS")
    failed_count = sum(1 for item in results if item["status"] == "FAILED")

    lines = [
        "",
        DIVIDER,
        "Pipeline 执行汇总",
        DIVIDER,
        f"成功步骤数：{success_count}",
        f"失败步骤数：{failed_count}",
        f"跳过步骤数：{len(skipped_steps)}",
        f"总耗时：{format_seconds(total_duration)}",
        INNER_DIVIDER,
    ]

    for index, item in enumerate(results, start=1):
        step = item["step"]
        lines.append(f"[{index}] {step.script_name} | 状态={item['status']} | 耗时={format_seconds(item['duration'])}")

    for step in skipped_steps:
        lines.append(f"[SKIPPED] {step.script_name} | 状态=SKIPPED | 耗时=0.0 秒")

    lines.append(DIVIDER)

    for line in lines:
        safe_print(line)
        log_file.write(line + "\n")
    log_file.flush()


def main() -> int:
    """主入口。"""
    args = parse_args()
    run_id = datetime.now().strftime("%Y%m%d_r%H%M%S")
    from_index = resolve_step_index(args.from_step, "--from-step", 0)
    to_index = resolve_step_index(args.to_step, "--to-step", len(STEP_CONFIGS) - 1)
    if from_index > to_index:
        raise SystemExit("--from-step 不能晚于 --to-step")

    selected_steps = STEP_CONFIGS[from_index : to_index + 1]
    skipped_steps = STEP_CONFIGS[:from_index] + STEP_CONFIGS[to_index + 1 :]

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    with log_path.open("w", encoding="utf-8", errors="replace", newline="\n") as log_file:
        startup_lines = [
            DIVIDER,
            "Pipeline 总控启动",
            DIVIDER,
            f"项目目录：{PROJECT_ROOT}",
            f"脚本目录：{SCRIPTS_DIR}",
            f"日志文件：{log_path}",
            f"run_id：{run_id}",
            f"Python 解释器：{args.python_executable}",
            f"continue_on_error：{args.continue_on_error}",
            f"file_id：{args.file_id if args.file_id else '未指定'}",
            f"limit：{args.limit if args.limit is not None else '未指定'}",
            f"statement_type：{args.statement_type if args.statement_type else '未指定'}",
            f"target_table：{args.target_table if args.target_table else '未指定'}",
            f"执行范围：{selected_steps[0].script_name} -> {selected_steps[-1].script_name}",
            DIVIDER,
        ]
        for line in startup_lines:
            safe_print(line)
            log_file.write(line + "\n")
        log_file.flush()

        print_selected_steps(selected_steps, log_file)

        overall_started = time.perf_counter()
        results: List[Dict] = []

        for index, step in enumerate(selected_steps, start=1):
            command = build_command(
                step=step,
                python_executable=args.python_executable,
                file_ids=args.file_id,
                limit=args.limit,
                statement_types=args.statement_type,
                target_tables=args.target_table,
                run_id=run_id,
            )
            result = run_step(step=step, index=index, total=len(selected_steps), command=command, log_file=log_file)
            results.append(result)

            if result["status"] == "FAILED" and not args.continue_on_error:
                line = "检测到失败步骤，未开启 --continue-on-error，后续步骤停止执行。"
                safe_print(line)
                log_file.write(line + "\n")
                skipped_steps = selected_steps[index:] + skipped_steps
                break

        total_duration = time.perf_counter() - overall_started
        print_summary(results=results, skipped_steps=skipped_steps, total_duration=total_duration, log_file=log_file)
        summary_path = write_pipeline_summary(
            run_id=run_id,
            log_path=log_path,
            results=results,
            skipped_steps=skipped_steps,
            total_duration=total_duration,
        )
        if summary_path is not None:
            line = f"结构化摘要：{summary_path}"
            safe_print(line)
            log_file.write(line + "\n")

    has_failure = any(item["status"] == "FAILED" for item in results)
    return 1 if has_failure else 0


if __name__ == "__main__":
    sys.exit(main())
