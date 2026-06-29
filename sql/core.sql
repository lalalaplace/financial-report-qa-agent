  DROP TABLE IF EXISTS core_performance;

  CREATE TABLE core_performance AS
  WITH file_map AS (
      SELECT
          r.stock_code,
          r.report_year,
          r.report_period,
          MIN(r.file_id) AS file_id,
          MIN(r.company_id) AS company_id
      FROM report_file_index r
      WHERE r.parse_status = 'parsed'
      GROUP BY r.stock_code, r.report_year, r.report_period
  ),
  base AS (
      SELECT
          COALESCE(i.stock_code, b.stock_code, c.stock_code) AS stock_code,
          COALESCE(i.report_year, b.report_year, c.report_year) AS report_year,
          COALESCE(i.report_period, b.report_period, c.report_period) AS report_period,

          COALESCE(i.stock_abbr, b.stock_abbr, c.stock_abbr) AS stock_abbr,
          cd.company_name,

          i.total_operating_revenue,
          i.operating_revenue_yoy_growth,
          i.net_profit,
          i.net_profit_yoy_growth,
          i.operating_expense_cost_of_sales,

          b.equity_total_equity,

          c.operating_cf_net_amount

      FROM income_sheet i
      FULL OUTER JOIN balance_sheet b
          ON i.stock_code = b.stock_code
         AND i.report_year = b.report_year
         AND i.report_period = b.report_period
      FULL OUTER JOIN cash_flow_sheet c
          ON COALESCE(i.stock_code, b.stock_code) = c.stock_code
         AND COALESCE(i.report_year, b.report_year) = c.report_year
         AND COALESCE(i.report_period, b.report_period) = c.report_period
      LEFT JOIN company_dim cd
          ON cd.stock_code = COALESCE(i.stock_code, b.stock_code, c.stock_code)
  )
  SELECT
      fm.file_id,
      fm.company_id,
      b.stock_code,
      b.stock_abbr,
      b.report_year,
      b.report_period,
      CURRENT_TIMESTAMP AS created_at,
      CURRENT_TIMESTAMP AS updated_at,

      ROW_NUMBER() OVER (ORDER BY b.stock_code, b.report_year, b.report_period) AS serial_number,

      /* 当前现有表无法稳定反推的字段，先置空 */
      NULL::numeric(20,4) AS eps,
      NULL::numeric(20,4) AS operating_revenue_qoq_growth,
      ROUND(b.net_profit / 10000.0, 2) AS net_profit_10k_yuan,
      NULL::numeric(20,4) AS net_profit_qoq_growth,
      NULL::numeric(20,4) AS net_asset_per_share,
      NULL::numeric(20,4) AS roe,
      NULL::numeric(20,4) AS operating_cf_per_share,
      NULL::numeric(20,2) AS net_profit_excl_non_recurring,
      NULL::numeric(20,4) AS net_profit_excl_non_recurring_yoy,
      CASE
          WHEN b.total_operating_revenue IS NULL OR b.total_operating_revenue = 0 THEN NULL
          WHEN b.operating_expense_cost_of_sales IS NULL THEN NULL
          ELSE ROUND(
              (b.total_operating_revenue - b.operating_expense_cost_of_sales)
              / b.total_operating_revenue,
              4
          )
      END AS gross_profit_margin,
      CASE
          WHEN b.total_operating_revenue IS NULL OR b.total_operating_revenue = 0 THEN NULL
          WHEN b.net_profit IS NULL THEN NULL
          ELSE ROUND(b.net_profit / b.total_operating_revenue, 4)
      END AS net_profit_margin,
      NULL::numeric(20,4) AS roe_weighted_excl_non_recurring,

      b.total_operating_revenue,
      b.operating_revenue_yoy_growth,
      b.net_profit_yoy_growth

  FROM base b
  LEFT JOIN file_map fm
      ON fm.stock_code = b.stock_code
     AND fm.report_year = b.report_year
     AND fm.report_period = b.report_period;

  ALTER TABLE core_performance
      ADD CONSTRAINT core_performance_pkey PRIMARY KEY (file_id);

  CREATE INDEX core_performance_company_id_idx
      ON core_performance (company_id);

  CREATE INDEX core_performance_report_period_idx
      ON core_performance (report_year, report_period);