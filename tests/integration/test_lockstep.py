"""lock-step 共有エンジン run_fixedpoint_multi の単一keyword同値テスト（Phase4 Task3）。

単一 keyword の multi パスは逐次版 run_fixedpoint と byte 同値でなければならない
（spec §4.1）。golden(92) byte 不変の最小単位検証。
"""

# §6.2＝§8.4 走査構造依存・全件性対象外（rev.2 C-2連鎖で確定した固定の除外集合）。
# lock-step の diagnostics detail/件数が逐次版併合と一致する保証から外れる唯一のカテゴリ。
EXCLUDED_FROM_PARITY = frozenset({"automaton_split", "graph_spilled"})


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


def _parse_diagnostics(text):
    """diagnostics.txt を (summary: dict[cat,int], detail: dict[cat,list[str]]) に分解する。

    render 形式は `# summary` 区画にカテゴリ別件数（`cat\\tN`）、`# detail` 区画に
    `cat\\tmessage`（message 自体に \\t を含むことがある＝最初の \\t のみで分割）。
    """
    summary: dict[str, int] = {}
    detail: dict[str, list[str]] = {}
    section = None
    for ln in text.splitlines():
        if ln == "# summary":
            section = "summary"
            continue
        if ln == "# detail":
            section = "detail"
            continue
        if not ln:
            continue
        cat, _, msg = ln.partition("\t")
        if section == "summary":
            summary[cat] = int(msg)
        elif section == "detail":
            detail.setdefault(cat, []).append(msg)
    return summary, detail


def test_lockstep_diagnostics順序が逐次版と一致_除外automaton_split_graph_spilled(tmp_path):
    """lock-step diagnostics.txt のカテゴリ別 detail 順・SUMMARY 件数が、各 keyword を
    単独 run した逐次版を sorted keyword 順に併合したものと一致する（Phase4 Task5）。

    §6.2＝§8.4 走査構造依存・全件性対象外の `automaton_split` と `graph_spilled` のみ
    比較対象から除外する（rev.2 C-2連鎖で確定した固定の除外集合）:
    - automaton_split は GLOBAL hop ごとに全 keyword の diag へ1回ずつ発火するため、
      逐次版の per-keyword 発火（keyword ごとの local hop で個別発火）とは detail も件数も
      構造的に異なる。
    - graph_spilled の `hop={hop}` は lock-step では global hop 番号、逐次版では local hop
      番号であり一致しない。
    これら走査構造に依存する2カテゴリ以外（decode_replaced / symbol_rejected /
    missing_source / bad_grep_line 等）は merge_in_order により逐次版と byte 一致しなければ
    ならない（pipeline.py §6 の併合が逐次版の単一 diag 追記順を再現する保証のロック）。

    本コーパスが実際に産出する非除外カテゴリ:
      bad_grep_line / decode_replaced / missing_source / symbol_rejected。
    """
    import dataclasses
    from grep_analyzer.pipeline import run, _default_opts
    from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes

    src = tmp_path / "src"; src.mkdir()
    # ALPHA 定数定義（chase の起点）。同じ行に short var x を置き symbol_rejected(too_short) を誘発。
    (src / "Const.java").write_text(
        "class Const { public static final int ALPHA = 1; int x; }\n", "utf-8")
    # ALPHA を参照しつつ short var v/q を導入（symbol_rejected を更に発生させる）。
    (src / "UseA.java").write_text(
        "class UseA { int v = Const.ALPHA; int q = x; }\n", "utf-8")
    # chase 中に走査されるが symbol 非ヒットの replaced=True ファイル → decode_replaced。
    bad_bytes = "class Zz { int ALPHA; }\n".encode("utf-8") + b"// \x80\x81\xff\n"
    (src / "Bad.java").write_bytes(bad_bytes)
    _, _, replaced = decode_bytes(bad_bytes, DEFAULT_FALLBACK)
    assert replaced, "前提崩れ: Bad.java が replaced=True で復号されない"

    inp = tmp_path / "in"; inp.mkdir()
    # ALPHA.grep: 正常行＋欠落ソース行(missing_source)＋コロン無し行(bad_grep_line)。
    (inp / "ALPHA.grep").write_text(
        "Const.java:1:    public static final int ALPHA = 1;\n"
        "MISSING.java:5:something here\n"
        "garbage line no colon\n", "utf-8")
    (inp / "BETA.grep").write_text(
        "Const.java:1:    public static final int ALPHA = 1;\n", "utf-8")

    # use_ripgrep=False ＝テスト対象の OFF 経路（prefilter で relpath を脱落させない）。
    opts = dataclasses.replace(_default_opts(), jobs=1, use_ripgrep=False)

    out_new = tmp_path / "new"
    assert run(inp, out_new, src, opts) == 0
    ls_summary, ls_detail = _parse_diagnostics(
        (out_new / "diagnostics.txt").read_text("utf-8"))

    # 逐次版相当: 各 keyword を単独入力 dir で run し、sorted keyword 順に併合。
    seq_summary: dict[str, int] = {}
    seq_detail: dict[str, list[str]] = {}
    for kw in sorted(("ALPHA", "BETA")):
        sub = tmp_path / f"in_{kw}"; sub.mkdir()
        (sub / f"{kw}.grep").write_text((inp / f"{kw}.grep").read_text("utf-8"), "utf-8")
        out_kw = tmp_path / f"seq_{kw}"
        assert run(sub, out_kw, src, opts) == 0
        s, d = _parse_diagnostics((out_kw / "diagnostics.txt").read_text("utf-8"))
        for c, n in s.items():
            seq_summary[c] = seq_summary.get(c, 0) + n
        for c, msgs in d.items():
            seq_detail.setdefault(c, []).extend(msgs)

    # 本テストが意図したカバレッジ（コーパスが退行して空にならないことのロック）。
    produced = set(ls_detail) - EXCLUDED_FROM_PARITY
    assert {"bad_grep_line", "decode_replaced", "missing_source",
            "symbol_rejected"} <= produced, \
        f"コーパスが想定カテゴリを産出していない: {sorted(produced)}"

    # 非除外カテゴリの DETAIL 順が逐次版併合と完全一致すること。
    for cat in sorted((set(ls_detail) | set(seq_detail)) - EXCLUDED_FROM_PARITY):
        assert ls_detail.get(cat, []) == seq_detail.get(cat, []), (
            f"非除外カテゴリ {cat} の detail が逐次版と不一致:\n"
            f"  lock-step={ls_detail.get(cat, [])}\n"
            f"  sequential={seq_detail.get(cat, [])}")

    # 非除外カテゴリの SUMMARY 件数も一致すること。
    for cat in sorted((set(ls_summary) | set(seq_summary)) - EXCLUDED_FROM_PARITY):
        assert ls_summary.get(cat, 0) == seq_summary.get(cat, 0), (
            f"非除外カテゴリ {cat} の summary 件数が不一致: "
            f"lock-step={ls_summary.get(cat, 0)} sequential={seq_summary.get(cat, 0)}")
