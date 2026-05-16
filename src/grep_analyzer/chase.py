"""追跡シンボル抽出規則（spec §8.1）。Phase 2 不動点エンジンが消費する純関数。

Phase 1.5 では direct パイプラインには配線せず、抽出規則の正しさを unit で固定する
（spec §15 フェーズ1.5: Oracle/csh 代入抽出を Phase 2 前に確定し golden 誤固定を防ぐ）。
"""

import re

# 代入左辺の識別子。Oracle は直前が : / & のもの（バインド/置換変数）を除外（spec §8.4）。
_ORACLE_ASSIGN_RE = re.compile(r"(?<![:&])\b([A-Za-z_]\w*)\s*:=")
_BOURNE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)=")
_CSHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:set\s+([A-Za-z_]\w*)\s*=|setenv\s+([A-Za-z_]\w*)\b|@\s+([A-Za-z_]\w*)\s*=)"
)


def extract_var_symbols(language: str, dialect: str, line: str) -> list[str]:
    """1行から indirect:var 追跡シンボル（代入の左辺識別子）を決定的に抽出する。

    - SQL(Oracle): PL/SQL `var := 式` の左辺。バインド `:v`／置換 `&v` は非抽出。
    - Shell(bourne): 行頭 `var=` の左辺。
    - Shell(cshell): `set v =`／`setenv V`／`@ v =` の左辺。
    対象外言語・該当なしは空リスト。
    """
    if language == "sql":
        return [m.group(1) for m in _ORACLE_ASSIGN_RE.finditer(line)]
    if language == "shell" and dialect == "cshell":
        out: list[str] = []
        for m in _CSHELL_ASSIGN_RE.finditer(line):
            out.append(next(g for g in m.groups() if g))
        return out
    if language == "shell":
        m = _BOURNE_ASSIGN_RE.match(line)
        return [m.group(1)] if m else []
    return []
