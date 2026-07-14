"""FlexibleSQLSpec 的 QuerySpec 编译测试。"""
from agent.schemas.flexible_sql_spec import flexible_sql_spec_from_query_spec


def test_flexible_sql_spec_compiles_query_spec() -> None:
    spec = flexible_sql_spec_from_query_spec(
        {"metrics": ["营业收入"], "filters": [{"metric": "营业收入", "operator": ">", "value": 1}], "sort": [{"metric": "营业收入", "direction": "desc"}], "time_scope": {"year": 2024, "period": "FY"}, "limit": 10},
        [{"table": "income_sheet", "field": "total_operating_revenue"}], ["company_dim", "income_sheet"],
    )
    assert spec["question"] == ""
    assert spec["filters"][0]["metric"] == "营业收入"
    assert spec["limit"] == 10
