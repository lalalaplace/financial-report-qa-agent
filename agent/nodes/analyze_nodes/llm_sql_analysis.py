"""受控 LLM SQL 查询结果分析节点。"""

from __future__ import annotations

from typing import Any

from agent.nodes.llm_sql_node import _tabular_analysis_from_query_result


def analyze_llm_sql_node(state: dict[str, Any]) -> dict[str, Any]:
    """把单条受控 LLM SQL 的查询结果转换为通用表格分析结果。"""
    return _tabular_analysis_from_query_result(state.get("query_result") or {})


__all__ = ["analyze_llm_sql_node"]
