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


def test_同一終端で部分一致は境界規則で一意に排除される():
    """CODE と DECODE が同一 index で終端共有。iter() 列挙順に依らず
    CODE は直前 'E'（識別子）で排除され DECODE のみ。pyahocorasick の
    版差（同一終端の列挙順）を吸収する回帰（spec v10・2.3.1）。"""
    au = build(["CODE", "DECODE"])
    assert scan_line(au, "x DECODE y") == ["DECODE"]
    assert scan_line(au, "a=DECODE; b=CODE;") == ["CODE", "DECODE"]


def test_非ASCII隣接でも文字index境界判定が成立する():
    """`end` は文字 index・境界は line[start-1]/line[end+1]（文字）。
    多バイト/非ASCII 隣接でも語境界成立を固定。将来版が byte offset を
    返す回帰（line[end+1] の誤 index 化）を検出する（spec v10）。"""
    au = build(["var"])
    assert scan_line(au, "日本語 var 日本語") == ["var"]
    assert scan_line(au, "あvarい") == ["var"]
    assert scan_line(au, "α=var=β") == ["var"]
    assert scan_line(au, "xvarあ") == []  # 直前が ASCII 識別子→排除
