# 展示案例

## 说明

本文档用于面试和 GitHub 展示，重点展示 Agent 的能力边界和工程链路，不覆盖全部测试用例。

金额统一按“亿元”四舍五入展示。不同本地数据库、模型配置或重新跑 PDF 抽取后，具体数值和补充解读文本可能变化。

每个案例都可以配合 `scripts/agent_demo_cli.py --trace` 展示中间状态，例如 intent、公司标准化、指标映射、SQL Guard 和最终回答。

## Demo 01：单公司单指标查询

用户问题：
`华润三九 2024 年营业收入是多少？`

预期意图：
`single_metric_query`

关键槽位：
公司=`华润三九`；指标=`营业收入`；年份=`2024`；报告期=`FY`

预期行为：
解析公司和指标，生成单点查询 SQL，只读执行后返回 2024 年营业收入。

实际结果：
```text
[route] new_query
[intent] single_metric_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue FROM c...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

- 营业收入：276.17 亿元
```

展示重点：
基础 point query 链路：`QueryPlan -> resolve_company -> map_metric -> generate_point_sql -> SQL Guard -> answer`。

## Demo 02：多指标查询

用户问题：
`华润三九 2024 年营业收入和净利润分别是多少？`

预期意图：
`multi_metric_query`

关键槽位：
公司=`华润三九`；指标=`营业收入`、`净利润`；年份=`2024`；报告期=`FY`

预期行为：
一次查询中映射多个指标，并返回多个财务字段。

实际结果：
```text
[route] new_query
[intent] multi_metric_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue, i.net...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

- 营业收入：276.17 亿元
- 净利润：37.78 亿元
```

展示重点：
同一家公司、同一年度下的多指标映射和 SQL 字段选择。

## Demo 03：趋势查询

用户问题：
`华润三九近三年营业收入趋势如何？`

预期意图：
`trend_query`

关键槽位：
公司=`华润三九`；指标=`营业收入`；时间范围=`近三年`；报告期=`FY`

预期行为：
解析近三年时间范围，查询多年度营业收入，并生成趋势回答。

实际结果：
```text
[route] new_query
[intent] trend_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue FROM c...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 年报中营业收入整体呈上升趋势。

营业收入：
年度数据：
  - 2022 年：41.94 亿元
  - 2023 年：247.39 亿元
  - 2024 年：276.17 亿元
首末变化：
  - 2022 年到 2024 年增加 234.22 亿元
  - 累计变化率：+558.42%

补充解读：
营业收入连续三年增长，但2022→2023年增幅（约490%）远高于2023→2024年增幅（约11.6%），呈现先陡后缓的上升形态。
趋势仅基于2022-2024年数据，无法判断中长期走势或增速变化的持续性，亦不能排除因数据口径或报告期调整带来的影响。

可继续分析：
可查询2019-2021年营业收入观察更长期趋势，或对比同期净利润、净利率等结果性指标。
```

展示重点：
时间范围归一化、趋势 SQL、分析节点，而不是只查单年数值。

## Demo 04：同比查询

用户问题：
`华润三九 2024 年净利润同比增长多少？`

预期意图：
`yoy_query`

关键槽位：
公司=`华润三九`；指标=`净利润`；年份=`2024`；报告期=`FY`

预期行为：
查询 2024 年和 2023 年净利润，计算同比变化并回答。

实际结果：
```text
[route] new_query
[intent] yoy_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.net_profit AS income_sheet__net_profit FROM company_dim c LEFT JOIN inc...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

净利润为 37.78 亿元，2023 年为 31.73 亿元，同比增加 6.04 亿元，同比增速为 19.04%。

补充解读：
同比分析仅基于相邻两个完整财年，未考虑更早年份波动或周期性因素；该增速可能受一次性项目影响，但输入数据未提供相关拆分信息。

可继续分析：
建议查看华润三九近三年（2022-2024）净利润同比趋势，或并列对比营业收入、净利率的同期变化。

```

展示重点：
同比查询需要当前年和上一年数据，不能只查单行。

## Demo 05：派生指标单点查询

用户问题：
`华润三九 2024 年净利率是多少？`

预期意图：
`derived_metric_query`

关键槽位：
公司=`华润三九`；派生指标=`净利率`；年份=`2024`；报告期=`FY`

预期行为：
从指标字典读取公式：`净利润 / 营业收入`，查询基础字段后计算净利率。

