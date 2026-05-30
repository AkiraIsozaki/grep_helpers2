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


def test_use_ripgrep既定はNone_閾値判定():
    """rg prefilter は既定=閾値判定(None)。フラグ無しは None で、実効可否は
    後段（threshold+availability）で決まる。明示 True/False のみ強制（spec rev.2）。"""
    from grep_analyzer.cli import _build_opts
    o = _build_opts(["--input", "i", "--output", "o", "--source-root", "s"])
    assert o.use_ripgrep is None


def test_use_ripgrepで明示ON():
    from grep_analyzer.cli import _build_opts
    o = _build_opts(["--input", "i", "--output", "o", "--source-root", "s", "--use-ripgrep"])
    assert o.use_ripgrep is True


def test_grep入力の絶対パスはsource_root外を読まない(tmp_path):
    from grep_analyzer.cli import main
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ int x=1; }\n", "utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP_SECRET_TOKEN\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    # 絶対パスと .. トラバーサルの両方を仕込む
    (inp / "x.grep").write_text(
        f"{secret}:1:TOP_SECRET_TOKEN\n"
        f"../../secret.txt:1:TOP_SECRET_TOKEN\n", "utf-8")
    out = tmp_path / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    tsv = (out / "x.tsv").read_text("utf-8-sig")
    assert "TOP_SECRET_TOKEN" not in tsv          # 秘密の内容が漏れない
    assert str(secret) not in tsv
    diag = (out / "diagnostics.txt").read_text("utf-8")
    assert "missing_source" in diag               # 拒否は診断へ


import os


def test_grep入力のdir_symlink経由でroot外を読まない(tmp_path):
    from grep_analyzer.cli import main
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ int x=1; }\n", "utf-8")
    secret = tmp_path / "secret"; secret.mkdir()
    (secret / "token.txt").write_text("TOP_SECRET_TOKEN\n", "utf-8")
    os.symlink(secret, src / "link")          # src 配下に外向き dir symlink
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "x.grep").write_text("link/token.txt:1:TOP_SECRET_TOKEN\n", "utf-8")
    out = tmp_path / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    tsv = (out / "x.tsv").read_text("utf-8-sig")
    assert "TOP_SECRET_TOKEN" not in tsv       # symlink 越えの内容が漏れない
    diag = (out / "diagnostics.txt").read_text("utf-8")
    assert "missing_source" in diag
