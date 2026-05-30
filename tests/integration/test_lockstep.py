"""lock-step 共有エンジン run_fixedpoint_multi の単一keyword同値テスト（Phase4 Task3）。

単一 keyword の multi パスは逐次版 run_fixedpoint と byte 同値でなければならない
（spec §4.1）。golden(92) byte 不変の最小単位検証。
"""


def test_multiは単一keywordで逐次版とindirect一致(tmp_path):
    from grep_analyzer.pipeline import _default_opts
    from grep_analyzer.fixedpoint import run_fixedpoint
    from grep_analyzer.fixedpoint._lockstep import run_fixedpoint_multi
    from grep_analyzer.fixedpoint._seed import initialize_state
    from grep_analyzer.diagnostics import Diagnostics
    from grep_analyzer.walk import collect_files
    from grep_analyzer.model import Hit
    src = tmp_path
    (src / "A.java").write_text(
        "class A { static final int KCODE=1; int r=KCODE; }\n", "utf-8")
    opts = _default_opts()
    seed = [Hit(keyword="K", language="java", file="A.java", lineno=1,
                ref_kind="direct", category="定義", category_sub="",
                usage_summary="", via_symbol="", chain="", snippet="",
                encoding="utf-8", confidence="high")]
    files = collect_files(src, include=[], exclude=[], follow_symlinks=False,
                          max_file_bytes=5_000_000, diag=Diagnostics())
    st1 = initialize_state(seed, src, opts, Diagnostics())
    seq = run_fixedpoint(seed, src, opts, st1.diagnostics, files=files)
    st2 = initialize_state(seed, src, opts, Diagnostics())
    multi = run_fixedpoint_multi({"K": st2}, src, opts, files=files,
                                 unsafe_rels=set(), enc_memo=None)["K"]
    assert [h.chain for h in seq] == [h.chain for h in multi]
    assert [h.file for h in seq] == [h.file for h in multi]


def test_単一keywordの走査済み非ヒットreplacedファイルのdecode_replacedが保たれる(tmp_path):
    """走査されたが symbol 非ヒットの replaced=True ファイルの decode_replaced 診断が
    lockstep 単一 keyword 経路で逐次版と byte 同値に保たれる回帰ロック（FIX 1）。

    rev.2 C-2 の「any found」絞り込みはこの relpath を pass_results から落とすため
    decode_replaced を欠落させた（golden 92 が見逃すケース）。FULL pass_results を
    absorb へ渡す修正で復活する。
    """
    import dataclasses
    from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
    from grep_analyzer.pipeline import _default_opts, run

    src = tmp_path / "src"
    src.mkdir()
    # hit file: seed の KCODE を含み chase を生む
    (src / "A.java").write_text(
        "class A { static final int KCODE=1; int r=KCODE; }\n", "utf-8")
    # no-hit file: latin-1 replace を強制する生バイト＋chase 記号を一切含まない
    b_bytes = "class Zqxj {}\n".encode("utf-8") + b"// \x80\x81\x82\x83\xfd\xfe\xff\n"
    (src / "B.java").write_bytes(b_bytes)
    # 前提検証: B.java は replaced=True で復号される
    _, _, replaced = decode_bytes(b_bytes, DEFAULT_FALLBACK)
    assert replaced, "前提崩れ: B.java が replaced=True で復号されない"

    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "KCODE.grep").write_text(
        "A.java:1:class A { static final int KCODE=1; int r=KCODE; }\n", "utf-8")

    # use_ripgrep=False ＝ B.java を必ず走査対象に残す（prefilter で脱落させない）
    out = tmp_path / "o"
    opts = dataclasses.replace(_default_opts(), jobs=1, use_ripgrep=False)
    rc = run(input_dir=inp, output_dir=out, source_root=src, opts=opts)
    assert rc == 0
    diag = (out / "diagnostics.txt").read_text("utf-8")
    detail = diag.split("# detail", 1)[1] if "# detail" in diag else diag
    assert any(ln.startswith("decode_replaced\t") and "B.java" in ln
               for ln in detail.splitlines()), \
        "走査済み・symbol 非ヒットの replaced ファイルの decode_replaced が欠落"
