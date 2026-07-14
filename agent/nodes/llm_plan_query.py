import json
import os
import re
from time import perf_counter
from pathlib import Path
from typing import Any

from agent.schemas.composite_query_plan import validate_composite_query_plan
from agent.schemas.query_spec import (
    QuerySpec,
    normalize_query_spec,
    query_spec_company_mentions,
    query_spec_metric_mentions,
    query_spec_report_period,
    query_spec_report_year,
)
from agent.schemas.query_plan import validate_plan
from agent.runtime.task_graph import build_task_dag
from agent.nodes.composite_task_planner_node import plan_composite_tasks_node, repair_composite_plan_from_slots
from agent.nodes.intent_classifier_node import normalize_intent_classification
from agent.nodes.slot_extraction_node import extract_slots_node
from agent.services.llm_json_service import (
    build_llm as _shared_build_llm,
    extract_json as _shared_extract_json,
    invoke_json_prompt,
)
from agent.utils.stage_trace import record_llm_event


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "query_spec_planner.md"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _load_dotenv_if_available() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    try:
        from dotenv import load_dotenv
    except ImportError:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped_line = line.strip()
            if not stripped_line or stripped_line.startswith("#") or "=" not in stripped_line:
                continue
            key, value = stripped_line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        return

    load_dotenv(env_path)


def _get_required_env(*names: str) -> str:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise RuntimeError(f"未配置环境变量：{' 或 '.join(names)}")


def _get_optional_env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _extract_json(text: str) -> dict:
    """从 LLM 文本响应中提取 JSON 对象。"""
    return _shared_extract_json(text)
    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 代码块
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试提取首个 { ... } 块
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 响应中提取 JSON：{text[:200]}")


def _build_llm():
    return _shared_build_llm("planner")
    _load_dotenv_if_available()

    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise RuntimeError("未安装 langchain_openai，无法调用查询规划 LLM。") from exc

    model = (
        _get_optional_env("AGENT_LLM_MODEL", "OPENAI_MODEL", "DEEPSEEK_MODEL")
        or DEFAULT_DEEPSEEK_MODEL
    )
    api_key = _get_required_env(
        "AGENT_LLM_API_KEY",
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
    )
    base_url = (
        _get_optional_env("AGENT_LLM_BASE_URL", "OPENAI_BASE_URL", "DEEPSEEK_BASE_URL")
        or DEFAULT_DEEPSEEK_BASE_URL
    )

    kwargs: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "api_key": api_key,
    }
    if base_url:
        kwargs["base_url"] = base_url

    return ChatOpenAI(**kwargs)


def _state_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    time_range = plan["time_range"]
    return {
        "query_type": "single",
        "composite_query_plan": None,
        "query_plan": plan,
        "intent_type": plan["intent_type"],
        "company_mentions": plan["company_mentions"],
        "metric_mentions": plan["metric_mentions"],
        "time_range": time_range,
        "report_period": None
        if plan["report_period"] == "unspecified"
        else plan["report_period"],
        "time_mode": time_range["mode"],
        "report_year": time_range.get("report_year"),
        "recent_n_years": time_range.get("recent_n_years"),
        "start_year": time_range.get("start_year"),
        "end_year": time_range.get("end_year"),
        "report_years": time_range.get("report_years") or [],
        "compare_spec": plan.get("compare_spec"),
        "rank_direction": plan.get("rank_direction"),
        "limit": plan.get("limit"),
        "change_metric": plan.get("change_metric"),
        "need_clarification": plan.get("need_clarification", False),
        "clarification_question": plan.get("clarification_reason"),
    }


