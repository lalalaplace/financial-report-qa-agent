"""公司趋势对比回答测试。"""

from agent.nodes.answer_nodes.compare_trend_answer import _generate_compare_trend_answer


def test_compare_trend_semantic_answer_keeps_yearly_details():
    """“谁增长更快”命中语义化结论时仍展示逐年数据。"""
    state = {
        "compare_spec": {"operator": "faster_growth"},
        "compare_trend_result": [
            {
                "metric_name": "营业收入",
                "unit": "yuan",
                "precision": 2,
                "years": [2022, 2023, 2024],
                "status": "ok",
                "items": [
                    {
                        "company_name": "华润三九医药股份有限公司",
                        "series": [
                            {"year": 2022, "value": 4_194_386_685.74, "status": "ok"},
                            {"year": 2023, "value": 24_738_963_319.76, "status": "ok"},
                            {"year": 2024, "value": 27_616_611_772.61, "status": "ok"},
                        ],
                        "first_value": 4_194_386_685.74,
                        "last_value": 27_616_611_772.61,
                        "absolute_change": 23_422_225_086.87,
                        "change_rate": 5.5842,
                        "change_unit": "yuan",
                        "status": "ok",
                    },
                    {
                        "company_name": "云南白药集团股份有限公司",
                        "series": [
                            {"year": 2022, "value": 36_488_372_649.73, "status": "ok"},
                            {"year": 2023, "value": 39_111_292_156.00, "status": "ok"},
                            {"year": 2024, "value": 40_033_300_814.72, "status": "ok"},
                        ],
                        "first_value": 36_488_372_649.73,
                        "last_value": 40_033_300_814.72,
                        "absolute_change": 3_544_928_164.99,
                        "change_rate": 0.0972,
                        "change_unit": "yuan",
                        "status": "ok",
                    },
                ],
            }
        ],
    }

    result = _generate_compare_trend_answer(state)
    answer = result["final_answer"]

    assert "2022 到 2024 年营业收入增长更快的是华润三九医药股份有限公司。" in answer
    assert "年度数据：" in answer
    assert "- 华润三九医药股份有限公司：" in answer
    assert "  - 2022 年：41.94 亿元" in answer
    assert "  - 2024 年：276.17 亿元" in answer
    assert "  - 2022 到 2024 年增加 234.22 亿元" in answer
    assert "- 云南白药集团股份有限公司：" in answer
    assert "  - 2022 年：364.88 亿元" in answer
    assert "  - 2024 年：400.33 亿元" in answer
    assert "  - 2022 到 2024 年增加 35.45 亿元" in answer
    assert result["answer_facts"]
