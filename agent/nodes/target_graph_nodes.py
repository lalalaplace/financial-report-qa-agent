"""目标主图适配节点。

这些节点提供新的图语义命名，并在内部复用现有稳定实现。
"""

from __future__ import annotations

import re
from typing import Any, Callable

from agent.nodes.answer_assembler import assemble_contract_answer, validate_assembled_answer_sections
from agent.nodes.answer_nodes.answer_dispatcher import generate_answer_node
from agent.nodes.answer_nodes.common import append_llm_insight_section
from agent.nodes.answer_nodes.clarify_answer import build_clarification_response_node
from agent.nodes.capability_router import route_query_capability
from agent.nodes.global_structured_query_detector import has_out_of_scope_signal
from agent.nodes.context_llm_nodes import (
    clarification_patch_node,
    followup_plan_node,
    merge_clarification_patch_node,
)
from agent.nodes.deterministic_table_renderer import render_deterministic_table
from agent.nodes.execute_sql_node import execute_partitioned_sql_node, review_and_execute_sql_node
from agent.nodes.llm_answer_synthesis_node import _build_prompt, _execution_failed, _fallback_response
from agent.nodes.llm_sql_node import generate_llm_sql_node
from agent.nodes.llm_sql_repair_node import llm_sql_repair_node
from agent.nodes.result_context_builder import build_answer_context, build_answer_context_from_contract
from agent.nodes.result_contract_builder import build_result_contract
from agent.nodes.slot_nodes import check_slots_node, map_metric_node, resolve_company_node
from agent.schemas.flexible_sql_spec import compile_flexible_sql_spec
from agent.tools.sql_tools import ALLOWED_TABLE_COLUMNS, review_sql
from agent.nodes.sql_generation_router_node import TEMPLATE_SQL_NODES
from agent.routing import route_analysis, route_by_intent
from agent.services.llm_json_service import invoke_json_prompt
from agent.schemas.state_sections import error_update
from agent.validators.answer_validator import validate_llm_answer_narrative
from agent.validators.sql_semantic_validator import validate_llm_sql_semantics
from db.readonly_executor import dry_run_sql
from db.sql_llm_guard import validate_llm_sql_static


def _with_section(result: dict[str, Any], section: str, values: dict[str, Any]) -> dict[str, Any]:
    """迁移期同时返回旧字段和分区字段。"""
    return {**result, section: values}


def _execution(state: dict[str, Any]) -> dict[str, Any]:
    """读取执行分区；旧扁平字段不再作为新节点输入。"""
    value = state.get("execution")
    return dict(value) if isinstance(value, dict) else {}


def _capability_mode(state: dict[str, Any]) -> str | None:
    planning = state.get("planning") if isinstance(state.get("planning"), dict) else {}
    decision = planning.get("capability_decision") if isinstance(planning.get("capability_decision"), dict) else {}
    return decision.get("execution_mode") if isinstance(decision.get("execution_mode"), str) else None


def _legacy_execution_view(state: dict[str, Any]) -> dict[str, Any]:
    """为尚未迁移的底层实现提供只读兼容视图。"""
    execution = _execution(state)
    return {
        **state,
        "sql": execution.get("generated_sql"),
        "flexible_sql_spec": execution.get("flexible_sql_spec"),
        "dry_run_result": execution.get("dry_run_result"),
        "query_result": execution.get("execution_result"),
    }


def _execution_mirror(values: dict[str, Any]) -> dict[str, Any]:
    """从执行分区单向生成旧扁平字段，禁止反向回填。"""
    fields = (
        "flexible_sql_spec", "generated_sql", "sql_attempts", "guard_result",
        "dry_run_result", "execution_result",
    )
    return {field: values[field] for field in fields if field in values}


def _deterministic_sql_entries(state: dict[str, Any]) -> list[dict[str, Any]]:
    """提取确定性构建器产生的多 SQL 计划，供目标主图统一审查。"""
    entries: list[dict[str, Any]] = []
    for key, value in state.items():
        if not key.endswith("_sqls") or not isinstance(value, list):
            continue
        entries.extend(item for item in value if isinstance(item, dict) and isinstance(item.get("sql"), str))
    return entries


def _with_error(
    result: dict[str, Any], stage: str, error_type: str, message: str | None, *, retryable: bool = False
) -> dict[str, Any]:
    return {**result, **error_update(stage, error_type, message, retryable=retryable)}


def merge_context_node(state: dict[str, Any]) -> dict[str, Any]:
    """合并澄清回答或上下文追问到当前查询状态。"""
    route_type = state.get("route_type")
    working_state = dict(state)
    if route_type == "clarification_answer":
        working_state.update(clarification_patch_node(working_state))
        if working_state.get("need_clarification"):
            return working_state
        working_state.update(merge_clarification_patch_node(working_state))
        return working_state
    if route_type == "contextual_followup":
        working_state.update(followup_plan_node(working_state))
        return working_state
    return {}


