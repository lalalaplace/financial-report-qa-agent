"""Agent 常量定义。"""

DEFAULT_REPORT_PERIOD = "FY"
DEFAULT_QUERY_TYPE = "single_metric_query"
MAX_LLM_SQL_REPAIR_ATTEMPTS = 1
TABLE_ALIASES = {
    "balance_sheet": "b",
    "income_sheet": "i",
    "cash_flow_sheet": "cf",
    "core_performance": "cp",
}
COMPARE_INTENTS = {
    "company_compare_query",
    "company_compare_trend_query",
    "company_compare_yoy_query",
}
