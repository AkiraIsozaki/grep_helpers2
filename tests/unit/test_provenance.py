"""来歴グラフと chain 正規形の仕様（spec §9・07e81bb 明確化準拠）。"""

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.provenance import Occurrence, ProvenanceGraph


def _g(seed, edges):
    g = ProvenanceGraph()
    g.add_seed(seed)
    for p, c in edges:
        g.add_edge(p, c)
    return g


def test_単一経路のchainは起点から連結される():
    s, m = Occurrence("KEY", "a.c", 1), Occurrence("CODE", "b.c", 5)
    assert _g(s, [(s, m)]).chains_to(m, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "KEY@a.c:1 -> CODE@b.c:5"]


def test_同名keywordと追跡識別子は単純パスとして許容する():
    s, u = Occurrence("CODE", "r.sh", 1), Occurrence("CODE", "r.sh", 2)
    assert _g(s, [(s, u)]).chains_to(u, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "CODE@r.sh:1 -> CODE@r.sh:2"]


def test_複数単純パスは経路ごとに別chainを決定的順で返す():
    s = Occurrence("KEY", "a.c", 1)
    p, q, h = Occurrence("P", "p.c", 2), Occurrence("Q", "q.c", 3), Occurrence("H", "h.c", 9)
    assert _g(s, [(s, p), (s, q), (p, h), (q, h)]).chains_to(
        h, max_depth=10, max_paths=100, diag=Diagnostics()) == [
        "KEY@a.c:1 -> P@p.c:2 -> H@h.c:9", "KEY@a.c:1 -> Q@q.c:3 -> H@h.c:9"]


def test_追跡識別子の循環は再訪エッジで打ち切り診断記録する():
    s = Occurrence("KEY", "a.c", 1)
    x, y = Occurrence("X", "x.c", 2), Occurrence("Y", "y.c", 3)
    x2, h = Occurrence("X", "x.c", 9), Occurrence("H", "h.c", 4)
    diag = Diagnostics()
    chains = _g(s, [(s, x), (x, y), (y, x2), (y, h)]).chains_to(
        h, max_depth=10, max_paths=100, diag=diag)
    assert chains == ["KEY@a.c:1 -> X@x.c:2 -> Y@y.c:3 -> H@h.c:4"]
    assert "prov_cycle_cut" in diag.render()


def test_max_depthはホップ数で単一定義され0は間接ゼロ():
    s = Occurrence("KEY", "a.c", 1)
    a, b = Occurrence("A", "a.c", 2), Occurrence("B", "b.c", 3)
    g = _g(s, [(s, a), (a, b)])
    d1 = Diagnostics()
    assert g.chains_to(b, max_depth=1, max_paths=100, diag=d1) == []
    assert "prov_max_depth" in d1.render()
    assert g.chains_to(b, max_depth=2, max_paths=100, diag=Diagnostics()) == [
        "KEY@a.c:1 -> A@a.c:2 -> B@b.c:3"]
    assert g.chains_to(a, max_depth=0, max_paths=100, diag=Diagnostics()) == []


def test_経路数上限超過は決定的に辞書順先頭を採り診断記録する():
    s, h = Occurrence("KEY", "a.c", 1), Occurrence("H", "h.c", 9)
    mids = [Occurrence(f"M{i}", f"m{i}.c", i) for i in range(5)]
    g = ProvenanceGraph()
    g.add_seed(s)
    for mid in mids:
        g.add_edge(s, mid)
        g.add_edge(mid, h)
    diag = Diagnostics()
    chains = g.chains_to(h, max_depth=10, max_paths=2, diag=diag)
    assert chains == ["KEY@a.c:1 -> M0@m0.c:0 -> H@h.c:9", "KEY@a.c:1 -> M1@m1.c:1 -> H@h.c:9"]
    assert "prov_path_capped" in diag.render()


def test_seed物理行は間接から除外判定できる():
    g = ProvenanceGraph()
    g.add_seed(Occurrence("X", "o.sql", 2))
    assert g.is_seed_location("o.sql", 2) is True
    assert g.is_seed_location("o.sql", 1) is False
