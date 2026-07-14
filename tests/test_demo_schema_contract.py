from pathlib import Path


DEMO_SQL_PATH = Path(__file__).resolve().parents[1] / "demo" / "init_demo_db.sql"


def test_demo_schema_uses_formal_metric_fields_and_fy_period():
    sql = DEMO_SQL_PATH.read_text(encoding="utf-8")

    for field in (
        "total_operating_revenue",
        "net_profit",
        "asset_total_assets",
        "liability_total_liabilities",
        "equity_total_equity",
        "operating_cf_net_amount",
    ):
        assert field in sql

    assert "revenue NUMERIC" not in sql
    assert "'FY'" in sql
