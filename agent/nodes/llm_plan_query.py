import json
import os
import re
from pathlib import Path
from typing import Any

from agent.schemas.query_plan import validate_plan
from agent.services.llm_json_service import (
    build_llm as _shared_build_llm,
    extract_json as _shared_extract_json,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "query_planner.md"
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
    return _shared_build_llm()
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
