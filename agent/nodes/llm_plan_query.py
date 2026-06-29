from pathlib import Path
from typing import Any

from agent.schemas.query_plan import validate_plan
from agent.services.llm_json_service import (
    build_llm as _shared_build_llm,
    extract_json as _shared_extract_json,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "query_planner.md"


def load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def _extract_json(text: str) -> dict:
    """从 LLM 文本响应中提取 JSON 对象。"""
    return _shared_extract_json(text)

def _build_llm():
    return _shared_build_llm()

def _state_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    time_range = plan["time_range"]
    return {
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


def llm_plan_query_node(state: dict) -> dict:
    question = state["user_question"]

    try:
        llm = _build_llm()
        prompt = load_prompt() + f"\n\n用户问题：\n{question}"
        response = llm.invoke(prompt)
        plan = validate_plan(_extract_json(response.content))
    except Exception as exc:
        return {
            "need_clarification": True,
            "clarification_question": f"无法解析您的问题，请重新描述。（错误：{exc}）",
            "error_messages": [f"LLM 查询规划失败: {exc}"],
            "error_type": "planner_parse_error",
            "retry_count": 0,
        }

    return _state_from_plan(plan)

