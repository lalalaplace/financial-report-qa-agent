"""回答模块共享工具。"""


def append_llm_insight_section(answer_payload: dict, state: dict) -> dict:
    """在成功答案后追加 LLM 补充洞察段落。"""
    if state.get("llm_analysis_success") is not True:
        return answer_payload
    analysis = state.get("llm_analysis")
    if not isinstance(analysis, dict):
        return answer_payload
    final_answer = answer_payload.get("final_answer")
    if not isinstance(final_answer, str) or not final_answer:
        return answer_payload

    insight = analysis.get("insight") if isinstance(analysis.get("insight"), str) else ""
    boundary = (
        analysis.get("interpretation_boundary")
        if isinstance(analysis.get("interpretation_boundary"), str)
        else ""
    )
    followup = (
        analysis.get("suggested_followup")
        if isinstance(analysis.get("suggested_followup"), str)
        else ""
    )

    insight_lines = [text.strip() for text in (insight, boundary) if text and text.strip()]
    followup_text = followup.strip() if followup and followup.strip() else ""
    if not insight_lines and not followup_text:
        return answer_payload

    section_parts: list[str] = []
    if insight_lines:
        section_parts.append("补充解读：\n" + "\n".join(insight_lines))
    if followup_text:
        section_parts.append("可继续分析：\n" + followup_text)

    updated = dict(answer_payload)
    updated["final_answer"] = final_answer.rstrip() + "\n\n" + "\n\n".join(section_parts)
    return updated


def _fmt_yuan_value(value: float) -> str:
    """将元值格式化为亿元显示。"""
    return f"{value / 100000000:.2f} 亿元"


def _section_numeral(index: int) -> str:
    numerals = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]
    return numerals[index - 1] if 1 <= index <= len(numerals) else str(index)


def append_llm_sql_notice(answer_payload: dict, state: dict) -> dict:
    """受控 LLM SQL 成功路径补充审计提示。"""
    if state.get("sql_generation_mode") != "llm_sql":
        return answer_payload
    final_answer = answer_payload.get("final_answer")
    if not isinstance(final_answer, str) or not final_answer:
        return answer_payload
    notice = "本次查询由受控 LLM SQL 生成，已通过只读和字段校验。"
    if notice in final_answer:
        return answer_payload
    updated = dict(answer_payload)
    updated["final_answer"] = final_answer.rstrip() + "\n\n" + notice
    return updated


def assemble_final_answer_node(state: dict) -> dict:
    """最终答案拼接节点。"""
    payload = append_llm_sql_notice({"final_answer": state.get("final_answer")}, state)
    return append_llm_insight_section(payload, state)
