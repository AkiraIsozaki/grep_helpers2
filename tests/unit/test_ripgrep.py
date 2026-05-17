"""任意 ripgrep 一次フィルタの仕様（spec §8.2・walk 上位集合・出力保存）。"""

from pathlib import Path

import pytest

from grep_analyzer.ripgrep import available, prefilter


def test_利用不可時はNoneでフィルタ無効(monkeypatch):
    monkeypatch.setattr("grep_analyzer.ripgrep._RG", None)
    assert available() is False
    assert prefilter(Path("."), {}, ["CODE"]) is None


@pytest.mark.requires_ripgrep
def test_部分文字列を含むrelの上位集合を返す(tmp_path):
    (tmp_path / "a.c").write_text("int CODE = 1;\n", "utf-8")
    (tmp_path / "b.c").write_text("int other = 2;\n", "utf-8")
    (tmp_path / "c.c").write_text("// DECODE\n", "utf-8")
    rel_abs = {p.name: p for p in tmp_path.glob("*.c")}
    got = prefilter(tmp_path, rel_abs, ["CODE"])
    assert "a.c" in got and "c.c" in got and "b.c" not in got


@pytest.mark.requires_ripgrep
def test_gitignore隠しNUL含みも上位集合に含む(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.c\n", "utf-8")
    (tmp_path / "ignored.c").write_text("int CODE=1;\n", "utf-8")
    (tmp_path / ".hidden.c").write_text("int CODE=2;\n", "utf-8")
    (tmp_path / "nul.c").write_bytes(b"int CODE=3;\n\x00trailer\n")
    (tmp_path / "visible.c").write_text("int CODE=4;\n", "utf-8")
    rel_abs = {n: tmp_path / n for n in
               ("ignored.c", ".hidden.c", "nul.c", "visible.c")}
    got = prefilter(tmp_path, rel_abs, ["CODE"])
    assert {"ignored.c", ".hidden.c", "nul.c", "visible.c"} <= got


@pytest.mark.requires_ripgrep
def test_空シンボルは空集合(tmp_path):
    assert prefilter(tmp_path, {}, []) == set()