实际结果：
```text
[route] new_query
[intent] yoy_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.net_profit AS income_sheet__net_profit FROM company_dim c LEFT JOIN inc...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

净利润为 37.78 亿元，2023 年为 31.73 亿元，同比增加 6.04 亿元，同比增速为 19.04%。

补充解读：
同比分析仅基于相邻两个完整财年，未考虑更早年份波动或周期性因素；该增速可能受一次性项目影响，但输入数据未提供相关拆分信息。

可继续分析：
建议查看华润三九近三年（2022-2024）净利润同比趋势，或并列对比营业收入、净利率的同期变化。

用户：华润三九 2024 年净利率是多少？
[route] new_query
[intent] derived_metric_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.net_profit AS income_sheet__net_profit, i.total_operating_revenue AS in...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

净利率：13.68%（计算口径：净利润 / 营业收入 × 100%）

补充解读：
净利率衡量每元营业收入转化为净利润的效率，13.68%表示2024年每100元收入可获得约13.68元净利润。该指标受成本、费用、税率等多因素综合影响，单期数据无法判断盈利质量或变动方向。
```

展示重点：
派生指标不是 LLM 临时编公式，而是来自 `data/metric_dictionary.json` 的固定公式。

## Demo 06：派生指标趋势查询

用户问题：
`华润三九近三年净利率趋势如何？`

预期意图：
`trend_query`

关键槽位：
公司=`华润三九`；派生指标=`净利率`；时间范围=`近三年`；报告期=`FY`

预期行为：
按年度查询净利润和营业收入，逐年计算净利率并生成趋势分析。

实际结果：
```text
[route] new_query
[intent] trend_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year, 'FY' AS report_period, i.net_profit AS numerator_value, i.total_operating_revenue AS denominator_value FROM com...
[answer] 华润三九医药股份有限公司 2022–2024 年净利率整体呈波动下降趋势，从 2022 年的 59.53% 变化至 2024 年的 13.68%，累计下降 45.85 个百分点。
各年结果为：2022 年 59.53%，2023 年 12.83%，2024 年 13.68%。
计算口径为：净利润 / 营业收入 × 100%。

补充解读：
净利率为净利润/营业收入，其波动趋势仅反映两者相对变化的结果，无法判断是净利润还是营业收入主导变化，也不代表盈利质量或持续性。

可继续分析：
建议查看同期的净利润和营业收入各自逐年趋势，或对比毛利率、营业利润率等结果性指标以多角度观察盈利结构。
```

展示重点：
派生指标趋势会走 `generate_derived_trend_sql` 和派生趋势分析链路。

## Demo 07：派生指标同比查询

用户问题：
`华润三九 2024 年净利率同比变化多少？`

预期意图：
`yoy_query`

关键槽位：
公司=`华润三九`；派生指标=`净利率`；年份=`2024`；报告期=`FY`

预期行为：
查询 2024 年和 2023 年净利率依赖的基础字段，计算两年派生指标及同比变化。

实际结果：
```text
[route] new_query
[intent] yoy_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, y.report_year, 'FY' AS report_period, i.net_profit AS numerator_value, i.total_operating_revenue AS denominator_value FROM com...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

净利率为 13.68%，2023 年为 12.83%，较上年上升 0.85 个百分点。

计算口径：
- 净利率 = 净利润 / 营业收入 × 100%（净利润 / 营业收入 × 100%，反映企业盈利能力）

补充解读：
同比仅基于相邻两个报告期，不能判断中长期趋势、持续性或变化原因。

可继续分析：
建议查看近三至四年华润三九净利率趋势，或对比净利润、营业收入同比变化。
```

展示重点：
派生同比不是直接查一个字段，而是先计算派生指标，再比较年度变化。

## Demo 08：公司横向对比

用户问题：
`华润三九和云南白药 2024 年谁的营业收入更高？`

预期意图：
`company_compare_query`

关键槽位：
公司=`华润三九`、`云南白药`；指标=`营业收入`；年份=`2024`；比较方向=`更高`

预期行为：
标准化两家公司，查询同一年同一指标，比较大小并生成结论。

实际结果：
```text
[route] new_query
[intent] company_compare_query
[company] 华润三九 -> 华润三九医药股份有限公司；云南白药 -> 云南白药集团股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year, 'FY' AS report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue FROM company_dim c LE...
[answer] 2024 年营业收入更高的是云南白药集团股份有限公司，为400.33 亿元。

补充解读：
营业收入属于规模指标，当前对比只反映收入规模差异，不代表经营质量。
该结论仅基于当前年份、报告期和指标口径，不能扩展为原因解释。
```

展示重点：
多公司解析、对比 SQL、对比分析，不是分别回答两个单点查询。

## Demo 09：公司趋势对比

用户问题：
`华润三九和云南白药近三年营业收入谁增长更快？`

预期意图：
`company_compare_trend_query`

关键槽位：
公司=`华润三九`、`云南白药`；指标=`营业收入`；时间范围=`近三年`；比较目标=`增长更快`

