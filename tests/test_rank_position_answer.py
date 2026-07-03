"""排名位置回答测试。"""

from agent.nodes.answer_nodes.rank_position_answer import generate_rank_position_answer_node
from agent.nodes.analyze_nodes.rank_position_analysis import _build_result_summary


def test_rank_position_answer_uses_single_position_label():
    """排名位置只输出一个分位层级，避免前 10% 和前 25% 重复。"""
    state = {
        "analysis_result": {
            "company_name": "华润三九",
            "metric_name": "净利润",
            "report_year": 2024,
            "rank_direction": "desc",
            "rank_no": 2,
            "total_count": 62,
            "display_value": "37.78 亿元",
            "is_empty": False,
            "result_summary": _build_result_summary("华润三九", 2, 62),
        }
    }

    result = generate_rank_position_answer_node(state)

    assert "位于前 10% 区间" in result["final_answer"]
    assert "属于前 25%" not in result["final_answer"]
    assert "处于前 10% 区间，属于" not in result["final_answer"]


def test_rank_position_answer_middle_position_label():
    """中游排名输出中游区间，不拼接百分位和粗分位。"""
    state = {
        "analysis_result": {
            "company_name": "甲公司",
            "metric_name": "营业收入",
            "report_year": 2024,
            "rank_direction": "desc",
            "rank_no": 30,
            "total_count": 62,
            "display_value": "10.00 亿元",
            "is_empty": False,
            "result_summary": _build_result_summary("甲公司", 30, 62),
        }
    }

    result = generate_rank_position_answer_node(state)

    assert "处于中游区间" in result["final_answer"]
    assert "属于" not in result["final_answer"]
