"""TSV サニタイズ規約のユニットテスト（spec §9 規約①）。"""

from grep_analyzer.tsv import _sanitize


def test_拡張空白文字を半角空白へ():
    assert _sanitize("a\tb\rc\nd\x0be\x0cf\x85g h i") == \
        "a b c d e f g h i"


def test_U2028_U2029も空白化_spec11名指し集合():
    assert _sanitize("a b c") == "a b c"


def test_通常文字とU2026マーカは保持():
    assert _sanitize("…(+3上行省略) X") == "…(+3上行省略) X"
