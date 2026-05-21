"""TSV サニタイズ規約のユニットテスト（spec §9 規約①）。"""

from grep_analyzer.tsv import sanitize_field


def test_拡張空白文字を半角空白へ():
    assert sanitize_field("a\tb\rc\nd\x0be\x0cf\x85g h i") == \
        "a b c d e f g h i"


def test_U2028_U2029も空白化_spec11名指し集合():
    assert sanitize_field("a b c") == "a b c"


def test_通常文字とU2026マーカは保持():
    assert sanitize_field("…(+3上行省略) X") == "…(+3上行省略) X"
