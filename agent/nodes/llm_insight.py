"""LLM 补充洞察节点。

该节点只基于已生成的主答案、查询结果和确定性分析结果生成补充洞察。
"""

from __future__ import annotations

import json
import re
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

FORBIDDEN_EXTERNAL_TERMS = (
    "并购",
    "内生增长",
    "外部因素",
    "外部环境",
    "政策",
    "市场需求",
    "产品销量",
    "价格变化",
    "价格因素",
    "渠道",
    "公告",
    "附注",
    "管理层",
    "经营原因",
    "业务范围变化",
    "通胀",
    "宏观",
    "行业",
    "行业背景",
    "分产品",
    "分地区",
    "结构性因素",
    "业务结构",
    "一次性因素",
    "非经常性",
    "营业成本",
    "销售费用",
    "特殊事件",
    "基数效应",
    "因素影响",
    "多种因素",
)


def _has_rows(result: Any) -> bool:
    """判断单个查询结果是否有返回行。"""
    if not isinstance(result, dict):
        return False
    if result.get("success") is False or result.get("sql_success") is False:
        return False
    rows = result.get("rows")
    if isinstance(rows, list):
        return len(rows) > 0
    row_count = result.get("row_count")
    return isinstance(row_count, int) and row_count > 0


def _has_any_query_data(state: AgentState) -> bool:
    """兼容单 SQL、对比、派生等多种查询结果结构。"""
    if _has_rows(state.get("query_result")):
        return True
    for field_name in (
        "derived_query_results",
        "compare_query_results",
        "compare_trend_query_results",
        "compare_yoy_query_results",
    ):
        if any(_has_rows(item) for item in state.get(field_name) or []):
            return True
    for field_name in (
        "derived_trend_query_results",
        "derived_yoy_query_results",
        "derived_compare_query_results",
        "derived_compare_trend_query_results",
        "derived_compare_yoy_query_results",
    ):
        if any(_has_rows(item) for item in (state.get(field_name) or {}).values()):
            return True
    return False


def should_run_llm_insight(state: AgentState) -> bool:
    """判断是否需要执行 LLM 补充洞察。"""
    if state.get("business_success") is not True:
        return False
    if state.get("error_type"):
        return False
    if state.get("intent_type") not in ANALYZABLE_INTENTS:
        return False
    if not isinstance(state.get("final_answer"), str) or not state.get("final_answer"):
        return False
    return _has_any_query_data(state)


def build_result_insight_payload(state: AgentState) -> dict[str, Any]:
    """构造传给 LLM 的最小洞察载荷。"""
    return {
        "intent_type": state.get("intent_type"),
        "query_result": state.get("query_result"),
        "analysis_result": state.get("analysis_result"),
        "base_answer": state.get("final_answer"),
    }


def parse_llm_insight_response(response: Any) -> dict[str, Any]:
    """解析 LLM 响应中的 JSON 对象。"""
    if isinstance(response, dict):
        return response
    if isinstance(response, str):
        return extract_json(response)
    content = getattr(response, "content", None)
    if isinstance(content, str):
        return extract_json(content)
    raise ValueError("LLM 响应缺少可解析的文本内容")


