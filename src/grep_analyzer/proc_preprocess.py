"""Pro*C前処理: EXEC SQL / EXEC ORACLE 区間を行数保存で中立トークンに置換（spec §7）。

行番号を原ソースと不変に保つため、置換は各物理行を「同じ行数の空文字列」に潰し
改行のみ残す（桁ズレは許容、行番号は不変）。
"""

import re

# `EXEC SQL ... ;` / `EXEC SQL ... END-EXEC` / `EXEC ORACLE ... ;` を行跨ぎで捕捉
_EXEC_RE = re.compile(
    r"\bEXEC\s+(?:SQL|ORACLE)\b.*?(?:;|END-EXEC\b)",
    re.IGNORECASE | re.DOTALL,
)


def mask_exec_sql(source: str) -> str:
    """EXEC SQL/ORACLE 区間を中立化。区間内の各行を空行化し改行数を保存する。"""

    def _blank(m: re.Match) -> str:
        # マッチ内の改行数を保ち、各行の中身を消す（行番号不変）
        return "\n" * m.group(0).count("\n")

    return _EXEC_RE.sub(_blank, source)


import re as _re
from grep_analyzer.chase import _MASK_SPECS

_PROC_LIT_RE = _re.compile("|".join(_MASK_SPECS["proc"]), _re.DOTALL)


def _blank_literals(source: str) -> str:
    return _PROC_LIT_RE.sub(
        lambda m: "".join(c if c == "\n" else " " for c in m.group(0)), source)


def exec_spans(source: str) -> list[tuple[int, int]]:
    """EXEC SQL/ORACLE 区間を (start_line, end_line)（0始まり）で返す。

    リテラル・コメント空白化コピー上で _EXEC_RE を走らせ文字列内 ;/
    END-EXEC の誤切断を防ぐ（spec §7 v9 Crit-1）。空白化は長さ保存
    のため原ソース行へ正しく写像できる。
    """
    masked = _blank_literals(source)
    return [(source.count("\n", 0, m.start()), source.count("\n", 0, m.end()))
            for m in _EXEC_RE.finditer(masked)]
