"""普通同比查询回答模块（单公司）。"""

from typing import Any


def _generate_yoy_answer(state: dict[str, Any]) -> dict:
    yoy_result = state.get("yoy_result") or {}
    items = yoy_result.get("items") or []
    company_name = yoy_result.get("company_name", "")
    report_year = yoy_result.get("report_year") or "未知年份"
    prev_year = yoy_result.get("previous_year") or "上年"

    if not items:
        return {
            "final_answer": "数据库中没有查询到对应同比数据。可能是公司、年份、报告期或指标字段缺失。",
            "answer_facts": [],
            "sql_success": True,
            "business_success": False,
            "error_type": "empty_result",
            "empty_fields": [],
        }

    answer_facts: list[dict[str, Any]] = []
    metric_lines: list[str] = []
    ok_count = 0
    failed_count = 0

    for item in items:
        metric_name = item["metric_name"]
        status = item["status"]
        source_field = f"{item['table']}.{item['field']}"

        if status == "ok":
            ok_count += 1
            current_val = item["current_value"]
            prev_val = item["previous_value"]
            change_abs = item["change_abs"]
            yoy_rate = item["yoy_rate"]

            current_yi = current_val / 100000000
            prev_yi = prev_val / 100000000

            if change_abs > 0:
                direction_word = "增加"
                rate_word = "增速"
            elif change_abs < 0:
                direction_word = "减少"
                rate_word = "降幅"
            else:
                direction_word = ""
                rate_word = ""

            change_yi = abs(change_abs) / 100000000
            rate_pct = round(abs(yoy_rate) * 100, 2)

            if change_abs != 0:
                line = (
                    f"{metric_name}为 {current_yi:.2f} 亿元，{prev_year} 年为 {prev_yi:.2f} 亿元，"
                    f"同比{direction_word} {change_yi:.2f} 亿元，同比{rate_word}为 {rate_pct:.2f}%。"
                )
            else:
                line = (
                    f"{metric_name}为 {current_yi:.2f} 亿元，{prev_year} 年为 {prev_yi:.2f} 亿元，"
                    f"同比持平。"
                )
            metric_lines.append(line)
            answer_facts.append({
                "metric_name": metric_name,
                "source_field": source_field,
                "status": "ok",
                "current_value": current_val,
                "previous_value": prev_val,
                "change_abs": change_abs,
                "yoy_rate": yoy_rate,
            })

        elif status == "zero_previous_value":
            failed_count += 1
            current_yi = item["current_value"] / 100000000
            change_yi = abs(item["change_abs"]) / 100000000
            line = (
                f"{metric_name}为 {current_yi:.2f} 亿元，{prev_year} 年为 0。"
                f"由于上年基数为 0，无法计算有意义的同比增速；绝对变化为 {change_yi:.2f} 亿元。"
            )
            metric_lines.append(line)
            answer_facts.append({
                "metric_name": metric_name,
                "source_field": source_field,
                "status": "zero_previous_value",
                "current_value": item["current_value"],
                "previous_value": 0,
            })

        else:
            failed_count += 1
            status_msgs = {
                "missing_current_year": f"缺少 {report_year} 年数据",
                "missing_previous_year": f"缺少 {prev_year} 年数据",
                "empty_current_value": f"{report_year} 年字段值为空",
                "empty_previous_value": f"{prev_year} 年字段值为空",
            }
            reason = status_msgs.get(status, status)
            line = f"{metric_name}：{reason}，无法计算同比。"
            metric_lines.append(line)
            answer_facts.append({
                "metric_name": metric_name,
                "source_field": source_field,
                "status": status,
            })

    if ok_count == 0:
        business_success = False
        error_type = "yoy_unavailable"
    elif failed_count > 0:
        business_success = True
        error_type = "partial_empty_value"
    else:
        business_success = True
        error_type = None

    answer = (
        f"根据数据库查询结果，{company_name} {report_year} 年年报中：\n\n"
        + "\n".join(metric_lines)
    )
    return {
        "final_answer": answer,
        "answer_facts": answer_facts,
        "sql_success": True,
        "business_success": business_success,
        "error_type": error_type,
        "empty_fields": [],
    }
