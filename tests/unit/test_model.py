"""ドメインモデルとTSV決定的ソートの仕様。"""

from grep_analyzer.model import TSV_COLUMNS, Hit, sort_key


def test_TSV列順はspec9の固定順である():
    assert TSV_COLUMNS == [
        "keyword", "language", "file", "lineno", "ref_kind",
        "category", "category_sub", "usage_summary", "via_symbol",
        "chain", "snippet", "encoding", "confidence",
    ]


def test_Hitはタプル化でTSV列順に並ぶ():
    h = Hit(
        keyword="K", language="java", file="a/b.java", lineno=3,
        ref_kind="direct", category="比較", category_sub="",
        usage_summary="if 比較", via_symbol="", chain="K@a/b.java:3",
        snippet='if (x.equals("K"))', encoding="utf-8", confidence="high",
    )
    assert h.to_row() == [
        "K", "java", "a/b.java", "3", "direct", "比較", "",
        "if 比較", "", "K@a/b.java:3", 'if (x.equals("K"))', "utf-8", "high",
    ]


def test_sort_keyはdirect同士でfile_lineno順を与える():
    a = Hit("K", "java", "a.java", 2, "direct", "比較", "", "", "", "K@a.java:2", "s", "utf-8", "high")
    b = Hit("K", "java", "a.java", 10, "direct", "比較", "", "", "", "K@a.java:10", "s", "utf-8", "high")
    assert sorted([b, a], key=sort_key) == [a, b]


def _h(**kw):
    base = dict(keyword="K", language="java", file="/r/A.java", lineno=1,
                ref_kind="direct", category="宣言", category_sub="",
                usage_summary="u", via_symbol="", chain="K@A.java:1",
                snippet="s", encoding="utf-8", confidence="high")
    base.update(kw)
    return Hit(**base)


def test_directブロックがindirectより前に来る():
    d = _h(ref_kind="direct", lineno=5, chain="K@A.java:5")
    i = _h(ref_kind="indirect:constant", lineno=1, via_symbol="V",
           chain="K@A.java:1 -> V@B.java:1")
    assert sorted([i, d], key=sort_key) == [d, i]


def test_indirectはchain文字列ごとに集約されてからfile_lineno():
    a = _h(ref_kind="indirect:constant", file="/r/Z.java", lineno=9,
           via_symbol="V", chain="K@A:1 -> V@A:1")
    b = _h(ref_kind="indirect:constant", file="/r/A.java", lineno=1,
           via_symbol="W", chain="K@A:1 -> W@B:1")
    assert sorted([a, b], key=sort_key) == [a, b]


def test_direct同士はfile_lineno数値順():
    x = _h(lineno=10, chain="K@A.java:10")
    y = _h(lineno=2, chain="K@A.java:2")
    assert sorted([x, y], key=sort_key) == [y, x]


def test_完全同値近傍はlanguage_encodingで全順序():
    p = _h(language="java")
    q = _h(language="shell")
    assert sorted([q, p], key=sort_key) == [p, q]
    # encoding タイブレーク: "utf-16" < "utf-8" (昇順文字列比較: '1' < '8')
    e1 = _h(encoding="utf-16")
    e2 = _h(encoding="utf-8")
    assert sorted([e2, e1], key=sort_key) == [e1, e2]
