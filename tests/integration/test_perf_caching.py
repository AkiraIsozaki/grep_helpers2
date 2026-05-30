"""perf リファクタの振る舞い保証（end-to-end・出力不変は golden が別途担保）。

ここでは「同一ファイルへの複数ヒットで tree-sitter parse / automaton 構築が
ヒット数に比例して増えない（ファイル単位 1 回に集約される）」ことを決定的に検証する。
"""

from pathlib import Path

import pytest
import tree_sitter

from grep_analyzer.pipeline import _default_opts, run


def _count_parses(monkeypatch):
    calls = {"n": 0}
    real = tree_sitter.Parser.parse

    def counting(self, *a, **k):
        calls["n"] += 1
        return real(self, *a, **k)

    monkeypatch.setattr(tree_sitter.Parser, "parse", counting)
    return calls


def _run_java_comment_hits(tmp_path, monkeypatch, n_hits):
    """1 つの java ファイルへ n_hits 件のコメント行ヒットを与え parse 回数を返す。

    コメント行ヒットは chase シンボルを生まない＝不動点スキャンが起動しない
    （automaton 走査由来の parse ノイズを排除）。残る parse は direct パスと
    seed 取込のファイル単位処理のみ。
    """
    src = tmp_path / "src"
    pkg = src / "pkg"
    pkg.mkdir(parents=True)
    body = ["class C {"]
    for i in range(n_hits):
        body.append(f"  // KW marker {i}")
    body.append("}")
    java = pkg / "C.java"
    java.write_text("\n".join(body) + "\n", "utf-8")

    inp = tmp_path / "in"
    inp.mkdir()
    grep_lines = [f"pkg/C.java:{i + 2}:  // KW marker {i}" for i in range(n_hits)]
    (inp / "KW.grep").write_text("\n".join(grep_lines) + "\n", "utf-8")

    out = tmp_path / "o"
    calls = _count_parses(monkeypatch)
    rc = run(input_dir=inp, output_dir=out, source_root=src, opts=_default_opts())
    assert rc == 0
    return calls["n"]


def test_direct_path_は同一ファイルへのヒット数に比例して再parseしない(tmp_path, monkeypatch):
    one = _run_java_comment_hits(tmp_path / "a", monkeypatch, 1)
    many = _run_java_comment_hits(tmp_path / "b", monkeypatch, 8)
    # ファイル単位で parse を集約していればヒット数によらず一定。
    assert one == many


def test_finalize_build_snippet_はoccurrence単位でchain数に比例しない(tmp_path, monkeypatch):
    from grep_analyzer.fixedpoint import _finalize

    calls = {"n": 0}
    real = _finalize.build_snippet

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    # _finalize モジュールが参照する build_snippet のみ差し替え（direct パスは別参照）。
    monkeypatch.setattr(_finalize, "build_snippet", counting)

    case = Path(__file__).resolve().parents[1] / "golden" / "cases" / "chain_multipath"
    out = tmp_path / "o"
    rc = run(input_dir=case / "input", output_dir=out,
             source_root=case / "src", opts=_default_opts())
    assert rc == 0
    rows = (out / "KSEED.tsv").read_text("utf-8-sig").splitlines()[1:]
    indirect = [ln for ln in rows if "\tindirect" in ln]
    # multipath: 同一 occurrence が複数 chain で到達する＝indirect Hit 数 > occurrence 数。
    # build_snippet が occurrence 単位なら呼出回数は indirect Hit 数より厳密に小さい。
    assert indirect, "indirect Hit が無い＝ケース前提が崩れている"
    assert calls["n"] < len(indirect)


def test_automaton_はチャンク単位で構築されファイル数に比例しない(tmp_path, monkeypatch):
    from grep_analyzer import automaton

    n_ref = 10
    src = tmp_path / "src"
    src.mkdir(parents=True)
    # 定数 KW を seed とし、多数のファイルが KW を参照（call のみ＝新規シンボル非生成
    # で 1 hop で飽和）。hop1 で全ファイルを 1 チャンク走査する構成。
    (src / "A.java").write_text("class A { static final int KW = 1; }\n", "utf-8")
    for i in range(n_ref):
        (src / f"B{i}.java").write_text(
            f"class B{i} {{ void m(){{ use(KW); }} }}\n", "utf-8")

    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "KW.grep").write_text("A.java:1:class A { static final int KW = 1; }\n", "utf-8")

    calls = {"n": 0}
    real = automaton.build

    def counting(symbols):
        calls["n"] += 1
        return real(symbols)

    monkeypatch.setattr(automaton, "build", counting)
    out = tmp_path / "o"
    rc = run(input_dir=inp, output_dir=out, source_root=src, opts=_default_opts())
    assert rc == 0
    # 走査ファイル数（>=11）に比例して automaton を再構築しないこと。
    assert calls["n"] < n_ref


