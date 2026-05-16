"""SQL/Shell の正規表現分類（spec §7）。"""

import re

from grep_analyzer.classifiers.base import ClassifyResult

_SQL_RULES = [
    (re.compile(r"\bWHERE\b.*?[=<>]", re.IGNORECASE), "比較"),
    (re.compile(r"\bCASE\s+WHEN\b", re.IGNORECASE), "分岐"),
    (re.compile(r"\b(?:INSERT|UPDATE)\b", re.IGNORECASE), "代入"),
]
_SHELL_RULES = [
    (re.compile(r"^\s*\w+="), "代入"),
    (re.compile(r"\[\s+.+?(?:=|==|-eq)\s+.+?\]"), "比較"),
    (re.compile(r"^\s*case\s+"), "分岐"),
]


def _apply(rules, line: str) -> ClassifyResult:
    for pat, cat in rules:
        if pat.search(line):
            return (cat, "medium")
    return ("その他", "medium")


def classify_sql(line: str) -> ClassifyResult:
    """SQL行を分類する。"""
    return _apply(_SQL_RULES, line)


def classify_shell(line: str) -> ClassifyResult:
    """Shell行を分類する。"""
    return _apply(_SHELL_RULES, line)
