"""CLI境界契約（spec §10.4）。in-process 既定。"""

from pathlib import Path

from grep_analyzer.cli import main


def test_必須引数で実行しexit0とTSVを返す(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "A.java").write_text('class A{String K="K";}\n', "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "K.grep").write_text('A.java:1:class A{String K="K";}\n', "utf-8")
    out = tmp_path / "out"
    rc = main([
        "--input", str(inp), "--output", str(out), "--source-root", str(tmp_path / "src"),
    ])
    assert rc == 0
    assert (out / "K.tsv").exists()


def test_use_ripgrep既定はOFF_optin():
    """rg prefilter は既定 OFF（opt-in）。rg 有無に依らずフラグ無しは False
    （実測で利得が確認できず既定 ON を撤回・phase3-perf-report.md）。"""
    from grep_analyzer.cli import _build_opts
    o = _build_opts(["--input", "i", "--output", "o", "--source-root", "s"])
    assert o.use_ripgrep is False


def test_use_ripgrepで明示ON():
    from grep_analyzer.cli import _build_opts
    o = _build_opts(["--input", "i", "--output", "o", "--source-root", "s", "--use-ripgrep"])
    assert o.use_ripgrep is True
