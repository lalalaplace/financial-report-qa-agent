"""根据 ResultContract 确定性渲染结果表格。"""

from __future__ import annotations

from typing import Any

def render_deterministic_table(result_contract: dict[str, Any]) -> dict[str, Any]:
    rows = [dict(row) for row in result_contract.get("display_rows") or [] if isinstance(row, dict)]
    columns = list(result_contract.get("display_columns") or [])
    if not columns and rows:
        columns = list(rows[0].keys())
    rendered_rows = [{column: row.get(column) for column in columns} for row in rows]
    return {
        "columns": columns,
        "rows": rendered_rows,
        "source": "result_contract.display_rows",
        "row_count": len(rendered_rows),
        "is_truncated": bool(result_contract.get("result_truncated")),
    }


def render_deterministic_table_node(state: dict[str, Any]) -> dict[str, Any]:
    contract = state.get("result_contract") if isinstance(state.get("result_contract"), dict) else {}
    return {"deterministic_table": render_deterministic_table(contract), "table_source": "result_contract"}


__all__ = ["render_deterministic_table", "render_deterministic_table_node"]