def test_direct_path_は同一ファイルへのヒット数に比例して物理行分割しない(tmp_path, monkeypatch):
    import grep_analyzer.snippet as snip
    calls = {"n": 0}
    real = snip._physical_lines

    def spy(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(snip, "_physical_lines", spy)

    def run_hits(sub, n):
        s = tmp_path / sub / "src"; (s / "pkg").mkdir(parents=True)
        body = ["class C {"] + [f"  // KW {i}" for i in range(n)] + ["}"]
        (s / "pkg" / "C.java").write_text("\n".join(body) + "\n", "utf-8")
        i_ = tmp_path / sub / "in"; i_.mkdir(parents=True)
        (i_ / "KW.grep").write_text(
            "\n".join(f"pkg/C.java:{i + 2}:  // KW {i}" for i in range(n)) + "\n", "utf-8")
        calls["n"] = 0
        run(input_dir=i_, output_dir=tmp_path / sub / "o", source_root=s, opts=_default_opts())
        return calls["n"]

    assert run_hits("a", 1) == run_hits("b", 8)   # ヒット数に依らず一定


def test_missing_source_は欠落ファイルへのヒット数ぶん発火する(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "KW.grep").write_text(
        "no/such.java:1:KW\nno/such.java:2:KW\nno/such.java:3:KW\n", "utf-8")
    out = tmp_path / "o"
    run(input_dir=inp, output_dir=out, source_root=src, opts=_default_opts())
    diag = (out / "diagnostics.txt").read_text("utf-8")
    summary = {}
    in_sum = False
    for ln in diag.splitlines():
        if ln == "# summary":
            in_sum = True; continue
        if ln == "# detail":
            break
        if in_sum and "\t" in ln:
            k, v = ln.split("\t", 1); summary[k] = v
    assert summary.get("missing_source") == "3"


def test_FileCache_はLRUとbyte予算で退避する():
    from grep_analyzer.fixedpoint._scan import _FileCache
    c = _FileCache(budget=10)                  # text 長 10 文字ぶんのみ常駐可
    meta = lambda s: (s, "utf-8", False, "java", "bourne")
    c.put("a", meta("aaaaa"))                  # 5
    c.put("b", meta("bbbbb"))                  # +5 = 10（ちょうど）
    assert c.get("a") is not None and c.get("b") is not None
    c.put("c", meta("ccccc"))                  # +5 → 15 超過 → LRU(a) 退避
    assert c.get("a") is None                  # a は退避済み
    assert c.get("b") is not None and c.get("c") is not None


def test_read_meta_は同一abspathを2回読まない(tmp_path, monkeypatch):
    from grep_analyzer.fixedpoint import _scan
    f = tmp_path / "C.java"
    f.write_text("class C { int KW = 1; }\n", "utf-8")
    calls = {"n": 0}
    real = _scan.file_meta

    def spy(*a, **k):
        calls["n"] += 1
        return real(*a, **k)

    monkeypatch.setattr(_scan, "file_meta", spy)
    cache = _scan._FileCache()
    a = _scan._read_meta("C.java", str(f), {}, ["cp932"], cache)
    b = _scan._read_meta("C.java", str(f), {}, ["cp932"], cache)
    assert a == b
    assert calls["n"] == 1                      # 2 回目はキャッシュ命中


def test_scan_はsymbol非ヒットのファイルをparseしない(tmp_path, monkeypatch):
    """automaton 0 ヒットのファイルは tree-sitter parse されない（lazy parse）。
    rg prefilter で対象が絞られると区別不能になるため use_ripgrep=False で単離。"""
    import dataclasses
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { static final int KW = 1; }\n", "utf-8")
    n_noise = 12
    for i in range(n_noise):
        (src / f"N{i}.java").write_text(f"class N{i} {{ int z{i} = {i}; }}\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "KW.grep").write_text(
        "A.java:1:class A { static final int KW = 1; }\n", "utf-8")
    calls = _count_parses(monkeypatch)
    opts = dataclasses.replace(_default_opts(), use_ripgrep=False)
    rc = run(input_dir=inp, output_dir=tmp_path / "o", source_root=src, opts=opts)
    assert rc == 0
    # KW を含まない N*.java は parse されない（残るは A.java の direct/seed 数件のみ）。
    assert calls["n"] < n_noise


def test_診断は同一ファイルでもヒット行ごとに発火する(tmp_path):
    """direct パスのファイル単位キャッシュ導入後も、診断はヒット行ごとに発火する
    （§10.3 の件数を 1 回化していないことの回帰ロック）。

    キャッシュ済フラグ経由で発火する unsupported_shebang を用いる（拡張子無し＋
    非対応 shebang で決定的に発火。同一ファイルへの 3 ヒットで件数 3 を要求）。
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "script").write_text(
        "#!/usr/bin/env ruby\nputs KW\nputs KW\nputs KW\n", "utf-8")

    n_hits = 3
    inp = tmp_path / "in"
    inp.mkdir()
    grep_lines = [f"script:{i + 2}:puts KW" for i in range(n_hits)]
    (inp / "KW.grep").write_text("\n".join(grep_lines) + "\n", "utf-8")

    out = tmp_path / "o"
    rc = run(input_dir=inp, output_dir=out, source_root=src, opts=_default_opts())
    assert rc == 0
    diag = (out / "diagnostics.txt").read_text("utf-8")
    summary, in_summary = {}, False
    for ln in diag.splitlines():
        if ln == "# summary":
            in_summary = True
            continue
        if ln == "# detail":
            break
        if in_summary and "\t" in ln:
            cat, cnt = ln.split("\t", 1)
            summary[cat] = cnt
    # ファイル単位キャッシュでも 1 回化せず、ヒット数ぶん発火する。
    assert summary.get("unsupported_shebang") == str(n_hits)
    # detail 区間の行もヒット数ぶん（カテゴリ内順序＝grep 行順を保持）。
    detail_text = diag.split("# detail", 1)[1]
    detail = [ln for ln in detail_text.splitlines()
              if ln.startswith("unsupported_shebang\t")]
    assert len(detail) == n_hits


def test_pool_はrun単位で1回だけ生成される(tmp_path, monkeypatch):
    """jobs>1 の複数 hop でも Pool 生成は 1 回（chunk×hop 再生成しない）。"""
    import dataclasses
    from grep_analyzer.fixedpoint import _lockstep
    from tests.perf.corpus_gen import generate
    src = tmp_path / "src"; generate(src, seed=7, n_files=60)
    c0 = (src / "pkg0" / "C0.java").read_text("utf-8").splitlines()[0]
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "S0.grep").write_text(f"pkg0/C0.java:1:{c0}\n", "utf-8")

    n_pools = {"n": 0}
    real = _lockstep.make_pool

    def spy(opts):
        p = real(opts)
        if p is not None:
            n_pools["n"] += 1
        return p

    # _lockstep は `from ..._scan import make_pool` で名前を束縛し bare 呼出するため、
    # 利用箇所（_lockstep モジュール名前空間）の make_pool を差し替える。
    monkeypatch.setattr(_lockstep, "make_pool", spy)
    opts = dataclasses.replace(_default_opts(), jobs=2)
    rc = run(input_dir=inp, output_dir=tmp_path / "o", source_root=src, opts=opts)
    assert rc == 0
    assert n_pools["n"] == 1


def test_jobs2の出力はjobs1とbyte一致(tmp_path):
    """並列でも TSV byte 一致（§9 並列完了順非依存）。同一 source_root を共有して
    出力中の絶対パスを揃え、2 つの output dir を直接比較する。"""
    import dataclasses
    from tests.perf.corpus_gen import generate
    src = tmp_path / "src"; generate(src, seed=7, n_files=60)
    c0 = (src / "pkg0" / "C0.java").read_text("utf-8").splitlines()[0]
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "S0.grep").write_text(f"pkg0/C0.java:1:{c0}\n", "utf-8")

    def run_jobs(jobs):
        out = tmp_path / f"o{jobs}"
        run(input_dir=inp, output_dir=out, source_root=src,
            opts=dataclasses.replace(_default_opts(), jobs=jobs))
        return (out / "S0.tsv").read_text("utf-8-sig")

    assert run_jobs(1) == run_jobs(2)


@pytest.mark.requires_ripgrep
def test_rg_optinは非ASCIIシンボル_非UTF8で出力不変(tmp_path):
    """--use-ripgrep（opt-in）が非 ASCII chase シンボル＋非 UTF-8 ファイルでも
    出力 byte を変えない回帰ロック。修正前は rg が automaton ヒット行を取りこぼし、
    indirect ヒットが欠落＝出力不変違反だった（spec §9・対象は SJIS 混在環境）。"""
    import dataclasses
    src = tmp_path / "src"; src.mkdir()
    (src / "def.sh").write_text("caféVar=1\n", "utf-8")            # seed 元（UTF-8）
    (src / "use.sh").write_bytes("echo $caféVar\n".encode("latin-1"))  # 非 UTF-8 参照
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("def.sh:1:caféVar=1\n", "utf-8")

    def go(rg):
        out = tmp_path / f"o_{rg}"
        run(input_dir=inp, output_dir=out, source_root=src,
            opts=dataclasses.replace(_default_opts(), use_ripgrep=rg))
        return (out / "K.tsv").read_text("utf-8-sig")

    off = go(False)
    assert "use.sh" in off, "前提崩れ: rg OFF でも indirect が出ていない"
    assert go(True) == off                                          # rg ON == rg OFF（byte）
