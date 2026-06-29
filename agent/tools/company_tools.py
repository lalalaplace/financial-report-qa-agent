"""公司识别工具。"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from db.readonly_executor import get_engine


MAX_CANDIDATES = 10
MIN_SHORT_TERM_LENGTH = 2
QUERY_STOP_WORDS = {
    "年",
    "多少",
    "是多少",
    "多少元",
    "多少钱",
    "营收",
    "收入",
    "营业收入",
    "总资产",
    "净利润",
    "利润",
    "现金流",
    "年报",
    "半年报",
    "一季报",
    "三季报",
    "年度",
    "报告",
}


def _normalize_query_text(query_text: str) -> str:
    """标准化用户问题文本，降低空白和全半角差异对匹配的影响。"""
    return (
        (query_text or "")
        .strip()
        .replace("\u3000", " ")
        .replace("\xa0", " ")
        .replace("（", "(")
        .replace("）", ")")
    )


def _extract_stock_code(query_text: str) -> str | None:
    """从问题中提取 6 位股票代码。"""
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", query_text)
    if not match:
        return None
    return match.group(1)


def _extract_short_terms(query_text: str) -> list[str]:
    """从用户问题中抽取可用于反向包含匹配的短词。"""
    text_without_code = re.sub(r"(?<!\d)\d{6}(?!\d)", " ", query_text)
    text_without_year = re.sub(r"20\d{2}", " ", text_without_code)
    cleaned_text = text_without_year
    for stop_word in sorted(QUERY_STOP_WORDS, key=len, reverse=True):
        cleaned_text = cleaned_text.replace(stop_word, " ")
    raw_terms = re.findall(r"[\u4e00-\u9fffA-Za-z0-9]+", cleaned_text)

    terms: list[str] = []
    seen_terms: set[str] = set()
    for term in raw_terms:
        term = term.strip()
        if len(term) < MIN_SHORT_TERM_LENGTH:
            continue
        if term in QUERY_STOP_WORDS:
            continue
        if term in seen_terms:
            continue
        seen_terms.add(term)
        terms.append(term)
    return terms


def _empty_result(candidates: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """构造统一返回结构。"""
    candidate_rows = candidates or []
    return {
        "matched": len(candidate_rows) == 1,
        "need_clarification": len(candidate_rows) > 1,
        "candidates": candidate_rows,
    }


def _candidate_from_row(row: Any) -> dict[str, str]:
    """把数据库行转换为对外候选公司结构。"""
    mapping = row._mapping
    return {
        "stock_code": mapping["stock_code"],
        "stock_abbr": mapping["stock_abbr"],
        "company_name": mapping["company_name"],
    }


def _dedupe_candidates(rows: list[Any]) -> list[dict[str, str]]:
    """按股票代码去重，保留分数最高、别名最长的候选。"""
    candidates: list[dict[str, str]] = []
    seen_stock_codes: set[str] = set()

    for row in rows:
        stock_code = row._mapping["stock_code"]
        if stock_code in seen_stock_codes:
            continue
        seen_stock_codes.add(stock_code)
        candidates.append(_candidate_from_row(row))

    return candidates


def _query_company_candidates(
    query_text: str,
    stock_code: str | None,
    short_terms: list[str],
) -> list[dict[str, str]]:
    """查询 company_dim 和 company_alias，返回可能出现在问题中的公司。"""
    sql = text(
        """
        SELECT
            c.stock_code,
            c.stock_abbr,
            c.company_name,
            MAX(
                CASE
                    WHEN :stock_code IS NOT NULL AND c.stock_code = :stock_code THEN 1000
                    WHEN LOWER(c.company_name) = LOWER(:query_text)
                      OR LOWER(c.stock_abbr) = LOWER(:query_text)
                      OR LOWER(a.alias_name) = LOWER(:query_text) THEN 950
                    WHEN EXISTS (
                        SELECT 1
                        FROM unnest(:short_terms) AS term
                        WHERE LOWER(c.company_name) = LOWER(term)
                           OR LOWER(c.stock_abbr) = LOWER(term)
                           OR LOWER(a.alias_name) = LOWER(term)
                    ) THEN 920
                    WHEN POSITION(LOWER(c.company_name) IN LOWER(:query_text)) > 0 THEN 900
                    WHEN POSITION(LOWER(c.stock_abbr) IN LOWER(:query_text)) > 0 THEN 850
                    WHEN POSITION(LOWER(a.alias_name) IN LOWER(:query_text)) > 0 THEN
                        CASE
                            WHEN COALESCE(a.is_primary, FALSE) THEN 800
                            ELSE 750
                        END
                    WHEN EXISTS (
                        SELECT 1
                        FROM unnest(:short_terms) AS term
                        WHERE POSITION(LOWER(term) IN LOWER(c.company_name)) > 0
                           OR POSITION(LOWER(term) IN LOWER(c.stock_abbr)) > 0
                           OR POSITION(LOWER(term) IN LOWER(a.alias_name)) > 0
                    ) THEN 500
                    ELSE 0
                END
            ) AS match_score,
            MAX(
                GREATEST(
                    LENGTH(COALESCE(c.company_name, '')),
                    LENGTH(COALESCE(c.stock_abbr, '')),
                    LENGTH(COALESCE(a.alias_name, ''))
                )
            ) AS match_length
        FROM company_dim c
        LEFT JOIN company_alias a
          ON a.company_id = c.company_id
        WHERE (:stock_code IS NOT NULL AND c.stock_code = :stock_code)
           OR LOWER(c.company_name) = LOWER(:query_text)
           OR LOWER(c.stock_abbr) = LOWER(:query_text)
           OR LOWER(a.alias_name) = LOWER(:query_text)
           OR EXISTS (
               SELECT 1
               FROM unnest(:short_terms) AS term
               WHERE LOWER(c.company_name) = LOWER(term)
                  OR LOWER(c.stock_abbr) = LOWER(term)
                  OR LOWER(a.alias_name) = LOWER(term)
           )
           OR (c.company_name IS NOT NULL AND POSITION(LOWER(c.company_name) IN LOWER(:query_text)) > 0)
           OR (c.stock_abbr IS NOT NULL AND POSITION(LOWER(c.stock_abbr) IN LOWER(:query_text)) > 0)
           OR (a.alias_name IS NOT NULL AND POSITION(LOWER(a.alias_name) IN LOWER(:query_text)) > 0)
           OR EXISTS (
               SELECT 1
               FROM unnest(:short_terms) AS term
               WHERE POSITION(LOWER(term) IN LOWER(c.company_name)) > 0
                  OR POSITION(LOWER(term) IN LOWER(c.stock_abbr)) > 0
                  OR POSITION(LOWER(term) IN LOWER(a.alias_name)) > 0
           )
        GROUP BY c.stock_code, c.stock_abbr, c.company_name
        ORDER BY match_score DESC, match_length DESC, c.stock_code
        LIMIT :limit
        """
    )

    safe_short_terms = short_terms or ["__NO_SHORT_TERM__"]

    with get_engine().connect() as conn:
        rows = conn.execute(
            sql,
            {
                "query_text": query_text,
                "stock_code": stock_code,
                "short_terms": safe_short_terms,
                "limit": MAX_CANDIDATES,
            },
        ).fetchall()

    return _dedupe_candidates(rows)


def resolve_company(query_text: str) -> dict:
    """
    从用户问题中识别公司。
    返回：
    - matched: bool
    - candidates: list
    - need_clarification: bool
    """
    normalized_query = _normalize_query_text(query_text)
    if not normalized_query:
        return _empty_result()

    stock_code = _extract_stock_code(normalized_query)
    short_terms = _extract_short_terms(normalized_query)

    try:
        candidates = _query_company_candidates(normalized_query, stock_code, short_terms)
    except (SQLAlchemyError, ValueError):
        return _empty_result()

    return _empty_result(candidates)
