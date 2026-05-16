"""ファイルの言語判定（spec §5.1）。"""

import os
import re

_EXT_MAP = {
    ".java": "java",
    ".sql": "sql",
    ".sh": "shell", ".ksh": "shell", ".bash": "shell",
    ".csh": "shell", ".tcsh": "shell",
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
    """spec §5.1 の決定的優先順位で言語を返す。

    1) --lang-map 上書き 2) 拡張子マップ 3) 拡張子未知/無ならシェバン検出
    4) EXEC SQL ヒューリスティック 5) C にフォールバック。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in lang_map:
        return lang_map[ext]
    lang = _EXT_MAP.get(ext)
    if lang == "shell":
        return "shell"
    if lang in ("c", "proc") or ext == ".h":
        if _EXEC_SQL_RE.search(content_sample):
            return "proc"
        return lang or "c"
    if lang is not None:  # java / sql
        return lang
    # 拡張子が未知または無い: シェバン検出（手順3）→ EXEC SQL（手順4）→ c（手順5）
    if shebang_dialect(content_sample) in ("bourne", "cshell"):
        return "shell"
    if _EXEC_SQL_RE.search(content_sample):
        return "proc"
    return "c"


def extension_resolves_language(path: str, lang_map: dict[str, str]) -> bool:
    """拡張子（または --lang-map）だけで言語が確定するなら True（spec §5.1 手順1〜2）。

    False のときのみ手順3（シェバン検出）に到達する。
    """
    ext = os.path.splitext(path)[1].lower()
    return ext in lang_map or ext in _EXT_MAP


def detect_shell_dialect(path: str, content_sample: str) -> str:
    """言語が Shell のとき方言（"bourne"/"cshell"）を決定的に返す（spec §5.1）。

    ① シェル系シェバンがあればそれを優先 ② 無ければ拡張子 ③ どちらも無ければ bourne。
    本関数は言語判定とは独立に呼ばれ、既知シェル拡張子でも第1物理行のシェバンを必ず見る。
    """
    sd = shebang_dialect(content_sample)
    if sd in ("bourne", "cshell"):
        return sd
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csh", ".tcsh"):
        return "cshell"
    return "bourne"
