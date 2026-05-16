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
