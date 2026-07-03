# Agent 测试分组

V0.4.5 起测试按版本和职责分组维护，不再继续把新增用例堆到单个大文件。

## 总入口

```powershell
python scripts\agent\run_v045_test_suite.py
python scripts\agent\run_v05_test_suite.py
```

列出分组：

```powershell
python scripts\agent\run_v045_test_suite.py --list
python scripts\agent\run_v05_test_suite.py --list
```

只运行某个分组：

```powershell
python scripts\agent\run_v045_test_suite.py v043_compare_yoy
python scripts\agent\run_v05_test_suite.py yoy_ranking_tests
```

## 分组说明

- `v03_regression`：V0.3 旧端到端回归，依赖实际 Agent 运行环境；默认不跑，需加 `--include-live`。
- `v040_company_compare`：V0.4.0 单年公司对比。
- `v041_stability`：query type、QueryPlan schema、AgentState 稳定性。
- `v042_compare_trend`：V0.4.2 公司趋势对比。
- `v043_compare_yoy`：V0.4.3 公司同比对比 schema、slot、场景。
- `v044_semantics`：V0.4.4 compare 语义增强。
- `v045_contracts`：V0.4.5 结果结构、error_type、节点职责、日志可观测性。
- `unsupported_clarify`：unsupported 与 clarify 相关边界。

## V0.5 ranking 分组

- `ranking_base_tests`：基础指标 ranking schema、slot、SQL 生成。
- `ranking_derived_tests`：派生指标 ranking SQL、analysis、answer。
- `ranking_stability_tests`：ranking intent 注册一致性和路由稳定性。
- `yoy_ranking_tests`：同比排名。
- `trend_ranking_tests`：区间增长排名。
- `rank_position_tests`：指定公司排名位置。
- `ranking_result_analysis_tests`：ranking 系列结果分析和回答。
- `intent_boundary_tests`：ranking 与 compare、trend、yoy 的 intent 边界。
- `sql_guard_ranking_tests`：ranking 系列 SQL guard。
- `regression_tests`：V0.4.5 合同回归。

## 维护规则

- 新增 V0.4.5 合同类测试，优先放入 `test_v045_*` 文件。
- 新增 V0.5 ranking 能力测试时，同步更新 `run_v05_test_suite.py` 的分组。
- 依赖外部 API、真实数据库或完整 Agent 运行环境的测试，不放入默认分组。
