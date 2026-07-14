# V0.5.3：yoy_ranking_query 同比排名

## 1. 版本目标

新增同比排名能力，支持这类问题：

```
2024 年营业收入同比增速最高的前 10 家公司
2024 年净利润同比增长最快的前 5 家公司
2024 年总资产同比增速最低的前 10 家公司
2024 年净利润同比下降最大的前 5 家公司
```

核心语义：

```
按某一年相对上一年的同比变化率排序。
```

也就是：

```
yoy_rate = (current_value - previous_value) / previous_value
```

## 2. 建议新增 intent

不要塞进 `ranking_query`。

新增：

```
intent_type = "yoy_ranking_query"
```

原因：

| intent                | 排序对象                 |
| --------------------- | ------------------------ |
| `ranking_query`       | 单年指标值               |
| `yoy_ranking_query`   | 当年相对上年的同比变化率 |
| `trend_ranking_query` | 区间起止年份变化率       |

## 4. QueryPlan 设计

### 4.1 新增字段

如果现有字段已足够，可以复用：

```
rank_direction: "asc" | "desc"
limit: int
report_year: int
metric_mentions: list[str]
```

建议新增一个字段，用于区分排序口径：

```
ranking_basis: "yoy_rate"
```

或者更通用：

```
change_metric: "yoy_rate"
```

V0.5.3 推荐：

```
change_metric = "yoy_rate"
```

这样 V0.5.4 可以继续复用：

```
change_metric = "growth_rate"
```

### 4.2 QueryPlan 示例

```
{
  "intent_type": "yoy_ranking_query",
  "company_mentions": [],
  "metric_mentions": ["营业收入"],
  "time_mode": "single_year",
  "report_year": 2024,
  "report_period": "annual",
  "rank_direction": "desc",
  "limit": 10,
  "change_metric": "yoy_rate"
}
```

## 5. Planner 规则

修改：

```
agent/prompts/query_planner.md
```

新增规则：

```
当用户要求“同比增速最高 / 同比增长最快 / 同比下降最大 / 同比降幅最大 / 同比增速最低”的公司排名时，识别为 yoy_ranking_query。
```

方向规则：

| 用户表达     | rank_direction |
| ------------ | -------------- |
| 同比增速最高 | desc           |
| 同比增长最快 | desc           |
| 同比增幅最大 | desc           |
| 同比增速最低 | asc            |
| 同比下降最大 | asc            |
| 同比降幅最大 | asc            |
| 同比下降最快 | asc            |

注意边界：

| 用户问题                                  | intent              |
| ----------------------------------------- | ------------------- |
| 2024 年营业收入同比是多少                 | `yoy_query`         |
| 华润三九 2024 年营业收入同比是多少        | `yoy_query`         |
| 2024 年营业收入同比增速最高的前 10 家公司 | `yoy_ranking_query` |
| 2024 年营业收入最高的前 10 家公司         | `ranking_query`     |

## 6. 新增文件

建议新增独立链路，不要塞进已有 ranking 文件。

## 7. slot validator 设计

新增：

```
yoy_ranking_validator.py
```

校验条件：

```
1. intent_type = yoy_ranking_query
2. companies 必须为空
3. metrics 必须有且只有一个
4. report_year 必须存在
5. time_mode 必须是 single_year
6. rank_direction 必须是 asc / desc
7. limit 必须存在，且 1 <= limit <= 50
8. V0.5.3 第一版只允许 base 指标
```

错误类型建议：

```
missing_metric
multiple_metrics_not_supported
scoped_company_yoy_ranking_not_supported
missing_year
unsupported_yoy_ranking_time_mode
missing_rank_direction
missing_limit
invalid_limit
derived_yoy_ranking_not_supported_v053
```

## 8. SQL 生成设计

新增：

```
agent/nodes/sql_nodes/yoy_ranking_sql.py
```

核心函数：

```
generate_yoy_ranking_sql_node
build_base_yoy_ranking_sql
```

SQL 模板：

