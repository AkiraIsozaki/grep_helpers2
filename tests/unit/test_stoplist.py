"""静的シンボル採否ポリシーの仕様（spec §8.3・cap は大域で fixedpoint 側）。"""

from grep_analyzer.stoplist import SymbolPolicy, admit, load_stoplist


def _pol(min_spec=2, stop=frozenset()):
    return SymbolPolicy(min_specificity=min_spec, user_stoplist=stop)


def test_言語キーワードは採用しない():
    r = admit(["if", "STATUS_OK", "class"], "java", _pol())
    assert r.accepted == ["STATUS_OK"]
    assert ("if", "keyword") in r.rejected and ("class", "keyword") in r.rejected


def test_最小長未満は採用しない():
    r = admit(["x", "ab", "abc"], "c", _pol(min_spec=3))
    assert r.accepted == ["abc"]
    assert ("x", "too_short") in r.rejected and ("ab", "too_short") in r.rejected


def test_ユーザストップリストは採用しない():
    r = admit(["FOO", "BAR"], "c", _pol(stop=frozenset({"BAR"})))
    assert r.accepted == ["FOO"] and ("BAR", "user_stoplist") in r.rejected


def test_順序保存で採否しcapはここで行わない():
    r = admit(["zzz", "ab", "yy"], "c", _pol(min_spec=1))
    assert r.accepted == ["zzz", "ab", "yy"]


def test_ストップリストファイルは空行とコメントを無視する(tmp_path):
    f = tmp_path / "stop.txt"
    f.write_text("# c\nFOO\n\n  BAR  \n", "utf-8")
    assert load_stoplist(f) == frozenset({"FOO", "BAR"})
    assert load_stoplist(None) == frozenset()


from grep_analyzer.chase import ChaseSymbols
from grep_analyzer.stoplist import partition


def test_getterとsetterは横展開せずterminalへ回す():
    cs = ChaseSymbols(constants=("STATUS_OK",), vars=("count",), getters=("getName",), setters=("setX",))
    p = partition(cs, "java", _pol(min_spec=2))
    assert p.chase == ["STATUS_OK", "count"]
    assert p.terminal == ["getName", "setX"] and p.rejected == []


def test_terminalにもキーワード最小長は効く():
    cs = ChaseSymbols(getters=("getX",), setters=("set",))
    p = partition(cs, "java", _pol(min_spec=4))
    assert p.terminal == ["getX"] and ("set", "too_short") in p.rejected