def query_planner_node(state: dict[str, Any]) -> dict[str, Any]:
    """执行 QuerySpec 规划，并清理上一轮阶段错误。"""
    from agent.nodes.llm_plan_query import llm_plan_query_node

    result = llm_plan_query_node(state)
    if isinstance(result.get("error_type"), str) and result["error_type"].endswith("_TIMEOUT"):
        return _with_error(result, "planning", result["error_type"], result.get("clarification_question"))
    result = _with_section(result, "conversation", {"user_question": state.get("user_question", "")})
    result = _with_section(result, "planning", {"query_spec": result.get("query_spec")})
    return {
        **result,
        "error": {"error_stage": None, "error_type": None, "error_message": None, "retryable": False, "details": {}},
    }


def irrelevant_answer_node(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_answer": "当前问题与结构化财报查询无关，请提供公司、指标和年份等查询条件。",
        "business_success": False,
        "error_type": "irrelevant_query",
    }


def entity_normalization_node(state: dict[str, Any]) -> dict[str, Any]:
    """标准化公司和指标。"""
    working_state = dict(state)
    company_result = resolve_company_node(working_state)
    working_state.update(company_result)
    metric_result = map_metric_node(working_state)
    result = {**company_result, **metric_result}
    return _with_section(result, "planning", {
        "normalization": {
            "companies": result.get("companies") or [],
            "metrics": result.get("metrics") or [],
            "company_resolution_status": result.get("company_resolution_status"),
            "metric_resolution_status": result.get("metric_resolution_status"),
        }
    })


def _recover_registered_metric_filter_spec(state: dict[str, Any]) -> dict[str, Any] | None:
    """将被 Planner 误拒绝的单指标结构化筛选恢复为受控 Flexible SQL 规格。"""
    query_spec = state.get("query_spec")
    metrics = state.get("metrics")
    if not isinstance(query_spec, dict) or query_spec.get("execution_mode") != "unsupported":
        return None
    if not isinstance(metrics, list) or len(metrics) != 1 or not isinstance(metrics[0], dict):
        return None

    question = str(state.get("user_question") or "")
    metric_name = metrics[0].get("metric_name")
    report_year = state.get("report_year")
    if not isinstance(metric_name, str) or not metric_name or not isinstance(report_year, int):
        return None

    threshold_match = re.search(r"(低于|小于|不超过|高于|大于|超过)\s*(\d+(?:\.\d+)?)\s*%?", question)
    order_match = re.search(r"(从低到高|升序|从高到低|降序)", question)
    limit_match = re.search(r"(?:取|前)\s*(\d+)\s*(?:家|个|只|条)?", question)
    if not threshold_match or not order_match or not limit_match:
        return None

    operator = {
        "低于": "<", "小于": "<", "不超过": "<=",
        "高于": ">", "大于": ">", "超过": ">",
    }[threshold_match.group(1)]
    threshold_value = float(threshold_match.group(2))
    if threshold_value.is_integer():
        threshold_value = int(threshold_value)
    direction = "asc" if order_match.group(1) in {"从低到高", "升序"} else "desc"

    return {
        "execution_mode": "flexible_sql",
        "operation": "metric_threshold_filter",
        "entities": [],
        "metrics": [metric_name],
        "time_scope": {"year": report_year, "period": state.get("report_period") or "FY"},
        "filters": [{"metric": metric_name, "operator": operator, "value": threshold_value}],
        "sort": [{"metric": metric_name, "direction": direction}],
        "limit": int(limit_match.group(1)),
        "group_by": [],
        "set_operations": [],
        "derived_expressions": [],
        "answer_mode": "analytical",
        "unsupported_reason": None,
        "clarification_question": None,
    }


def _correct_derived_point_query_spec(state: dict[str, Any], query_spec: dict[str, Any]) -> dict[str, Any] | None:
    """指标标准化后，避免派生指标误入需要直接字段的普通点查构建器。"""
    metrics = state.get("metrics")
    if (
        query_spec.get("execution_mode") != "deterministic"
        or query_spec.get("operation") != "point_query"
        or not isinstance(metrics, list)
        or not metrics
        or any(not isinstance(metric, dict) or metric.get("metric_type") != "derived" for metric in metrics)
    ):
        return None
    corrected_spec = dict(query_spec)
    corrected_spec["operation"] = "derived_metric_query"
    return corrected_spec


def _correct_derived_yoy_query_spec(state: dict[str, Any], query_spec: dict[str, Any]) -> dict[str, Any] | None:
    """将已注册派生指标的同比问题统一恢复为确定性同比查询。"""
    metrics = state.get("metrics")
    companies = state.get("companies")
    question = str(state.get("user_question") or "")
    if (
        "同比" not in question
        or isinstance(companies, list) and len(companies) >= 2
        or not isinstance(metrics, list)
        or not metrics
        or any(not isinstance(metric, dict) or metric.get("metric_type") != "derived" for metric in metrics)
    ):
        return None
    corrected_spec = dict(query_spec)
    corrected_spec.update({
        "execution_mode": "deterministic",
        "operation": "yoy_query",
        "answer_mode": "fixed",
        "unsupported_reason": None,
        "clarification_question": None,
    })
    return corrected_spec


