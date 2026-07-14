"""统一 SQL 生成路由节点。"""

from __future__ import annotations

from agent.nodes.answer_nodes.clarify_answer import generate_unsupported_answer_node
from agent.nodes.sql_generation_router import route_sql_generation
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


TEMPLATE_SQL_NODES = {
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


def route_sql_generation_node(state: dict) -> dict:
    """统一执行 SQL 生成路由。"""
    return route_sql_generation(state, template_nodes=TEMPLATE_SQL_NODES)


__all__ = ["TEMPLATE_SQL_NODES", "route_sql_generation_node"]
