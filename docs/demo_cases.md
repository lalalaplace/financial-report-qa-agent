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
该同比增速仅反映2023年至2024年两个相邻完整财年的变化，无法判断该增速是否代表长期趋势或具有可持续性。
同比分析仅基于相邻两个报告期的数据，不包含对中期或长期趋势的判断，也不涉及增速背后的驱动因素。

可继续分析：
建议查看华润三九近三至四年的净利润及同比增速趋势，或并列对比同期的营业收入、净利率等指标。

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
净利率反映每百元营业收入中转化为净利润的比例，该指标受利润表各项目综合影响，但当前结果仅基于2024年单一年份数据，无法判断该水平在历史区间中的位置。
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
同比分析仅基于相邻两个完整会计年度，未考虑更长时间窗口内的波动或周期性因素，不能外推至未来业绩或作为公司盈利质量判断依据。

可继续分析：
建议查看华润三九近3-4年净利率的同比变化趋势，或并列对比同期的营业收入、净利润等指标以观察盈利规模与效率的匹配情况。
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
[answer] 2024 年，华润三九医药股份有限公司为 276.17 亿元，云南白药集团股份有限公司为 400.33 亿元。云南白药集团股份有限公司更高，高出 124.17 亿元。

补充解读：
营业收入反映企业在一定时期内的经营规模，两家公司2024年数据均为全年合计口径，可直接对比规模差异。
该对比仅基于2024年全年营业收入，不反映盈利质量、成本控制或现金流状况，也不代表公司整体价值或市场地位。

可继续分析：
可对比两家公司2024年净利润、净利率或经营活动现金流净额，以多维度观察经营结果。
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

可继续分析：
可对比两家公司近三年（2022-2024）的净利润或净利率趋势，以观察盈利效率的同步变化情况。
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
[answer] 2024 年公司同比对比结果如下：

一、净利润
- 华润三九医药股份有限公司：2023 年 31.73 亿元，2024 年 37.78 亿元，同比 增长 +19.04%
- 云南白药集团股份有限公司：2023 年 40.94 亿元，2024 年 47.67 亿元，同比 增长 +16.45%
结论：华润三九医药股份有限公司 同比增速更高，高出 2.59 个百分点。

补充解读：
当前同比对比仅基于2023年和2024年两个相邻报告期，无法判断增速差异的中长期持续性或趋势稳定性。
同比增速比较仅反映该两期之间的相对变化幅度，不涉及公司经营效率、盈利质量或未来增长潜力。

可继续分析：
建议查看两家公司近三至四年的净利润同比趋势，或并列对比营业收入、净利率等指标。
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
用户：2024 年营业收入最高的前 10 家公司是谁？
[route] new_query
[intent] ranking_query
[time] 2024 FY
[sql_guard] passed
[sql] SELECT c.stock_code, c.stock_abbr, c.company_name, i.report_year, 'FY' AS report_period, i.total_operating_revenue AS income_sheet__total_operating_revenue FROM company_dim c LE...
[answer] 2024 年营业收入排名前 10 的公司如下：

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
可对比这些公司2024年的净利润或净利率排名，以观察规模与盈利能力的差异。
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

可继续分析：
可对比同一样本中排名第1和第2公司的营业收入，或查看华润三九近三年营业收入排名变化趋势。
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
[answer] 你想查询华润三九在该指标中的排名位置，还是查看全市场排名列表？
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

## Demo 17：正式支持的派生指标筛选与排序

用户问题：
`找出 2024 年资产负债率低于 50% 的公司，按资产负债率从低到高取前 10 家。`

预期意图：
`unknown`（由 `QuerySpec.execution_mode=flexible_sql` 决定执行通道）

关键槽位：
指标=`资产负债率`；年份=`2024`；阈值=`50%`；排序=`asc`；数量=`10`

预期行为：
系统从指标字典读取注册公式 `总负债 / 总资产`，生成不可变语义合同；合同将用户阈值 `50%` 归一化为 SQL 事实层使用的 `0.5`。LLM 只负责生成 SQL 写法，不能使用 `NULL AS 资产负债率` 或替换公式依赖字段。

实际结果：
```text
[route] new_query
[intent] unknown
[time] 2024 FY
[sql_guard] passed
[sql] WITH stage_0 AS ( SELECT b.stock_code, b.report_year, b.liability_total_liabilities, b.asset_total_assets, b.liability_total_liabilities / NULLIF(b.asset_total_assets, 0) AS 资产负...
[answer] 查询结果

根据数据库查询结果，符合条件的公司如下。

| stock_code | report_year | 资产负债率 |
| --- | --- | --- |
| 002773 | 2024 | 7.44% |
| 002907 | 2024 | 13.43% |
| 600436 | 2024 | 15.40% |
| 600351 | 2024 | 16.42% |
| 600993 | 2024 | 18.92% |
| 600535 | 2024 | 19.13% |
| 600566 | 2024 | 20.22% |
| 300026 | 2024 | 21.20% |
| 002737 | 2024 | 21.21% |
| 002566 | 2024 | 21.45% |

查询口径：本回答基于已执行查询结果自动生成。

数据说明：表格数据来自结构化查询结果。

补充解读：
该查询展示了2024年资产负债率最低的10家公司，样本范围受限于数据库中所有满足资产负债率<50%的公司，并按升序排列。

```