def _correct_company_compare_query_spec(state: dict[str, Any], query_spec: dict[str, Any]) -> dict[str, Any] | None:
    """将已解析多家公司之间的高低比较统一恢复为确定性对比查询。"""
    companies = state.get("companies")
    question = str(state.get("user_question") or "")
    if (
        not isinstance(companies, list)
        or len(companies) < 2
        or not re.search(r"(?:谁|哪家|哪个).{0,24}(?:更高|更低|较高|较低)", question)
    ):
        return None
    operation = "company_compare_yoy_query" if "同比" in question else "company_compare_query"
    if query_spec.get("execution_mode") == "deterministic" and query_spec.get("operation") == operation:
        return None
    corrected_spec = dict(query_spec)
    corrected_spec.update({
        "execution_mode": "deterministic",
        "operation": operation,
        "answer_mode": "fixed",
        "unsupported_reason": None,
        "clarification_question": None,
    })
    return corrected_spec


def _recent_n_years_from_question(question: str) -> int | None:
    """识别“近 N 年”的明确时间范围，不为未说明年份的查询臆造范围。"""
    match = re.search(r"近\s*([1-9]\d*|[一二三四五六七八九十])\s*年", question)
    if not match:
        return None
    value = match.group(1)
    if value.isdigit():
        return int(value)
    return {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}[value]


def _correct_company_compare_trend_query_spec(state: dict[str, Any], query_spec: dict[str, Any]) -> dict[str, Any] | None:
    """将多公司“近 N 年增长/变化”统一恢复为确定性趋势对比查询。"""
    companies = state.get("companies")
    question = str(state.get("user_question") or "")
    recent_n_years = _recent_n_years_from_question(question)
    if (
        not isinstance(companies, list)
        or len(companies) < 2
        or recent_n_years is None
        or not re.search(r"增长|下降|趋势|变化", question)
    ):
        return None
    if query_spec.get("execution_mode") == "deterministic" and query_spec.get("operation") == "company_compare_trend_query":
        return None
    corrected_spec = dict(query_spec)
    corrected_spec.update({
        "execution_mode": "deterministic",
        "operation": "company_compare_trend_query",
        "answer_mode": "fixed",
        "unsupported_reason": None,
        "clarification_question": None,
    })
    return corrected_spec


def _correct_rank_position_query_spec(state: dict[str, Any], query_spec: dict[str, Any]) -> dict[str, Any] | None:
    """将指定公司的“排第几/第几名”统一恢复为确定性排名位置查询。"""
    companies = state.get("companies")
    metrics = state.get("metrics")
    question = str(state.get("user_question") or "")
    if (
        not isinstance(companies, list)
        or len(companies) != 1
        or not isinstance(metrics, list)
        or len(metrics) != 1
        or not re.search(r"排第几|排名第几|第几名", question)
    ):
        return None
    if query_spec.get("execution_mode") == "deterministic" and query_spec.get("operation") == "rank_position_query":
        return None
    corrected_spec = dict(query_spec)
    corrected_spec.update({
        "execution_mode": "deterministic",
        "operation": "rank_position_query",
        "answer_mode": "fixed",
        "unsupported_reason": None,
        "clarification_question": None,
    })
    return corrected_spec


