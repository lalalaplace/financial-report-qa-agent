"""澄清/不支持问答模块。"""

from agent.state import AgentState
from agent.services.clarification_context import build_pending_clarification_state
from agent.services.clarification_service import build_clarification_question


def generate_unsupported_answer_node(state: AgentState) -> dict:
    """混合查询不支持的回答节点：从 state 读取 error_type 动态输出。"""
    error_type = state.get("error_type") or "unsupported_query"
    messages = {
        "unsupported_mixed_trend": "当前版本暂不支持原始指标和派生指标混合趋势查询。你可以分别查询原始指标趋势和派生指标趋势。",
        "unsupported_mixed_yoy": "当前版本暂不支持原始指标和派生指标混合同比查询。请分别查询。",
        "unsupported_mixed_compare": "当前版本暂不支持原始指标和派生指标混合对比。请分别查询。",
        "unsupported_mixed_compare_trend": "当前版本暂不支持原始指标和派生指标混合趋势对比。请分别查询。",
        "unsupported_mixed_compare_yoy": "当前版本暂不支持原始指标和派生指标混合同比对比。请分别查询。",
    }
    message = messages.get(error_type, "当前版本暂不支持该查询，请调整问题后重试。")
    return {
        "need_clarification": True,
        "clarification_question": message,
        "final_answer": message,
        "business_success": False,
        "error_type": error_type,
        "empty_fields": [],
    }


def _unsupported_node_response(message: str) -> dict:
    return {
        "need_clarification": True,
        "clarification_question": message,
    }


def build_clarification_response_node(state: AgentState) -> dict:
    """统一澄清回答节点。"""
    payload = state.get("clarification_payload")
    if payload:
        question = build_clarification_question(payload)
    else:
        question = state.get("clarification_question") or "请补充查询条件。"
    response = {
        "final_answer": question,
        "clarification_question": question,
        "sql_success": False,
        "business_success": False,
        "error_type": state.get("error_type") or "clarification_required",
        "empty_fields": state.get("empty_fields") or [],
        "clarification_candidates": state.get("clarification_candidates") or [],
    }
    response.update(build_pending_clarification_state({**state, **response}))
    return response