结果表中 `report_year` 应展示为 `2024`，资产负债率应展示为百分比，例如 `7.44%`，不展示为 `2,024.00` 或小数 `0.0744`。

展示重点：
已注册派生公式、百分比阈值归一化、语义合同和确定性表格格式化。

## Demo 18：正式支持的多条件同比筛选与排序

用户问题：
`找出 2024 年营业收入同比增长超过 5%、净利润同比增长超过 10% 的公司，按净利润同比增速从高到低排序。`

预期意图：
`unknown`（`flexible_sql`）

关键槽位：
指标=`营业收入同比`、`净利润同比`；年份=`2024`；阈值=`5%`、`10%`；排序=`净利润同比 desc`

预期行为：
Planner 一次性将两个百分比阈值写入 QuerySpec；语义合同归一化为 `0.05` 和 `0.1`。SQL 必须同时取 2023、2024 年数据，分别计算两个同比值，在两个条件同时满足后按净利润同比增速排序。

实际结果：

```text
[route] new_query
[intent] unknown
[time] 2024 FY
[sql_guard] passed
[sql] WITH current_year AS ( SELECT stock_code, total_operating_revenue, net_profit FROM income_sheet WHERE report_year = 2024 AND report_period = 'FY' ), previous_year AS ( SELECT st...
[answer] 查询结果

根据数据库查询结果，符合条件的公司如下。

| stock_code | 营业收入 | 净利润 | 营业收入同比增速 | 净利润同比增速 |
| --- | --- | --- | --- | --- |
| 002219 | 37.99 亿元 | 1.15 亿元 | 5.81% | 272.90% |
| 002907 | 7.75 亿元 | 0.77 亿元 | 12.04% | 134.66% |
| 002166 | 17.72 亿元 | 1.67 亿元 | 18.60% | 69.99% |
| 000423 | 59.21 亿元 | 15.57 亿元 | 25.57% | 35.17% |
| 000999 | 276.17 亿元 | 37.78 亿元 | 11.63% | 19.04% |
| 002773 | 44.53 亿元 | 11.91 亿元 | 12.51% | 14.02% |
| 600436 | 100.58 亿元 | 28.51 亿元 | 15.69% | 13.01% |

查询口径：本回答基于已执行查询结果自动生成。

数据说明：表格数据来自结构化查询结果。
```

展示重点：
阈值不会由 SQL Generator 自行解释；若 SQL 使用 `5`、`10` 作为事实层比例，或遗漏任一同比条件，合同校验拒绝执行。

## Demo 19：正式支持的两个 Top N 单次交集

用户问题：
`找出 2024 年营业收入前 20 且净利润前 20 的公司，按净利率从高到低排序。`

预期意图：
`unknown`（`flexible_sql`）

关键槽位：
Top N 1=`营业收入前20`；Top N 2=`净利润前20`；交集键=`stock_code`；最终排序=`净利率 desc`

预期行为：
合同固定四个阶段：

1. `revenue_top20`：按营业收入取前 20。
2. `profit_top20`：按净利润取前 20。
3. `intersection_stage`：以前两阶段的 `stock_code` 取交集。
4. 在交集结果上计算并按净利率排序。

实际结果：

```text
用户：找出 2024 年营业收入前 20 且净利润前 20 的公司，按净利率从高到低排序。
[route] new_query
[intent] unknown
[time] 2024 FY
[sql_guard] passed
[sql] WITH revenue_top20 AS ( SELECT stock_code, report_year, total_operating_revenue, net_profit FROM income_sheet WHERE report_year = 2024 AND report_period = 'FY' AND total_operati...
[answer] 查询结果

根据数据库查询结果，符合条件的公司如下。

| stock_code | report_year | 营业收入 | 净利润 | 净利率 |
| --- | --- | --- | --- | --- |
| 600436 | 2024 | 100.58 亿元 | 28.51 亿元 | 28.35% |
| 002773 | 2024 | 44.53 亿元 | 11.91 亿元 | 26.75% |
| 000423 | 2024 | 59.21 亿元 | 15.57 亿元 | 26.30% |
| 600285 | 2024 | 35.01 亿元 | 7.23 亿元 | 20.64% |
| 002737 | 2024 | 33.77 亿元 | 4.92 亿元 | 14.57% |
| 600993 | 2024 | 31.37 亿元 | 4.52 亿元 | 14.40% |
| 000999 | 2024 | 276.17 亿元 | 37.78 亿元 | 13.68% |
| 000538 | 2024 | 400.33 亿元 | 47.67 亿元 | 11.91% |
| 600535 | 2024 | 86.74 亿元 | 10.17 亿元 | 11.72% |
| 000650 | 2024 | 50.32 亿元 | 5.67 亿元 | 11.27% |
| 600572 | 2024 | 65.15 亿元 | 6.58 亿元 | 10.10% |
| 600085 | 2024 | 185.97 亿元 | 15.26 亿元 | 8.21% |
| 600332 | 2024 | 749.93 亿元 | 30.01 亿元 | 4.00% |

查询口径：本回答基于已执行查询结果自动生成。

数据说明：表格数据来自结构化查询结果。

补充解读：
该查询通过取营业收入和净利润各自前20名公司的交集，筛选出13家在2024年两项指标均排名靠前的公司，并按净利率降序排列。结果展示了这些公司在规模与盈利效率上的综合表现。

可继续分析：
可进一步查询这些公司近3-5年的营业收入、净利润及净利率趋势，或对比其资产负债率、经营活动现金流净额等指标。
```

