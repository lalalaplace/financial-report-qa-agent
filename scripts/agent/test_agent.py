"""20 条 Agent 测试用例 — 覆盖所有意图类型和边界场景。"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.graph import app

TEST_CASES = [
    # ── 单指标点查 ──
    ("单指标-年报", "华润三九 2024 年总资产是多少"),
    ("单指标-半年报", "万达信息 2024 年半年报营业收入"),
    ("单指标-一季报", "白云山 2024 年一季报净利润"),

    # ── 多指标点查 ──
    ("多指标-3项", "华润三九 2024 年总资产、营业收入和净利润"),
    ("多指标-跨表", "万达信息 2024 年总资产和经营活动现金流量净额"),

    # ── 趋势查询 ──
    ("趋势-近三年", "华润三九近三年营业收入"),
    ("趋势-近五年", "白云山近五年净利润趋势如何"),
    ("趋势-多指标", "华润三九近三年总资产和净利润趋势"),

    # ── 同比查询（存根） ──
    ("同比-增长率", "华润三九 2024 年营收同比增长多少"),

    # ── 排名查询（存根） ──
    ("排名", "哪家公司 2024 年营业收入最高"),

    # ── 公司对比（存根） ──
    ("对比-两家", "对比华润三九和白云山 2024 年的营收"),

    # ── 歧义指标 ──
    ("歧义-现金流", "华润三九 2024 年现金流"),
    ("歧义-利润", "白云山 2024 年利润"),

    # ── 边界场景 ──
    ("无公司", "2024 年营业收入"),
    ("无指标", "华润三九 2024 年"),
    ("模糊问题", "查一下数据"),
    ("无年份-点查", "华润三九总资产是多少"),
    ("跨年区间", "华润三九 2020 到 2024 年总资产变化"),

    # ── 不同报告期 ──
    ("三季报查询", "白云山 2024 年三季报营业收入"),

    # ── 股票代码输入 ──
    ("股票代码", "000999 2024 年营收"),

    # ── 派生指标 ──
    ("派生-资产负债率", "华润三九 2024 年资产负债率是多少"),
    ("派生-净利率", "白云山 2024 年净利率"),
    ("派生-ROE", "华润三九 2024 年 ROE"),
    ("派生-ROA", "万达信息 2024 年总资产收益率"),
    ("派生-经营现金流净利比", "华润三九 2024 年经营现金流净利比"),

    # ── 派生指标-边界场景 ──
    ("派生-缺少年份", "华润三九资产负债率"),
    ("派生-无公司", "2024 年资产负债率"),
    ("派生-指标歧义", "华润三九 2024 年比率"),

    # ── 派生指标趋势 ──
    ("派生趋势-资产负债率", "华润三九近三年资产负债率趋势如何"),
    ("派生趋势-ROE", "华润三九近五年ROE趋势"),
    ("派生趋势-净利率", "白云山 2020 到 2024 年净利率变化"),

    # ── V0.3.4 派生指标趋势-新增用例 ──
    ("T1-资产负债率趋势", "华润三九近五年资产负债率趋势如何"),
    ("T2-净利率趋势(茅台)", "贵州茅台 2020 年到 2024 年净利率变化如何"),
    ("T3-ROE趋势", "华润三九近五年 ROE 变化如何"),
    ("T4-ROA趋势", "万达信息 2020 年到 2024 年 ROA 趋势如何"),
    ("T5-经营现金流净利比趋势", "华润三九近五年经营现金流净利比趋势如何"),
    ("T6-多派生指标趋势", "华润三九近五年资产负债率和净利率趋势如何"),
    ("T7-混合指标暂不支持", "华润三九近五年营业收入和净利率趋势如何"),
    ("T8-公司歧义", "华润近五年资产负债率趋势如何"),

    # ── V0.3.5 派生指标同比 ──
    ("DY1-资产负债率同比", "华润三九 2024 年资产负债率同比变化如何"),
    ("DY2-净利率同比", "贵州茅台 2024 年净利率同比增长多少"),
    ("DY3-ROE同比", "华润三九 2024 年 ROE 较上年变化如何"),
    ("DY4-ROA同比", "万达信息 2024 年总资产收益率同比变化"),
    ("DY5-经营现金流净利比同比", "华润三九 2024 年现金流净利比同比变化"),
    ("DY6-多派生指标同比", "华润三九 2024 年资产负债率和净利率同比变化如何"),
    ("DY7-混合不支持", "华润三九 2024 年营业收入和资产负债率同比变化如何"),
    ("DY8-缺少年份", "华润三九资产负债率同比变化如何"),
    ("DY9-公司歧义", "华润 2024 年资产负债率同比变化如何"),
]

RESULTS: list[dict] = []

for name, question in TEST_CASES:
    print(f"\n{'='*60}")
    print(f"【{name}】{question}")
    print("=" * 60)
    try:
        result = app.invoke({"user_question": question})
    except Exception as exc:
        result = {"final_answer": f"异常: {exc}", "error_type": "exception"}
    answer = result.get("final_answer", "") or "(空)"
    intent = result.get("intent_type", "?")
    error = result.get("error_type", "-")
    success = result.get("business_success")
    print(f"  意图: {intent} | 错误: {error} | 业务成功: {success}")

    # T1-T8 专项验证
    validations: list[str] = []
    if name.startswith("T") and name[1:2].isdigit():
        num = int(name[1])
        if num == 1:
            dt = result.get("derived_trend_result") or {}
            items = dt.get("items") or []
            if items and items[0].get("series"):
                validations.append("series 有数据 [OK]")
            else:
                validations.append("series 为空 [FAIL]")
        elif num == 2:
            sy = result.get("start_year")
            ey = result.get("end_year")
            if sy == 2020:
                validations.append(f"start_year={sy} [OK]")
            else:
                validations.append(f"start_year={sy} [FAIL]")
            if ey == 2024:
                validations.append(f"end_year={ey} [OK]")
            else:
                validations.append(f"end_year={ey} [FAIL]")
            dt = result.get("derived_trend_result") or {}
            items = dt.get("items") or []
            if items and items[0].get("metric_key") == "net_profit_margin":
                validations.append("metric_key=net_profit_margin [OK]")
            else:
                keys = [i.get("metric_key") for i in items]
                validations.append(f"metric_key={keys} [FAIL]")
        elif num == 3:
            dt = result.get("derived_trend_result") or {}
            items = dt.get("items") or []
            if items and items[0].get("metric_key") == "roe":
                validations.append("metric_key=roe [OK]")
            else:
                validations.append(f"metric_key={items[0].get('metric_key') if items else '?'} [FAIL]")
        elif num == 4:
            dt = result.get("derived_trend_result") or {}
            items = dt.get("items") or []
            if items and items[0].get("metric_key") == "roa":
                validations.append("metric_key=roa [OK]")
            else:
                validations.append(f"metric_key={items[0].get('metric_key') if items else '?'} [FAIL]")
        elif num == 5:
            dt = result.get("derived_trend_result") or {}
            items = dt.get("items") or []
            if items and items[0].get("metric_key") == "operating_cf_to_net_profit":
                validations.append("metric_key=operating_cf_to_net_profit [OK]")
            else:
                validations.append(f"metric_key={items[0].get('metric_key') if items else '?'} [FAIL]")
        elif num == 6:
            dt = result.get("derived_trend_result") or {}
            items = dt.get("items") or []
            if len(items) >= 2:
                validations.append(f"items 数量={len(items)} [OK]")
            else:
                validations.append(f"items 数量={len(items)} [FAIL] 预期≥2")
            if answer:
                validations.append("answer 非空 [OK]")
        elif num == 7:
            if error == "unsupported_mixed_trend":
                validations.append("error_type=unsupported_mixed_trend [OK]")
            else:
                validations.append(f"error_type={error} [FAIL]")
            if "暂不支持" in answer:
                validations.append("提示不支持混合趋势 [OK]")
        elif num == 8:
            if success:
                validations.append("business_success=True [OK]")
            else:
                validations.append(f"business_success={success} [FAIL]")

    # V0.3.5 DY(DerivedYoy) 验证
    if name.startswith("DY"):
        num = int(name[2])
        dy_result = result.get("derived_yoy_result") or {}
        dy_items = dy_result.get("items") or []
        if num == 1:
            if dy_items and dy_items[0].get("metric_key") == "debt_to_asset_ratio":
                validations.append("metric_key=debt_to_asset_ratio [OK]")
            else:
                keys = [i.get("metric_key") for i in dy_items]
                validations.append(f"metric_key={keys} [FAIL]")
            if answer:
                validations.append("answer 非空 [OK]")
        elif num == 2:
            if dy_items and dy_items[0].get("metric_key") == "net_profit_margin":
                validations.append("metric_key=net_profit_margin [OK]")
            else:
                keys = [i.get("metric_key") for i in dy_items]
                validations.append(f"metric_key={keys} [FAIL]")
        elif num == 3:
            if dy_items and dy_items[0].get("metric_key") == "roe":
                validations.append("metric_key=roe [OK]")
            else:
                keys = [i.get("metric_key") for i in dy_items]
                validations.append(f"metric_key={keys} [FAIL]")
        elif num == 4:
            if dy_items and dy_items[0].get("metric_key") == "roa":
                validations.append("metric_key=roa [OK]")
            else:
                keys = [i.get("metric_key") for i in dy_items]
                validations.append(f"metric_key={keys} [FAIL]")
        elif num == 5:
            if dy_items and dy_items[0].get("metric_key") == "operating_cf_to_net_profit":
                validations.append("metric_key=operating_cf_to_net_profit [OK]")
            else:
                keys = [i.get("metric_key") for i in dy_items]
                validations.append(f"metric_key={keys} [FAIL]")
        elif num == 6:
            if len(dy_items) >= 2:
                validations.append(f"items 数量={len(dy_items)} [OK]")
            else:
                validations.append(f"items 数量={len(dy_items)} [FAIL]")
            if answer:
                validations.append("answer 非空 [OK]")
        elif num == 7:
            if error == "unsupported_mixed_yoy":
                validations.append("error_type=unsupported_mixed_yoy [OK]")
            else:
                validations.append(f"error_type={error} [FAIL]")
            if "暂不支持" in answer:
                validations.append("提示不支持混合同比 [OK]")
        elif num == 8:
            # LLM planner 在 check_slots 前已设 need_clarification（无年份）
            if error in ("need_clarification", "missing_report_year"):
                validations.append(f"error_type={error} [OK]")
            else:
                validations.append(f"期望 need_clarification/missing_report_year，实际 error_type={error} [FAIL]")
        elif num == 9:
            # "华润" 可直接匹配到华润三九，业务成功为正常预期
            if success:
                validations.append(f"business_success=True [OK]")
            else:
                validations.append(f"business_success={success} [FAIL]")
    preview = answer[:150].replace("\n", "\\n")
    print(f"  回答: {preview}...")
    if validations:
        print(f"  验证: {'; '.join(validations)}")
    RESULTS.append({
        "case": name,
        "question": question,
        "intent_type": intent,
        "error_type": error,
        "business_success": success,
        "validations": validations,
        "answer_preview": answer[:300],
    })

print("\n\n" + "=" * 60)
print("测试汇总")
print("=" * 60)
for r in RESULTS:
    status = "OK" if r["business_success"] else ("~" if not r["error_type"] or r["error_type"] in ("need_clarification", "unsupported_mixed_trend", "unsupported_mixed_yoy", "-") else "XX")
    print(f"  {status} {r['case']:12s} | {r['intent_type']:22s} | {r['error_type'] or '-':20s} | {r['answer_preview'][:80]}")
