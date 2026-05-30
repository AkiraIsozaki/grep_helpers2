from grep_analyzer.fixedpoint._encmemo import EncMemo


def test_EncMemoは件数上限で古いものを退避():
    m = EncMemo(max_entries=2)
    m["a"] = ("cp932", False); m["b"] = ("euc-jp", False)
    assert m.get("a") == ("cp932", False)
    m["c"] = ("utf-8", False)            # b を退避（a は直近 get で延命）
    assert m.get("b") is None and m.get("a") is not None and m.get("c") is not None