def query_spec_validator_node(state: dict[str, Any]) -> dict[str, Any]:
    """校验 QuerySpec 和标准化槽位。"""
    query_spec = state.get("query_spec") if isinstance(state.get("query_spec"), dict) else {}
    if has_out_of_scope_signal(state):
        message = query_spec.get("unsupported_reason") or "当前问题依赖结构化财报数据库之外的数据或能力。"
        result = {
            "query_spec_validation_status": "unsupported",
            "need_clarification": False,
            "error_type": "UNSUPPORTED_OUT_OF_SCOPE",
            "sql_generation_mode": "unsupported",
            "sql_generation_error_type": "UNSUPPORTED_OUT_OF_SCOPE",
            "sql_generation_error_message": message,
        }
        result = _with_section(result, "planning", {"validation_status": "unsupported"})
        return _with_error(result, "planning", "UNSUPPORTED_OUT_OF_SCOPE", message)
    recovered_spec = _recover_registered_metric_filter_spec(state)
    if recovered_spec is not None:
        query_spec = recovered_spec
        state = {**state, "query_spec": query_spec}
    company_compare_spec = _correct_company_compare_query_spec(state, query_spec)
    if company_compare_spec is not None:
        query_spec = company_compare_spec
        state = {**state, "query_spec": query_spec, "intent_type": query_spec["operation"]}
    company_compare_trend_spec = _correct_company_compare_trend_query_spec(state, query_spec)
    if company_compare_trend_spec is not None:
        recent_n_years = _recent_n_years_from_question(str(state.get("user_question") or ""))
        compare_operator = "faster_growth" if re.search(r"增长更快|增速", str(state.get("user_question") or "")) else "larger_change"
        query_spec = company_compare_trend_spec
        state = {
            **state,
            "query_spec": query_spec,
            "intent_type": "company_compare_trend_query",
            "time_mode": "recent_n",
            "recent_n_years": recent_n_years,
            "report_year": None,
            "start_year": None,
            "end_year": None,
            "report_years": [],
            "compare_spec": {"operator": compare_operator, "target": None, "subject_company": None, "reference_company": None},
        }
    rank_position_spec = _correct_rank_position_query_spec(state, query_spec)
    if rank_position_spec is not None:
        query_spec = rank_position_spec
        state = {
            **state,
            "query_spec": query_spec,
            "intent_type": "rank_position_query",
            "rank_direction": "asc" if re.search(r"从低到高|最低", str(state.get("user_question") or "")) else "desc",
        }
    derived_yoy_spec = _correct_derived_yoy_query_spec(state, query_spec)
    if derived_yoy_spec is not None:
        query_spec = derived_yoy_spec
        state = {**state, "query_spec": query_spec, "intent_type": "yoy_query"}
    derived_point_spec = _correct_derived_point_query_spec(state, query_spec)
    if derived_point_spec is not None:
        query_spec = derived_point_spec
        state = {**state, "query_spec": query_spec, "intent_type": "derived_metric_query"}
    if any((recovered_spec, company_compare_spec, company_compare_trend_spec, rank_position_spec, derived_yoy_spec, derived_point_spec)):
        state = {
            **state,
            "need_clarification": False,
            "clarification_question": None,
            "error_type": None,
            "sql_generation_error_type": None,
            "sql_generation_error_message": None,
        }
    if query_spec.get("clarification_question"):
        result = {
            "query_spec_validation_status": "need_clarification",
            "need_clarification": True,
            "clarification_question": query_spec.get("clarification_question"),
            "error_type": "clarification_required",
        }
        result = _with_section(result, "planning", {"validation_status": "need_clarification"})
        return _with_error(result, "planning", "MISSING_REQUIRED_SLOTS", query_spec.get("clarification_question"))
    slot_result = check_slots_node(state)
    status = "need_clarification" if slot_result.get("need_clarification") else "valid"
    result = {"query_spec_validation_status": status, **slot_result}
    if recovered_spec is not None or company_compare_spec is not None or company_compare_trend_spec is not None or rank_position_spec is not None or derived_yoy_spec is not None or derived_point_spec is not None:
        result["query_spec"] = query_spec
    if company_compare_spec is not None:
        result["intent_type"] = query_spec["operation"]
    elif company_compare_trend_spec is not None:
        result["intent_type"] = "company_compare_trend_query"
    elif rank_position_spec is not None:
        result["intent_type"] = "rank_position_query"
        result["rank_direction"] = state["rank_direction"]
    elif derived_yoy_spec is not None:
        result["intent_type"] = "yoy_query"
    elif derived_point_spec is not None:
        result["intent_type"] = "derived_metric_query"
    result = _with_section(result, "planning", {
        "validation_status": status,
        **({"query_spec": query_spec, "planner_recovery": "registered_metric_filter"} if recovered_spec else {}),
        **({"query_spec": query_spec, "planner_correction": "company_compare_query"} if company_compare_spec else {}),
        **({"query_spec": query_spec, "planner_correction": "company_compare_trend_query"} if company_compare_trend_spec else {}),
        **({"query_spec": query_spec, "planner_correction": "rank_position_query"} if rank_position_spec else {}),
        **({"query_spec": query_spec, "planner_correction": "derived_metric_yoy_query"} if derived_yoy_spec else {}),
        **({"query_spec": query_spec, "planner_correction": "derived_metric_point_query"} if derived_point_spec else {}),
    })
    if status == "need_clarification":
        return _with_error(result, "planning", "MISSING_REQUIRED_SLOTS", slot_result.get("clarification_question"))
    return result


def capability_boundary_answer_node(state: dict[str, Any]) -> dict[str, Any]:
    message = (
        state.get("sql_generation_error_message")
        or state.get("clarification_question")
        or "当前问题超出结构化数据库可回答范围。"
    )
    return {
        "final_answer": message,
        "business_success": False,
        "error_type": state.get("error_type") or "UNSUPPORTED_OUT_OF_SCOPE",
    }


def capability_router_node(state: dict[str, Any]) -> dict[str, Any]:
    decision = route_query_capability(state)
    result = _with_section({}, "planning", {"capability_decision": decision})
    return _with_section(result, "execution", {"execution_mode": decision.get("execution_mode")})