def _state_from_composite_plan(plan: dict[str, Any]) -> dict[str, Any]:
    task_dag = build_task_dag(plan.get("tasks", []))
    clarification_required = (
        plan.get("clarification_required", False)
        or task_dag.get("clarification_required", False)
    )
    clarification_question = (
        plan.get("clarification_question")
        or task_dag.get("clarification_question")
    )
    return {
        "query_type": "composite",
        "composite_plan": plan,
        "query_plan": None,
        "composite_query_plan": plan,
        "task_dag": task_dag,
        "task_execution_order": task_dag.get("task_ids", []),
        "need_clarification": clarification_required,
        "clarification_question": clarification_question,
        "error_type": "clarification_required"
        if clarification_required
        else None,
        "empty_fields": [],
    }


def _query_spec_time_range(spec: QuerySpec) -> dict[str, Any]:
    report_year = query_spec_report_year(spec)
    time_scope = spec.get("time_scope") if isinstance(spec.get("time_scope"), dict) else {}
    start_year = time_scope.get("start_year")
    end_year = time_scope.get("end_year")
    if isinstance(start_year, int) and isinstance(end_year, int):
        start_year, end_year = min(start_year, end_year), max(start_year, end_year)
        return {
            "mode": "explicit_range",
            "report_year": None,
            "recent_n_years": None,
            "start_year": start_year,
            "end_year": end_year,
            "report_years": list(range(start_year, end_year + 1)),
        }
    if report_year is None:
        return {
            "mode": "unspecified",
            "report_year": None,
            "recent_n_years": None,
            "start_year": None,
            "end_year": None,
            "report_years": [],
        }
    return {
        "mode": "single_year",
        "report_year": report_year,
        "recent_n_years": None,
        "start_year": None,
        "end_year": None,
        "report_years": [report_year],
    }


def _requirement_type_from_operation(operation: str) -> str:
    mapping = {
        "set_intersection_ranking": "set_intersection",
        "multi_metric_yoy_filter": "multi_metric_yoy_filter",
        "yoy_direction_filter_sort": "yoy_direction_filter_sort",
        "derived_metric_ranking": "derived_metric_ranking",
        "derived_metric_filter": "derived_metric_filter",
        "cross_statement_filter": "cross_statement_filter",
        "topn_then_filter": "topn_then_filter",
        "metric_threshold_screen": "metric_threshold_screen",
        "scoped_ranking": "scoped_ranking",
        "compare_to_group_average": "compare_to_group_average",
    }
    return mapping.get(operation, "general_structured_query")


def _query_spec_to_llm_sql_requirement(spec: QuerySpec) -> dict[str, Any]:
    metric_mentions = query_spec_metric_mentions(spec)
    company_mentions = query_spec_company_mentions(spec)
    report_year = query_spec_report_year(spec)
    sort = spec.get("sort") or []
    first_sort = sort[0] if sort else {}
    sort_metric = first_sort.get("metric") if isinstance(first_sort, dict) else None
    sort_direction = first_sort.get("direction") if isinstance(first_sort, dict) else None
    if sort_direction not in {"asc", "desc"}:
        sort_direction = "desc"

    return {
        "can_use_llm_sql": True,
        "reason": "database_answerable_template_gap",
        "requirement_type": _requirement_type_from_operation(spec.get("operation") or "unknown"),
        "template_status": "missing",
        "read_only": True,
        "metric_mentions": metric_mentions,
        "company_mentions": company_mentions,
        "report_year": report_year,
        "report_period": query_spec_report_period(spec),
        "company_universe": {
            "type": "explicit_companies" if company_mentions else "all_companies",
            "companies": company_mentions,
        },
        "base_universe": {
            "type": "intersection" if spec.get("set_operations") else "filter",
            "metric_mention": metric_mentions[0] if metric_mentions else None,
            "calculation": "metric_value",
            "rank_direction": sort_direction,
            "limit": spec.get("limit"),
            "filters": spec.get("filters") or [],
        },
        "metrics": [
            {
                "metric_mention": mention,
                "role": "output_metric",
                "calculation": "metric_value",
            }
            for mention in metric_mentions
        ],
        "filters": spec.get("filters") or [],
        "set_operations": spec.get("set_operations") or [],
        "derived_metrics": spec.get("derived_expressions") or [],
        "grouping": spec.get("group_by") or [],
        "order_by": {
            "metric_mention": sort_metric or (metric_mentions[-1] if metric_mentions else None),
            "calculation": "derived_metric" if sort_metric else "metric_value",
            "direction": sort_direction,
        }
        if sort or metric_mentions
        else None,
        "limit": spec.get("limit"),
        "expected_output": {"grain": "company", "must_include": []},
        "needs": {
            "prediction": False,
            "external_data": False,
            "text_understanding": False,
            "pdf_evidence": False,
        },
        "clarification_question": spec.get("clarification_question"),
        "unsupported_reason": spec.get("unsupported_reason"),
        "query_spec": spec,
    }


