"""Java 用 Chaser — 言語別シンボル抽出とリテラルマスク。

`Chaser` プロトコル準拠のモジュールレベル関数を公開する。
chase.py の dispatcher が `_CHASERS["java"]` 経由で呼び出す。
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    JAVA_CONST_RE,
    JAVA_GETSET_RE,
    JAVA_VAR_RE,
)


def mask(line: str) -> str:
    """Java のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["java"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Java の規則で分類抽出する（dialect は無視）。

    static final 修飾子付き宣言を constant、それ以外の代入を var、
    getter/setter を terminal として収集する。
    """
    masked = mask(line)
    consts = tuple(
        g.group(2) for g in JAVA_CONST_RE.finditer(masked)
        if "static" in g.group(1).split() and "final" in g.group(1).split()
    )
    getters = tuple(
        x.group(1) for x in JAVA_GETSET_RE.finditer(masked) if x.group(1)[0] == "g"
    )
    setters = tuple(
        x.group(1) for x in JAVA_GETSET_RE.finditer(masked) if x.group(1)[0] == "s"
    )
    const_set = set(consts)
    vars_ = tuple(
        v for v in (x.group(1) for x in JAVA_VAR_RE.finditer(masked))
        if v not in const_set
    )
    return ChaseSymbols(consts, vars_, getters, setters)
