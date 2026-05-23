"""perl/groovy ヒューリスティック snippet 境界（spec §6）。"""

from grep_analyzer.snippet import build_snippet


def test_perlのsnippetは文末セミコロンで境界を取る():
    # src: 4行。ヒット行2（my $x = 1;）。
    # heuristic_span が動けば return $x; の行も含む複数行 snippet になる。
    # フォールバック (hit,hit) だと1行のみ＝return $x; は入らない。
    src = "sub f {\n    my $x = 1;\n    return $x;\n}\n"
    out = build_snippet("perl", "bourne", src, 2)   # my $x = 1; の行
    assert "my $x = 1;" in out
    # heuristic が機能すれば隣接行も取り込まれる（1行だけなら失敗）
    assert "return $x;" in out


def test_groovyのsnippetは波括弧で境界を取る():
    # src: 5行。ヒット行3（def x = compute()）。
    # heuristic_span が動けば def run() { の行も含む。
    # フォールバック (hit,hit) だと1行のみ＝def run() { は入らない。
    src = "class A {\n    def run() {\n        def x = compute()\n    }\n}\n"
    out = build_snippet("groovy", "bourne", src, 3)
    assert "def x = compute()" in out
    # heuristic が機能すれば上方向の def run() { も取り込まれる
    assert "def run()" in out
