"""方言伝播と非シェルシェバン診断の境界契約（spec §5.1/§7/§8.4）。"""

from pathlib import Path

from grep_analyzer.pipeline import run


def test_csh拡張子は方言cshellで分類されshell言語で出力される(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "r.csh").write_text('set CODE = "X"\n', "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "CODE.grep").write_text('r.csh:1:set CODE = "X"\n', "utf-8")
    out = tmp_path / "out"
    assert run(input_dir=inp, output_dir=out, source_root=src) == 0
    tsv = (out / "CODE.tsv").read_text("utf-8-sig").splitlines()
    row = dict(zip(tsv[0].split("\t"), tsv[1].split("\t")))
    assert row["language"] == "shell"
    assert row["category"] == "代入"
    assert row["confidence"] == "medium"


def test_拡張子なしpythonシェバンはpythonとして認識し診断しない(tmp_path: Path):
    # python は track A で追加済み（shebang_language=="python"）＝unsupported_shebang を出さない
    src = tmp_path / "src"
    src.mkdir()
    (src / "tool").write_text("#!/usr/bin/python3\nx='X'\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "X.grep").write_text("tool:2:x='X'\n", "utf-8")
    out = tmp_path / "out"
    assert run(input_dir=inp, output_dir=out, source_root=src) == 0
    assert "unsupported_shebang" not in (out / "diagnostics.txt").read_text("utf-8")


def test_拡張子なしperlシェバンはunsupported_shebangを出さない(tmp_path: Path):
    # perl は track B で language=perl に解決＝診断しない（誤記録回帰防止・C-H）
    src = tmp_path / "src"
    src.mkdir()
    (src / "tool").write_text("#!/usr/bin/perl\nmy $x='X';\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "X.grep").write_text("tool:2:my $x='X';\n", "utf-8")
    out = tmp_path / "out"
    assert run(input_dir=inp, output_dir=out, source_root=src) == 0
    assert "unsupported_shebang" not in (out / "diagnostics.txt").read_text("utf-8")


def test_既知拡張子の非シェルシェバンは診断しない(tmp_path: Path):
    # spec §5.1: 手順2 で言語確定する既知拡張子は手順3 に来ない＝unsupported_shebang
    # は出さない（手順3 到達時のみ記録。負の契約）。
    src = tmp_path / "src"
    src.mkdir()
    (src / "weird.c").write_text("#!/usr/bin/perl\nint x;\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "X.grep").write_text("weird.c:2:int x;\n", "utf-8")
    out = tmp_path / "out"
    assert run(input_dir=inp, output_dir=out, source_root=src) == 0
    assert "unsupported_shebang" not in (out / "diagnostics.txt").read_text("utf-8")
