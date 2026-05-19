"""pyahocorasick ラッパ（spec §8.2）。識別子語境界一致のみ採用し決定的に返す。"""

import ahocorasick

_IDENT = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_")


def build(symbols: list[str]) -> ahocorasick.Automaton | None:
    """非空シンボル集合から Automaton を構築する。空集合/全空文字は None。"""
    syms = [s for s in symbols if s]
    if not syms:
        return None
    au = ahocorasick.Automaton()
    for s in syms:
        au.add_word(s, s)
    au.make_automaton()
    return au


def scan_line(au: ahocorasick.Automaton | None, line: str) -> list[str]:
    """1 行から語境界一致シンボルを昇順ユニークで返す（決定的）。

    版非依存の根拠: 列挙は `set` で集約し最後に `sorted()` で正規化、採否は
    `end`/`len(sym)` から算出する位置（文字 index）のみに依存し iter() の
    列挙順に非依存。よって pyahocorasick の版差（iter 順序・同一終端多重）を
    構造的に吸収する（2.1.0→2.3.1 版更新で出力 byte 不変＝spec v10 で実証）。
    """
    if au is None:
        return []
    found = set()
    n = len(line)
    for end, sym in au.iter(line):
        start = end - len(sym) + 1
        before = line[start - 1] if start > 0 else ""
        after = line[end + 1] if end + 1 < n else ""
        if before not in _IDENT and after not in _IDENT:
            found.add(sym)
    return sorted(found)