def _clean_optional_text(value: Any, max_length: int) -> str:
    """清理可为空文本字段并限制长度。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("LLM 洞察字段必须是字符串")
    return value.strip()[:max_length]


def validate_llm_insight(data: dict[str, Any]) -> dict[str, str]:
    """校验并裁剪 LLM 洞察 JSON。"""
    if not isinstance(data, dict):
        raise ValueError("LLM 洞察结果必须是 JSON 对象")
    return {
        "insight": _clean_optional_text(data.get("insight"), 160),
        "interpretation_boundary": _clean_optional_text(
            data.get("interpretation_boundary"),
            160,
        ),
        "suggested_followup": _clean_optional_text(data.get("suggested_followup"), 120),
    }


def _normalize_text(text: str) -> str:
    """用于重复检测的文本归一化。"""
    return re.sub(r"\s+", "", text).lower()


def _core_numeric_tokens(text: str) -> set[str]:
    """提取核心数值片段，年份不作为复述数值处理。"""
    tokens = set(re.findall(r"\d+(?:\.\d+)?%?", text))
    core_tokens: set[str] = set()
    for token in tokens:
        plain_token = token.rstrip("%")
        if plain_token.isdigit() and 1900 <= int(plain_token) <= 2099:
            continue
        core_tokens.add(token)
    return core_tokens


def is_redundant_with_base_answer(text: str, base_answer: str) -> bool:
    """判断洞察文本是否与主答案重复。"""
    cleaned = text.strip()
    if not cleaned:
        return True
    normalized_text = _normalize_text(cleaned)
    normalized_base = _normalize_text(base_answer)
    if normalized_text and normalized_text in normalized_base:
        return True
    text_numbers = _core_numeric_tokens(cleaned)
    if text_numbers and text_numbers <= _core_numeric_tokens(base_answer):
        return True
    return False


def remove_redundant_insight_fields(
    analysis: dict[str, str],
    base_answer: str,
) -> dict[str, str]:
    """移除与主答案重复的洞察字段。"""
    cleaned = dict(analysis)
    for key in ("insight", "interpretation_boundary", "suggested_followup"):
        value = cleaned.get(key) or ""
        if is_redundant_with_base_answer(value, base_answer):
            cleaned[key] = ""
    return cleaned


def remove_external_insight_fields(analysis: dict[str, str]) -> dict[str, str]:
    """移除包含库外因素、经营原因或未提供拆分维度的洞察字段。"""
    cleaned = dict(analysis)
    for key in ("insight", "interpretation_boundary", "suggested_followup"):
        value = cleaned.get(key) or ""
        if any(term in value for term in FORBIDDEN_EXTERNAL_TERMS):
            cleaned[key] = ""
    return cleaned


def _fallback_ranking_insight(state: AgentState, analysis: dict[str, str]) -> dict[str, str]:
    """排名类查询补充通用样本口径边界。"""
    if state.get("intent_type") not in {"ranking_query", "rank_position_query"}:
        return analysis
    cleaned = dict(analysis)
    if not cleaned.get("interpretation_boundary"):
        cleaned["interpretation_boundary"] = (
            "排名仅覆盖当前数据库中该年份、报告期和指标非空的公司样本。"
        )
    if not has_displayable_insight(cleaned):
        cleaned["suggested_followup"] = "可继续查看排名公司之间的指标差距或该指标多年排名变化。"
    return cleaned


def _fallback_yoy_insight(state: AgentState, analysis: dict[str, str]) -> dict[str, str]:
    """同比类查询补充相邻两期口径边界。"""
    if state.get("intent_type") not in {"yoy_query", "company_compare_yoy_query", "derived_yoy_query"}:
        return analysis
    cleaned = dict(analysis)
    if not cleaned.get("interpretation_boundary"):
        cleaned["interpretation_boundary"] = (
            "同比仅基于相邻两个报告期，不能判断中长期趋势、持续性或变化原因。"
        )
    if not cleaned.get("suggested_followup"):
        metrics = state.get("metrics") or []
        metric_name = ""
        if metrics and isinstance(metrics[0], dict):
            metric_name = str(metrics[0].get("metric_name") or "")
        if "营业收入" in metric_name or "营收" in metric_name:
            cleaned["suggested_followup"] = (
                "可继续查看该指标近三至四年同比趋势，或并列对比净利润、净利率、毛利率。"
            )
        else:
            cleaned["suggested_followup"] = "可继续查看该指标近三至四年趋势及同比变化。"
    return cleaned


def _compare_metric_scope(metric_name: str) -> str:
    """根据指标名称给出对比类查询的通用解释口径。"""
    if "营业收入" in metric_name or "营收" in metric_name:
        return "营业收入属于规模指标，当前对比只反映收入规模差异，不代表经营质量。"
    if "净利率" in metric_name or "毛利率" in metric_name:
        return "该比率用于观察盈利效率差异，不代表公司整体优劣或投资判断。"
    if "资产负债率" in metric_name:
        return "资产负债率用于观察资本结构差异，不代表公司整体风险判断。"
    return "当前对比只反映所选指标口径下的差异，不代表公司整体优劣。"


def _fallback_compare_insight(state: AgentState, analysis: dict[str, str]) -> dict[str, str]:
    """对比类查询在 LLM 返回空时补充指标口径边界。"""
    if state.get("intent_type") != "company_compare_query":
        return analysis
    if has_displayable_insight(analysis):
        return analysis
    metrics = state.get("metrics") or []
    metric_name = ""
    if metrics and isinstance(metrics[0], dict):
        metric_name = str(metrics[0].get("metric_name") or "")
    return {
        "insight": _compare_metric_scope(metric_name),
        "interpretation_boundary": "该结论仅基于当前年份、报告期和指标口径，不能扩展为原因解释。",
        "suggested_followup": "",
    }


def has_displayable_insight(analysis: Any) -> bool:
    """判断洞察结构是否有可展示内容。"""
    if not isinstance(analysis, dict):
        return False
    return any(
        isinstance(analysis.get(key), str) and analysis.get(key).strip()
        for key in ("insight", "interpretation_boundary", "suggested_followup")
    )


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def llm_insight_node(state: AgentState) -> dict[str, Any]:
    """调用 LLM 生成补充洞察，失败时不影响主链路。"""
    if not should_run_llm_insight(state):
        return {
            "llm_analysis": None,
            "llm_analysis_success": False,
            "llm_analysis_error": None,
        }

    base_answer = state.get("final_answer") or ""
    try:
        payload = build_result_insight_payload(state)
        prompt = (
            _load_prompt()
            + "\n\n输入数据：\n"
            + json.dumps(payload, ensure_ascii=False, default=str)
        )
        response = build_llm().invoke(prompt)
        analysis = validate_llm_insight(parse_llm_insight_response(response))
        analysis = remove_external_insight_fields(analysis)
        analysis = remove_redundant_insight_fields(analysis, base_answer)
        analysis = _fallback_yoy_insight(state, analysis)
        analysis = _fallback_ranking_insight(state, analysis)
        analysis = _fallback_compare_insight(state, analysis)
    except Exception as exc:
        return {
            "llm_analysis": None,
            "llm_analysis_success": False,
            "llm_analysis_error": str(exc),
        }

    if not has_displayable_insight(analysis):
        return {
            "llm_analysis": analysis,
            "llm_analysis_success": False,
            "llm_analysis_error": None,
        }

    return {
        "llm_analysis": analysis,
        "llm_analysis_success": True,
        "llm_analysis_error": None,
    }


__all__ = [
    "should_run_llm_insight",
    "build_result_insight_payload",
    "parse_llm_insight_response",
    "validate_llm_insight",
    "remove_redundant_insight_fields",
    "remove_external_insight_fields",
    "has_displayable_insight",
    "llm_insight_node",
]
