"""ファイルの言語判定（spec §5.1）。"""

import os
import re

_EXT_MAP = {
    ".java": "java",
    ".sql": "sql",
    ".sh": "shell", ".ksh": "shell", ".bash": "shell",
    ".pc": "proc",
    ".c": "c", ".h": "c",
}
_EXEC_SQL_RE = re.compile(r"\bEXEC\s+SQL\b", re.IGNORECASE)

# シェバンは第1物理行の1列目（任意の先頭BOM=U+FEFF 可）に #! が必須（spec §5.1 手順3）。
_SHEBANG_RE = re.compile(r"^\ufeff?#!\s*(\S+)(?:\s+(\S+))?")
_BOURNE_INTERP = {"sh", "bash", "ksh", "dash"}
_CSHELL_INTERP = {"csh", "tcsh"}


def shebang_dialect(content_sample: str) -> str | None:
    """第1物理行のシェバンからシェル方言を判定する（spec §5.1）。

    戻り値: "bourne" / "cshell" / "other"（シェバンだが非シェル）/ None（シェバン無し）。
    `#!/usr/bin/env X` は X を interpreter とみなす。判定は第1行のみに依存し決定的。
    """
    first_line = content_sample.split("\n", 1)[0]
    m = _SHEBANG_RE.match(first_line)
    if m is None:
        return None
    interp = m.group(1).rsplit("/", 1)[-1]
    if interp == "env" and m.group(2):
        interp = m.group(2).rsplit("/", 1)[-1]
    if interp in _BOURNE_INTERP:
        return "bourne"
    if interp in _CSHELL_INTERP:
        return "cshell"
    return "other"


def detect_language(path: str, content_sample: str, lang_map: dict[str, str]) -> str:
    """拡張子マップ＋内容ヒューリスティックで言語を返す。判定不能は "c"。"""
    ext = os.path.splitext(path)[1].lower()
    if ext in lang_map:
        return lang_map[ext]
    lang = _EXT_MAP.get(ext)
    if lang in ("c", "proc") or ext == ".h":
        if _EXEC_SQL_RE.search(content_sample):
            return "proc"
        return lang or "c"
    if lang is not None:
        return lang
    return "c"
