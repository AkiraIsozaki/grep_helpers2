"""A-5: ワーカ走査の per-file 例外降格（読めないファイルで run 全体を落とさない）。"""

from grep_analyzer import automaton
from grep_analyzer.fixedpoint._scan import _scan_one


def test_読めないファイルは例外でなく空ヒットを返す(tmp_path):
    missing = tmp_path / "ghost.java"            # walk 後に消えた想定（存在しない）
    auto = automaton.build(["K1"])
    rel, enc, replaced, lang, dialect, found = _scan_one(
        "ghost.java", str(missing), auto, {}, ["cp932", "euc-jp", "latin-1"])
    assert rel == "ghost.java"
    assert found == []                            # 例外送出せず空


def test_読めるファイルは従来どおりヒットを返す(tmp_path):
    f = tmp_path / "A.java"
    f.write_text("int K1 = 1;\n", "utf-8")
    auto = automaton.build(["K1"])
    rel, enc, replaced, lang, dialect, found = _scan_one(
        "A.java", str(f), auto, {}, ["cp932", "euc-jp", "latin-1"])
    assert any(sym == "K1" for sym, *_ in found)