def _state_from_query_spec(spec_payload: object) -> dict[str, Any]:
    spec = normalize_query_spec(spec_payload)
    metric_mentions = query_spec_metric_mentions(spec)
    company_mentions = query_spec_company_mentions(spec)
    time_range = _query_spec_time_range(spec)
    base_state = {
        "query_spec": spec,
        "planner_stage": "query_spec",
        "company_mentions": company_mentions,
        "metric_mentions": metric_mentions,
        "time_range": time_range,
        "report_period": query_spec_report_period(spec),
        "report_year": time_range.get("report_year"),
        "report_years": time_range.get("report_years") or [],
        "time_mode": time_range.get("mode"),
        "need_clarification": False,
        "clarification_question": spec.get("clarification_question"),
    }

    if spec.get("clarification_question"):
        return {
            **base_state,
            "query_type": "single",
            "query_plan": None,
            "composite_query_plan": None,
            "intent_type": "unknown",
            "need_clarification": True,
            "error_type": "clarification_required",
            "sql_generation_mode": None,
            "sql_generation_error_type": None,
            "sql_generation_error_message": None,
        }

    if spec["execution_mode"] == "unsupported":
        return {
            **base_state,
            "query_type": "single",
            "query_plan": None,
            "composite_query_plan": None,
            "intent_type": "unknown",
            "need_clarification": bool(spec.get("clarification_question")),
            "error_type": "UNSUPPORTED_OUT_OF_SCOPE",
            "sql_generation_mode": "unsupported",
            "sql_generation_error_type": "UNSUPPORTED_OUT_OF_SCOPE",
            "sql_generation_error_message": spec.get("unsupported_reason"),
        }

    if spec["execution_mode"] == "flexible_sql":
        return {
            **base_state,
            "query_type": "single",
            "query_plan": None,
            "composite_query_plan": None,
            "composite_plan": None,
            "task_dag": None,
            "task_execution_order": [],
            "intent_type": "unknown",
            "company_source": "all_companies" if not company_mentions else "explicit",
            "is_global_structured_query": not company_mentions,
            "answer_mode": "llm_answer",
            "final_answer_mode": spec["answer_mode"],
        }

    deterministic_intent = {
        "point_query": "single_metric_query",
        "multi_metric_query": "multi_metric_query",
        "trend_query": "trend_query",
        "yoy_query": "yoy_query",
        "company_compare_query": "company_compare_query",
        "company_compare_trend_query": "company_compare_trend_query",
        "company_compare_yoy_query": "company_compare_yoy_query",
        "ranking_query": "ranking_query",
        "yoy_ranking_query": "yoy_ranking_query",
        "trend_ranking_query": "trend_ranking_query",
        "rank_position_query": "rank_position_query",
        "derived_metric_query": "derived_metric_query",
        "derived_trend_query": "derived_trend_query",
        "derived_yoy_query": "derived_yoy_query",
    }.get(spec.get("operation") or "", spec.get("operation") or "unknown")
    plan = validate_plan(
        {
            "intent_type": deterministic_intent,
            "company_mentions": company_mentions,
            "metric_mentions": metric_mentions,
            "report_period": query_spec_report_period(spec),
            "time_range": time_range,
            "compare_spec": None,
            "rank_direction": (spec.get("sort") or [{}])[0].get("direction") if spec.get("sort") else None,
            "limit": spec.get("limit"),
            "change_metric": None,
            "need_clarification": False,
            "clarification_reason": None,
        }
    )
    return {**base_state, **_state_from_plan(plan)}


