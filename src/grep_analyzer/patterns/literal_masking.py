"""言語別リテラル / コメントのマスク用 regex。

`mask_literals` が偽陽性抑止のため、リテラル文字列・コメントを同字数空白に
置換するときの言語別パターン集。マッチ全体を空白に潰すため、後段の正規表現
抽出は行番号・桁を保ったまま行える。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 1
"""

import re

MASK_SPECS: dict[str, list[str]] = {
    "java": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "c": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "proc": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "sql": [r"'(?:''|[^'])*'", r"--[^\n]*", r"/\*.*?\*/"],
    "shell": [r'"(?:\\.|[^"\\])*"', r"'[^']*'", r"#[^\n]*"],
}

MASK_PATTERNS: dict[str, re.Pattern[str]] = {
    lang: re.compile("|".join(p), re.DOTALL) for lang, p in MASK_SPECS.items()
}