预期行为：
查询两家公司多年度营业收入，比较趋势和增长表现。

实际结果：
```text
[route] new_query
[intent] company_compare_trend_query
[company] 华润三九 -> 华润三九医药股份有限公司；云南白药 -> 云南白药集团股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, y.report_year, 'FY' AS report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue FROM company_dim c CR...
[answer] 你未指定年份，我将默认以最新年报（2024 年）为终点进行趋势对比。

2022 到 2024 年营业收入增长更快的是华润三九医药股份有限公司。

年度数据：
- 华润三九医药股份有限公司：
  - 2022 年：41.94 亿元
  - 2023 年：247.39 亿元
  - 2024 年：276.17 亿元
  - 2022 到 2024 年增加 234.22 亿元
- 云南白药集团股份有限公司：
  - 2022 年：364.88 亿元
  - 2023 年：391.11 亿元
  - 2024 年：400.33 亿元
  - 2022 到 2024 年增加 35.45 亿元

补充解读：
仅基于2022-2024年三个报告期的绝对增长额，未考虑各年基数差异；增长量包含收购、业务调整等影响，但本数据不提供具体构成原因。

可继续分析：
建议查看两家公司2022-2024年营业收入同比增速对比，或进一步对比净利润、净利率等盈利效率指标。
```

展示重点：
多公司、多年度、同指标的趋势对比链路。

## Demo 10：公司同比对比

用户问题：
`华润三九和云南白药 2024 年谁的净利润同比增速更高？`

预期意图：
`company_compare_yoy_query`

关键槽位：
公司=`华润三九`、`云南白药`；指标=`净利润`；年份=`2024`；比较目标=`同比增速更高`

预期行为：
分别查询两家公司 2024 年和 2023 年净利润，计算同比增速并比较。

实际结果：
```text
[route] new_query
[intent] company_compare_yoy_query
[company] 华润三九 -> 华润三九医药股份有限公司；云南白药 -> 云南白药集团股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, y.report_year, 'FY' AS report_period, i.stock_code AS income_sheet__record_exists, i.net_profit AS income_sheet__net_profit FR...
[answer] 2024 年净利润同比增速更高的是华润三九医药股份有限公司。

同比数据：
- 华润三九医药股份有限公司：2023 年 31.73 亿元，2024 年 37.78 亿元，同比增长 19.04%
- 云南白药集团股份有限公司：2023 年 40.94 亿元，2024 年 47.67 亿元，同比增长 16.45%
- 差值：华润三九医药股份有限公司同比增速高出 2.59 个百分点

补充解读：
净利润同比增速对比反映两家公司当期盈利增长相对表现，但增速高低受基数影响，且仅基于2023-2024两个报告期，无法判断增长持续性或趋势。
此比较仅针对2023年与2024年净利润同比增速，不涵盖更长时间序列或利润质量（如扣非净利润、现金流匹配）差异；规模基数不同可能导致增速可比性受限。

可继续分析：
可查看近3-4年净利润同比趋势，或对比营业收入同比增速、净利率变化等指标作进一步分析。
```

展示重点：
公司对比和同比计算组合在一起，不是简单比较 2024 年绝对值。

## Demo 11：排名查询

用户问题：
`2024 年营业收入最高的前 10 家公司是谁？`

预期意图：
`ranking_query`

关键槽位：
指标=`营业收入`；年份=`2024`；排序方向=`desc`；数量=`10`；报告期=`FY`

预期行为：
生成受控排名 SQL，按营业收入降序返回前 10 家公司。

实际结果：
```text
2024 年营业收入排名前 10 的公司如下：

1. 广州白云山医药集团股份有限公司：749.93 亿元
2. 云南白药集团股份有限公司：400.33 亿元
3. 华润三九医药股份有限公司：276.17 亿元
4. 北京同仁堂股份有限公司：185.97 亿元
5. 漳州片仔癀药业股份有限公司：100.58 亿元
6. 天士力医药集团股份有限公司：86.74 亿元
7. 瑞康医药集团股份有限公司：80.34 亿元
8. 浙江康恩贝制药股份有限公司：65.15 亿元
9. 石家庄以岭药业股份有限公司：65.13 亿元
10. 贵州信邦制药股份有限公司：60.32 亿元

其中，广州白云山医药集团股份有限公司排名第一，营业收入为749.93 亿元；前 10 家公司的平均营业收入为207.07 亿元。
广州白云山医药集团股份有限公司比第二名云南白药集团股份有限公司高349.60 亿元，约高87.33%。

补充解读：
排名仅覆盖当前数据库中该年份、报告期和指标非空的公司样本。

可继续分析：
可进一步查询这些公司2024年的净利润或净利率排名，对比盈利规模与效率的差异。
```

