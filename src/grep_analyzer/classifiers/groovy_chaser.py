"""Groovy 用 Chaser — final 定数と def/型付き変数代入を抽出する。

final（static 任意）を constant、それ以外の代入左辺を var とする。getter/setter
は型解決依存のため不追跡（§8.4）。`obj.field=` の限定子剥がし・複数行 GString・
slashy string は §8.4 既知境界。

chase.py の dispatcher が `_CHASERS["groovy"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    GROOVY_CONST_RE,
    GROOVY_VAR_RE,
)


def mask(line: str) -> str:
    """Groovy のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["groovy"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Groovy の規則で分類抽出する（dialect は無視）。"""
    masked = mask(line)
    consts = tuple(
        g.group(2) for g in GROOVY_CONST_RE.finditer(masked)
        if "final" in g.group(1).split()
    )
    const_set = set(consts)
    vars_ = tuple(
        v for v in (m.group(1) for m in GROOVY_VAR_RE.finditer(masked))
        if v not in const_set
    )
    return ChaseSymbols(consts, vars_, (), ())
