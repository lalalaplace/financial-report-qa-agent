"""V0.5.7.6 ranking 系列回答格式统一测试。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from agent.nodes.answer_nodes.ranking_answer import generate_ranking_answer_node
from agent.nodes.answer_nodes.yoy_ranking_answer import generate_yoy_ranking_answer_node
from agent.nodes.answer_nodes.trend_ranking_answer import generate_trend_ranking_answer_node
from agent.nodes.answer_nodes.rank_position_answer import generate_rank_position_answer_node


def test_ranking_answer_uses_result_list_summary_formula_order():
    answered = generate_ranking_answer_node(
        {
            "analysis_result": {
                "metric_name": "净利率",
                "metric_type": "derived",
                "report_year": 2024,
                "report_period": "FY",
                "rank_direction": "desc",
                "limit": 2,
                "row_count": 2,
                "is_empty": False,
                "rows": [
                    {"rank": 1, "company_name": "A公司", "metric_value": 35.2, "display_value": "35.20%"},
                    {"rank": 2, "company_name": "B公司", "metric_value": 28.1, "display_value": "28.10%"},
                ],
                "result_summary": {
                    "first_company_name": "A公司",
                    "second_company_name": "B公司",
                    "first_rank_label": "排名第一",
                    "first_display_value": "35.20%",
                    "topn_count": 2,
                    "average_label": "平均净利率",
                    "average_display_value": "31.65%",
                    "gap_compare_word": "高",
                    "gap_display_value": "7.10 个百分点",
                    "gap_ratio_display": None,
                },
            },
            "sql_metadata": {"formula_display": "净利润 / 营业收入"},
        }
    )

    paragraphs = answered["final_answer"].split("\n\n")
    assert paragraphs[0] == "2024 年净利率排名前 2 的公司如下："
    assert paragraphs[1].startswith("1. A公司：35.20%\n2. B公司：28.10%")
    assert "其中，A公司排名第一，净利率为35.20%；前 2 家公司的平均净利率为31.65%" in paragraphs[2]
    assert "A公司比第二名B公司高7.10 个百分点" in paragraphs[2]
    assert paragraphs[3] == "口径：净利率 = 净利润 / 营业收入。"


def test_yoy_ranking_answer_uses_rate_list_and_percentage_point_gap():
    answered = generate_yoy_ranking_answer_node(
        {
            "analysis_result": {
                "metric_name": "营业收入",
                "report_year": 2024,
                "previous_year": 2023,
                "report_period": "FY",
                "rank_direction": "desc",
                "limit": 2,
                "row_count": 2,
                "is_empty": False,
                "rows": [
                    {
                        "rank": 1,
                        "company_name": "A公司",
                        "display_yoy_rate": "35.20%",
                        "display_current_value": "135.20 亿元",
                        "display_previous_value": "100.00 亿元",
                    },
                    {
                        "rank": 2,
                        "company_name": "B公司",
                        "display_yoy_rate": "28.10%",
                        "display_current_value": "128.10 亿元",
                        "display_previous_value": "100.00 亿元",
                    },
                ],
                "result_summary": {
                    "first_company_name": "A公司",
                    "second_company_name": "B公司",
                    "first_rank_label": "同比增速最高",
                    "first_rate_display": "35.20%",
                    "topn_count": 2,
                    "average_label": "平均同比增速",
                    "average_rate_display": "31.65%",
                    "gap_compare_word": "高",
                    "gap_percentage_points": "7.10",
                    "positive_count": 2,
                    "negative_count": 0,
                },
            }
        }
    )

    paragraphs = answered["final_answer"].split("\n\n")
    assert paragraphs[0] == "2024 年营业收入同比增速排名前 2 的公司如下："
    assert "1. A公司：同比增长 35.20%，2024 年营业收入为 135.20 亿元，2023 年为 100.00 亿元" in paragraphs[1]
    assert "前 2 家公司的平均同比增速为 31.65%" in paragraphs[2]
    assert "A公司比第二名B公司高 7.10 个百分点" in paragraphs[2]


def test_trend_ranking_answer_uses_growth_rate_summary():
    answered = generate_trend_ranking_answer_node(
        {
            "analysis_result": {
                "metric_name": "营业收入",
                "start_year": 2022,
                "end_year": 2024,
                "report_period": "FY",
                "rank_direction": "desc",
                "limit": 2,
                "row_count": 2,
                "is_empty": False,
                "rows": [
                    {
                        "rank": 1,
                        "company_name": "A公司",
                        "display_growth_rate": "50.00%",
                        "display_start_value": "100.00 亿元",
                        "display_end_value": "150.00 亿元",
                    },
                    {
                        "rank": 2,
                        "company_name": "B公司",
                        "display_growth_rate": "42.30%",
                        "display_start_value": "100.00 亿元",
                        "display_end_value": "142.30 亿元",
                    },
                ],
                "result_summary": {
                    "first_company_name": "A公司",
                    "second_company_name": "B公司",
                    "first_rank_label": "区间增长率最高",
                    "first_rate_display": "50.00%",
                    "topn_count": 2,
                    "average_label": "平均区间增长率",
                    "average_rate_display": "46.15%",
                    "gap_compare_word": "高",
                    "gap_percentage_points": "7.70",
                    "positive_count": 2,
                    "negative_count": 0,
                },
            }
        }
    )

    paragraphs = answered["final_answer"].split("\n\n")
    assert paragraphs[0] == "2022 到 2024 年营业收入增长率排名前 2 的公司如下："
    assert "1. A公司：增长率 50.00%" in paragraphs[1]
    assert "前 2 家公司的平均区间增长率为 46.15%" in paragraphs[2]
    assert "A公司比第二名B公司高 7.70 个百分点" in paragraphs[2]


def test_rank_position_answer_uses_position_percentile_formula_order():
    answered = generate_rank_position_answer_node(
        {
            "analysis_result": {
                "analysis_type": "rank_position",
                "company_name": "华润三九",
                "metric_name": "净利率",
                "metric_type": "derived",
                "report_year": 2024,
                "rank_direction": "desc",
                "display_value": "23.56%",
                "rank_no": 3,
                "total_count": 42,
                "is_empty": False,
                "result_summary": {
                    "company_name": "华润三九",
                    "percentile_bucket": 10,
                    "position_zone": "前 25%",
                },
                "formula_text": "净利率 = 净利润 / 营业收入",
            }
        }
    )

    paragraphs = answered["final_answer"].split("\n\n")
    assert paragraphs[0] == "华润三九 2024 年净利率为 23.56%，从高到低排名第 3 / 42。"
    assert paragraphs[1] == "按名次位置看，华润三九处于前 10% 区间，属于前 25%。"
    assert paragraphs[2] == "口径：净利率 = 净利润 / 营业收入。"
