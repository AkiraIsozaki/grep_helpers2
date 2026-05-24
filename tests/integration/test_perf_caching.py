"""perf リファクタの振る舞い保証（end-to-end・出力不変は golden が別途担保）。

ここでは「同一ファイルへの複数ヒットで tree-sitter parse / automaton 構築が
ヒット数に比例して増えない（ファイル単位 1 回に集約される）」ことを決定的に検証する。
"""

from pathlib import Path

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
