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


def test_read_meta_enc_memo経路はreplaced_Trueでもfile_metaと同一(tmp_path):
    from grep_analyzer.fixedpoint._scan import _read_meta, file_meta
    from grep_analyzer.fixedpoint._encmemo import EncMemo
    # utf-8/ascii(strict) を通らず latin-1 + replace に落ちるバイト列で replaced=True を強制。
    f = tmp_path / "y.c"; f.write_bytes(b"int x=1; \x81\xff\n")
    raw = f.read_bytes()
    want = file_meta("y.c", raw, {}, fallback_chain=["ascii", "latin-1"])
    assert want[2] is True                      # replaced フラグが実際に立つことを確認
    got = _read_meta("y.c", str(f), {}, ["ascii", "latin-1"], cache=None, enc_memo=EncMemo())
    assert got == want


def test_read_meta_enc_memo経路はshell方言分岐でもfile_metaと同一(tmp_path):
    from grep_analyzer.fixedpoint._scan import _read_meta, file_meta
    from grep_analyzer.fixedpoint._encmemo import EncMemo
    f = tmp_path / "s.sh"; f.write_bytes("#!/bin/bash\nx=1\n".encode("utf-8"))
    raw = f.read_bytes()
    want = file_meta("s.sh", raw, {}, fallback_chain=["cp932", "euc-jp", "latin-1"])
    assert want[3] == "shell"                   # dialect 分岐を実際に通ることを確認
    got = _read_meta("s.sh", str(f), {}, ["cp932", "euc-jp", "latin-1"], cache=None, enc_memo=EncMemo())
    assert got == want


def test_direct経路は同一ファイル複数keywordでchardet1回(tmp_path, monkeypatch):
    """run 共有 enc-memo で direct の同一ファイル再 chardet を抑止（jobs=1 in-process 限定）。"""
    import dataclasses
    import grep_analyzer.encoding as e
    calls = {"n": 0}; real = e.chardet.detect
    monkeypatch.setattr(e.chardet, "detect",
                        lambda b: calls.__setitem__("n", calls["n"] + 1) or real(b))
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_bytes("class A { int KCODE=1; int r=KCODE; } // あ".encode("euc-jp") + b"\n")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:KCODE\n", "utf-8")
    (inp / "K2.grep").write_text("A.java:1:KCODE\n", "utf-8")
    run(inp, tmp_path / "out", src, dataclasses.replace(_default_opts(), jobs=1))
    assert calls["n"] == 1               # euc-jp は utf-8-strict 不成立＝chardet が確定的に 1 回（jobs=1）


def test_chardet回数はユニークファイル数以下_cp932(tmp_path, monkeypatch):
    """run 共有 enc-memo で chardet 呼び出しが「ユニークファイル数」を超えないことを固定。

    jobs=1（in-process）限定：chardet spy は同一プロセス前提。並列の回数検証はしない
    （並列は worker 毎 _WORKER_ENC ＝プロセス跨ぎ共有不可）。spy は呼び出し回数カウンタ
    （len(b) ではない＝同長ファイル衝突による過小カウントを排除・rev.2 H-4）。
    """
    import dataclasses
    import grep_analyzer.encoding as e
    calls = {"n": 0}; real = e.chardet.detect
    monkeypatch.setattr(e.chardet, "detect",
                        lambda b: calls.__setitem__("n", calls["n"] + 1) or real(b))
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    for i in range(5):
        f = src / f"C{i}.java"
        f.write_bytes(f"class C{i} {{ int KCODE={i}; int r=KCODE; }} // 定数".encode("cp932") + b"\n")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("C0.java:1:KCODE\n", "utf-8")
    run(inp, tmp_path / "out", src, dataclasses.replace(_default_opts(), jobs=1))
    # cp932 ファイルは utf-8 strict 失敗で chardet 経路へ。ユニーク 5 ファイル以下。
    assert calls["n"] <= 5
