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


from dataclasses import dataclass

_MASK_SPECS = {
    "java": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "c": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "proc": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "sql": [r"'(?:''|[^'])*'", r"--[^\n]*", r"/\*.*?\*/"],
    "shell": [r'"(?:\\.|[^"\\])*"', r"'[^']*'", r"#[^\n]*"],
}
_MASK_RE = {lang: re.compile("|".join(p), re.DOTALL) for lang, p in _MASK_SPECS.items()}

_JAVA_GETSET_RE = re.compile(r"\b((?:get|set)[A-Z]\w*)\s*\(")
_JAVA_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+[\w.$]+(?:\s*<[^=;{}]*?>)?(?:\s*\[\s*\])*\s+([A-Za-z_]\w*)\s*=")
_JAVA_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
_C_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
_C_CONST_RE = re.compile(r"\bconst\b[\w\s*]*?\b([A-Za-z_]\w*)\s*=")
_C_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
_BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")


def mask_literals(language: str, line: str) -> str:
    """文字列リテラル・コメントを同幅の空白へ置換（行長・桁・行番号を保存）。

    偽陽性ノイズ抑止（spec §8）。マッチ全体を同字数スペースに潰すので後段の
    正規表現抽出に影響しない。automaton 走査は raw 行（spec 解釈の明示・非対称根拠）。
    """
    re_ = _MASK_RE.get(language)
    return line if re_ is None else re_.sub(lambda m: " " * len(m.group(0)), line)


@dataclass(frozen=True)
class ChaseSymbols:
    """1行から抽出した追跡候補（spec §8.1/§9）。getters/setters は §8.3 で

    横展開しない報告専用候補（fixedpoint が terminal として全件 low 報告）。
    """

    constants: tuple[str, ...] = ()
    vars: tuple[str, ...] = ()
    getters: tuple[str, ...] = ()
    setters: tuple[str, ...] = ()


def extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols:
    """1行をマスク後に spec §9 ref_kind×言語表で分類抽出する（決定的・出現順）。

    var は extract_var_symbols 再利用。getter/setter は Java 字句のみ。Pro*C
    ホスト変数 :var は追跡投入しない（spec §8.1 手順1 外部・ホスト境界）。
    """
    m = mask_literals(language, line)
    if language == "java":
        consts = tuple(g.group(2) for g in _JAVA_CONST_RE.finditer(m)
                       if "static" in g.group(1).split() and "final" in g.group(1).split())
        getters = tuple(x.group(1) for x in _JAVA_GETSET_RE.finditer(m) if x.group(1)[0] == "g")
        setters = tuple(x.group(1) for x in _JAVA_GETSET_RE.finditer(m) if x.group(1)[0] == "s")
        cset = set(consts)
        vars_ = tuple(v for v in (x.group(1) for x in _JAVA_VAR_RE.finditer(m)) if v not in cset)
        return ChaseSymbols(consts, vars_, getters, setters)
    if language in ("c", "proc"):
        consts = tuple(x.group(1) for x in _C_DEFINE_RE.finditer(m)) + tuple(
            x.group(1) for x in _C_CONST_RE.finditer(m))
        cset = set(consts)
        vars_ = tuple(v for v in (x.group(1) for x in _C_VAR_RE.finditer(m))
                      if v not in cset and v != "const")
        return ChaseSymbols(consts, vars_, (), ())  # Pro*C :host は非投入（spec §8.1手順1）
    if language == "shell" and dialect != "cshell":
        rm = _BOURNE_READONLY_RE.match(m)
        if rm is not None:
            return ChaseSymbols((rm.group(1),), (), (), ())
    return ChaseSymbols((), tuple(extract_var_symbols(language, dialect, m)), (), ())