def _normalize_planner_output(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("query_spec"), dict):
        return _state_from_query_spec(payload["query_spec"])
    if payload.get("execution_mode") in {"deterministic", "flexible_sql", "unsupported"}:
        return _state_from_query_spec(payload)

    query_type = payload.get("query_type")
    if query_type in ("composite", "composite_query") or isinstance(payload.get("tasks"), list):
        payload = repair_composite_plan_from_slots(
            payload,
            payload.get("slot_extraction") if isinstance(payload.get("slot_extraction"), dict) else {},
        )
        composite_plan = validate_composite_query_plan(payload)
        if composite_plan["query_type"] != "composite":
            raise ValueError("复合查询必须输出 query_type=composite。")
        return _state_from_composite_plan(composite_plan)

    if query_type in ("single", "single_query") and isinstance(payload.get("query_plan"), dict):
        return _state_from_plan(validate_plan(payload["query_plan"]))

    return _state_from_plan(validate_plan(payload))


def _is_complete_legacy_payload(payload: dict[str, Any]) -> bool:
    """判断 LLM 是否仍返回旧版完整计划，保持兼容。"""
    if isinstance(payload.get("query_spec"), dict):
        return True
    if payload.get("execution_mode") in {"deterministic", "flexible_sql", "unsupported"}:
        return True
    if isinstance(payload.get("tasks"), list):
        return True
    if isinstance(payload.get("query_plan"), dict):
        return True
    return "time_range" in payload and "metric_mentions" in payload


def _compatible_single_plan_from_split(
    intent_classification: dict[str, Any],
    slot_extraction: dict[str, Any],
) -> dict[str, Any]:
    """把拆分节点结果组装为兼容 QueryPlan。"""
    plan = validate_plan(
        {
            "intent_type": intent_classification.get("intent_type") or "unknown",
            "company_mentions": slot_extraction.get("company_mentions") or [],
            "metric_mentions": slot_extraction.get("metric_mentions") or [],
            "report_period": slot_extraction.get("report_period") or "unspecified",
            "time_range": slot_extraction.get("time_range") or {},
            "compare_spec": slot_extraction.get("compare_spec"),
            "rank_direction": slot_extraction.get("rank_direction"),
            "limit": slot_extraction.get("limit"),
            "change_metric": slot_extraction.get("change_metric"),
            "need_clarification": False,
            "clarification_reason": None,
        }
    )
    # 拆分后 planner 不再直接决定澄清，后续 slot validator / clarification_decision 承接。
    plan["need_clarification"] = False
    plan["clarification_reason"] = None
    return plan


