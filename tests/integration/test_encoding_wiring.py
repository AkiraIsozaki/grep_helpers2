"""encoding 配線（spec v4 §4 WS4・3 decode 経路）。

検出原理の前提: `encoding.decode_bytes` は ① utf-8 厳格 → ② chardet 検出
→ ③ fallback 鎖 → ④ 末尾+replace（encoding.py:19-38）。短いソースは
chardet が高確信で確定し ③ に到達しないため、`--encoding-fallback` の
効果を観測するには **chardet を None 固定**して ③ を決定的に踏ませる
（spec §10.4「② フォールバック候補鎖のみ置換／① chardet は常に最初」
の挙動自体は不変利用＝テスト都合で ② を中立化するだけ・本番挙動不変）。
jobs 既定 1 ＝ pipeline/_scan_file は in-process ゆえ monkeypatch 伝播。
"""

from grep_analyzer.cli import main


def _no_chardet(monkeypatch):
    # ② chardet を None 固定 → ③ fallback 鎖を決定的に経由させる。
    monkeypatch.setattr("grep_analyzer.encoding.chardet.detect",
                        lambda data: {"encoding": None})


def _run(tmp_path, src_bytes, fallback):
    src = tmp_path / "src"; src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_bytes(b"class A{ String s=\"" + src_bytes + b"\"; }\n")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "K.grep").write_text("A.java:1:String s\n", "utf-8")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src),
          "--encoding-fallback", fallback])
    return (out / "K.tsv").read_text("utf-8-sig")


def test_fallback鎖差し替えが入力grepとdirectソースの出力を変える(
        tmp_path, monkeypatch):
    _no_chardet(monkeypatch)
    b = b"\x83\x65"                       # cp932「テ」/ latin-1 では別字
    a = _run(tmp_path / "a", b, "cp932,latin-1")   # cp932 厳格成功
    c = _run(tmp_path / "c", b, "latin-1")         # 末尾 latin-1+replace
    assert a != c   # 鎖が .grep/direct decode に届く（未配線なら両者
                    # DEFAULT(cp932..) で同一＝RED→配線で GREEN）


def test_indirect走査ソースのfallback鎖も届く(tmp_path, monkeypatch):
    _no_chardet(monkeypatch)
    # K は A.java で定義（非utf8バイト混入）、B.java から間接参照。
    # indirect hit の encoding は _file_meta（fixedpoint）走査側 decode 由来。
    def run1(root, fb):
        src = root / "src"; src.mkdir(parents=True, exist_ok=True)
        (src / "A.java").write_bytes(
            b"class A{ static final int K=1; String s=\"\x83\x65\"; }\n")
        (src / "B.java").write_bytes(b"class B{ int z=K; }\n")
        inp = root / "in"; inp.mkdir(parents=True, exist_ok=True)
        (inp / "K.grep").write_text("A.java:1:static final int K\n", "utf-8")
        out = root / "o"
        main(["--input", str(inp), "--output", str(out),
              "--source-root", str(src), "--encoding-fallback", fb])
        return (out / "K.tsv").read_text("utf-8-sig")
    assert run1(tmp_path / "p", "cp932,latin-1") != run1(tmp_path / "q", "latin-1")


def test_direct_indirectが同一鎖で一貫_かつ配線感応(tmp_path, monkeypatch):
    # 非DEFAULT結果になる鎖 "latin-1" を使う＝未配線(DEFAULT=cp932先頭)なら
    # encoding は cp932 となり expected{"latin-1 要確認"} と不一致＝RED、
    # 配線後は direct/indirect とも latin-1 で一貫＝GREEN（配線感応＋一貫性）。
    _no_chardet(monkeypatch)
    src = tmp_path / "src"; src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_bytes(
        b"class A{ static final int K=1; String s=\"\x83\x65\"; }\n")
    (src / "B.java").write_bytes(b"class B{ int z=K; }\n")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "K.grep").write_text("A.java:1:static final int K\n", "utf-8")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src),
          "--encoding-fallback", "latin-1"])
    rows = [r for r in (out / "K.tsv").read_text("utf-8-sig").splitlines()[1:]
            if r]
    encs = {r.split("\t")[11] for r in rows}         # encoding 列
    # " 要確認" 接尾辞の有無に依存しない頑健形: 全行が latin-1 系で 1 種
    # （direct/indirect 一貫）かつ cp932 でない（＝未配線 DEFAULT と区別）。
    assert len(encs) == 1 and next(iter(encs)).startswith("latin-1")
    assert "cp932" not in encs                        # 未配線なら cp932＝RED


