"""来歴エッジのディスクスピルの仕様（spec §8.2 priority-2・出力透過・決定的）。"""

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.provenance import Occurrence
from grep_analyzer.spill import EdgeStore, parse_edge, serialize_edge


def test_制御文字込みで完全往復可逆():
    p = Occurrence("A\tB\\x", "a\nb.c", 3)
    c = Occurrence("C", "d.c", 9)
    assert parse_edge(serialize_edge(p, c)) == (p, c)


def test_メモリ内sorted_uniqueはsorted_setと同一かつin_memory_len(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    e1 = (Occurrence("Q", "q.c", 2), Occurrence("H", "h.c", 9))
    e2 = (Occurrence("P", "p.c", 1), Occurrence("H", "h.c", 9))
    for p, c in [e1, e2, e1]:
        s.add(p, c)
    assert s.spilled is False and s.in_memory_len() == 3
    assert list(s.sorted_unique()) == sorted({e1, e2})
    s.close()


def test_unitフック強制スピルでも同一集合同一順序かつin_memory_len0(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    s._force_spill_threshold = 1
    edges = [(Occurrence(f"S{i}", f"s{i}.c", i), Occurrence("H", "h.c", 9))
             for i in (3, 1, 2, 1)]
    for p, c in edges:
        s.add(p, c)
    assert s.spilled is True and s.in_memory_len() == 0
    assert list(s.sorted_unique()) == sorted(set(edges))
    s.close()


def test_maybe_spill_nowは閾値非経由で即スピルし透過(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    e = (Occurrence("A", "a.c", 1), Occurrence("B", "b.c", 2))
    s.add(*e)
    assert s.spilled is False and s._force_spill_threshold is None
    s.maybe_spill_now()
    assert s.spilled is True and s._force_spill_threshold is None  # フック不使用
    assert list(s.sorted_unique()) == [e] and s.in_memory_len() == 0
    s.close()


def test_budget0は1件目でスピルし同一(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(0))
    e = (Occurrence("A", "a.c", 1), Occurrence("B", "b.c", 2))
    s.add(*e)
    assert s.spilled is True and s.in_memory_len() == 0
    assert list(s.sorted_unique()) == [e]
    s.close()
