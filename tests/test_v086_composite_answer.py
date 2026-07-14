"""复合查询回答生成测试。"""

from agent.nodes.answer_nodes.composite_answer import generate_composite_answer_node
from agent.routing import route_after_composite_execution


def test_composite_execution_routes_to_composite_answer() -> None:
    assert route_after_composite_execution({"composite_success": True}) == "composite_answer"
    assert (
        route_after_composite_execution({"need_clarification": True})
        == "build_clarification_response"
    )


def test_composite_answer_summarizes_ranking_and_yoy_table() -> None:
    result = generate_composite_answer_node(
        {
            "composite_success": True,
            "task_results": {
                "t1": {
                    "analysis_result": {
                        "analysis_type": "ranking",
                        "rows": [
                            {
                                "rank": 1,
                                "stock_code": "000001",
                                "company_name": "公司A",
                                "metric_value": 150,
                                "display_value": "150.00 亿元",
                            },
                            {
                                "rank": 2,
                                "stock_code": "000002",
                                "company_name": "公司B",
                                "metric_value": 130,
                                "display_value": "130.00 亿元",
                            },
                        ],
                    },
                    "success": True,
                },
                "t2": {
                    "analysis_result": {
                        "analysis_type": "company_set_yoy",
                        "rows": [
                            {
                                "stock_code": "000001",
                                "company_name": "公司A",
                                "metric_name": "净利润",
                                "current_value": 15_000_000_000,
                                "yoy_rate": 0.2,
                                "status": "ok",
                            },
                            {
                                "stock_code": "000001",
                                "company_name": "公司A",
                                "metric_name": "营业收入",
                                "current_value": 100_000_000_000,
                                "yoy_rate": 0.1,
                                "status": "ok",
                            },
                        ],
                    },
                    "success": True,
                },
            },
            "composite_analysis_result": {"task_ids": ["t1", "t2"]},
        }
    )

    assert result["business_success"] is True
    answer = result["final_answer"]
    assert "排名结果：" in answer
    assert "1. 公司A：150.00 亿元" in answer
    assert "这些公司的同比情况：" in answer
    assert "净利润：150.00 亿元，同比20.00%" in answer
    assert "营业收入：1,000.00 亿元，同比10.00%" in answer
