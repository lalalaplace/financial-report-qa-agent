"""LLM 结果解释节点。

该节点只解释确定性查询和分析结果，不参与 SQL、数值计算或成功失败判断。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.services.llm_json_service import build_llm, extract_json
from agent.state import AgentState


PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "result_analyzer.md"

ANALYZABLE_INTENTS = {
    "trend_query",
    "yoy_query",
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
    "ranking_query",
    "yoy_ranking_query",
    "trend_ranking_query",
    "rank_position_query",
    "derived_metric_query",
    "derived_trend_query",
    "derived_yoy_query",
}


def _has_non_empty_query_result(query_result: Any) -> bool:
    """判断主查询结果是否存在有效行。"""
    if not isinstance(query_result, dict):
        return False
    if query_result.get("success") is False:
        return False
    rows = query_result.get("rows")
    if isinstance(rows, list):
        return len(rows) > 0
    row_count = query_result.get("row_count")
    return isinstance(row_count, int) and row_count > 0


def should_run_llm_analysis(state: AgentState) -> bool:
    """判断是否需要执行 LLM 结果解释。"""
    if state.get("business_success") is not True:
        return False
    if state.get("error_type"):
        return False
    if not _has_non_empty_query_result(state.get("query_result")):
        return False
    intent_type = state.get("intent_type")
    return intent_type in ANALYZABLE_INTENTS


def build_result_analysis_payload(state: AgentState) -> dict[str, Any]:
    """构造传给 LLM 的最小结果解释载荷。"""
    return {
        "intent_type": state.get("intent_type"),
        "query_result": state.get("query_result"),
        "analysis_result": state.get("analysis_result"),
    }


def parse_llm_analysis_response(response: Any) -> dict[str, Any]:
    """解析 LLM 响应中的 JSON 对象。"""
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        return extract_json(response)
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return extract_json(content)
    raise ValueError("LLM 响应缺少可解析的文本内容")


def _clean_text(value: Any, max_length: int) -> str:
    """清理单个文本字段并限制长度。"""
    if not isinstance(value, str):
        raise ValueError("LLM 分析字段必须是字符串")
    text = value.strip()
    if len(text) > max_length:
        return text[:max_length]
    return text


def _clean_text_list(value: Any, *, max_items: int, max_length: int) -> list[str]:
    """清理文本数组并限制条数和长度。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("LLM 分析列表字段必须是数组")
    cleaned: list[str] = []
    for item in value[:max_items]:
        cleaned.append(_clean_text(item, max_length))
    return cleaned


def validate_llm_analysis(data: dict[str, Any]) -> dict[str, Any]:
    """校验并裁剪 LLM 结果解释 JSON。"""
    if not isinstance(data, dict):
        raise ValueError("LLM 分析结果必须是 JSON 对象")
    summary = _clean_text(data.get("summary"), 60)
    observations = _clean_text_list(
        data.get("observations"),
        max_items=3,
        max_length=50,
    )
    caveats = _clean_text_list(
        data.get("caveats"),
        max_items=2,
        max_length=80,
    )
    return {
        "summary": summary,
        "observations": observations,
        "caveats": caveats,
    }


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def llm_analyze_result_node(state: AgentState) -> dict[str, Any]:
    """调用 LLM 生成简短结果解释，失败时不影响主链路。"""
    if not should_run_llm_analysis(state):
        return {
            "llm_analysis": None,
            "llm_analysis_success": False,
            "llm_analysis_error": None,
        }

    try:
        payload = build_result_analysis_payload(state)
        prompt = (
            _load_prompt()
            + "\n\n输入数据：\n"
            + json.dumps(payload, ensure_ascii=False, default=str)
        )
        response = build_llm().invoke(prompt)
        analysis = validate_llm_analysis(parse_llm_analysis_response(response))
    except Exception as exc:
        return {
            "llm_analysis": None,
            "llm_analysis_success": False,
            "llm_analysis_error": str(exc),
        }

    return {
        "llm_analysis": analysis,
        "llm_analysis_success": True,
        "llm_analysis_error": None,
    }


__all__ = [
    "should_run_llm_analysis",
    "build_result_analysis_payload",
    "parse_llm_analysis_response",
    "validate_llm_analysis",
    "llm_analyze_result_node",
]

# 兼容旧导入路径：主流程已迁移到 llm_insight_node。
from agent.nodes.llm_insight import (
    build_result_insight_payload as build_result_analysis_payload,
    llm_insight_node as llm_analyze_result_node,
    parse_llm_insight_response as parse_llm_analysis_response,
    should_run_llm_insight as should_run_llm_analysis,
    validate_llm_insight as validate_llm_analysis,
)
