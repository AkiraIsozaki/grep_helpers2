"""診断の集約とスキーマ（spec §10.3: カテゴリ別件数サマリ＋詳細）。"""

from grep_analyzer.diagnostics import Diagnostics


def test_カテゴリ別件数サマリが先頭に来る():
    d = Diagnostics()
    d.add("bad_grep_line", "input/k.grep:5")
    d.add("bad_grep_line", "input/k.grep:9")
    d.add("decode_replaced", "src/a.c")
    text = d.render()
    lines = text.splitlines()
    assert lines[0] == "# summary"
    assert "bad_grep_line\t2" in text
    assert "decode_replaced\t1" in text
    assert "# detail" in text
