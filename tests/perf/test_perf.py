"""非ゲート perf ベースライン（spec §11・@pytest.mark.perf）。"""

import resource
import time
import pytest
from grep_analyzer.cli import main
from tests.perf.corpus_gen import generate


@pytest.mark.perf
@pytest.mark.parametrize("n", [200, 400, 800])
def test_scale(tmp_path, n):
    src = tmp_path / "src"; generate(src, seed=1, n_files=n)
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "S0.grep").write_text("pkg0/C0.java:1:S0\n", "utf-8")
    out = tmp_path / "o"
    t0 = time.perf_counter()
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    dt = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"PERF n={n} dt={dt:.3f}s rss_kb={rss}")


@pytest.mark.perf
@pytest.mark.parametrize("hits_per_file", [50, 200])
def test_high_hit_density(tmp_path, hits_per_file):
    """高ヒット密度＝1 ファイルに多数の direct ヒット（grep はファイル単位でまとまる）。

    direct パスのファイル単位キャッシュ（読込/復号/言語判定/tree-sitter パース）の
    効きを単離するため、ヒット行は追跡シンボルを生まないコメント行にして不動点を
    不活性化する（旧実装はヒット毎にファイル全体を再読込・2 回再パースしていた）。
    """
    n_files = 20
    src = tmp_path / "src"
    src.mkdir()
    grep_lines = []
    for f in range(n_files):
        body = ["class C%d {" % f]
        for i in range(hits_per_file):
            body.append("  // KW marker %d" % i)
        body.append("}")
        (src / f"C{f}.java").write_text("\n".join(body) + "\n", "utf-8")
        for i in range(hits_per_file):
            lineno = i + 2                       # class 行の次から
            grep_lines.append(f"C{f}.java:{lineno}:  // KW marker {i}")

    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "KW.grep").write_text("\n".join(grep_lines) + "\n", "utf-8")
    out = tmp_path / "o"
    t0 = time.perf_counter()
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    dt = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    total = n_files * hits_per_file
    print(f"PERF density files={n_files} hits/file={hits_per_file} "
          f"total_hits={total} dt={dt:.3f}s rss_kb={rss}")


@pytest.mark.perf
@pytest.mark.parametrize("n", [300, 600])
def test_fixedpoint_heavy(tmp_path, n):
    """不動点多ホップの実測。corpus は相互参照(u{i}=S{ref})で連鎖を作るため、
    実ファイル行を seed にすると extract_chase_symbols が連鎖を起動する
    (test_calibrate_items_per_mb と同じ起動条件)。"""
    from tests.perf.corpus_gen import generate
    src = tmp_path / "src"; generate(src, seed=7, n_files=n)
    c0_line = (src / "pkg0" / "C0.java").read_text("utf-8").splitlines()[0]
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "S0.grep").write_text(f"pkg0/C0.java:1:{c0_line}\n", "utf-8")
    out = tmp_path / "o"
    t0 = time.perf_counter()
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    dt = time.perf_counter() - t0
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    print(f"PERF fixedpoint n={n} dt={dt:.3f}s rss_kb={rss}")


@pytest.mark.perf
def test_calibrate_items_per_mb(tmp_path, monkeypatch):
    """`_ITEMS_PER_MB` 較正の具体手順（実行可能・非ゲート）。

    重要: `estimate_items` は `fixedpoint.py` の全呼出が `if not
    budget.unlimited` 配下。既定 `--memory-limit` 無
    （budget.unlimited=True）では **一度も呼ばれない**。よって較正は
    **十分大きい有限 `--memory-limit`** を与え budget 経路を有効化しつつ
    degrade を発火させない（exceeded=False のまま実 item を計測）。
    spy 0 回なら計測不能として **明示的に FAIL** させる。
    """
    import tracemalloc
    from grep_analyzer import budget as _b

    seen = []
    real = _b.estimate_items

    def _spy(*, n_symbols, n_edges, n_intro):
        v = real(n_symbols=n_symbols, n_edges=n_edges, n_intro=n_intro)
        seen.append(v)
        return v

    # _budget_control は `from grep_analyzer import budget as _budget`（モジュール
    # 属性参照）ゆえ budget モジュール側の属性を差し替える。
    monkeypatch.setattr("grep_analyzer.budget.estimate_items", _spy)

    src = tmp_path / "src"; generate(src, seed=7, n_files=600)
    # grep 入力のスニペットは実ファイル行を使用 → extract_chase_symbols がシンボルを抽出
    c0_line = (src / "pkg0" / "C0.java").read_text("utf-8").splitlines()[0]
    inp = tmp_path / "in"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "S0.grep").write_text(f"pkg0/C0.java:1:{c0_line}\n", "utf-8")
    out = tmp_path / "o"
    BIG_LIMIT_MB = 100_000          # budget 経路有効化・degrade 非発火に十分大
    tracemalloc.start()
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src),
          "--memory-limit", str(BIG_LIMIT_MB)])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert seen, ("estimate_items が呼ばれていない＝較正不能。"
                  "--memory-limit 指定で budget 経路を有効化すること")
    max_items = max(seen)
    bytes_per_item = peak / max_items
    items_per_mb = int(1_048_576 // max(1.0, bytes_per_item))
    print(f"CALIB peak_bytes={peak} max_items={max_items} "
          f"bytes_per_item={bytes_per_item:.1f} ITEMS_PER_MB={items_per_mb}")
    assert items_per_mb > 0
