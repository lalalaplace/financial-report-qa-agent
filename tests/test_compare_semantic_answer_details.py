"""语义化对比回答明细测试。"""

from agent.nodes.answer_nodes.compare_answer import _generate_compare_answer
from agent.nodes.answer_nodes.compare_yoy_answer import _generate_compare_yoy_answer


def test_point_compare_semantic_answer_keeps_compare_details():
    """单年“谁更高”输出结论后保留两家公司支撑数据。"""
    state = {
        "report_year": 2024,
        "compare_spec": {"operator": "higher", "target": "metric_value"},
        "compare_result": [
            {
                "metric_name": "营业收入",
                "unit": "yuan",
                "status": "ok",
                "winner_company": "云南白药集团股份有限公司",
                "diff": 12_416_689_042.11,
                "diff_unit": "yuan",
                "items": [
                    {
                        "company_name": "华润三九医药股份有限公司",
                        "value": 27_616_611_772.61,
                        "status": "ok",
                    },
                    {
                        "company_name": "云南白药集团股份有限公司",
                        "value": 40_033_300_814.72,
                        "status": "ok",
                    },
                ],
            }
        ],
    }

    result = _generate_compare_answer(state)
    answer = result["final_answer"]

    assert "2024 年营业收入更高的是云南白药集团股份有限公司" in answer
    assert "对比数据：" in answer
    assert "- 华润三九医药股份有限公司：276.17 亿元" in answer
    assert "- 云南白药集团股份有限公司：400.33 亿元" in answer
    assert "- 差值：云南白药集团股份有限公司高出 124.17 亿元" in answer
    assert result["answer_facts"]


def test_yoy_compare_semantic_answer_keeps_yoy_details():
    """同比“谁增速更高”输出结论后保留两家公司同比数据。"""
    state = {
        "compare_spec": {"operator": "faster_growth", "target": "yoy_rate"},
        "compare_yoy_result": [
            {
                "metric_name": "净利润",
                "metric_type": "base",
                "unit": "yuan",
                "current_year": 2024,
                "previous_year": 2023,
                "status": "ok",
                "winner_company": "华润三九医药股份有限公司",
                "diff_yoy_rate": 0.0259,
                "items": [
                    {
                        "company_name": "华润三九医药股份有限公司",
                        "current_value": 3_777_741_284.58,
                        "previous_value": 3_173_478_654.27,
                        "absolute_change": 604_262_630.31,
                        "yoy_rate": 0.1904,
                        "status": "ok",
                    },
                    {
                        "company_name": "云南白药集团股份有限公司",
                        "current_value": 4_767_072_360.28,
                        "previous_value": 4_093_782_074.02,
                        "absolute_change": 673_290_286.26,
                        "yoy_rate": 0.1645,
                        "status": "ok",
                    },
                ],
            }
        ],
    }

    result = _generate_compare_yoy_answer(state)
    answer = result["final_answer"]

    assert "2024 年净利润同比增速更高的是华润三九医药股份有限公司" in answer
    assert "同比数据：" in answer
    assert "- 华润三九医药股份有限公司：2023 年 31.73 亿元，2024 年 37.78 亿元，同比增长 19.04%" in answer
    assert "- 云南白药集团股份有限公司：2023 年 40.94 亿元，2024 年 47.67 亿元，同比增长 16.45%" in answer
    assert "- 差值：华润三九医药股份有限公司同比增速高出 2.59 个百分点" in answer
    assert result["answer_facts"]
