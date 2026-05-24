"""SQL/Shell/Perl/Groovy の正規表現分類。

Related: spec §7, §4
"""

import re

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS

# spec §7（Oracle 方言）。_apply は先頭一致優先。:= を最優先にし、
# 既存 golden 等価のため WHERE比較→分岐(DECODE/CASE/||)→INSERT/UPDATE代入 の順。
_SQL_RULES = [
    (re.compile(r":="), "代入"),
    (re.compile(r"\bWHERE\b.*?[=<>]", re.IGNORECASE), "比較"),
    (re.compile(r"\bCASE\s+WHEN\b|\bDECODE\s*\(|\|\|", re.IGNORECASE), "分岐"),
    (re.compile(r"\b(?:INSERT|UPDATE)\b", re.IGNORECASE), "代入"),
    # --- PL/SQL append（設計 §4.1・出力先頭・宣言/ループ行頭アンカー） ---
    (re.compile(r"^\s*(?:DBMS_OUTPUT\.PUT_LINE|RAISE_APPLICATION_ERROR)\b", re.IGNORECASE), "出力"),
    (re.compile(r"^\s*(?:CREATE\s+(?:OR\s+REPLACE\s+)?)?"
                r"(?:PROCEDURE|FUNCTION|PACKAGE(?:\s+BODY)?|TRIGGER|TYPE)\b", re.IGNORECASE), "宣言"),
    (re.compile(r"^\s*CURSOR\b", re.IGNORECASE), "宣言"),
    (re.compile(r"\bIF\b.*\bTHEN\b|^\s*ELSIF\b", re.IGNORECASE), "比較"),
    (re.compile(r"^\s*(?:WHILE|FOR)\b|\bLOOP\s*$", re.IGNORECASE), "分岐"),
]
_SHELL_RULES_BOURNE = [
    (re.compile(r"^\s*\w+="), "代入"),
    (re.compile(r"\[\s+.+?(?:=|==|-eq)\s+.+?\]"), "比較"),
    (re.compile(r"^\s*case\s+"), "分岐"),
]
# spec §7 C系シェル。代入: set V=/setenv V/@ V=、比較: if(/while(、分岐: switch(/case ...:/breaksw
_SHELL_RULES_CSHELL = [
    (re.compile(r"^\s*(?:set\s+\w+\s*=|setenv\s+\w+|@\s+\w+\s*=)"), "代入"),
    (re.compile(r"^\s*(?:if|while)\s*\("), "比較"),
    (re.compile(r"^\s*switch\s*\(|^\s*case\s+.+:|^\s*breaksw\b"), "分岐"),
]


def _apply(rules, line: str) -> ClassifyResult:
    for pat, cat in rules:
        if pat.search(line):
            return (cat, "medium")
    return ("その他", "medium")


# spec §7 コメントカテゴリ。行頭アンカーで純コメント行のみ（同居行はコード優先）。
# Oracle ヒント句 /*+ ... */ ・ --+ ... は最適化指示でコメントではない（(?!\+) で除外）。
_SQL_COMMENT = re.compile(r"^\s*--(?!\+)|^\s*/\*(?!\+).*\*/\s*$")
_SHELL_COMMENT = re.compile(r"^\s*#")
_PERL_COMMENT = re.compile(r"^\s*#")
_GROOVY_COMMENT = re.compile(r"^\s*//|^\s*/\*.*\*/\s*$")


def classify_sql(line: str) -> ClassifyResult:
    """SQL行（Oracle方言）を分類する（spec §7・confidence=medium／コメントは low）。"""
    if _SQL_COMMENT.match(line):
        return ("コメント", "low")
    return _apply(_SQL_RULES, line)


def classify_shell(line: str, dialect: str = "bourne") -> ClassifyResult:
    """Shell行を分類する（spec §7・confidence=medium／コメントは low）。

    dialect="cshell" のとき csh/tcsh 規則、それ以外（既定）は bourne 規則。
    """
    if _SHELL_COMMENT.match(line):
        return ("コメント", "low")
    rules = _SHELL_RULES_CSHELL if dialect == "cshell" else _SHELL_RULES_BOURNE
    return _apply(rules, line)


def _mask(language: str, line: str) -> str:
    pat = MASK_PATTERNS.get(language)
    return line if pat is None else pat.sub(lambda m: " " * len(m.group(0)), line)


# spec §4.2 Perl（先頭一致優先）。比較の裸 < > は -> / => / <= >= を除外。
_PERL_RULES = [
    (re.compile(r"^\s*sub\s+\w+|\bpackage\s+\w+|\buse\s+constant\b"), "宣言"),
    (re.compile(r"^\s*(?:my|our|local|state)\s+[$@%]|[$@%]\w+\s*=(?![=~>])"), "代入"),
    (re.compile(r"\b(?:if|unless|elsif)\b|==|!=|<=|>=|\beq\b|\bne\b|\blt\b|\bgt\b|\ble\b|"
                r"\bge\b|=~|!~|(?<![-=])<(?!=)|(?<![-=])>(?!=)"), "比較"),
    (re.compile(r"\b(?:for|foreach|while|until)\b"), "分岐"),
    (re.compile(r"\b(?:print|printf|say|warn|die)\b"), "出力"),
]
# spec §4.3 Groovy（先頭一致優先）。規則1の def はメソッド宣言形 `def name(` 限定。
_GROOVY_RULES = [
    (re.compile(r"^\s*(?:class|interface|enum|trait)\s+|"
                r"^\s*(?:[\w.<>,\s]+\s+)?def\s+\w+\s*\("), "宣言"),
    (re.compile(r"^\s*(?:def|final|[A-Za-z_]\w*(?:<[^>]*>)?)\s+\w+\s*=(?!=)|"
                r"\b\w+\s*=(?!=)"), "代入"),
    (re.compile(r"\b(?:if|while)\b|==~|<=>|==|!=|<=|>=|=~|"
                r"(?<![-=])<(?!=)|(?<![-=])>(?!=)"), "比較"),
    (re.compile(r"\b(?:switch|for|case)\b"), "分岐"),
    (re.compile(r"\breturn\b"), "return"),
    (re.compile(r"\b(?:println|print|printf)\b|\blog\.\w+"), "出力"),
]


def classify_perl(line: str) -> ClassifyResult:
    """Perl行を分類する（spec §4.2・confidence=medium／コメントは low・内部 mask）。"""
    if _PERL_COMMENT.match(line):
        return ("コメント", "low")
    return _apply(_PERL_RULES, _mask("perl", line))


def classify_groovy(line: str) -> ClassifyResult:
    """Groovy行を分類する（spec §4.3・confidence=medium／コメントは low・内部 mask）。"""
    if _GROOVY_COMMENT.match(line):
        return ("コメント", "low")
    return _apply(_GROOVY_RULES, _mask("groovy", line))
