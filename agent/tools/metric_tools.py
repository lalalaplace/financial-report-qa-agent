"""财务指标映射工具。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
METRIC_DICTIONARY_PATH = PROJECT_ROOT / "data" / "metric_dictionary.json"

AMBIGUOUS_METRICS = {
    "现金流": {
        "question": "请明确要查询经营活动现金流、投资活动现金流还是筹资活动现金流。",
        "candidate_metric_keys": [
            "operating_cf_net_amount",
            "investing_cf_net_amount",
            "financing_cf_net_amount",
        ],
        "resolved_by_keywords": ["经营", "投资", "筹资", "融资", "净增加", "净额"],
    },
    "利润": {
        "question": "请明确要查询净利润、利润总额还是营业利润。",
        "candidate_metric_keys": [
            "net_profit",
            "total_profit",
            "operating_profit",
        ],
        "resolved_by_keywords": ["净利润", "利润总额", "营业利润", "经营利润", "归母净利润"],
    },
}


def load_metric_dictionary() -> dict[str, dict[str, Any]]:
    """读取结构化指标字典。"""
    with METRIC_DICTIONARY_PATH.open("r", encoding="utf-8") as file:
        metric_dict = json.load(file)
    _check_formula_errors(metric_dict)
    return metric_dict


# 向后兼容
_load_metric_dictionary = load_metric_dictionary


def _check_formula_errors(metric_dict: dict[str, dict[str, Any]]) -> None:
    """校验所有 derived 指标的 formula 引用是否有效，有误时打印告警但不阻断。"""
    errors: list[str] = []
    for metric_key, metric in metric_dict.items():
        if metric.get("metric_type") != "derived":
            continue
        formula = metric.get("formula") or {}
        for role in ("numerator", "denominator"):
            dep_key = formula.get(role)
            if not dep_key:
                errors.append(f"[WARN] {metric_key} formula 缺少 {role}")
                continue
            dep = metric_dict.get(dep_key)
            if not dep:
                errors.append(f"[WARN] {metric_key}.formula.{role} 引用了不存在的指标: {dep_key}")
                continue
            if not dep.get("table") or not dep.get("field"):
                errors.append(f"[WARN] {metric_key}.formula.{role} 引用了无效 base 指标: {dep_key}")
            if dep.get("metric_type") == "derived":
                errors.append(f"[WARN] {metric_key}.formula.{role} 不应引用派生指标: {dep_key}")
    if errors:
        print("\n".join(errors))


def _compact_text(text: str) -> str:
    """压缩问题文本，避免空白影响短别名匹配。"""
    return "".join((text or "").split())


def _build_metric(metric_key: str, info: dict[str, Any], matched_alias: str) -> dict[str, Any]:
    """构造对外返回的指标对象。"""
    result: dict[str, Any] = {
        "metric_key": metric_key,
        "metric_name": info["metric_name"],
        "table": info.get("table", ""),
        "field": info.get("field", ""),
        "unit": info.get("unit", "yuan"),
        "metric_type": info.get("metric_type", "base"),
        "aliases": info.get("aliases", []),
        "query_types": info.get("query_types", []),
        "description": info.get("description"),
        "matched_alias": matched_alias,
    }
    if info.get("metric_type") == "derived":
        result["formula"] = info.get("formula", {})
        result["scale"] = info.get("scale", 1)
        result["precision"] = info.get("precision", 2)
    return result


def _find_matches(question: str, metric_dict: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """按别名长度优先匹配指标，支持一个问题命中多个指标。"""
    compact_question = _compact_text(question)
    raw_matches: list[tuple[int, int, dict[str, Any]]] = []

    for index, (metric_key, info) in enumerate(metric_dict.items()):
        aliases = sorted(info.get("aliases", []), key=len, reverse=True)
        for alias in aliases:
            compact_alias = _compact_text(alias)
            if compact_alias and compact_alias in compact_question:
                metric = _build_metric(metric_key, info, alias)
                raw_matches.append((len(compact_alias), -index, metric))
                break

    raw_matches.sort(reverse=True)

    matched_metrics: list[dict[str, Any]] = []
    seen_metric_keys: set[str] = set()
    for _, _, metric in raw_matches:
        metric_key = metric["metric_key"]
        if metric_key in seen_metric_keys:
            continue
        seen_metric_keys.add(metric_key)
        matched_metrics.append(metric)

    return matched_metrics


def _matched_alias_contains_phrase(
    compact_question: str,
    matched_metrics: list[dict[str, Any]],
    phrase: str,
) -> bool:
    """检查已匹配指标是否有别名完整覆盖模糊短语（如'现金流净利比'含'现金流'）。"""
    for metric in matched_metrics:
        for alias in metric.get("aliases", []):
            compact_alias = _compact_text(alias)
            if phrase in compact_alias and compact_alias in compact_question:
                return True
    return False


def _find_ambiguities(
    question: str,
    metric_dict: dict[str, dict[str, Any]],
    matched_metrics: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """识别需要用户澄清的宽泛指标说法。"""
    compact_question = _compact_text(question)
    matched_keys = {metric["metric_key"] for metric in matched_metrics}
    ambiguities: list[dict[str, Any]] = []

    for phrase, rule in AMBIGUOUS_METRICS.items():
        if phrase not in compact_question:
            continue
        if any(keyword in compact_question for keyword in rule["resolved_by_keywords"]):
            continue

        # 如果已匹配的指标别名完整覆盖了模糊短语（如"现金流净利比"含"现金流"），
        # 说明用户指向明确，无需澄清
        if _matched_alias_contains_phrase(compact_question, matched_metrics, phrase):
            continue

        candidate_keys = [
            key for key in rule["candidate_metric_keys"]
            if key in metric_dict
        ]
        if matched_keys.intersection(candidate_keys):
            continue

        ambiguities.append(
            {
                "phrase": phrase,
                "question": rule["question"],
                "candidates": [
                    _build_metric(key, metric_dict[key], phrase)
                    for key in candidate_keys
                ],
            }
        )

    return ambiguities


def map_metrics(question: str) -> dict:
    """
    从用户问题中识别财务指标。
    返回匹配到的指标列表。
    """
    metric_dict = _load_metric_dictionary()
    matched_metrics = _find_matches(question, metric_dict)
    ambiguities = _find_ambiguities(question, metric_dict, matched_metrics)

    if ambiguities:
        return {
            "matched": bool(matched_metrics),
            "metrics": matched_metrics,
            "need_clarification": True,
            "clarification_question": "；".join(item["question"] for item in ambiguities),
            "ambiguities": ambiguities,
        }

    if not matched_metrics:
        return {
            "matched": False,
            "metrics": [],
            "need_clarification": True,
            "clarification_question": "请说明你要查询的财务指标，例如总资产、营业收入、净利润或经营活动现金流量净额。",
            "ambiguities": [],
        }

    return {
        "matched": True,
        "metrics": matched_metrics,
        "need_clarification": False,
        "clarification_question": None,
        "ambiguities": [],
    }
