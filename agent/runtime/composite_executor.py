"""V0.8.3 复合查询 task-by-task 执行器。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from agent.constants import DEFAULT_REPORT_PERIOD
from agent.nodes.analyze_nodes.compare_analysis import analyze_compare_node, analyze_derived_compare_node
from agent.nodes.analyze_nodes.compare_trend_analysis import (
    analyze_compare_trend_node,
    analyze_derived_compare_trend_node,
)
from agent.nodes.analyze_nodes.compare_yoy_analysis import (
    analyze_compare_yoy_node,
    analyze_derived_compare_yoy_node,
)
from agent.nodes.analyze_nodes.derived_analysis import analyze_derived_metric_node
from agent.nodes.analyze_nodes.rank_position_analysis import analyze_rank_position_node
from agent.nodes.analyze_nodes.ranking_analysis import analyze_ranking_node
from agent.nodes.analyze_nodes.trend_analysis import analyze_derived_trend_node, analyze_trend_node
from agent.nodes.analyze_nodes.trend_ranking_analysis import analyze_trend_ranking_node
from agent.nodes.analyze_nodes.yoy_analysis import analyze_derived_yoy_node, analyze_yoy_node
from agent.nodes.analyze_nodes.yoy_ranking_analysis import analyze_yoy_ranking_node
from agent.nodes.answer_nodes.clarify_answer import generate_unsupported_answer_node
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.nodes.execute_sql_node import review_and_execute_sql_node
from agent.nodes.llm_sql_node import generate_llm_sql_node, _tabular_analysis_from_query_result
from agent.nodes.sql_generation_router import (
    build_llm_sql_requirement_from_state,
    is_template_gap_error,
    route_sql_generation,
)
from agent.nodes.global_structured_query_detector import is_global_structured_query
from agent.nodes.slot_nodes import check_slots_node, map_metric_node, resolve_company_node
from agent.nodes.sql_nodes.compare_sql import generate_compare_sql_node
from agent.nodes.sql_nodes.compare_trend_sql import generate_compare_trend_sql_node
from agent.nodes.sql_nodes.compare_yoy_sql import generate_compare_yoy_sql_node
from agent.nodes.sql_nodes.derived_sql import (
    generate_derived_compare_sql_node,
    generate_derived_compare_trend_sql_node,
    generate_derived_compare_yoy_sql_node,
    generate_derived_sql_node,
    generate_derived_trend_sql_node,
    generate_derived_yoy_sql_node,
)
from agent.nodes.sql_nodes.point_sql import generate_point_sql_node
from agent.nodes.sql_nodes.rank_position_sql import generate_rank_position_sql_node
from agent.nodes.sql_nodes.ranking_sql import generate_ranking_sql_node
from agent.nodes.sql_nodes.trend_ranking_sql import generate_trend_ranking_sql_node
from agent.nodes.sql_nodes.trend_sql import generate_trend_sql_node
from agent.nodes.sql_nodes.yoy_ranking_sql import generate_yoy_ranking_sql_node
from agent.nodes.sql_nodes.yoy_sql import generate_yoy_sql_node
from agent.routing import route_by_intent
from agent.runtime.composite_sql import (
    analyze_company_set_yoy_result,
    analyze_yoy_ranking_from_metric_table,
    build_company_set_ranking_sql,
    build_revenue_profit_intersection_sql,
    build_company_set_yoy_sqls,
)
from agent.runtime.task_graph import build_task_dag
from agent.schemas.task_plan import TaskPlan
from agent.state import AgentState
from agent.tools.metric_tools import map_metrics


SQL_NODES = {
    "generate_point_sql": generate_point_sql_node,
    "generate_trend_sql": generate_trend_sql_node,
    "generate_derived_trend_sql": generate_derived_trend_sql_node,
    "generate_yoy_sql": generate_yoy_sql_node,
    "generate_derived_yoy_sql": generate_derived_yoy_sql_node,
    "generate_derived_sql": generate_derived_sql_node,
    "generate_compare_sql": generate_compare_sql_node,
    "generate_derived_compare_sql": generate_derived_compare_sql_node,
    "generate_compare_trend_sql": generate_compare_trend_sql_node,
    "generate_derived_compare_trend_sql": generate_derived_compare_trend_sql_node,
    "generate_compare_yoy_sql": generate_compare_yoy_sql_node,
    "generate_derived_compare_yoy_sql": generate_derived_compare_yoy_sql_node,
    "generate_ranking_sql": generate_ranking_sql_node,
    "generate_yoy_ranking_sql": generate_yoy_ranking_sql_node,
    "generate_trend_ranking_sql": generate_trend_ranking_sql_node,
    "generate_rank_position_sql": generate_rank_position_sql_node,
    "generate_unsupported_answer": generate_unsupported_answer_node,
}


GLOBAL_RUNTIME_FIELDS = {
    "sql",
    "query_result",
    "analysis_result",
    "final_answer",
    "business_success",
    "sql_success",
    "error_type",
    "need_clarification",
    "clarification_question",
}


def _task_to_state(task: TaskPlan, base_state: AgentState, task_artifacts: dict[str, Any]) -> AgentState:
    time_range = task.get("time") or {}
    ranking = task.get("ranking") or {}
    company_mentions = list(task.get("company_mentions") or [])
    metric_mentions = list(task.get("metric_mentions") or [])
    if task.get("intent") == "unknown":
        metric_mentions.extend(
            mention
            for mention in (base_state.get("global_metric_mentions") or [])
            if isinstance(mention, str) and mention.strip()
        )
        metric_mentions = list(dict.fromkeys(metric_mentions))

    for dependency in task.get("depends_on", []):
        if dependency.get("consume_as") != "company_mentions":
            continue
        artifact_key = dependency.get("artifact_key")
        artifact_value = task_artifacts.get(artifact_key)
        if isinstance(artifact_value, list):
            company_mentions.extend(_company_mentions_from_artifact(artifact_value))

    company_mentions = list(dict.fromkeys(company_mentions))

    return {
        "user_question": base_state.get("user_question", ""),
        "query_plan": None,
        "task_plan": dict(task),
        "intent_type": task.get("intent", "unknown"),
        "company_mentions": company_mentions,
        "metric_mentions": metric_mentions,
        "time_range": time_range,
        "report_period": base_state.get("report_period") or DEFAULT_REPORT_PERIOD,
        "time_mode": time_range.get("mode"),
        "report_year": time_range.get("report_year"),
        "recent_n_years": time_range.get("recent_n_years"),
        "start_year": time_range.get("start_year"),
        "end_year": time_range.get("end_year"),
        "report_years": time_range.get("report_years") or [],
        "rank_direction": ranking.get("rank_direction"),
        "limit": ranking.get("limit"),
        "change_metric": "yoy_rate" if task.get("intent") == "yoy_ranking_query" else None,
        "companies": [],
        "metrics": [],
        "warnings": [],
        "need_clarification": False,
        "llm_sql_requirement": task.get("llm_sql_requirement"),
        "global_metric_mentions": list(base_state.get("global_metric_mentions") or []),
        "global_metrics": list(base_state.get("global_metrics") or []),
    }


def _company_mentions_from_artifact(artifact_value: list[Any]) -> list[str]:
    mentions: list[str] = []
    for item in artifact_value:
        if isinstance(item, str):
            mentions.append(item)
        elif isinstance(item, dict):
            mention = item.get("stock_code") or item.get("company_name") or item.get("stock_abbr")
            if mention:
                mentions.append(str(mention))
    return mentions


def _run_analysis_node(task_state: AgentState) -> dict[str, Any]:
    intent_type = task_state.get("intent_type")
    metric_types = {m.get("metric_type", "base") for m in (task_state.get("metrics") or [])}

    if intent_type == "company_compare_yoy_query":
        return (
            analyze_derived_compare_yoy_node
            if metric_types == {"derived"}
            else analyze_compare_yoy_node
        )(task_state)
    if intent_type == "company_compare_trend_query":
        return (
            analyze_derived_compare_trend_node
            if metric_types == {"derived"}
            else analyze_compare_trend_node
        )(task_state)
    if intent_type == "company_compare_query":
        return (
            analyze_derived_compare_node
            if metric_types == {"derived"}
            else analyze_compare_node
        )(task_state)
    if intent_type == "yoy_query":
        if metric_types == {"derived"}:
            return analyze_derived_yoy_node(task_state)
        return analyze_yoy_node(task_state)
    if intent_type == "derived_metric_query":
        return analyze_derived_metric_node(task_state)
    if intent_type == "trend_query":
        if metric_types == {"derived"}:
            return analyze_derived_trend_node(task_state)
        return analyze_trend_node(task_state)
    if intent_type == "ranking_query":
        return analyze_ranking_node(task_state)
    if intent_type == "yoy_ranking_query":
        return analyze_yoy_ranking_node(task_state)
    if intent_type == "trend_ranking_query":
        return analyze_trend_ranking_node(task_state)
    if intent_type == "rank_position_query":
        return analyze_rank_position_node(task_state)
    return {}


def _extract_sql_payload(task_state: AgentState) -> Any:
    for key in (
        "sql",
        "yoy_sqls",
        "derived_sqls",
        "derived_trend_sqls",
        "derived_yoy_sqls",
        "compare_sqls",
        "compare_trend_sqls",
        "compare_yoy_sqls",
        "derived_compare_sqls",
        "derived_compare_trend_sqls",
        "derived_compare_yoy_sqls",
    ):
        value = task_state.get(key)
        if value:
            return value
    return None


def _extract_company_set(task_state: AgentState) -> list[dict[str, Any]]:
    analysis_result = task_state.get("analysis_result") or {}
    rows = analysis_result.get("rows") if isinstance(analysis_result, dict) else None
    if not isinstance(rows, list):
        return []
    company_set: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        company_set.append(
            {
                "stock_code": row.get("stock_code"),
                "company_name": row.get("company_name"),
            }
        )
    return company_set


def _dependency_artifact(task: TaskPlan, task_artifacts: dict[str, Any], consume_as: str) -> Any:
    for dependency in task.get("depends_on", []):
        if dependency.get("consume_as") != consume_as:
            continue
        artifact_key = dependency.get("artifact_key")
        if artifact_key in task_artifacts:
            return task_artifacts[artifact_key]
    return None


def _extract_artifacts(task: TaskPlan, task_state: AgentState) -> dict[str, Any]:
    output_artifact = task.get("output_artifact") or {}
    artifact_type = output_artifact.get("artifact_type") or "unspecified"

    if artifact_type == "company_set":
        return {"company_set": _extract_company_set(task_state)}
    if artifact_type in {"metric_table", "ranking_table"}:
        return {artifact_type: deepcopy(task_state.get("analysis_result"))}
    if artifact_type == "scalar":
        return {"scalar": deepcopy(task_state.get("analysis_result"))}
    return {"answer_fragment": deepcopy(task_state.get("analysis_result"))}


def _store_artifacts(
    task: TaskPlan,
    task_result: dict[str, Any],
    task_artifacts: dict[str, Any],
) -> None:
    output_artifact = task.get("output_artifact") or {}
    artifact_key = output_artifact.get("artifact_key")
    artifact_type = output_artifact.get("artifact_type")
    artifacts = task_result.get("artifacts") or {}
    if artifact_key and artifact_type and artifact_type in artifacts:
        task_artifacts[artifact_key] = artifacts[artifact_type]


def _strip_global_runtime_fields(state: AgentState) -> AgentState:
    return {key: value for key, value in state.items() if key not in GLOBAL_RUNTIME_FIELDS}


def _task_metric_mentions(composite_plan: dict[str, Any]) -> list[str]:
    mentions: list[str] = []
    for task in composite_plan.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        mentions.extend(
            mention
            for mention in (task.get("metric_mentions") or [])
            if isinstance(mention, str) and mention.strip()
        )
        ranking = task.get("ranking")
        if isinstance(ranking, dict):
            for key in ("rank_by", "secondary_rank_by"):
                value = ranking.get(key)
                if isinstance(value, str) and value.strip():
                    mentions.append(value.strip())
    return list(dict.fromkeys(mentions))


def _full_metric_mentions_from_state(state: AgentState, composite_plan: dict[str, Any] | None = None) -> list[str]:
    mentions: list[str] = []
    slot_extraction = state.get("slot_extraction") if isinstance(state.get("slot_extraction"), dict) else {}
    for source in (
        state.get("metric_mentions") or [],
        slot_extraction.get("metric_mentions") or [],
        _task_metric_mentions(composite_plan or {}),
    ):
        mentions.extend(item for item in source if isinstance(item, str) and item.strip())
    return list(dict.fromkeys(mentions))


def _map_full_question_metrics(state: AgentState, composite_plan: dict[str, Any] | None = None) -> tuple[list[str], list[dict[str, Any]]]:
    mentions = _full_metric_mentions_from_state(state, composite_plan)
    metrics_by_key: dict[str, dict[str, Any]] = {}
    if mentions:
        metric_result = map_metrics(" ".join(mentions))
        if not metric_result.get("need_clarification"):
            for metric in metric_result.get("metrics") or []:
                key = metric.get("metric_key")
                if key:
                    metrics_by_key[key] = metric

    metric_result = map_metrics(state.get("user_question") or "")
    if not metric_result.get("need_clarification"):
        for metric in metric_result.get("metrics") or []:
            key = metric.get("metric_key")
            if key:
                metrics_by_key.setdefault(key, metric)
                name = metric.get("metric_name") or metric.get("metric_key")
                if isinstance(name, str) and name.strip():
                    mentions.append(name.strip())
    metrics = list(metrics_by_key.values())
    metric_mentions = [
        metric.get("metric_name") or metric.get("metric_key")
        for metric in metrics
        if isinstance(metric, dict) and (metric.get("metric_name") or metric.get("metric_key"))
    ]
    return list(dict.fromkeys([item for item in [*mentions, *metric_mentions] if item])), metrics


def _report_year_from_state_or_plan(state: AgentState, composite_plan: dict[str, Any]) -> int | None:
    if isinstance(state.get("report_year"), int):
        return state["report_year"]
    slot_extraction = state.get("slot_extraction") if isinstance(state.get("slot_extraction"), dict) else {}
    time_range = slot_extraction.get("time_range") if isinstance(slot_extraction.get("time_range"), dict) else {}
    if isinstance(time_range.get("report_year"), int):
        return time_range["report_year"]
    for task in composite_plan.get("tasks") or []:
        task_time = task.get("time") if isinstance(task, dict) and isinstance(task.get("time"), dict) else {}
        if isinstance(task_time.get("report_year"), int):
            return task_time["report_year"]
    return None


def _is_set_intersection_question(state: AgentState, composite_plan: dict[str, Any]) -> bool:
    question = state.get("user_question") or ""
    if not is_global_structured_query(
        {
            **state,
            "metric_mentions": _full_metric_mentions_from_state(state, composite_plan),
            "report_year": _report_year_from_state_or_plan(state, composite_plan),
        }
    ):
        return False
    return (
        ("都进入" in question or "都进" in question)
        and ("前" in question or "top" in question.lower())
        and ("按" in question or "排序" in question)
    )


def _execute_whole_composite_with_llm_sql(
    state: AgentState,
    composite_plan: dict[str, Any],
) -> dict[str, Any]:
    metric_mentions, metrics = _map_full_question_metrics(state, composite_plan)
    report_year = _report_year_from_state_or_plan(state, composite_plan)
    llm_sql_state = _strip_global_runtime_fields(state)
    report_period = state.get("report_period") or DEFAULT_REPORT_PERIOD
    requirement = {
        "can_use_llm_sql": False,
        "reason": "template_should_handle",
        "requirement_type": "set_intersection",
        "template_status": "matched",
        "read_only": True,
        "metric_mentions": metric_mentions,
        "company_mentions": [],
        "report_year": report_year,
        "report_period": report_period,
        "company_universe": {"type": "all_companies", "companies": []},
        "base_universe": {
            "type": "intersection",
            "metric_mention": metric_mentions[0] if metric_mentions else None,
            "calculation": "metric_value",
            "rank_direction": "desc",
            "limit": 20,
            "filters": [],
        },
        "metrics": [
            {"metric_mention": mention, "role": "output_metric", "calculation": "metric_value"}
            for mention in metric_mentions
        ],
        "filters": [],
        "order_by": {
            "metric_mention": metric_mentions[-1] if metric_mentions else None,
            "calculation": "derived_metric",
            "direction": "desc",
        },
        "limit": 20,
        "expected_output": {"grain": "company", "must_include": []},
        "needs": {
            "prediction": False,
            "external_data": False,
            "text_understanding": False,
            "pdf_evidence": False,
        },
        "clarification_question": None,
        "unsupported_reason": None,
    }
    llm_sql_state.update(
        {
            "query_type": "composite",
            "task_plan": {"task_id": "whole_query", "intent": "unknown"},
            "intent_type": "unknown",
            "metric_mentions": metric_mentions,
            "metrics": metrics,
            "report_year": report_year,
            "time_range": {"mode": "single_year", "report_year": report_year} if report_year else state.get("time_range"),
            "report_period": report_period,
            "company_mentions": [],
            "companies": [],
            "company_source": "all_companies",
            "is_global_structured_query": True,
            "force_llm_sql": False,
            "template_gap_reason": None,
            "requirement_type": "set_intersection",
            "llm_sql_requirement": requirement,
        }
    )
    try:
        sql, sql_metadata = build_revenue_profit_intersection_sql(
            report_year=report_year,
            report_period=report_period,
            top_limit=20,
        )
    except ValueError as exc:
        llm_sql_state.update(
            {
                "need_clarification": True,
                "clarification_question": str(exc),
                "error_type": "invalid_set_intersection_template",
                "sql_generation_mode": "template",
            }
        )
        task_result = _task_result_from_state(llm_sql_state, False)
    else:
        llm_sql_state.update(
            {
                "sql": sql,
                "sql_metadata": sql_metadata,
                "sql_generation_mode": "template",
                "sql_generation_status": "success",
            }
        )
        llm_sql_state.update(review_and_execute_sql_node(llm_sql_state))
        llm_sql_state.update(_tabular_analysis_from_query_result(llm_sql_state.get("query_result") or {}))
        task_result = _task_result_from_state(llm_sql_state, bool(llm_sql_state.get("business_success")))

    return {
        "current_task_id": "whole_query",
        "task_results": {"whole_query": task_result},
        "task_artifacts": {},
        "composite_success": task_result["success"],
        "composite_error_type": task_result.get("error_type") or task_result.get("sql_generation_error_type"),
        "composite_analysis_result": task_result.get("analysis_result")
        if task_result.get("success")
        else {
            "completed_task_ids": ["whole_query"],
            "failed_task_id": "whole_query",
            "failed_stage": task_result.get("failed_stage"),
            "error_type": task_result.get("sql_generation_error_type") or task_result.get("error_type"),
            "error_message": task_result.get("error_message"),
            "template_gap_reason": task_result.get("template_gap_reason"),
            "sql_generation_mode": task_result.get("sql_generation_mode"),
        },
    }


def _execute_single_task(
    task: TaskPlan,
    base_state: AgentState,
    task_artifacts: dict[str, Any],
) -> dict[str, Any]:
    task_state = _task_to_state(task, base_state, task_artifacts)

    if task.get("intent") == "yoy_ranking_query":
        metric_table = _dependency_artifact(task, task_artifacts, "input_rows")
        if isinstance(metric_table, dict):
            ranking = task.get("ranking") or {}
            task_state.update(
                analyze_yoy_ranking_from_metric_table(
                    metric_table=metric_table,
                    rank_direction=ranking.get("rank_direction") or "desc",
                    limit=ranking.get("limit") or 10,
                )
            )
            return _task_result_from_state(task_state, bool(task_state.get("business_success")))

    if task.get("intent") == "ranking_query" and task.get("company_source") == "dependency":
        task_state.update(map_metric_node(task_state))
        if task_state.get("need_clarification"):
            return _task_result_from_state(task_state, False)

        metric_types = {
            metric.get("metric_type", "base")
            for metric in (task_state.get("metrics") or [])
            if isinstance(metric, dict)
        }
        if "derived" in metric_types:
            task_state["template_gap_reason"] = "dependency_scoped_derived_ranking"
            task_state["force_llm_sql"] = True
            task_state["llm_sql_requirement"] = build_llm_sql_requirement_from_state(task_state)
            task_state.update(route_sql_generation(task_state, template_nodes=SQL_NODES))
            if task_state.get("need_clarification") or not task_state.get("sql"):
                return _task_result_from_state(task_state, False)
            task_state.update(review_and_execute_sql_node(task_state))
            task_state.update(_tabular_analysis_from_query_result(task_state.get("query_result") or {}))
            return _task_result_from_state(task_state, bool(task_state.get("business_success")))

        company_set = _dependency_artifact(task, task_artifacts, "company_mentions")
        if not isinstance(company_set, list) or not company_set:
            task_state.update(
                {
                    "need_clarification": True,
                    "clarification_question": "复合排名任务缺少前序公司集合。",
                    "error_type": "missing_company_set_artifact",
                }
            )
            return _task_result_from_state(task_state, False)

        report_year = task_state.get("report_year")
        if report_year is None:
            task_state.update(
                {
                    "need_clarification": True,
                    "clarification_question": "复合排名任务缺少年份。",
                    "error_type": "missing_year",
                }
            )
            return _task_result_from_state(task_state, False)

        ranking = task.get("ranking") or {}
        try:
            sql, sql_metadata = build_company_set_ranking_sql(
                metric=(task_state.get("metrics") or [])[0],
                company_set=company_set,
                report_period=task_state.get("report_period") or DEFAULT_REPORT_PERIOD,
                report_year=report_year,
                rank_direction=ranking.get("rank_direction") or "desc",
                limit=ranking.get("limit") or 10,
            )
        except (IndexError, KeyError, ValueError) as exc:
            task_state.update(
                {
                    "need_clarification": True,
                    "clarification_question": str(exc),
                    "error_type": "invalid_company_set_ranking_template",
                }
            )
            return _task_result_from_state(task_state, False)

        task_state["sql"] = sql
        task_state["sql_metadata"] = sql_metadata
        task_state.update(review_and_execute_sql_node(task_state))
        task_state.update(analyze_ranking_node(task_state))
        return _task_result_from_state(task_state, bool(task_state.get("business_success")))

    if task.get("intent") == "yoy_query" and task.get("company_source") == "dependency":
        task_state.update(map_metric_node(task_state))
        if task_state.get("need_clarification"):
            return _task_result_from_state(task_state, False)
        company_set = _dependency_artifact(task, task_artifacts, "company_mentions")
        if not isinstance(company_set, list) or not company_set:
            task_state.update(
                {
                    "need_clarification": True,
                    "clarification_question": "复合同比任务缺少前序公司集合。",
                    "error_type": "missing_company_set_artifact",
                }
            )
            return _task_result_from_state(task_state, False)
        report_year = task_state.get("report_year")
        if report_year is None:
            task_state.update(
                {
                    "need_clarification": True,
                    "clarification_question": "复合同比任务缺少年份。",
                    "error_type": "missing_year",
                }
            )
            return _task_result_from_state(task_state, False)

        try:
            task_state["yoy_sqls"] = build_company_set_yoy_sqls(
                metrics=task_state.get("metrics") or [],
                company_set=company_set,
                report_period=task_state.get("report_period") or DEFAULT_REPORT_PERIOD,
                report_year=report_year,
            )
        except ValueError as exc:
            task_state.update(
                {
                    "need_clarification": True,
                    "clarification_question": str(exc),
                    "error_type": "invalid_composite_yoy_template",
                }
            )
            return _task_result_from_state(task_state, False)

        task_state.update(review_and_execute_sql_node(task_state))
        task_state.update(
            analyze_company_set_yoy_result(
                query_result=task_state.get("query_result") or {},
                metrics=task_state.get("metrics") or [],
                report_year=report_year,
            )
        )
        return _task_result_from_state(task_state, bool(task_state.get("business_success")))

    for node in (resolve_company_node, map_metric_node, check_slots_node):
        task_state.update(node(task_state))
        if task_state.get("need_clarification"):
            dependency_scoped_ranking_gap = (
                task.get("intent") == "ranking_query"
                and task.get("company_source") == "dependency"
                and bool(task.get("depends_on"))
            )
            if is_template_gap_error(task_state.get("error_type")) or dependency_scoped_ranking_gap:
                task_state["template_gap_reason"] = task_state.get("clarification_question") or task_state.get("error_type")
                task_state["llm_sql_requirement"] = build_llm_sql_requirement_from_state(task_state)
                task_state["force_llm_sql"] = True
                task_state["need_clarification"] = False
                task_state["clarification_question"] = None
                break
            return _task_result_from_state(task_state, False)

    task_state.update(route_sql_generation(task_state, template_nodes=SQL_NODES))
    if task_state.get("need_clarification"):
        return _task_result_from_state(task_state, False)

    task_state.update(review_and_execute_sql_node(task_state))
    task_state.update(_run_analysis_node(task_state))
    return _task_result_from_state(task_state, bool(task_state.get("business_success")))


def _task_result_from_state(task_state: AgentState, success: bool) -> dict[str, Any]:
    artifacts: dict[str, Any] = {}
    sql_generation_error_type = task_state.get("sql_generation_error_type")
    error_type = task_state.get("error_type")
    if sql_generation_error_type in {
        "SQL_UNSAFE",
        "SQL_FIELD_NOT_ALLOWED",
        "SQL_TABLE_NOT_ALLOWED",
        "SQL_SEMANTIC_INVALID",
        "YOY_MISSING_PREVIOUS_YEAR",
        "RANKING_MISSING_ORDER_BY",
    }:
        error_category = "sql_validation_failed"
    elif task_state.get("need_clarification"):
        error_category = "clarification"
    elif task_state.get("template_gap_reason"):
        error_category = "template_gap"
    elif error_type:
        error_category = "unsupported"
    else:
        error_category = None
    failed_stage = None
    if not success:
        if task_state.get("sql_generation_error_type") in {"SQL_UNSAFE", "SQL_FIELD_NOT_ALLOWED", "SQL_TABLE_NOT_ALLOWED"}:
            failed_stage = "sql_guard"
        elif task_state.get("sql_generation_error_type") in {"SQL_SEMANTIC_INVALID", "YOY_MISSING_PREVIOUS_YEAR", "RANKING_MISSING_ORDER_BY"}:
            failed_stage = "semantic_validation"
        elif task_state.get("sql_generation_error_type") == "LLM_SQL_REQUIREMENT_REJECTED":
            failed_stage = "llm_sql_requirement"
        elif task_state.get("sql_generation_error_type") == "LLM_SQL_GENERATION_FAILED":
            failed_stage = "llm_sql_generation"
        elif task_state.get("template_gap_reason"):
            failed_stage = "template_router"
        elif task_state.get("need_clarification"):
            failed_stage = "slot_validation"
        elif error_type == "sql_execution_error" or task_state.get("sql_success") is False:
            failed_stage = "execution"
        else:
            failed_stage = "template_router"
    return {
        "sql": _extract_sql_payload(task_state),
        "query_result": deepcopy(task_state.get("query_result")),
        "analysis_result": deepcopy(task_state.get("analysis_result")),
        "success": success,
        "sql_success": task_state.get("sql_success"),
        "business_success": task_state.get("business_success"),
        "error_type": task_state.get("error_type"),
        "error_category": error_category,
        "failed_stage": failed_stage,
        "error_message": (
            task_state.get("sql_generation_error_message")
            or task_state.get("clarification_question")
            or ((task_state.get("query_result") or {}).get("error") if isinstance(task_state.get("query_result"), dict) else None)
        ),
        "sql_generation_error_type": sql_generation_error_type,
        "sql_generation_error_message": task_state.get("sql_generation_error_message"),
        "sql_generation_mode": task_state.get("sql_generation_mode"),
        "template_name": route_by_intent(task_state),
        "template_gap_reason": task_state.get("template_gap_reason"),
        "llm_sql_candidate": task_state.get("llm_sql_candidate"),
        "validation_errors": [
            item
            for item in [
                task_state.get("sql_generation_error_type"),
                task_state.get("sql_generation_error_message"),
            ]
            if item
        ],
        "sql_guard_passed": bool((task_state.get("llm_sql_validation") or task_state.get("sql_review") or {}).get("is_valid", (task_state.get("sql_review") or {}).get("is_safe"))),
        "semantic_guard_passed": bool((task_state.get("sql_semantic_validation") or {}).get("semantic_guard_passed", task_state.get("sql_generation_mode") == "template")),
        "llm_sql_request": deepcopy(task_state.get("llm_sql_request")),
        "llm_sql_raw_response": deepcopy(task_state.get("llm_sql_raw_response")),
        "dry_run_result": deepcopy(task_state.get("dry_run_result")),
        "need_clarification": task_state.get("need_clarification", False),
        "clarification_question": task_state.get("clarification_question"),
        "artifacts": artifacts,
    }


def execute_composite_plan_node(state: AgentState) -> dict[str, Any]:
    composite_plan = state.get("composite_query_plan") or state.get("composite_plan")
    if not isinstance(composite_plan, dict):
        return {
            "composite_success": False,
            "composite_error_type": "missing_composite_plan",
            "composite_analysis_result": None,
        }

    if _is_set_intersection_question(state, composite_plan) or isinstance(composite_plan.get("llm_sql_requirement"), dict):
        return {
            "composite_success": False,
            "composite_error_type": "single_sql_must_use_flexible_channel",
            "composite_analysis_result": {"failed_stage": "capability_routing", "error_type": "single_sql_must_use_flexible_channel"},
        }

    task_dag = state.get("task_dag") or build_task_dag(composite_plan.get("tasks", []))
    if task_dag.get("clarification_required"):
        return {
            "need_clarification": True,
            "clarification_question": task_dag.get("clarification_question"),
            "task_dag": task_dag,
            "composite_success": False,
            "composite_error_type": "clarification_required",
        }

    task_results: dict[str, dict[str, Any]] = {}
    task_artifacts: dict[str, Any] = {}
    base_state = _strip_global_runtime_fields(state)
    global_metric_mentions, global_metrics = _map_full_question_metrics(state, composite_plan)
    base_state["global_metric_mentions"] = global_metric_mentions
    base_state["global_metrics"] = global_metrics

    for task in task_dag.get("execution_order", []):
        task_id = task["task_id"]
        task_result = _execute_single_task(task, base_state, task_artifacts)
        task_result["artifacts"] = _extract_artifacts(task, {
            "analysis_result": task_result.get("analysis_result"),
        })
        task_results[task_id] = task_result
        _store_artifacts(task, task_result, task_artifacts)

        if not task_result.get("success"):
            return {
                "current_task_id": task_id,
                "task_results": task_results,
                "task_artifacts": task_artifacts,
                "composite_success": False,
                "composite_error_type": (
                    task_result.get("sql_generation_error_type")
                    or task_result.get("error_type")
                    or task_result.get("error_category")
                    or "task_failed"
                ),
                "composite_analysis_result": {
                    "completed_task_ids": list(task_results),
                    "failed_task_id": task_id,
                    "failed_stage": task_result.get("failed_stage"),
                    "error_type": (
                        task_result.get("sql_generation_error_type")
                        or task_result.get("error_type")
                        or task_result.get("error_category")
                    ),
                    "error_message": task_result.get("error_message"),
                    "template_gap_reason": task_result.get("template_gap_reason"),
                    "sql_generation_mode": task_result.get("sql_generation_mode"),
                },
            }

    return {
        "current_task_id": None,
        "task_results": task_results,
        "task_artifacts": task_artifacts,
        "composite_success": True,
        "composite_error_type": None,
        "composite_analysis_result": {
            "task_ids": list(task_results),
            "artifact_keys": list(task_artifacts),
        },
    }
