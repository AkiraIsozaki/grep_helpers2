from grep_analyzer.fixedpoint._encmemo import EncMemo


def test_EncMemoは件数上限で古いものを退避():
    m = EncMemo(max_entries=2)
    m["a"] = ("cp932", False); m["b"] = ("euc-jp", False)
    assert m.get("a") == ("cp932", False)
    m["c"] = ("utf-8", False)            # b を退避（a は直近 get で延命）
    assert m.get("b") is None and m.get("a") is not None and m.get("c") is not None


def test_read_metaはenc_memo経由でchardetを2回目回避(tmp_path, monkeypatch):
    import grep_analyzer.encoding as enc
    from grep_analyzer.fixedpoint._scan import _read_meta
    from grep_analyzer.fixedpoint._encmemo import EncMemo
    calls = {"n": 0}; real = enc.chardet.detect
    monkeypatch.setattr(enc.chardet, "detect",
                        lambda b: calls.__setitem__("n", calls["n"] + 1) or real(b))
    f = tmp_path / "a.c"; f.write_bytes("int x=1; // あ".encode("euc-jp") + b"\n")
    em = EncMemo()
    _read_meta("a.c", str(f), {}, ["cp932", "euc-jp", "latin-1"], cache=None, enc_memo=em)
    _read_meta("a.c", str(f), {}, ["cp932", "euc-jp", "latin-1"], cache=None, enc_memo=em)
    assert calls["n"] == 1


def test_read_meta_enc_memo経路はfile_metaと同一5タプル(tmp_path):
    from grep_analyzer.fixedpoint._scan import _read_meta, file_meta
    from grep_analyzer.fixedpoint._encmemo import EncMemo
    f = tmp_path / "x.java"; f.write_bytes("class X { int あ = 1; }".encode("cp932") + b"\n")
    raw = f.read_bytes()
    want = file_meta("x.java", raw, {}, fallback_chain=["cp932", "euc-jp", "latin-1"])
    got = _read_meta("x.java", str(f), {}, ["cp932", "euc-jp", "latin-1"], cache=None, enc_memo=EncMemo())
    assert got == want
