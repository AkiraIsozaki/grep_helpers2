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


from grep_analyzer.diagnostics import Diagnostics, _MAX_RETAINED


def test_詳細保持はカテゴリごとに上限化されカウントは全件():
    d = Diagnostics()
    n = _MAX_RETAINED + 50
    for i in range(n):
        d.add("prov_cycle_cut", f"e{i}")        # 免除カテゴリでも保持は上限内
    assert d._counts["prov_cycle_cut"] == n      # summary は真総数
    assert len(d._detail["prov_cycle_cut"]) <= _MAX_RETAINED
    text = d.render(detail_limit=0)              # 無制限指定でも保持上限で OOM しない
    assert f"prov_cycle_cut\t{n}" in text         # summary 行は真総数
    assert "retained" in text                     # 保持打ち切りマーカが出る


def test_保持上限内は従来どおり全件詳細():
    d = Diagnostics()
    d.add("decode_replaced", "a.c")
    d.add("decode_replaced", "b.c")
    text = d.render(detail_limit=0)
    assert "decode_replaced\ta.c" in text
    assert "decode_replaced\tb.c" in text
    assert "retained" not in text
