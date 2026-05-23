"""snippet 切り出しパッケージ。

公開エントリは build_snippet。clamp_lines / heuristic_span / ts_span /
proc_exec_span は仕様検証用の test 由来公開 API として再 export する。

Related: spec §9
"""

from grep_analyzer.snippet._clamp import clamp_lines
from grep_analyzer.snippet._heuristic import heuristic_span
from grep_analyzer.snippet._sanitize_line import _escape_sep, _physical_lines
from grep_analyzer.snippet._ts import proc_exec_span, ts_span
from grep_analyzer.tsv import sanitize_field

__all__ = [
    "build_snippet",
    "clamp_lines",
    "heuristic_span",
    "ts_span",
    "proc_exec_span",
]


def build_snippet(language: str, dialect: str, file_text: str,
                  lineno: int) -> str:
    """spec §9 snippet 切り出しのエントリ。確定済み 1 セル文字列を返す。

    java/c: ts_span→無ければ ヒット 1 行（spec §9 フォールバック: java/c に
      sql/shell ヒューリスティックは適用しない）。
    proc: EXEC 区間=proc_exec_span／区間外=ts_span("proc",..)（内部で
      mask_exec_sql 後 C 解析）→ いずれも None なら ヒット 1 行（spec §7/§9）。
    sql/shell/perl/groovy: heuristic_span（AST 非使用）。
    `dialect` は将来 cshell 境界用の予約引数（v1 未使用・呼出互換のため受領）。
    連結前に各行へ sanitize_field→_escape_sep を適用し clamp_lines。

    Related: spec §7, §9
    """
    lines = _physical_lines(file_text)
    hit = lineno - 1
    if hit < 0 or hit >= len(lines):
        return ""
    span = None
    if language in ("java", "c", "python", "javascript", "typescript", "tsx"):
        span = ts_span(language, file_text, lineno)
    elif language == "proc":
        span = proc_exec_span(file_text, lineno)
        if span is None:
            span = ts_span("proc", file_text, lineno)
    elif language in ("sql", "shell", "perl", "groovy"):
        span = heuristic_span(lines, hit, language)
    if span is None:
        span = (hit, hit)
    span_start, span_end = span
    span_start = max(0, min(span_start, hit))
    span_end = min(len(lines) - 1, max(span_end, hit))
    body = [_escape_sep(sanitize_field(x)) for x in lines[span_start:span_end + 1]]
    return clamp_lines(body, hit - span_start)
