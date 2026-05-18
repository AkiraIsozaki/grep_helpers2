from grep_analyzer.snippet import clamp_lines


def test_上限内はそのまま連結():
    assert clamp_lines(["a", "b", "c"], 1) == "a \\n b \\n c"


def test_行数上限超過は上下対称縮約し上下マーカ():
    lines = [f"L{i}" for i in range(11)]   # 0..10, hit=5
    assert clamp_lines(lines, 5, line_max=3) == \
        "…(+4上行省略)L4 \\n L5 \\n L6…(+4下行省略)"


def test_ヒット行単独が文字数上限超過はコードポイント切詰():
    assert clamp_lines(["x" * 50], 0, char_max=10) == "x" * 9 + "…"


def test_片側範囲端到達後は反対側のみ継続():
    assert clamp_lines(["A", "B", "C", "D", "E"], 1, line_max=3) == \
        "A \\n B \\n C…(+2下行省略)"