展示重点：
校验器检查阶段存在性、前序阶段引用、`stock_code` 连接，以及最终排序发生在交集之后；不以匹配某一段固定 SQL 文本实现校验。

## Demo 20：同一正式能力的不同措辞

| 能力 | 可替换问题 | 必须保留的合同约束 |
| --- | --- | --- |
| 多条件同比筛选 | `筛选 2024 年营收同比大于 8% 且净利润同比为正的公司，按营收同比降序排列。` | 两个同比计算、2023/2024 年、`0.08` 与 `0` 阈值、最终排序 |
| 多条件同比筛选 | `2024 年哪些公司营业收入同比超过 15%，同时净利润同比超过 20%？按净利润增速排序。` | 两个归一化百分比阈值和净利润同比排序 |
| Top N 交集 | `2024 年营收排名前 10 和净利润排名前 10 的重合公司有哪些？` | 两个 Top 10 阶段、单次 `stock_code` 交集 |
| Top N 交集 | `取 2024 年净利润前 15 与营业收入前 15 的交集，再按净利率降序。` | 两个 Top 15、交集后计算净利率并排序 |
| 注册派生指标 | `2024 年净利率高于 10% 的公司有哪些？按净利率从高到低取前 10 家。` | `净利润 / 营业收入`、`0.1` 阈值、limit 10 |
| 注册派生指标 | `列出 2024 年资产负债率不超过 40% 的前 20 家公司，按最低优先。` | `总负债 / 总资产`、`0.4` 阈值、升序、limit 20 |

## Demo 21：暂不支持的嵌套 Top N

用户问题：
`先找出 2024 年营业收入前 50 的公司，再从中取净利润前 10 的公司。`

预期行为：
在 SQL 生成前返回 `UNSUPPORTED_FLEXIBLE_SQL`。不调用 SQL Generator，不执行候选 SQL。

实际结果：

```text
用户：先找出 2024 年营业收入前 50 的公司，再从中取净利润前 10 的公司。
[route] new_query
[intent] unknown
[time] 2024 FY
[sql_guard] unknown
[error] UNSUPPORTED_FLEXIBLE_SQL
[answer] 暂不支持该查询：当前仅支持两个独立 Top N 的单次交集，不支持嵌套 Top N。
```

展示重点：
V1 只支持两个独立 Top N 的单次交集，不将“可能运行成功”的嵌套 SQL 当作正确答案。

## Demo 22：暂不支持的自由公式

用户问题：
`找出 2024 年（净利润加经营现金流）除以总资产超过 20% 的公司。`

预期行为：
在 SQL 生成前返回 `UNSUPPORTED_FLEXIBLE_SQL`，因为该公式未在指标字典注册。

实际结果：

```text
用户：找出 2024 年（净利润加经营现金流）除以总资产超过 20% 的公司。
[route] new_query
[intent] unknown
[time] 2024 FY
[sql_guard] unknown
[error] UNSUPPORTED_FLEXIBLE_SQL
[answer] 暂不支持该查询：该派生公式尚未在指标字典中注册。
```

展示重点：
LLM 不能临时创造派生指标公式；正式支持的派生指标必须能追溯到公式 ID 和基础字段依赖。

## Demo 23：暂不支持的多阶段集合运算

用户问题：
`找出营业收入前 20、净利润前 20 且资产负债率最低 20 的共同公司。`

预期行为：
在 SQL 生成前返回 `UNSUPPORTED_FLEXIBLE_SQL`。不执行三集合交集 SQL。

实际结果：

```text
用户：找出2024年营业收入前 20、净利润前 20 且资产负债率最低 20 的共同公司
[route] new_query
[intent] unknown
[time] 2024 FY
[sql_guard] unknown
[error] UNSUPPORTED_FLEXIBLE_SQL
[answer] 暂不支持该查询：当前仅支持两个 Top N 的单次交集，不支持三个集合的交集运算。
```

展示重点：
受控拒绝也是 V1 的正确结果：它防止系统返回可执行但语义漂移的答案。