def _state_from_split_payload(state: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    intent_classification = normalize_intent_classification(payload)
    split_state = dict(state)
    split_state.update(
        {
            "intent_classification": intent_classification,
            "query_type": intent_classification["query_type"],
            "intent_type": intent_classification["intent_type"],
            "planner_stage": "intent_classification",
        }
    )
    split_state.update(extract_slots_node(split_state))

    if intent_classification.get("needs_composite_task_plan"):
        split_state.update(plan_composite_tasks_node(split_state))
        result = _state_from_composite_plan(split_state["composite_query_plan_candidate"])
    else:
        plan = _compatible_single_plan_from_split(intent_classification, split_state["slot_extraction"])
        result = _state_from_plan(plan)

    result["intent_classification"] = intent_classification
    result["slot_extraction"] = split_state.get("slot_extraction")
    result["planner_stage"] = "split_planner"
    return result


def _correct_explicit_operation(question: str, planner_state: dict[str, Any]) -> dict[str, Any]:
    """修正规划结果中与问题显式同比语义冲突的操作类型。"""
    query_spec = planner_state.get("query_spec")
    if not isinstance(query_spec, dict):
        return planner_state

    operation = query_spec.get("operation")
    corrected_spec = dict(query_spec)
    company_mentions = query_spec_company_mentions(query_spec)
    is_compare_yoy = (
        len(company_mentions) >= 2
        and "同比" in question
        and bool(re.search(r"谁.{0,12}(?:更)?[高低]|对比|比较", question))
    )
    if is_compare_yoy and operation != "company_compare_yoy_query":
        # 这是“多个明确实体 + 同比 + 比较方向”的通用语义规则，
        # 不能因 Planner 漏标 operation 而退化为单公司澄清或灵活 SQL。
        corrected_spec.update({
            "execution_mode": "deterministic",
            "operation": "company_compare_yoy_query",
            "answer_mode": "fixed",
            "clarification_question": None,
            "unsupported_reason": None,
        })
        return _state_from_query_spec(corrected_spec)

    if "同比" in question and operation in {"point_query", "multi_metric_query"}:
        corrected_spec["operation"] = (
            "derived_yoy_query"
            if corrected_spec.get("derived_expressions")
            else "yoy_query"
        )
        return _state_from_query_spec(corrected_spec)

    nested_top_n = re.search(r"在.+前\s*\d+.+中", question)
    set_operations = corrected_spec.get("set_operations")
    if nested_top_n and isinstance(set_operations, list):
        top_n = [item for item in set_operations if isinstance(item, dict) and item.get("type") == "top_n"]
        if len(top_n) >= 2:
            outer, inner = top_n[0], top_n[1]
            outer_output = outer.get("output") or "outer_top_n"
            corrected_spec["operation"] = "topn_then_filter"
            corrected_spec["set_operations"] = [
                {**outer, "output": outer_output},
                {**inner, "input": outer_output, "output": inner.get("output") or "nested_top_n"},
            ]
            return _state_from_query_spec(corrected_spec)
    return planner_state


def llm_plan_query_node(state: dict) -> dict:
    question = state["user_question"]

    try:
        started = perf_counter()
        prompt = load_prompt() + f"\n\n用户问题：\n{question}"
        if os.getenv("LLM_HARD_TIMEOUT_ENABLED", "1").strip().lower() in {"0", "false", "no"}:
            record_llm_event({"event": "request_start", "profile": "planner", "max_tokens": 1000, "thinking_enabled": False})
            llm = _build_llm()
            response = llm.invoke(prompt)
            metadata = getattr(response, "response_metadata", {}) or {}
            finish_reason = metadata.get("finish_reason")
            record_llm_event({"event": "response_end", "profile": "planner", "duration_ms": round((perf_counter() - started) * 1000, 3), "finish_reason": finish_reason, "token_usage": getattr(response, "usage_metadata", None) or metadata.get("token_usage"), "timeout_type": None})
            if finish_reason == "length":
                error = RuntimeError("Planner 响应因长度限制被截断。")
                error.error_code = "PLANNER_TRUNCATED"
                raise error
            payload = _extract_json(response.content)
        else:
            payload = invoke_json_prompt(prompt, profile="planner")
        if _is_complete_legacy_payload(payload):
            planner_state = _normalize_planner_output(payload)
        else:
            planner_state = _state_from_split_payload(state, payload)
        planner_state = _correct_explicit_operation(question, planner_state)
    except Exception as exc:
        if isinstance(exc, TimeoutError) or "timeout" in str(exc).lower():
            exc.error_code = "PLANNER_TIMEOUT"
            record_llm_event({"event": "response_end", "profile": "planner", "duration_ms": 0, "timeout_type": "PLANNER_TIMEOUT", "error_code": "PLANNER_TIMEOUT"})
        return {
            "need_clarification": True,
            "clarification_question": f"无法解析您的问题，请重新描述。（错误：{exc}）",
            "error_messages": [f"LLM 查询规划失败: {exc}"],
            "error_type": getattr(exc, "error_code", "planner_parse_error"),
            "retry_count": 0,
        }

    return planner_state
