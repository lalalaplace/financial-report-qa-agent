"""复合查询任务规划节点。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.schemas.composite_query_plan import validate_composite_query_plan
from agent.services.llm_json_service import invoke_json_prompt


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = PROJECT_ROOT / "agent" / "prompts" / "composite_task_planner.md"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_composite_task_planner_prompt(
    question: str,
    intent_classification: dict[str, Any],
    slot_extraction: dict[str, Any],
) -> str:
    payload = {
        "original_question": question,
        "intent_classification": intent_classification,
        "slot_extraction": slot_extraction,
    }
    return _load_prompt() + "\n\n输入：\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def repair_composite_plan_from_slots(
    plan: dict[str, Any],
    slot_extraction: dict[str, Any],
) -> dict[str, Any]:
    """用已抽取槽位修复 LLM 任务计划中的可确定缺口。"""
    tasks = plan.get("tasks")
    if not isinstance(tasks, list):
        return plan

    default_time = slot_extraction.get("time_range")
    repaired_tasks: list[dict[str, Any]] = []
    last_company_set_task: dict[str, Any] | None = None

    for raw_task in tasks:
        task = dict(raw_task) if isinstance(raw_task, dict) else {}
        metric_mentions = task.get("metric_mentions") if isinstance(task.get("metric_mentions"), list) else []
        ranking = task.get("ranking") if isinstance(task.get("ranking"), dict) else None

        if task.get("intent") in {None, "", "unknown"} and ranking and metric_mentions:
            task["intent"] = "ranking_query"

        if task.get("company_source") in {None, "", "unspecified"} and task.get("intent") == "ranking_query":
            task["company_source"] = "all_companies"

        task_time = task.get("time")
        if (
            isinstance(default_time, dict)
            and default_time.get("mode") not in {None, "unspecified"}
            and (not isinstance(task_time, dict) or not task_time.get("report_year"))
        ):
            task["time"] = dict(default_time)

        if ranking and not ranking.get("rank_by") and metric_mentions:
            ranking = dict(ranking)
            ranking["rank_by"] = metric_mentions[0]
            task["ranking"] = ranking

        output_artifact = task.get("output_artifact") if isinstance(task.get("output_artifact"), dict) else {}
        output_artifact = dict(output_artifact)
        if output_artifact.get("artifact_type") in {None, "", "unspecified"}:
            if task.get("intent") == "ranking_query" and task.get("company_source") != "dependency":
                output_artifact["artifact_type"] = "company_set"
            elif task.get("intent") == "ranking_query":
                output_artifact["artifact_type"] = "ranking_table"
        task["output_artifact"] = output_artifact

        depends_on = task.get("depends_on") if isinstance(task.get("depends_on"), list) else []
        if task.get("company_source") == "dependency" and not depends_on and last_company_set_task:
            producer_artifact = last_company_set_task.get("output_artifact") or {}
            task["depends_on"] = [
                {
                    "task_id": last_company_set_task.get("task_id"),
                    "artifact_key": producer_artifact.get("artifact_key"),
                    "consume_as": "company_mentions",
                }
            ]

        repaired_tasks.append(task)
        artifact_type = (task.get("output_artifact") or {}).get("artifact_type")
        if artifact_type == "company_set":
            last_company_set_task = task

    repaired_plan = dict(plan)
    repaired_plan["tasks"] = repaired_tasks
    return repaired_plan


def reject_composite_if_single_database_relational_query(query_spec: dict[str, Any]) -> None:
    """单数据库关系型查询必须由确定性或 Flexible SQL 通道处理。"""
    if query_spec.get("is_single_database_relational_query") is True:
        raise ValueError("单数据库关系型查询禁止进入 CompositePlan。")


def plan_composite_tasks_node(state: dict[str, Any]) -> dict[str, Any]:
    query_spec = state.get("query_spec") if isinstance(state.get("query_spec"), dict) else {}
    reject_composite_if_single_database_relational_query(query_spec)
    question = state.get("user_question") or ""
    intent_classification = state.get("intent_classification") if isinstance(state.get("intent_classification"), dict) else {}
    slot_extraction = state.get("slot_extraction") if isinstance(state.get("slot_extraction"), dict) else {}
    payload = invoke_json_prompt(build_composite_task_planner_prompt(question, intent_classification, slot_extraction))
    payload = repair_composite_plan_from_slots(payload, slot_extraction)
    plan = validate_composite_query_plan(payload)
    return {"composite_query_plan_candidate": plan}


__all__ = [
    "build_composite_task_planner_prompt",
    "plan_composite_tasks_node",
    "reject_composite_if_single_database_relational_query",
    "repair_composite_plan_from_slots",
]
