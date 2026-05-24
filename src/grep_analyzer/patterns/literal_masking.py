"""言語別リテラル / コメントのマスク用 regex。

`mask_literals` が偽陽性抑止のため、リテラル文字列・コメントを同字数空白に
置換するときの言語別パターン集。マッチ全体を空白に潰すため、後段の正規表現
抽出は行番号・桁を保ったまま行える。

注: java/c は AST 化（_AST_CHASERS 経路）のため MASK_SPECS 非対象。
    proc は proc_preprocess.py が MASK_PATTERNS["proc"] に直接依存するため残置。
"""

import re

MASK_SPECS: dict[str, list[str]] = {
    "proc": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "sql": [r"'(?:''|[^'])*'", r"--[^\n]*", r"/\*.*?\*/"],
    "shell": [r'"(?:\\.|[^"\\])*"', r"'[^']*'", r"#[^\n]*"],
    "perl": [r"'[^']*'", r'"(?:\\.|[^"\\])*"', r"\bqq\([^)]*\)", r"\bq\([^)]*\)",
             r"(?<![$@%])#[^\n]*"],
    "groovy": [r"'(?:\\.|[^'\\])*'", r'"(?:\\.|[^"\\])*"', r"//[^\n]*", r"/\*.*?\*/"],
}

MASK_PATTERNS: dict[str, re.Pattern[str]] = {
    lang: re.compile("|".join(p), re.DOTALL) for lang, p in MASK_SPECS.items()
}