def _split_fixture(root):
    # test_fixedpoint.py:212 と同型の「実際に automaton 分割が発火する」構成。
    # F.java（被走査ファイル）に非utf8バイト \x83\x65 を仕込む。
    root.mkdir(parents=True, exist_ok=True)
    (root / "A.java").write_bytes(b"class A{ static final int ZED=1; }\n")
    (root / "T.java").write_bytes(b"class T{ static final int ABE=2; }\n")
    (root / "F.java").write_bytes(
        b"class F{ static final int G1=ZED; static final int G2=ABE;"
        b" int u=G1; int w=G2; String s=\"\x83\x65\"; }\n")
    return root


def _run_split(tmp_path, fallback):
    src = _split_fixture(tmp_path / "src")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "ZED.grep").write_text("A.java:1:static final int ZED=1;\n", "utf-8")
    (inp / "ABE.grep").write_text("T.java:1:static final int ABE=2;\n", "utf-8")
    from grep_analyzer.cli import _build_opts
    from grep_analyzer.pipeline import run
    import dataclasses
    o = _build_opts(["--input", "i", "--output", "o", "--source-root", "s",
                     "--encoding-fallback", fallback])
    o = dataclasses.replace(o, force_chunks=3)   # 実際に automaton_split 発火
    out = tmp_path / "o"
    run(input_dir=inp, output_dir=out, source_root=src, opts=o)
    return (out / "ZED.tsv").read_text("utf-8-sig")


def test_空のencoding_fallbackは既定鎖に復帰しクラッシュしない(tmp_path, monkeypatch):
    # --encoding-fallback "" → opts.encoding_fallback==() 。chardet None 固定で
    # ③ 強制下、pipeline が [] を decode_bytes に渡すと IndexError クラッシュ。
    # _file_meta は空→DEFAULT_FALLBACK へ静かに復帰する。両経路を一致させ
    # （spec §10.1）、空指定でも既定鎖出力＝非クラッシュであることを検証。
    _no_chardet(monkeypatch)
    b = b"\x83\x65"
    src = tmp_path / "src"; src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_bytes(b"class A{ String s=\"" + b + b"\"; }\n")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "K.grep").write_text("A.java:1:String s\n", "utf-8")
    out = tmp_path / "o"
    # 空鎖でも例外を投げず 0 を返す
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src), "--encoding-fallback", ""]) == 0
    empty = (out / "K.tsv").read_text("utf-8-sig")
    # 既定鎖（DEFAULT_FALLBACK）と同一出力であること（_file_meta と一致）
    out2 = tmp_path / "o2"
    assert main(["--input", str(inp), "--output", str(out2),
                 "--source-root", str(src),
                 "--encoding-fallback", "cp932,euc-jp,latin-1"]) == 0
    assert empty == (out2 / "K.tsv").read_text("utf-8-sig")


def test_automaton分割発火構成でfallback鎖が届く(tmp_path, monkeypatch):
    # chardet 中立化で ③ 強制。force_chunks=3 で automaton_split を実発火
    # させた構成（test_fixedpoint.py:212 同型）で F.java を走査し、鎖が
    # decode 経路へ届けば 2 鎖で ZED.tsv が変わる。
    # 【検出範囲の明示・実測知見】本テストは「全 decode 経路が DEFAULT 化
    # （Task1 のみ＝未配線）か否か」を RED→GREEN で駆動する wiring スモーク
    # であり、`:248` 配線済で `:264` のみ漏れた状態を単独分離検出はしない
    # （F.java の最終 encoding/snippet は実コード上 :313 の indirect 再構成
    # ＋_scan_file enc_of 由来で表面化し :264 単独では不変なため）。
    # `:264` 配線必須は Step 3 で別途規定し、`pytest -q` 全緑＋分割 fixture
    # が分割経路を実行する事実で担保する（本テストは網羅保証でなく駆動用）。
    _no_chardet(monkeypatch)
    a = _run_split(tmp_path / "a", "cp932,latin-1")
    b = _run_split(tmp_path / "b", "latin-1")
    assert a != b   # 鎖が decode 経路へ届く（未配線=全DEFAULTなら同一＝RED）
