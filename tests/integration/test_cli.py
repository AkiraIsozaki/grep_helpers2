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
