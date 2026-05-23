"""Perl 用 Chaser — sigil 付き代入左辺・use constant を抽出する。

sigil（$ @ %）は剥がして bare 識別子を追跡シンボルとする（設計 §5.1）。
getter/setter は型解決依存のため不追跡（§8.4）。heredoc/POD/任意デリミタ
q// は行単位マスクの対象外＝§8.4 既知境界。

chase.py の dispatcher が `_CHASERS["perl"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    PERL_ASSIGN_RE,
    PERL_USE_CONSTANT_RE,
)


def mask(line: str) -> str:
    """Perl のリテラル / コメントを同字数空白に置換する（$# は壊さない）。"""
    pattern = MASK_PATTERNS["perl"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Perl の規則で分類抽出する（dialect は無視）。"""
    masked = mask(line)
    consts = tuple(m.group(1) for m in PERL_USE_CONSTANT_RE.finditer(masked))
    const_set = set(consts)
    vars_ = tuple(
        v for v in (m.group(1) for m in PERL_ASSIGN_RE.finditer(masked))
        if v not in const_set
    )
    return ChaseSymbols(consts, vars_, (), ())