def deterministic_sql_builder_node(state: dict[str, Any]) -> dict[str, Any]:
    route_name = route_by_intent(state)
    builder = TEMPLATE_SQL_NODES.get(route_name)
    if builder is None:
        result = {
            "sql_generation_mode": "unsupported",
            "sql_generation_error_type": "TEMPLATE_NOT_AVAILABLE",
            "sql_generation_error_message": f"未找到确定性 SQL 构建器：{route_name}",
            "error_type": "TEMPLATE_NOT_AVAILABLE",
        }
        return _with_error(result, "sql_generation", "TEMPLATE_NOT_AVAILABLE", result["sql_generation_error_message"])
    result = builder(state)
    result.setdefault("sql_generation_mode", "template")
    result.setdefault("deterministic_sql_builder", route_name)
    execution = {
        "execution_mode": "deterministic",
        "deterministic_plan": state.get("query_plan"),
        "generated_sql": result.get("sql"),
        "sql_attempts": [{"attempt": 1, "sql": result.get("sql"), "stage": "sql_generation", "success": bool(result.get("sql"))}],
    }
    return _with_section({**result, **_execution_mirror(execution)}, "execution", execution)


def flexible_sql_spec_builder_node(state: dict[str, Any]) -> dict[str, Any]:
    query_spec = state.get("query_spec") if isinstance(state.get("query_spec"), dict) else {}
    planning = state.get("planning") if isinstance(state.get("planning"), dict) else {}
    normalization = planning.get("normalization") if isinstance(planning.get("normalization"), dict) else {}
    resolved_metrics = [item for item in normalization.get("metrics") or [] if isinstance(item, dict)]
    resolved_entities = [item for item in normalization.get("companies") or [] if isinstance(item, dict)]
    # 派生指标的实际来源由公式合同展开；此处保留注册表供合同编译时验证。
    schema_registry = {table: sorted(columns) for table, columns in ALLOWED_TABLE_COLUMNS.items()}
    try:
        flexible_sql_spec = compile_flexible_sql_spec(
            query_spec, resolved_entities, resolved_metrics, schema_registry
        )
    except ValueError as exc:
        error_type = "UNSUPPORTED_FLEXIBLE_SQL" if str(exc).startswith("UNSUPPORTED_FLEXIBLE_SQL:") else "FLEXIBLE_SQL_SPEC_COMPILATION_FAILED"
        return _with_error(
            {"flexible_sql_spec_status": "failed"},
            "sql_generation",
            error_type,
            str(exc),
        )
    execution = {
        "execution_mode": "flexible_sql",
        "flexible_sql_spec": flexible_sql_spec,
    }
    return _with_section(_execution_mirror(execution), "execution", execution)


def llm_sql_generator_node(state: dict[str, Any]) -> dict[str, Any]:
    execution_state = _execution(state)
    result = generate_llm_sql_node(state)
    flexible_sql_spec = execution_state.get("flexible_sql_spec")
    execution = {
        "execution_mode": "flexible_sql",
        "flexible_sql_spec": flexible_sql_spec,
        "generated_sql": result.get("sql"),
        "sql_attempts": [{
            "attempt": 1, "sql": result.get("llm_sql_candidate") or result.get("sql"),
            "stage": "sql_generation", "success": result.get("sql_generation_status") == "success",
            "error_type": result.get("sql_generation_error_type"),
            "error_message": result.get("sql_generation_error_message"),
        }],
    }
    result = _with_section({
        **result,
        "sql": execution["generated_sql"],
        **_execution_mirror(execution),
    }, "execution", execution)
    if result.get("sql_generation_status") != "success":
        stage = result.get("failed_stage") if result.get("failed_stage") in {"sql_guard", "dry_run"} else "sql_generation"
        return _with_error(result, stage, result.get("sql_generation_error_type") or "SQL_GENERATION_FAILED", result.get("sql_generation_error_message"), retryable=True)
    return result


def sql_guard_node(state: dict[str, Any]) -> dict[str, Any]:
    """SQL guard 阶段标记。

    确定性链路的实际 guard 仍在 execute_sql 兼容节点内执行；
    flexible_sql 链路的 guard 已由 llm_sql_generator 产出校验结果。
    """
    execution = _execution(state)
    sql = execution.get("generated_sql") or ""
    if _capability_mode(state) == "flexible_sql":
        request = state.get("llm_sql_request") if isinstance(state.get("llm_sql_request"), dict) else {}
        validation = validate_llm_sql_static(
            sql,
            allowed_tables=request.get("allowed_tables"),
            allowed_columns=request.get("allowed_columns"),
            max_rows=request.get("max_rows") or 50,
        )
        result = {
            "sql_guard_status": "passed" if validation.get("is_valid") or validation.get("guard_passed") else "rejected",
            "sql_guard_repairable": bool(validation.get("repairable")),
        }
        guard_execution = {"guard_result": validation}
        result = _with_section({**result, **_execution_mirror(guard_execution)}, "execution", guard_execution)
        if result["sql_guard_status"] == "rejected":
            return _with_error(result, "sql_guard", validation.get("error_type") or "SQL_GUARD_REJECTED", validation.get("error_message"), retryable=result["sql_guard_repairable"])
        return result
    multi_sql_entries = _deterministic_sql_entries(state)
    if multi_sql_entries:
        reviews = [review_sql(item["sql"]) for item in multi_sql_entries]
        is_safe = all(review.get("is_safe") for review in reviews)
        validation = {
            "is_safe": is_safe,
            "reason": None if is_safe else next(
                (review.get("reason") for review in reviews if not review.get("is_safe")),
                "确定性多 SQL 审查失败。",
            ),
            "reviews": reviews,
        }
    else:
        validation = review_sql(sql)
    guard_execution = {"guard_result": validation}
    result = _with_section({"sql_guard_status": "passed" if validation.get("is_safe") else "rejected", **_execution_mirror(guard_execution)}, "execution", guard_execution)
    if not validation.get("is_safe"):
        return _with_error(result, "sql_guard", "SQL_GUARD_REJECTED", validation.get("reason"))
    return result