展示重点：
排名查询不需要指定公司，但必须有指标、年份、排序方向和 limit；SQL Guard 会限制无界排序。

## Demo 12：指定公司排名位置

用户问题：
`华润三九 2024 年营业收入排第几？`

预期意图：
`rank_position_query`

关键槽位：
公司=`华润三九`；指标=`营业收入`；年份=`2024`；报告期=`FY`

预期行为：
在全市场范围内计算营业收入排名，并返回华润三九的位置。

实际结果：
```text
[route] new_query
[intent] rank_position_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] WITH ranked AS ( SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year, i.report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue, RANK() OV...
[answer] 华润三九 2024 年营业收入为 276.17 亿元，从高到低排名第 3 / 49。

按名次位置看，华润三九位于前 10% 区间。

补充解读：
排名仅覆盖当前数据库中该年份、报告期和指标非空的公司样本。
```

展示重点：
不是 TopN 列表，而是指定公司在整体排名中的位置。

## Demo 13：缺槽位澄清

用户问题：
`2024 年营业收入是多少？`

预期意图：
`single_metric_query`

关键槽位：
指标=`营业收入`；年份=`2024`；缺失公司

预期行为：
不生成 SQL，不执行查询；进入澄清，询问用户要查询哪家公司。

实际结果：
```text
[route] new_query
[intent] unknown
[time] 2024 FY
[sql_guard] skipped
[error] clarification_required
[answer] 用户未指定公司
```

展示重点：
槽位校验优先于 SQL 生成，缺必要信息时不会让 LLM 猜公司。

## Demo 14：成功查询后的续问

用户问题：
第一轮：`华润三九 2024 年营业收入是多少？`

第二轮：`那净利润呢？`

预期意图：
第一轮=`single_metric_query`；第二轮=`contextual_followup` 后仍合并为单指标查询

关键槽位：
第一轮公司=`华润三九`；指标=`营业收入`；年份=`2024`

第二轮继承公司和年份，仅替换指标为 `净利润`

预期行为：
第一轮成功后保存 `last_successful_query_plan`；第二轮抽取 `slot_patch={"metric_mentions":["净利润"]}`，合并后重新标准化、重新生成 SQL、重新过 SQL Guard。

实际结果：
第一轮：

```text
[route] new_query
[intent] single_metric_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue FROM c...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

- 营业收入：276.17 亿元
```

第二轮：
```text
[route] contextual_followup
[intent] single_metric_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.net_profit AS income_sheet__net_profit FROM company_dim c LEFT JOIN inc...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

- 净利润：37.78 亿元
```

展示重点：
多轮上下文不是复用旧 SQL，而是复用 QueryPlan 并局部替换槽位。

## Demo 15：意图变更澄清

用户问题：
第一轮：`华润三九 2024 年营业收入是多少？`

第二轮：`那排名呢？`

预期意图：
第一轮=`single_metric_query`；第二轮=`contextual_followup`，但触发排名意图变更澄清

关键槽位：
已知公司=`华润三九`；指标=`营业收入`；年份=`2024`

排名查询仍缺排名范围、排序方向或 TopN 参数

预期行为：
第二轮不直接执行 SQL；系统保存新的 `pending_query_plan`，继续追问排名参数，例如“你想看前几名，还是这家公司排第几？”

实际结果：
第一轮：

```text
[route] new_query
[intent] single_metric_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year AS report_year, 'FY' AS report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue FROM c...
[answer] 根据数据库查询结果，华润三九医药股份有限公司 2024 年年报中：

- 营业收入：276.17 亿元
```

第二轮：
```text
[route] contextual_followup
[intent] unknown
[sql_guard] skipped
[error] clarification_required
[answer] 当前暂不支持该查询：排名续问存在指定公司排名位置和全市场排名列表两种解释。。请调整问题后重试。
```

展示重点：
多轮上下文能识别 intent transition，但信息不足时必须澄清，不能猜测执行。

## Demo 16：指标歧义澄清

用户问题：
`华润三九 2024 年现金流是多少？`

预期意图：
`single_metric_query`

关键槽位：
公司=`华润三九`；年份=`2024`；指标表达=`现金流` 存在歧义

预期行为：
不直接映射到某一个现金流字段；进入澄清，询问是经营活动现金流、投资活动现金流还是筹资活动现金流。

实际结果：
```text
[route] new_query
[intent] single_metric_query
[company] 华润三九 -> 华润三九医药股份有限公司
[time] 2024 FY
[sql_guard] skipped
[error] clarification_required
[answer] 请说明要查询的财务指标，例如营业收入、净利润、总资产或净利率。
```

展示重点：
指标映射有歧义保护，不会把宽泛指标强行猜成某个数据库字段。
