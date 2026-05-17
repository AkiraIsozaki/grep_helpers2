"""Aho-Corasick ラッパの仕様（spec §8.2・識別子境界一致）。"""

from grep_analyzer.automaton import build, scan_line


def test_語境界一致のみ採用し部分文字列は拾わない():
    au = build(["CODE", "v_code"])
    assert scan_line(au, "int CODE; x = DECODE(v_code);") == ["CODE", "v_code"]
    assert scan_line(au, "DECODES = ENCODED;") == []


def test_同一行の複数一致は昇順ユニークで返す():
    au = build(["A", "BB"])
    assert scan_line(au, "BB and A and A and BB") == ["A", "BB"]


def test_空集合と空文字シンボルはNoneあるいは除去():
    assert build([]) is None and build(["", ""]) is None
    assert scan_line(None, "anything") == []
    assert scan_line(build(["", "CODE"]), "CODE") == ["CODE"]


def test_先頭末尾と記号隣接の境界():
    au = build(["CODE"])
    assert scan_line(au, "CODE") == ["CODE"]
    assert scan_line(au, "$CODE)") == ["CODE"]
    assert scan_line(au, "xCODE") == [] and scan_line(au, "CODEx") == []