def semantic_validate_node(state: dict[str, Any]) -> dict[str, Any]:
    """只验证 Flexible SQL 是否符合已编译 QuerySpec 约束。"""
    execution = _execution(state)
    request = state.get("llm_sql_request") if isinstance(state.get("llm_sql_request"), dict) else {}
    semantic = validate_llm_sql_semantics(
        execution.get("generated_sql") or "", request=request, metrics=state.get("metrics") or []
    )
    result = {"sql_semantic_validation": semantic, "semantic_validation_status": "passed" if semantic.get("is_valid") else "rejected"}
    if not semantic.get("is_valid"):
        return _with_error(result, "semantic_validate", semantic.get("error_type") or "SQL_SEMANTIC_INVALID", semantic.get("error_message"), retryable=True)
    return result


def dry_run_node(state: dict[str, Any]) -> dict[str, Any]:
    execution = _execution(state)
    if _capability_mode(state) == "flexible_sql":
        dry_run_result = dry_run_sql(execution.get("generated_sql") or "", limit=5)
        result = {
            "dry_run_status": "passed" if dry_run_result.get("success") else "failed",
            "dry_run_repairable": False,
        }
        dry_run_execution = {"dry_run_result": dry_run_result}
        result = _with_section({**result, **_execution_mirror(dry_run_execution)}, "execution", dry_run_execution)
        if result["dry_run_status"] == "failed":
            return _with_error(result, "dry_run", "DRY_RUN_FAILED", dry_run_result.get("error"), retryable=True)
        return result
    return {"dry_run_status": "not_required_for_template"}


def execute_sql_node(state: dict[str, Any]) -> dict[str, Any]:
    execution_state = _execution(state)
    if _capability_mode(state) == "deterministic" and _deterministic_sql_entries(state):
        # 对比、同比等模板会生成多条按表分组的 SQL，必须沿用兼容执行器，
        # 不能丢失为 execution.generated_sql 后退化成占位查询。
        result = review_and_execute_sql_node(_legacy_execution_view(state), execution=execution_state)
    else:
        result = execute_partitioned_sql_node(execution_state)
    query_result = result.get("query_result")
    execution = {"execution_result": query_result}
    result = _with_section({**result, "query_result": query_result, **_execution_mirror(execution)}, "execution", execution)
    if isinstance(query_result, dict) and query_result.get("success") is False:
        return _with_error(result, "execution", "SQL_EXECUTION_FAILED", query_result.get("error"), retryable=True)
    return result


def deterministic_result_analyzer_node(state: dict[str, Any]) -> dict[str, Any]:
    analysis_nodes: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
    from agent.nodes.analyze_nodes.compare_analysis import analyze_compare_node, analyze_derived_compare_node
    from agent.nodes.analyze_nodes.compare_trend_analysis import analyze_compare_trend_node, analyze_derived_compare_trend_node
    from agent.nodes.analyze_nodes.compare_yoy_analysis import analyze_compare_yoy_node, analyze_derived_compare_yoy_node
    from agent.nodes.analyze_nodes.derived_analysis import analyze_derived_metric_node
    from agent.nodes.analyze_nodes.rank_position_analysis import analyze_rank_position_node
    from agent.nodes.analyze_nodes.ranking_analysis import analyze_ranking_node
    from agent.nodes.analyze_nodes.trend_analysis import analyze_derived_trend_node, analyze_trend_node
    from agent.nodes.analyze_nodes.trend_ranking_analysis import analyze_trend_ranking_node
    from agent.nodes.analyze_nodes.yoy_analysis import analyze_derived_yoy_node, analyze_yoy_node
    from agent.nodes.analyze_nodes.yoy_ranking_analysis import analyze_yoy_ranking_node

    analysis_nodes.update(
        {
            "analyze_yoy": analyze_yoy_node,
            "analyze_derived_yoy": analyze_derived_yoy_node,
            "analyze_derived_metric": analyze_derived_metric_node,
            "analyze_derived_trend": analyze_derived_trend_node,
            "analyze_trend": analyze_trend_node,
            "analyze_compare": analyze_compare_node,
            "analyze_derived_compare": analyze_derived_compare_node,
            "analyze_compare_trend": analyze_compare_trend_node,
            "analyze_derived_compare_trend": analyze_derived_compare_trend_node,
            "analyze_compare_yoy": analyze_compare_yoy_node,
            "analyze_derived_compare_yoy": analyze_derived_compare_yoy_node,
            "analyze_ranking": analyze_ranking_node,
            "analyze_yoy_ranking": analyze_yoy_ranking_node,
            "analyze_trend_ranking": analyze_trend_ranking_node,
            "analyze_rank_position": analyze_rank_position_node,
        }
    )
    node_name = route_analysis(state)
    analyzer = analysis_nodes.get(node_name, analyze_trend_node)
    result = analyzer(state)
    return _with_section(result, "result", {"analysis_result": result.get("analysis_result")})


