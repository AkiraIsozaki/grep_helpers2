"""sql/shell ヒューリスティック span（spec §9 表「決定的境界」）。

mask_literals を行ごとに適用し、句境界・文末・shell 終端で停止する。
heredoc は mask 非対応＝§8.4 既知境界。LINE_MAX で必ず有限停止。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

from grep_analyzer.chase import mask_literals
from grep_analyzer.patterns.snippet_boundaries import (
    SH_TERMINATOR_RE,
    SQL_CLAUSE_RE,
)
from grep_analyzer.snippet._clamp import LINE_MAX


def _balanced(text: str) -> bool:
    paren_depth = 0
    for c in text:
        if c in "([{":
            paren_depth += 1
        elif c in ")]}":
            paren_depth -= 1
    return paren_depth == 0 and text.count("'") % 2 == 0 and text.count('"') % 2 == 0


def heuristic_span(lines: list[str], hit: int, language: str) -> tuple[int, int]:
    """sql/shell の決定的境界（spec §9）。mask_literals を行ごと適用し誤爆防止。

    ヒット行自身は停止判定しない。各方向1行ずつ移動し、移動先が
    停止条件（行末\\ 無・括弧/クオートバランス・SQL は ; か句境界 /
    shell は ;/fi/done/esac/breaksw）ならその行を含めて停止。heredoc は
    mask 非対応＝§8.4 境界、LINE_MAX で必ず有限停止。
    """
    masked_lines = [mask_literals(language, ln) for ln in lines]

    def stop(i: int) -> bool:
        x = masked_lines[i]
        if x.rstrip().endswith("\\"):
            return False
        if not _balanced(x):
            return False
        if language == "sql":
            return x.rstrip().endswith(";") or bool(SQL_CLAUSE_RE.search(x))
        return bool(SH_TERMINATOR_RE.search(x))

    span_start = hit
    for _ in range(LINE_MAX - 1):
        if span_start == 0:
            break
        span_start -= 1
        if stop(span_start):
            break
    span_end = hit
    for _ in range(LINE_MAX - 1):
        if span_end == len(lines) - 1:
            break
        span_end += 1
        if stop(span_end):
            break
        if (span_end - span_start + 1) >= LINE_MAX:
            break
    return span_start, span_end
