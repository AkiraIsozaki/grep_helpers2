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


def test_sort_keyはfile_lineno_ref_kindの順で全順序を与える():
    a = Hit("K", "java", "a.java", 2, "direct", "比較", "", "", "", "K@a.java:2", "s", "utf-8", "high")
    b = Hit("K", "java", "a.java", 10, "direct", "比較", "", "", "", "K@a.java:10", "s", "utf-8", "high")
    assert sorted([b, a], key=sort_key) == [a, b]
