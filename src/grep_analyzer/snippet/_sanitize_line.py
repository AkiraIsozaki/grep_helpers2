"""snippet 行サニタイズ（spec §9 規約①②）と物理行分解。

物理行分解は末尾改行由来の人工空要素を 1 個だけ除去する。
区切り衝突エスケープは行中の ' \\n ' と同一 4 文字並びの \\ を二重化する。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

from grep_analyzer.snippet._clamp import SEP


def _physical_lines(file_text: str) -> list[str]:
    """物理行配列。末尾改行由来の人工空要素を 1 個だけ除去（spec §9 物理行定義）。"""
    lines = file_text.split("\n")
    if file_text.endswith("\n") and lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def _escape_sep(line: str) -> str:
    """行中の区切り列 ' \\n '(U+0020 005C 006E 0020) と同一 4 文字並びの
    \\(U+005C) を \\\\ へ二重化（区切りと本文の曖昧化防止）。"""
    return line.replace(SEP, " \\\\n ")
