"""Agent 结构化 schema 定义。"""

from agent.schemas.clarification import (
    ClarificationCandidate,
    ClarificationPayload,
    build_clarification_payload,
    validate_clarification_payload,
)
from agent.schemas.composite_query_plan import (
    CompositeQueryPlan,
    CompositeResult,
    validate_composite_query_plan,
)
from agent.schemas.task_plan import (
    RankingSpec,
    TaskArtifact,
    TaskDependency,
    TaskPlan,
    normalize_task_plan,
)
from agent.schemas.llm_sql import (
    LlmSqlRequest,
    LlmSqlResponse,
    LlmSqlValidationResult,
    SqlGenerationMode,
)
from agent.schemas.query_spec import (
    QuerySpec,
    normalize_query_spec,
)
from agent.schemas.flexible_sql_spec import FlexibleSQLSpec
from agent.schemas.state_sections import (
    AnswerState,
    ConversationState,
    ErrorState,
    ExecutionState,
    PlanningState,
    ResultState,
    SQLAttempt,
)

__all__ = [
    "ClarificationCandidate",
    "ClarificationPayload",
    "CompositeQueryPlan",
    "CompositeResult",
    "RankingSpec",
    "TaskArtifact",
    "TaskDependency",
    "TaskPlan",
    "LlmSqlRequest",
    "LlmSqlResponse",
    "LlmSqlValidationResult",
    "QuerySpec",
    "FlexibleSQLSpec",
    "AnswerState",
    "ConversationState",
    "ErrorState",
    "ExecutionState",
    "PlanningState",
    "ResultState",
    "SQLAttempt",
    "SqlGenerationMode",
    "build_clarification_payload",
    "normalize_query_spec",
    "normalize_task_plan",
    "validate_clarification_payload",
    "validate_composite_query_plan",
]
