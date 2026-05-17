"""静的シンボル採否ポリシー（spec §8.3）。汎用名の横展開爆発を篩で防ぐ。

v1 は静的ソースのみ。動的トップN は spec §14 外。集合サイズ上限の決定的
切り捨ては大域・累積のため fixedpoint 側（spec §8.3「(発見ホップ,長さ,辞書順)」）。
"""

from dataclasses import dataclass
from pathlib import Path

_JAVA_KW = frozenset(
    "abstract assert boolean break byte case catch char class const continue default do double "
    "else enum extends final finally float for goto if implements import instanceof int interface "
    "long native new package private protected public return short static strictfp super switch "
    "synchronized this throw throws transient try void volatile while true false null var".split())
_C_KW = frozenset(
    "auto break case char const continue default do double else enum extern float for goto if int "
    "long register return short signed sizeof static struct switch typedef union unsigned void "
    "volatile while inline restrict _Bool".split())
_SQL_KW = frozenset(
    "select insert update delete from where and or not null is in like between exists into values "
    "set begin end declare if then else elsif loop for while case when decode dual table view "
    "procedure function trigger as order by group having distinct union all".split())
_SHELL_KW = frozenset(
    "if then else elif fi for while until do done case esac in function select time set setenv "
    "unset export readonly local return break continue switch breaksw end foreach endif endsw "
    "echo test true false".split())
LANG_KEYWORDS: dict[str, frozenset[str]] = {
    "java": _JAVA_KW, "c": _C_KW, "proc": _C_KW, "sql": _SQL_KW, "shell": _SHELL_KW}


@dataclass(frozen=True)
class SymbolPolicy:
    """採否の静的パラメータ（spec §8.3）。cap は持たない（大域 cap は fixedpoint）。"""

    min_specificity: int
    user_stoplist: frozenset[str]


@dataclass(frozen=True)
class AdmissionResult:
    """採否の決定的結果。rejected は (シンボル, 理由) の順序保存列。"""

    accepted: list[str]
    rejected: list[tuple[str, str]]


def load_stoplist(path: Path | None) -> frozenset[str]:
    """ユーザ提供ストップリストを読む。空行と # コメント行を無視（静的）。"""
    if path is None:
        return frozenset()
    out = set()
    for raw in Path(path).read_text("utf-8").splitlines():
        s = raw.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return frozenset(out)


def admit(symbols: list[str], language: str, policy: SymbolPolicy) -> AdmissionResult:
    """シンボル列を静的ポリシーで決定的に採否（spec §8.3・cap 非適用）。"""
    kw = LANG_KEYWORDS.get(language, frozenset())
    accepted: list[str] = []
    rejected: list[tuple[str, str]] = []
    for s in symbols:
        if s in kw:
            rejected.append((s, "keyword"))
        elif len(s) < policy.min_specificity:
            rejected.append((s, "too_short"))
        elif s in policy.user_stoplist:
            rejected.append((s, "user_stoplist"))
        else:
            accepted.append(s)
    return AdmissionResult(accepted, rejected)
