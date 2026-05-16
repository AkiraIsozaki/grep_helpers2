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