def fixed_answer_renderer_node(state: dict[str, Any]) -> dict[str, Any]:
    result = generate_answer_node(state)
    return _with_section(result, "answer", {
        "answer_mode": result.get("answer_mode") or "template",
        "final_answer": result.get("final_answer"),
        "business_success": result.get("business_success"),
    })


def llm_insight_node_adapter(state: dict[str, Any]) -> dict[str, Any]:
    """在确定性事实答案后追加受约束的 LLM 补充洞察。"""
    from agent.nodes.llm_insight import llm_insight_node

    insight_result = llm_insight_node(state)
    final_answer = state.get("final_answer")
    if insight_result.get("llm_analysis_success") is True and isinstance(final_answer, str):
        appended = append_llm_insight_section(
            {"final_answer": final_answer},
            {**state, **insight_result},
        )
        insight_result["final_answer"] = appended["final_answer"]
    return _with_section(insight_result, "answer", {
        "final_answer": insight_result.get("final_answer", final_answer),
        "llm_analysis": insight_result.get("llm_analysis"),
        "llm_analysis_success": insight_result.get("llm_analysis_success"),
    })


def result_contract_builder_node(state: dict[str, Any]) -> dict[str, Any]:
    execution = _execution(state)
    result_state = state.get("result") if isinstance(state.get("result"), dict) else {}
    contract = build_result_contract(state, execution=execution, result=result_state)
    answer_context = build_answer_context_from_contract(state, contract)
    return _with_section({"answer_context": answer_context, "result_contract": contract}, "result", {"result_contract": contract})


def deterministic_table_node(state: dict[str, Any]) -> dict[str, Any]:
    result_state = state.get("result") if isinstance(state.get("result"), dict) else {}
    contract = result_state.get("result_contract") if isinstance(result_state.get("result_contract"), dict) else build_result_contract(state, execution=_execution(state), result=result_state)
    table = render_deterministic_table(contract)
    return _with_section({"deterministic_table": table, "table_source": "result_contract"}, "result", {"deterministic_table": table})


def llm_narrative_node(state: dict[str, Any]) -> dict[str, Any]:
    failure = _execution_failed(state)
    result_state = state.get("result") if isinstance(state.get("result"), dict) else {}
    result_contract = result_state.get("result_contract") if isinstance(result_state.get("result_contract"), dict) else build_result_contract(state, execution=_execution(state), result=result_state)
    answer_context = build_answer_context_from_contract(state, result_contract)
    table = result_state.get("deterministic_table") if isinstance(result_state.get("deterministic_table"), dict) else render_deterministic_table(result_contract)
    if failure:
        narrative = _fallback_response(answer_context, table)
        narrative["summary"] = f"查询未成功完成：{failure}"
        result = {"llm_narrative": narrative, "llm_answer_validation": {"is_valid": True}}
        return _with_section(result, "answer", {"narrative": narrative})
    try:
        narrative = invoke_json_prompt(_build_prompt(answer_context, result_contract), profile="narrative")
    except Exception as exc:
        narrative = _fallback_response(answer_context, table)
        narrative["warnings"] = [f"LLM 摘要生成失败：{exc}"]
        timeout_code = getattr(exc, "error_code", None)
        if timeout_code == "NARRATIVE_TIMEOUT":
            result = _with_error(
                {"llm_narrative": narrative, "llm_answer_failed": True},
                "narrative",
                timeout_code,
                str(exc),
            )
            return _with_section(result, "answer", {"narrative": narrative})
    if not isinstance(narrative, dict):
        narrative = _fallback_response(answer_context, table)
    validation = validate_llm_answer_narrative(narrative, answer_context)
    if not validation.get("is_valid"):
        fallback = _fallback_response(answer_context, table)
        result = {
            "llm_narrative": fallback,
            "llm_answer_raw_response": narrative,
            "llm_answer_validation": validation,
            "llm_answer_failed": True,
        }
        return _with_section(result, "answer", {"narrative": fallback})
    result = {
        "llm_narrative": narrative,
        "llm_answer_raw_response": narrative,
        "llm_answer_validation": validation,
        "llm_answer_failed": False,
    }
    return _with_section(result, "answer", {"narrative": narrative})


