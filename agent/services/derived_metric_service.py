"""从 graph.py 拆出的业务实现。"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.constants import DEFAULT_REPORT_PERIOD, DEFAULT_QUERY_TYPE, TABLE_ALIASES, COMPARE_INTENTS
from agent.schemas.query_plan import normalize_compare_spec
from agent.state import AgentState
from agent.tools.company_tools import resolve_company
from agent.tools.metric_tools import load_metric_dictionary, map_metrics
from agent.tools.sql_tools import execute_financial_sql, review_sql
from db.readonly_executor import execute_readonly_sql


def _metric_for_latest_year_lookup(metric: dict[str, Any]) -> dict[str, Any]:
    """为最新年份探测选择可落地到表的基础指标。"""
    if metric.get("metric_type") != "derived":
        return metric

    formula = metric.get("formula") or {}
    numerator_key = formula.get("numerator")
    metric_dict = load_metric_dictionary()
    numerator = metric_dict.get(numerator_key) if numerator_key else None
    if numerator:
        return numerator
    return {"table": "balance_sheet"}

__all__ = ['_metric_for_latest_year_lookup']
