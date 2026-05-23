"""SQL (Oracle PL/SQL) 用 Chaser — 言語別シンボル抽出とリテラルマスク。

PL/SQL 宣言 `name [CONSTANT] TYPE := …` では型名でなく先頭 id を採る（C-C）。
通常代入 `x := y`・複数代入 `a:=1;b:=2` は全左辺を温存（R2-C1）。CONSTANT を
constant、それ以外を var とする。getter/setter は SQL では発生しないため空。
バインド `:v`／置換 `&v` は lookbehind で除外。

chase.py の dispatcher が `_CHASERS["sql"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    ORACLE_CONSTANT_RE,
    ORACLE_DECL_ASSIGN_RE,
)


def mask(line: str) -> str:
    """SQL のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["sql"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def _extract_var_symbols(dialect: str, line: str) -> list[str]:
    """与えられた行から PL/SQL `:=` の左辺（宣言形は先頭 id）を抽出する。

    型付き宣言 `name TYPE := …` では型名でなく先頭 id を採る（C-C）。
    通常代入 `x := y`・複数代入 `a:=1;b:=2` は全左辺を温存（R2-C1）。
    バインド `:v`／置換 `&v` は lookbehind で除外。
    """
    return [m.group(1) for m in ORACLE_DECL_ASSIGN_RE.finditer(line)]


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に SQL(Oracle/PL-SQL) の規則で分類抽出する（dialect 無視）。"""
    masked = mask(line)
    consts = tuple(m.group(1) for m in ORACLE_CONSTANT_RE.finditer(masked))
    const_set = set(consts)
    vars_ = tuple(v for v in _extract_var_symbols(dialect, masked) if v not in const_set)
    return ChaseSymbols(consts, vars_, (), ())
