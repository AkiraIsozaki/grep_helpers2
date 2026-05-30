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


def test_pipeline_lockstepは複数keywordで各TSV逐次版一致(tmp_path):
    """複数 keyword の lock-step 出力が逐次版（各 keyword 単独 run）と byte 同値であり、
    かつ indirect 経路を実際に駆動することを検証する（Phase4 U3 レビュー反映）。

    コーパスは両 keyword が SHARED シンボル（ALPHA/BETA 両定数を宣言する Const.java:1）を
    seed し、OVERLAPPING ファイル（UseA/UseB）へ chase する形にしてある:
    - ALPHA は ALPHA/BETA を chase → UseA(ALPHA) と UseB(BETA) に hit
    - BETA も ALPHA/BETA を chase → UseA(ALPHA) と UseB(BETA) に hit
    これにより run_fixedpoint_multi の hop ループ本体（union 走査・cross-keyword chase・
    per-keyword absorb）が実走する。旧コーパス（K1=1/K2=2 の int リテラル）は indirect が
    一切出ず、ループ本体を一度も実行しなかった（lockstep エンジン未検証）。
    """
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "Const.java").write_text(
        "class Const { public static final int ALPHA = 1; public static final int BETA = 2; }\n", "utf-8")
    (src / "UseA.java").write_text("class UseA { int x = Const.ALPHA; }\n", "utf-8")
    (src / "UseB.java").write_text("class UseB { int y = Const.BETA; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "ALPHA.grep").write_text("Const.java:1:    public static final int ALPHA = 1;\n", "utf-8")
    (inp / "BETA.grep").write_text("Const.java:1:    public static final int BETA = 2;\n", "utf-8")
    out_new = tmp_path / "new"; run(inp, out_new, src, _default_opts())
    out_seq = tmp_path / "seq"
    for kw in ("ALPHA", "BETA"):
        sub = tmp_path / f"in_{kw}"; sub.mkdir()
        (sub / f"{kw}.grep").write_text((inp / f"{kw}.grep").read_text("utf-8"), "utf-8")
        run(sub, out_seq, src, _default_opts())
    alpha_new = (out_new / "ALPHA.tsv").read_bytes()
    beta_new = (out_new / "BETA.tsv").read_bytes()
    assert alpha_new == (out_seq / "ALPHA.tsv").read_bytes()
    assert beta_new == (out_seq / "BETA.tsv").read_bytes()
    # lockstep ループ本体が実走したことの保証: 各 TSV に indirect 行（chain は ` -> ` を含む）が
    # 存在する。将来 zero-indirect なコーパスに退行しても silently pass しないようロックする。
    assert b"indirect:" in alpha_new and b" -> " in alpha_new, \
        "ALPHA.tsv に indirect 行が無い（lockstep ループ本体が実走していない）"
    assert b"indirect:" in beta_new and b" -> " in beta_new, \
        "BETA.tsv に indirect 行が無い（lockstep ループ本体が実走していない）"


def test_pipeline_lockstep_resume済keywordは再finalizeされない(tmp_path):
    """opts.resume=True で完了済 keyword は再 finalize されず（mtime 不変）、
    resume_skipped 診断が出る。他 keyword は通常処理される。"""
    import dataclasses
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text(
        "class A { static final int K1=1; int a=K1; static final int K2=2; int b=K2; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:    static final int K1=1;\n", "utf-8")
    (inp / "K2.grep").write_text("A.java:1:    static final int K2=2;\n", "utf-8")
    out = tmp_path / "o"
    # 1回目: 通常 run で K1/K2 両方の完了出力（manifest 含む）を生成。
    run(inp, out, src, _default_opts())
    from grep_analyzer import resume
    resume_opts = dataclasses.replace(_default_opts(), resume=True)
    assert resume.is_complete(out, "K1", resume_opts), "前提崩れ: K1 が完了判定されない"
    # K1 の TSV mtime を記録 → resume run 後に不変であること（再 finalize 無し）を確認。
    k1_path = out / "K1.tsv"
    k1_mtime = k1_path.stat().st_mtime_ns
    # K2 を再処理させるため manifest を消す（未完了化）。
    (out / "K2.manifest.json").unlink()
    # 2回目: resume=True。K1 はスキップ、K2 は再処理。
    run(inp, out, src, resume_opts)
    assert k1_path.stat().st_mtime_ns == k1_mtime, "K1 が再 finalize された（resume スキップ失敗）"
    diag = (out / "diagnostics.txt").read_text("utf-8")
    assert any(ln == "resume_skipped\tK1" for ln in diag.splitlines()), \
        "resume_skipped 診断に K1 が無い"
    assert (out / "K2.tsv").read_bytes(), "K2 が再処理されていない"
