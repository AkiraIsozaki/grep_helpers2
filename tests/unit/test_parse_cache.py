"""tree-sitter parse 共有キャッシュの契約（perf リファクタ・出力不変前提）。

これらは「同一 (file, language) のパースを 1 回に集約する」最適化を駆動する
決定的テスト群。出力バイト不変は golden が別途保証する。
"""

import tree_sitter


def _count_parses(monkeypatch):
    """tree_sitter.Parser.parse の呼出回数カウンタを仕込み dict を返す。"""
    calls = {"n": 0}
    real = tree_sitter.Parser.parse

    def counting(self, *a, **k):
        calls["n"] += 1
        return real(self, *a, **k)

    monkeypatch.setattr(tree_sitter.Parser, "parse", counting)
    return calls


def test_parse_tree_cache_は同一言語で1回だけparseする(monkeypatch):
    from grep_analyzer.classifiers.ts_classifier import parse_tree

    src = "class C {\n int a = 1;\n int b = 2;\n}\n"
    cache: dict = {}
    calls = _count_parses(monkeypatch)
    r1 = parse_tree("java", src, cache=cache)
    r2 = parse_tree("java", src, cache=cache)
    assert calls["n"] == 1          # 2 回目はキャッシュ命中
    assert r1 is r2


def test_parse_tree_cache_未指定は毎回parseする(monkeypatch):
    from grep_analyzer.classifiers.ts_classifier import parse_tree

    src = "class C {\n int a = 1;\n}\n"
    calls = _count_parses(monkeypatch)
    parse_tree("java", src)
    parse_tree("java", src)
    assert calls["n"] == 2          # cache 無指定は従来どおり


def test_parse_tree_cache_は言語キーで別木を保持する():
    """同一 source・同一 cache でも language が異なれば別の木を返す（キー分離）。

    特に typescript（host_source=恒等）と angular_inline（host_source で inline
    template 以外を空白化）は同一ソースから別の木になる必要がある。
    """
    from grep_analyzer.classifiers.ts_classifier import parse_tree

    src = ('@Component({ template: `<b (click)="v=1">x</b>` })\n'
           'export class C { v = 0; }\n')
    cache: dict = {}
    r_ts = parse_tree("typescript", src, cache=cache)
    r_ang = parse_tree("angular_inline", src, cache=cache)
    assert set(cache) == {"typescript", "angular_inline"}
    assert r_ts is not r_ang
    # 再取得は各キーでキャッシュ命中（同一オブジェクト）。
    assert parse_tree("typescript", src, cache=cache) is r_ts
    assert parse_tree("angular_inline", src, cache=cache) is r_ang


def test_classify_hit_と_build_snippet_は同一cacheで1回のparseを共有する(monkeypatch):
    from grep_analyzer.classify import classify_hit
    from grep_analyzer.snippet import build_snippet

    src = "class C {\n  int a = 1;\n  int b = 2;\n}\n"
    cache: dict = {}
    calls = _count_parses(monkeypatch)
    # 同一 java ファイルの同一行に対する分類＋スニペット切出。
    classify_hit("java", "bourne", src, 2, "  int a = 1;", cache=cache)
    build_snippet("java", "bourne", src, 2, cache=cache)
    # 異なる行でも同一ファイル＝同一 cache なら再 parse しない。
    classify_hit("java", "bourne", src, 3, "  int b = 2;", cache=cache)
    build_snippet("java", "bourne", src, 3, cache=cache)
    assert calls["n"] == 1
