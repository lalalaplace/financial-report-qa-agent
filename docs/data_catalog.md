# 数据目录

## 结论

当前本地数据库覆盖医药相关上市公司财报结构化数据，核心查询表是 `balance_sheet`、`income_sheet`、`cash_flow_sheet`，Agent 通过 `company_dim`、`company_alias` 和 `data/metric_dictionary.json` 完成公司与指标标准化。

完整公司清单已导出到 [data_catalog_companies.csv](data_catalog_companies.csv)。

## 数据库总体范围

当前数据库包含 14 张 public 表：

| 类型 | 表 |
| --- | --- |
| 公司与文件索引 | `company_dim`、`company_alias`、`report_file_index`、`report_statement_locator` |
| 字段字典与抽取结果 | `attachment3_field_dict`、`attachment3_extract_result`、`attachment3_extract_final`、`attachment3_validation_result` |
| 最终财务表 | `balance_sheet`、`income_sheet`、`cash_flow_sheet`、`core_performance` |
| 追溯与校验 | `final_table_lineage`、`financial_validation_result` |

当前主要统计：

| 项目 | 数量或范围 |
| --- | ---: |
| 公司主表数量 | 71 |
| 公司别名数量 | 387 |
| 财报文件索引数量 | 2540 |
| 财报年份范围 | 2022-2025 |
| `balance_sheet` 行数 | 810 |
| `income_sheet` 行数 | 775 |
| `cash_flow_sheet` 行数 | 799 |

最终表覆盖情况：

| 最终表 | 行数 | 覆盖公司数 | 年份范围 |
| --- | ---: | ---: | --- |
| `balance_sheet` | 810 | 69 | 2022-2025 |
| `income_sheet` | 775 | 69 | 2022-2025 |
| `cash_flow_sheet` | 799 | 69 | 2022-2025 |

说明：

- `company_dim` 是公司主数据，Agent 公司标准化优先解析到这里。
- `company_alias` 保存公司简称、全称和别名，用于支持自然语言中的不同公司叫法。
- `report_file_index` 是 PDF 文件级索引，记录文件、公司、年份和报告期。
- 三张最终财务表是 Agent 当前主要查询对象。
- `final_table_lineage` 用于追溯最终字段来自哪条抽取结果。
- `financial_validation_result` 只记录一致性校验结果，不自动改写最终财务表。

## 公司覆盖范围

当前公司主表覆盖 71 家公司，最终财务表当前覆盖 69 家公司。文档中只列按财报文件数量排序的 Top 20，完整清单见 [data_catalog_companies.csv](data_catalog_companies.csv)。

| 股票代码 | 简称 | 公司全称 | 财报文件数 | 年份范围 |
| --- | --- | --- | ---: | --- |
| `000999` | 华润三九 | 华润三九医药股份有限公司 | 54 | 2022-2025 |
| `600080` | 金花股份 | 金花企业(集团)股份有限公司 | 54 | 2022-2025 |
| `300519` | 新光药业 | 浙江新光药业股份有限公司 | 42 | 2022-2025 |
| `002287` | 奇正藏药 | 西藏奇正藏药股份有限公司 | 40 | 2022-2025 |
| `002864` | 盘龙药业 | 陕西盘龙药业集团股份有限公司 | 40 | 2022-2025 |
| `300181` | 佐力药业 | 浙江佐力药业股份有限公司 | 40 | 2022-2025 |
| `000590` | 启迪药业 | 启迪药业集团股份公司 | 38 | 2022-2025 |
| `002275` | 桂林三金 | 桂林三金药业股份有限公司 | 38 | 2022-2025 |
| `300534` | 陇神戎发 | 甘肃陇神戎发药业股份有限公司 | 38 | 2022-2025 |
| `300878` | 维康药业 | 浙江维康药业股份有限公司 | 38 | 2022-2025 |
| `000766` | 通化金马 | 通化金马药业集团股份有限公司 | 36 | 2022-2025 |
| `000790` | 华神科技 | 成都华神科技集团股份有限公司 | 36 | 2022-2025 |
| `002082` | 万邦德 | 万邦德医药控股集团股份有限公司 | 36 | 2022-2025 |
| `002166` | 莱茵生物 | 桂林莱茵生物科技股份有限公司 | 36 | 2022-2025 |
| `002198` | 嘉应制药 | 广东嘉应制药股份有限公司 | 36 | 2022-2025 |
| `002219` | 新里程 | 新里程健康科技集团股份有限公司 | 36 | 2022-2025 |
| `002317` | 众生药业 | 广东众生药业股份有限公司 | 36 | 2022-2025 |
| `002390` | 信邦制药 | 贵州信邦制药股份有限公司 | 36 | 2022-2025 |
| `002566` | 益盛药业 | 吉林省集安益盛药业股份有限公司 | 36 | 2022-2025 |
| `002603` | 以岭药业 | 石家庄以岭药业股份有限公司 | 36 | 2022-2025 |

