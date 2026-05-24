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


@pytest.mark.requires_ripgrep
def test_非ASCII_symbolは無効化される_出力不変保証(tmp_path):
    """symbol は復号テキスト由来。非 ASCII symbol は非 UTF-8 ファイルでバイト不一致と
    なり rg が automaton ヒット行を取りこぼす（出力不変違反）。非 ASCII を含む場合は
    None（＝全件走査）にフォールバックして取りこぼしを防ぐ。"""
    # latin-1 で 'caféVar=1'（生バイト != UTF-8）。automaton は復号テキストでヒットする。
    (tmp_path / "a.sh").write_bytes("caféVar=1".encode("latin-1") + b"\n")
    got = prefilter(tmp_path, {"a.sh": tmp_path / "a.sh"}, ["caféVar"])
    assert got is None                       # 非 ASCII symbol → prefilter 無効化（全件走査）
    # ASCII symbol が混在しても、非 ASCII が 1 つでもあれば全体を無効化する。
    assert prefilter(tmp_path, {"a.sh": tmp_path / "a.sh"}, ["x", "caféVar"]) is None


@pytest.mark.requires_ripgrep
def test_非UTF8ファイル名で落ちず正しく一致する(tmp_path):
    """SJIS 等の非 UTF-8 ファイル名を rg が生バイトで出力しても、bytes 受け＋
    os.fsdecode で walk の relpath 表現と一致させ、UnicodeDecodeError で落とさない。"""
    import os
    name = os.fsdecode("コード.sh".encode("cp932"))   # 非 UTF-8 ファイル名（FS 表現）
    (tmp_path / name).write_text("getName=1\n", "utf-8")
    (tmp_path / "other.sh").write_text("nope=1\n", "utf-8")
    rel_abs = {name: tmp_path / name, "other.sh": tmp_path / "other.sh"}
    got = prefilter(tmp_path, rel_abs, ["getName"])   # 例外を出さない
    assert got is not None and name in got and "other.sh" not in got
