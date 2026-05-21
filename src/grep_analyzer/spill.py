"""来歴エッジのディスクスピル（priority-2）。予算内メモリ・超過で

ディスク追記退避。sorted_unique は in-memory/spill いずれでも
sorted(set(edges)) と同一（出力透過・決定的）。in_memory_len はメモリ常駐数
（スピル後 0＝estimate_items にスピルが圧解消として反映）。maybe_spill_now は
engine priority-2 用で内部 _spill_now 直呼び（_force_spill_threshold は
Task2 unit 専用・本番経路から設定しない）。

Related: spec §8.2
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.provenance import Occurrence

_ESC = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"}
_UNESC = {"\\\\": "\\", "\\t": "\t", "\\n": "\n", "\\r": "\r"}


def _enc(s: str) -> str:
    return "".join(_ESC.get(ch, ch) for ch in s)


def _dec(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            two = s[i:i + 2]
            if two in _UNESC:
                out.append(_UNESC[two])
                i += 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def serialize_edge(p: Occurrence, c: Occurrence) -> str:
    """1 エッジを 6 フィールドのタブ区切り1行へ（制御文字エスケープ）。"""
    return "\t".join((_enc(p.symbol), _enc(p.relpath), str(p.lineno),
                      _enc(c.symbol), _enc(c.relpath), str(c.lineno)))


def parse_edge(line: str) -> tuple[Occurrence, Occurrence]:
    """serialize_edge の逆。完全可逆。"""
    f = line.rstrip("\n").split("\t")
    return (Occurrence(_dec(f[0]), _dec(f[1]), int(f[2])),
            Occurrence(_dec(f[3]), _dec(f[4]), int(f[5])))


class EdgeStore:
    """来歴エッジを予算内メモリ、超過でディスクへ退避して保持する。"""

    def __init__(self, spill_dir: Path | None, budget) -> None:
        self._mem: list[tuple[Occurrence, Occurrence]] = []
        self._budget = budget
        self._dir = Path(spill_dir) if spill_dir is not None else Path(tempfile.gettempdir())
        self._fh = None
        self._path: Path | None = None
        self.spilled = False
        self._force_spill_threshold: int | None = None  # Task2 unit 専用

    def add(self, p: Occurrence, c: Occurrence) -> None:
        """1 エッジ追加。予算/unit フック超過で以降スピルへ。"""
        if self.spilled:
            self._fh.write(serialize_edge(p, c) + "\n")
            return
        self._mem.append((p, c))
        self.maybe_spill()

    def in_memory_len(self) -> int:
        """メモリ常駐エッジ数（スピル後は 0）。"""
        return 0 if self.spilled else len(self._mem)

    def maybe_spill(self) -> None:
        """予算/unit フック超過ならスピル。"""
        if self.spilled:
            return
        thr = self._force_spill_threshold
        over = (thr is not None and len(self._mem) >= thr) or \
               self._budget.exceeded(len(self._mem))
        if over:
            self._spill_now()

    def maybe_spill_now(self) -> None:
        """engine priority-2 用＝予算判定に依らず即スピル（フック非経由）。"""
        if not self.spilled:
            self._spill_now()

    def _spill_now(self) -> None:
        """メモリ内容を一時ファイルへ退避しスピル状態へ（内部）。"""
        fd, p = tempfile.mkstemp(dir=str(self._dir), prefix="ga_edges_", suffix=".tsv")
        self._path = Path(p)
        self._fh = os.fdopen(fd, "w", encoding="utf-8")
        for pp, cc in self._mem:
            self._fh.write(serialize_edge(pp, cc) + "\n")
        self._mem = []
        self.spilled = True

    def sorted_unique(self) -> Iterator[tuple[Occurrence, Occurrence]]:
        """sorted(set(edges)) と同一順序・同一集合（出力透過・決定的）。"""
        if not self.spilled:
            yield from sorted(set(self._mem))
            return
        self._fh.flush()
        seen: set[tuple[Occurrence, Occurrence]] = set()
        with open(self._path, encoding="utf-8") as r:
            for line in r:
                if line.strip():
                    seen.add(parse_edge(line))
        yield from sorted(seen)

    def close(self) -> None:
        """一時ファイルを閉じ削除する（確定ループ完了後・例外時も finally で）。"""
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        if self._path is not None and self._path.exists():
            self._path.unlink()
            self._path = None
