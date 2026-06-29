"""单年指标点查回答模块。"""

from typing import Any

from agent.services.sql_builders import _metric_column_alias


def _generate_point_answer(state: dict[str, Any]) -> dict:
    result = state.get("query_result")
    if not result:
        return {
            "final_answer": "查询失败：未生成查询结果。",
            "sql_success": False,
            "business_success": False,
            "error_type": "sql_execution_error",
            "empty_fields": [],
        }

    if not result["success"]:
        return {
            "final_answer": f"查询失败：{result['error']}",
            "sql_success": False,
            "business_success": False,
            "error_type": state.get("error_type") or "sql_execution_error",
            "empty_fields": [],
        }

    if result["row_count"] == 0:
        return {
            "final_answer": "数据库中没有查询到对应结果。可能是公司、年份、报告期或指标字段缺失。",
            "sql_success": True,
            "business_success": False,
            "error_type": "empty_result",
            "empty_fields": [],
        }

    rows = result["rows"]
    columns = result["columns"]
    metrics = state.get("metrics") or []

    data = dict(zip(columns, rows[0]))
    answer_facts: list[dict[str, Any]] = []
    empty_fields: list[str] = []

    for metric in metrics:
        column_alias = _metric_column_alias(metric)
        value = data.get(column_alias)
        if value is None:
            empty_fields.append(column_alias)
            answer_facts.append(
                {
                    "metric_name": metric["metric_name"],
                    "field": column_alias,
                    "source_field": f"{metric['table']}.{metric['field']}",
                    "status": "empty_value",
                    "text": f"{metric['metric_name']}：字段为空，可能是抽取 V1 未覆盖或该字段未成功入库。",
                }
            )
            continue
        value_yi = float(value) / 100000000
        answer_facts.append(
            {
                "metric_name": metric["metric_name"],
                "field": column_alias,
                "source_field": f"{metric['table']}.{metric['field']}",
                "status": "ok",
                "value": value,
                "value_text": f"{value_yi:.2f} 亿元",
                "text": f"{metric['metric_name']}：{value_yi:.2f} 亿元",
            }
        )

    if answer_facts and all(item["status"] == "empty_value" for item in answer_facts):
        return {
            "final_answer": "数据库中没有查询到对应指标数据。可能是公司、年份、报告期或指标字段缺失。",
            "answer_facts": answer_facts,
            "sql_success": True,
            "business_success": False,
            "error_type": "empty_value",
            "empty_fields": empty_fields,
        }

    if not answer_facts:
        return {
            "final_answer": "查询到了记录，但未找到可返回的指标字段。",
            "answer_facts": [],
            "sql_success": True,
            "business_success": False,
            "error_type": "empty_value",
            "empty_fields": [],
        }

    value_lines = [f"- {item['text']}" for item in answer_facts]
    answer = (
        f"根据数据库查询结果，{data.get('company_name')} "
        f"{data.get('report_year')} 年年报中：\n\n"
        + "\n".join(value_lines)
    )

    warnings = state.get("warnings") or []
    if warnings:
        answer = "\n".join(warnings) + "\n\n" + answer

    return {
        "final_answer": answer,
        "answer_facts": answer_facts,
        "sql_success": True,
        "business_success": not empty_fields,
        "error_type": "empty_value" if empty_fields else None,
        "empty_fields": empty_fields,
    }
