"""SQL (Oracle PL/SQL) 用 Chaser — 言語別シンボル抽出とリテラルマスク。

PL/SQL の `var := 式` の左辺を var として抽出する。
バインド変数 `:v` / 置換変数 `&v` は ORACLE_ASSIGN_RE の lookbehind で除外。
constant / getter / setter は SQL では発生しないため常に空タプル。

chase.py の dispatcher が `_CHASERS["sql"]` 経由で呼び出す。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import ORACLE_ASSIGN_RE


def mask(line: str) -> str:
    """SQL のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["sql"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def _extract_var_symbols(dialect: str, line: str) -> list[str]:
    """マスク前の生行から PL/SQL `:=` の左辺を抽出する。"""
    return [m.group(1) for m in ORACLE_ASSIGN_RE.finditer(line)]


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に SQL の規則で分類抽出する（dialect は無視）。"""
    masked = mask(line)
    return ChaseSymbols((), tuple(_extract_var_symbols(dialect, masked)), (), ())
