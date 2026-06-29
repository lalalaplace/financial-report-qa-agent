"""Agent 节点之间共享的状态定义。

字段按处理阶段分层维护：
1. 原始输入层：用户问题。
2. LLM 原始规划层：Planner 输出和原始抽取信息。
3. 系统标准化层：公司、指标、年份、报告期等可执行对象。
4. SQL 层：各类 SQL 生成结果和 SQL 审查结果。
5. 执行结果层：数据库执行返回。
6. 分析结果层：业务分析后的结构化结论。
7. 回答与错误层：最终回答、成功状态、错误与澄清信息。

V0.4.5 只稳定字段含义，不删除仍在运行链或日志中使用的兼容字段。
"""

from typing import Any, Literal, TypedDict

from agent.schemas.clarification import ClarificationCandidate, ClarificationPayload


class CompanyInfo(TypedDict, total=False):
    stock_code: str
    stock_abbr: str
    company_name: str
    match_type: str
    score: float


class MetricInfo(TypedDict, total=False):
    metric_key: str
    metric_name: str
    metric_type: str
    table: str
    field: str
    unit: str
    aliases: list[str]
    formula: dict
    scale: int | float
    precision: int


class TimeRangeState(TypedDict, total=False):
    mode: Literal["single_year", "recent_n", "explicit_range", "unspecified"]
    report_year: int | None
    recent_n_years: int | None
    start_year: int | None
    end_year: int | None
    report_years: list[int] | None


class SQLReview(TypedDict, total=False):
    is_safe: bool
    reason: str
    corrected_sql: str | None


class QueryResult(TypedDict, total=False):
    success: bool
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    error: str | None


class AgentState(TypedDict, total=False):
    # 1. 原始输入层
    user_question: str

    # 2. LLM 原始规划层
    query_plan: dict | None
    company_mentions: list[str]
    metric_mentions: list[str]
    time_range: TimeRangeState | None
    compare_spec: dict[str, Any] | None
    intent_type: Literal[
        "single_metric_query",
        "multi_metric_query",
        "trend_query",
        "yoy_query",
        "derived_metric_query",
        "company_compare_query",
        "company_compare_trend_query",
        "company_compare_yoy_query",
        "ranking_query",
        "yoy_ranking_query",
        "trend_ranking_query",
        "rank_position_query",
        "unknown",
    ]

    # 3. 系统标准化层
    companies: list[CompanyInfo]
    metrics: list[MetricInfo]
    report_year: int | None
    report_years: list[int]
    report_period: str | None

    # 3a. 标准化辅助字段，供澄清、默认年份推断和兼容旧节点使用。
    company_candidates: list[CompanyInfo]
    metric_candidates: list[MetricInfo]
    company_resolution_status: str | None
    metric_resolution_status: str | None
    time_mode: Literal[
        "single_year",
        "recent_n",
        "explicit_range",
        "unspecified",
    ] | None
    start_year: int | None
    end_year: int | None
    recent_n_years: int | None
    warnings: list[str]

    # 4. SQL 层
    sql: str | None
    sql_review: SQLReview | None
    compare_sqls: list[dict]
    compare_trend_sqls: list
    compare_yoy_sqls: list
    derived_compare_sqls: list[dict]
    derived_compare_trend_sqls: list
    derived_compare_yoy_sqls: list

    # 4a. 非 compare 和派生单公司链路仍在使用的 SQL 字段。
    yoy_sqls: list[str]
    derived_sqls: list[str]
    derived_trend_sqls: list[dict]
    derived_yoy_sqls: list[dict]

    # 5. 执行结果层
    query_result: QueryResult | None
    compare_query_results: list[QueryResult]
    compare_trend_query_results: list
    compare_yoy_query_results: list
    derived_compare_query_results: dict
    derived_compare_trend_query_results: dict
    derived_compare_yoy_query_results: dict

    # 5a. 非 compare 和派生单公司链路仍在使用的执行结果字段。
    derived_query_results: list[QueryResult]
    derived_trend_query_results: dict
    derived_yoy_query_results: dict
    sql_success: bool | None

    # 6. 分析结果层
    analysis_result: dict | None
    compare_result: list[dict[str, Any]]
    compare_trend_result: list
    compare_yoy_result: list[dict[str, Any]]
    derived_compare_result: list[dict[str, Any]]
    derived_compare_trend_result: list
    derived_compare_yoy_result: list[dict[str, Any]]

    # 6a. 非 compare 和派生单公司链路仍在使用的分析结果字段。
    yoy_result: dict | None
    derived_result: dict | None
    derived_trend_result: dict | None
    derived_yoy_result: dict | None
    answer_facts: list[dict[str, Any]]

    # 7. 回答与错误层
    final_answer: str | None
    business_success: bool | None
    error_type: str | None
    empty_fields: list[str]

    # 7a. 澄清、日志和重试辅助字段。
    need_clarification: bool
    clarification_type: str | None
    clarification_question: str | None
    clarification_candidates: list[ClarificationCandidate]
    clarification_payload: ClarificationPayload | None
    pending_query_plan: dict | None
    pending_clarification_type: str | None
    pending_empty_fields: list[str]
    pending_candidates: list[dict]
    slot_patch: dict | None
    merged_query_plan: dict | None
    route_type: Literal[
        "new_query",
        "clarification_answer",
        "contextual_followup",
        "ambiguous",
        "irrelevant",
    ] | None
    target_context: Literal[
        "none",
        "pending_query_plan",
        "last_successful_query_plan",
    ] | None
    last_successful_query_plan: dict | None
    error_messages: list[str]
    retry_count: int

    # 8. 排名查询字段（V0.5.0）
    rank_direction: Literal["desc", "asc"] | None
    limit: int | None
    change_metric: Literal["yoy_rate", "growth_rate"] | None