```
SELECT
    c.company_code,
    c.company_name,
    curr.report_year,
    curr.report_period,
    curr.<metric_field> AS current_value,
    prev.<metric_field> AS previous_value,
    (
        CAST(curr.<metric_field> AS DOUBLE)
        - CAST(prev.<metric_field> AS DOUBLE)
    ) / NULLIF(CAST(prev.<metric_field> AS DOUBLE), 0) AS yoy_rate
FROM <metric_table> curr
JOIN <metric_table> prev
    ON curr.company_id = prev.company_id
   AND curr.report_year = prev.report_year + 1
   AND curr.report_period = prev.report_period
JOIN company_dim c
    ON curr.company_id = c.company_id
WHERE curr.report_year = ?
  AND curr.report_period = ?
  AND curr.<metric_field> IS NOT NULL
  AND prev.<metric_field> IS NOT NULL
  AND prev.<metric_field> != 0
ORDER BY yoy_rate DESC, c.company_code ASC
LIMIT ?
```

当 `rank_direction = "asc"`：

```
ORDER BY yoy_rate ASC, c.company_code ASC
```

注意：

```
SQL 中 metric 字段只能来自 metric mapping。
ORDER BY 方向只能由 asc / desc 枚举映射。
limit 必须经过 validator 校验，并在 SQL 生成层二次防御。
```

## 9. analyze 设计

新增：

```
agent/nodes/analyze_nodes/yoy_ranking_analysis.py
```

输出结构建议：

```
analysis_result = {
    "analysis_type": "yoy_ranking",
    "metric_name": "营业收入",
    "metric_type": "base",
    "report_year": 2024,
    "previous_year": 2023,
    "report_period": "annual",
    "rank_direction": "desc",
    "limit": 10,
    "change_metric": "yoy_rate",
    "row_count": 10,
    "is_empty": False,
    "rows": [
        {
            "rank": 1,
            "company_code": "...",
            "company_name": "...",
            "current_value": 123.0,
            "previous_value": 100.0,
            "yoy_rate": 0.23,
            "display_yoy_rate": "23.00%",
            "display_current_value": "...",
            "display_previous_value": "..."
        }
    ]
}
```

------

## 10. answer 设计

新增：

```
agent/nodes/answer_nodes/yoy_ranking_answer.py
```

回答模板：

### 同比增长最高 TopN

```
2024 年营业收入同比增速排名前 10 的公司如下：

1. A 公司：同比增长 23.00%，2024 年营业收入为 xxx，2023 年为 xxx
2. B 公司：同比增长 18.50%，2024 年营业收入为 xxx，2023 年为 xxx
...
```

### 同比下降最大 TopN

```
2024 年净利润同比下降最大的前 5 家公司如下：

1. A 公司：同比变化 -35.20%，2024 年净利润为 xxx，2023 年为 xxx
2. B 公司：同比变化 -28.10%，2024 年净利润为 xxx，2023 年为 xxx
...
```

### 空结果

```
未查询到满足条件的数据。查询条件：2024 年，年度报告，指标为营业收入，同比变化率排序，返回数量为 10。
```

## 11. SQL Guard 检查

确认 SQL Guard 支持：

```
JOIN 同一张表两次
CAST
NULLIF
表达式字段 yoy_rate
ORDER BY yoy_rate
LIMIT
```

同时继续限制：

```
SELECT only
白名单表
必须有 curr.report_year 条件
必须有 report_period 条件
必须有 ORDER BY
必须有 LIMIT
LIMIT <= 50
禁止多语句
禁止 DDL / DML
```

------

## 12. V0.5.3 验收用例

### 必过

```
1. 2024 年营业收入同比增速最高的前 10 家公司
2. 2024 年净利润同比增长最快的前 5 家公司
3. 2024 年总资产同比增速最低的前 10 家公司
4. 2024 年净利润同比下降最大的前 5 家公司
```

### 必拦截

```
1. 2024 年营业收入同比增速最高的公司有哪些
   → 如果没有 limit，也没有 limit=1 语义，则 missing_limit

2. 华润三九 2024 年营业收入同比增速排名
   → scoped_company_yoy_ranking_not_supported

3. 2024 年净利率同比增速最高的前 10 家公司
   → V0.5.3 第一版可返回 derived_yoy_ranking_not_supported_v053

4. 近三年营业收入增长最快的前 10 家公司
   → 不进入 yoy_ranking_query，留给 trend_ranking_query
```