完整公司清单字段：

| 字段 | 说明 |
| --- | --- |
| `stock_code` | 股票代码 |
| `stock_abbr` | 股票简称 |
| `company_name` | 公司全称 |
| `report_count` | 当前索引到的财报文件数 |
| `min_report_year` | 最早报告年份 |
| `max_report_year` | 最晚报告年份 |

重新导出完整公司清单可使用以下 SQL：

```sql
SELECT
  c.stock_code,
  c.stock_abbr,
  c.company_name,
  COUNT(r.file_id) AS report_count,
  MIN(r.report_year) AS min_report_year,
  MAX(r.report_year) AS max_report_year
FROM company_dim c
LEFT JOIN report_file_index r ON r.stock_code = c.stock_code
GROUP BY c.stock_code, c.stock_abbr, c.company_name
ORDER BY c.stock_code;
```

## 指标覆盖范围

当前 Agent 指标字典位于 `data/metric_dictionary.json`，共覆盖 20 个可问指标：

| 类型 | 表或来源 | 数量 |
| --- | --- | ---: |
| 基础指标 | `balance_sheet` | 7 |
| 基础指标 | `income_sheet` | 4 |
| 基础指标 | `cash_flow_sheet` | 4 |
| 派生指标 | 基于基础指标公式计算 | 5 |

基础指标：

| 指标 key | 指标名称 | 来源表 | 字段 |
| --- | --- | --- | --- |
| `total_operating_revenue` | 营业收入 | `income_sheet` | `total_operating_revenue` |
| `operating_profit` | 营业利润 | `income_sheet` | `operating_profit` |
| `total_profit` | 利润总额 | `income_sheet` | `total_profit` |
| `net_profit` | 净利润 | `income_sheet` | `net_profit` |
| `asset_total_assets` | 总资产 | `balance_sheet` | `asset_total_assets` |
| `liability_total_liabilities` | 总负债 | `balance_sheet` | `liability_total_liabilities` |
| `equity_total_equity` | 所有者权益合计 | `balance_sheet` | `equity_total_equity` |
| `liability_and_equity_total` | 负债和所有者权益总计 | `balance_sheet` | `liability_and_equity_total` |
| `asset_cash_and_cash_equivalents` | 货币资金 | `balance_sheet` | `asset_cash_and_cash_equivalents` |
| `asset_accounts_receivable` | 应收账款 | `balance_sheet` | `asset_accounts_receivable` |
| `asset_inventory` | 存货 | `balance_sheet` | `asset_inventory` |
| `operating_cf_net_amount` | 经营活动现金流量净额 | `cash_flow_sheet` | `operating_cf_net_amount` |
| `investing_cf_net_amount` | 投资活动现金流量净额 | `cash_flow_sheet` | `investing_cf_net_amount` |
| `financing_cf_net_amount` | 筹资活动现金流量净额 | `cash_flow_sheet` | `financing_cf_net_amount` |
| `net_cash_flow` | 现金及现金等价物净增加额 | `cash_flow_sheet` | `net_cash_flow` |

派生指标：

| 指标 key | 指标名称 | 公式 |
| --- | --- | --- |
| `debt_to_asset_ratio` | 资产负债率 | `liability_total_liabilities / asset_total_assets` |
| `net_profit_margin` | 净利率 | `net_profit / total_operating_revenue` |
| `roe` | 净资产收益率 | `net_profit / equity_total_equity` |
| `roa` | 总资产收益率 | `net_profit / asset_total_assets` |
| `operating_cf_to_net_profit` | 经营现金流净利比 | `operating_cf_net_amount / net_profit` |

当前支持的常见查询能力包括：

- 单公司单指标查询。
- 多指标查询。
- 多年趋势查询。
- 同比查询。
- 公司横向对比。
- 排名和排名位置查询。
- 基于基础指标公式的派生指标查询。

边界说明：

- 指标字典覆盖的是 Agent 可问指标，不等于数据库全部字段。
- 最终财务表中可能还有未暴露给 Agent 的字段。
- 派生指标不直接存表，由 Agent 按固定公式基于基础指标计算。
- 指标覆盖变化时，应先更新 `data/metric_dictionary.json`，再同步更新本数据目录。
