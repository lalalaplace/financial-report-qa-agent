"""查询结果展示合同。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


ResultShape = Literal[
    "scalar",
    "single_entity",
    "comparison",
    "ranking",
    "filtered_table",
    "time_series",
]


class ColumnDefinition(TypedDict, total=False):
    name: str
    display_name: str
    role: str
    value_type: str
    numeric_semantic: "NumericSemantic"


class NumericSemantic(TypedDict):
    value_kind: Literal["currency", "count", "raw_number", "ratio", "percentage", "percentage_point"]
    storage_scale: Literal["unit", "fraction", "percent"]
    display_precision: int
    display_unit: Literal["raw", "hundred_million_yuan"]


class ResultContract(TypedDict, total=False):
    result_shape: ResultShape
    row_count: int
    columns: list[ColumnDefinition]
    display_columns: list[str]
    key_columns: list[str]
    must_render_table: bool
    max_display_rows: int
    result_truncated: bool
    summary_allowed: bool
    analysis_allowed: bool
    evidence_rows: list[dict[str, Any]]
    display_rows: list[dict[str, Any]]
    numeric_semantics: dict[str, NumericSemantic]
    ordering: list[dict[str, Any]]
    truncation: dict[str, Any]
    deterministic_observations: list[str]


__all__ = ["ColumnDefinition", "NumericSemantic", "ResultContract", "ResultShape"]
