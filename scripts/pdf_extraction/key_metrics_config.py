"""关键指标字段映射配置。"""

KEY_METRICS = {
    "balance_sheet": {
        "asset_total_assets": {"source_field": "asset_total_assets", "metric_type": "extracted_metric"},
        "liability_total_liabilities": {"source_field": "liability_total_liabilities", "metric_type": "extracted_metric"},
        "equity_total_equity": {"source_field": "equity_total_equity", "metric_type": "extracted_metric"},
        "liability_and_equity_total": {"source_field": "liability_and_equity_total", "metric_type": "extracted_metric"},
        "asset_cash_and_cash_equivalents": {"source_field": "asset_cash_and_cash_equivalents", "metric_type": "extracted_metric"},
        "asset_total_current_assets": {"source_field": None, "metric_type": "add_column_required"},
        "liability_total_current_liabilities": {"source_field": None, "metric_type": "add_column_required"},
    },
    "income_sheet": {
        "total_operating_revenue": {"source_field": "total_operating_revenue", "metric_type": "extracted_metric"},
        "operating_cost": {"source_field": "operating_expense_cost_of_sales", "metric_type": "extracted_metric"},
        "operating_profit": {"source_field": "operating_profit", "metric_type": "extracted_metric"},
        "total_profit": {"source_field": "total_profit", "metric_type": "extracted_metric"},
        "net_profit": {"source_field": "net_profit", "metric_type": "extracted_metric"},
        "net_profit_parent_company": {"source_field": None, "metric_type": "not_supported_in_v1"},
    },
    "cash_flow_sheet": {
        "operating_cf_net_amount": {"source_field": "operating_cf_net_amount", "metric_type": "extracted_metric"},
        "investing_cf_net_amount": {"source_field": "investing_cf_net_amount", "metric_type": "extracted_metric"},
        "financing_cf_net_amount": {"source_field": "financing_cf_net_amount", "metric_type": "extracted_metric"},
        "net_cash_flow": {"source_field": "net_cash_flow", "metric_type": "extracted_metric"},
        "cash_and_cash_equivalents_end": {"source_field": None, "metric_type": "not_supported_in_v1"},
        "exchange_rate_effect": {"source_field": None, "metric_type": "add_column_required"},
    },
}

V1_FILL_RATE_METRIC_TYPES = {"extracted_metric", "derived_metric"}