def answer_assembler_node(state: dict[str, Any]) -> dict[str, Any]:
    result_state = state.get("result") if isinstance(state.get("result"), dict) else {}
    answer_state = state.get("answer") if isinstance(state.get("answer"), dict) else {}
    contract = result_state.get("result_contract") if isinstance(result_state.get("result_contract"), dict) else build_result_contract(state, execution=_execution(state), result=result_state)
    table = result_state.get("deterministic_table") if isinstance(result_state.get("deterministic_table"), dict) else render_deterministic_table(contract)
    narrative = answer_state.get("narrative") if isinstance(answer_state.get("narrative"), dict) else _fallback_response(build_answer_context_from_contract(state, contract), table)
    final_answer = assemble_contract_answer(result_contract=contract, deterministic_table=table, narrative=narrative)
    result = {
        "answer_mode": "llm_answer",
        "final_answer": final_answer,
        "llm_answer_parsed": {**narrative, "table": table},
        "business_success": contract.get("row_count", 0) > 0,
    }
    return _with_section(result, "answer", {"answer_mode": "llm_answer", "final_answer": final_answer, "business_success": result["business_success"]})


def answer_validator_node(state: dict[str, Any]) -> dict[str, Any]:
    result_state = state.get("result") if isinstance(state.get("result"), dict) else {}
    answer_state = state.get("answer") if isinstance(state.get("answer"), dict) else {}
    contract = result_state.get("result_contract") if isinstance(result_state.get("result_contract"), dict) else {}
    table = result_state.get("deterministic_table") if isinstance(result_state.get("deterministic_table"), dict) else {}
    validation = validate_assembled_answer_sections(
        result_contract=contract,
        deterministic_table=table,
        final_answer=answer_state.get("final_answer") or "",
    )
    result = {
        "answer_validation": validation,
        "final_answer_validation": validation,
        "answer_validation_passed": validation.get("is_valid") is True,
        "answer_error_type": validation.get("error_type"),
        "error_type": validation.get("error_type"),
    }
    result = _with_section(result, "answer", {"validation": validation})
    if not validation.get("is_valid"):
        return _with_error(result, "answer_validation", validation.get("error_type") or "ANSWER_VALIDATION_FAILED", validation.get("error_message"))
    return result


def controlled_failure_node(state: dict[str, Any]) -> dict[str, Any]:
    message = (
        state.get("sql_generation_error_message")
        or (state.get("dry_run_result") or {}).get("error")
        or "受控 SQL 生成或校验失败。"
    )
    return {"final_answer": message, "business_success": False, "error_type": state.get("sql_generation_error_type") or "controlled_failure"}


def llm_sql_repair_node_adapter(state: dict[str, Any]) -> dict[str, Any]:
    """当前修复已在 llm_sql_generator 内部完成；保留目标图节点。"""
    execution = _execution(state)
    request = state.get("llm_sql_request") if isinstance(state.get("llm_sql_request"), dict) else {}
    try:
        repair = llm_sql_repair_node({
            "flexible_sql_spec": execution.get("flexible_sql_spec"),
            "semantic_sql_contract": (execution.get("flexible_sql_spec") or {}).get("semantic_contract"),
            "allowed_tables": request.get("allowed_tables"),
            "allowed_columns": request.get("allowed_columns"),
            "metric_bindings": request.get("metric_bindings"),
            "candidate_sql": execution.get("generated_sql"),
            "validation_error": state.get("error") or {},
            "contract_violations": state.get("sql_semantic_validation") or {},
            "repair_hint": "必须严格满足 FlexibleSQLSpec 的筛选、阶段、排序、同比尺度和财报期间合同。",
            "max_rows": request.get("max_rows"),
        })
    except Exception as exc:
        return _with_error(
            {"sql_repair_attempted": True, "sql_repair_success": False},
            "sql_repair",
            getattr(exc, "error_code", "LLM_SQL_REPAIR_FAILED"),
            str(exc),
        )
    sql = repair.get("sql")
    if not isinstance(sql, str) or not sql.strip():
        return _with_error({"sql_repair_attempted": True, "sql_repair_success": False}, "sql_guard", "LLM_SQL_REPAIR_FAILED", "SQL 修复未返回有效 SQL。")
    repaired_execution = {"generated_sql": sql, "sql_attempts": [*(execution.get("sql_attempts") or []), {"attempt": 2, "sql": sql, "stage": "sql_guard", "success": True}]}
    return _with_section({
        "sql": sql,
        "sql_repair_attempted": True,
        "sql_repair_success": True,
        "error": {"error_stage": None, "error_type": None, "error_message": None, "retryable": False, "details": {}},
        **_execution_mirror(repaired_execution),
    }, "execution", repaired_execution)


__all__ = [
    "answer_assembler_node",
    "answer_validator_node",
    "capability_boundary_answer_node",
    "capability_router_node",
    "controlled_failure_node",
    "deterministic_result_analyzer_node",
    "deterministic_sql_builder_node",
    "deterministic_table_node",
    "dry_run_node",
    "entity_normalization_node",
    "execute_sql_node",
    "fixed_answer_renderer_node",
    "llm_insight_node_adapter",
    "flexible_sql_spec_builder_node",
    "irrelevant_answer_node",
    "llm_narrative_node",
    "llm_sql_generator_node",
    "llm_sql_repair_node_adapter",
    "merge_context_node",
    "query_planner_node",
    "query_spec_validator_node",
    "result_contract_builder_node",
    "semantic_validate_node",
    "sql_guard_node",
]
