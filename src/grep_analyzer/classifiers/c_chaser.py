"""C / Pro*C 用 Chaser — 言語別シンボル抽出とリテラルマスク。

C と Pro*C は同じ抽出規則を共有する（Pro*C は C のスーパーセット）。
chase.py の dispatcher が `_CHASERS["c"]` / `_CHASERS["proc"]` 経由で呼び出す。
Pro*C のホスト変数 `:var` は追跡投入しない（spec §8.1 手順1 外部・ホスト境界）。
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    C_CONST_RE,
    C_DEFINE_RE,
    C_VAR_RE,
)


def mask(line: str) -> str:
    """C / Pro*C のリテラル / コメントを同字数空白に置換する。

    呼び出し元の dispatcher が `language` で `_CHASERS["c"]` と `_CHASERS["proc"]`
    を切り替えるが、現行 spec では両者の MASK パターンは完全同一。
    """
    pattern = MASK_PATTERNS["c"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に C / Pro*C の規則で分類抽出する（dialect は無視）。

    `#define` と `const ... var =` を constant、それ以外の代入を var として収集。
    """
    masked = mask(line)
    consts = tuple(x.group(1) for x in C_DEFINE_RE.finditer(masked)) + tuple(
        x.group(1) for x in C_CONST_RE.finditer(masked)
    )
    const_set = set(consts)
    vars_ = tuple(
        v for v in (x.group(1) for x in C_VAR_RE.finditer(masked))
        if v not in const_set and v != "const"
    )
    return ChaseSymbols(consts, vars_, (), ())
