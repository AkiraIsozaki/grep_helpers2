"""決定的ツリー走査の仕様（spec §8.2）。外部I/O境界＝実FS本物。"""

import os

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.walk import DEFAULT_EXCLUDE, walk_files


def _walk(root, **kw):
    diag = Diagnostics()
    kw.setdefault("include", [])
    kw.setdefault("exclude", list(DEFAULT_EXCLUDE))
    kw.setdefault("follow_symlinks", False)
    kw.setdefault("max_file_bytes", 1_000_000)
    return [r for r, _ in walk_files(root, diag=diag, **kw)], diag


def test_走査は相対パス昇順で決定的(tmp_path):
    (tmp_path / "b.c").write_text("x", "utf-8")
    (tmp_path / "a.c").write_text("y", "utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "c.c").write_text("z", "utf-8")
    assert _walk(tmp_path)[0] == ["a.c", "b.c", "sub/c.c"]


def test_生成コードは既定除外しトップでも深くても効き診断記録(tmp_path):
    for rel in ("target/Gen.java", "a/b/build/X.c", "src/Keep.java"):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("x", "utf-8")
    rels, diag = _walk(tmp_path)
    assert rels == ["src/Keep.java"] and "walk_excluded" in diag.render()


def test_バイナリと巨大ファイルはskipし診断記録(tmp_path):
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01CODE")
    (tmp_path / "big.c").write_text("a" * 50, "utf-8")
    (tmp_path / "ok.c").write_text("CODE", "utf-8")
    diag = Diagnostics()
    rels = [r for r, _ in walk_files(tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
            follow_symlinks=False, max_file_bytes=10, diag=diag)]
    assert rels == ["ok.c"]
    d = diag.render()
    assert "walk_skipped_binary" in d and "walk_skipped_large" in d


def test_includeグロブ指定時は一致のみ(tmp_path):
    (tmp_path / "a.java").write_text("x", "utf-8")
    (tmp_path / "b.txt").write_text("y", "utf-8")
    assert _walk(tmp_path, include=["*.java"])[0] == ["a.java"]


def test_symlinkは既定で辿らず実体重複は辞書順代表のみ(tmp_path):
    (tmp_path / "real.c").write_text("CODE", "utf-8")
    os.symlink(tmp_path / "real.c", tmp_path / "link.c")
    rels, diag = _walk(tmp_path)
    assert rels == ["real.c"] and "symlink_skipped" in diag.render()


from grep_analyzer.walk import collect_files


def test_collect_filesは走査一度materializeしrelpath昇順(tmp_path):
    (tmp_path / "b.c").write_text("x", "utf-8")
    (tmp_path / "a.c").write_text("y", "utf-8")
    diag = Diagnostics()
    got = collect_files(tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
                        follow_symlinks=False, max_file_bytes=1_000_000, diag=diag)
    assert [r for r, _ in got] == ["a.c", "b.c"]
    assert all(hasattr(p, "is_file") for _, p in got)


def test_collect_filesの診断は一回だけ(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "G.c").write_text("x", "utf-8")
    (tmp_path / "k.c").write_text("y", "utf-8")
    d = Diagnostics()
    collect_files(tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
                  follow_symlinks=False, max_file_bytes=1_000_000, diag=d)
    assert d.render().count("walk_excluded\tbuild/G.c") == 1


import os

from grep_analyzer.walk import walk_files
from grep_analyzer.diagnostics import Diagnostics


def test_dirシンボリックリンクのループを枝刈りして再走査しない(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    (root / "a.c").write_text("int x=1;\n", "utf-8")
    sub = root / "sub"; sub.mkdir()
    (sub / "b.c").write_text("int y=1;\n", "utf-8")
    os.symlink(root, sub / "loop")               # sub/loop -> root（ディレクトリ循環）
    diag = Diagnostics()
    rels = [r for r, _ in walk_files(
        root, include=[], exclude=[], follow_symlinks=True,
        max_file_bytes=5_000_000, diag=diag)]
    # 実ファイルは relpath 辞書順で決定的に1回ずつ
    assert rels == ["a.c", "sub/b.c"]
    # 枝刈りの観測可能効果: ループ配下を再走査しない＝symlink_dedup が発火しない。
    # （fix 前は Linux の ELOOP で約40段まで降り loop 配下を再走査→symlink_dedup 多数）
    assert diag._counts.get("symlink_dedup", 0) == 0


from grep_analyzer.walk import _classify_bytes


def test_classify_NUL含みはbinary():
    assert _classify_bytes(b"abc\x00def") == "binary"


def test_classify_utf16BOMはunsafe():
    assert _classify_bytes(b"\xff\xfe" + "漢字".encode("utf-16-le")) == "unsafe"
    assert _classify_bytes(b"\xfe\xff") == "unsafe"            # UTF-16-BE BOM
    assert _classify_bytes(b"\xff\xfe\x00\x00") == "unsafe"    # UTF-32-LE BOM


def test_classify_純ASCIIはok():
    assert _classify_bytes(b"int CODE = 1;\n") == "ok"


def test_collect_files_exはtotalbytesとunsafeを返す(tmp_path):
    from grep_analyzer.walk import collect_files_ex
    from grep_analyzer.diagnostics import Diagnostics
    (tmp_path / "a.c").write_text("int CODE=1;\n", "utf-8")          # ok
    (tmp_path / "u.c").write_bytes(b"\xff\xfe" + "漢=1".encode("utf-16-le"))  # unsafe
    (tmp_path / "b.bin").write_bytes(b"x\x00y")                       # binary skip
    files, total, unsafe = collect_files_ex(
        tmp_path, include=[], exclude=[], follow_symlinks=False,
        max_file_bytes=5_000_000, diag=Diagnostics())
    rels = {r for r, _ in files}
    assert "a.c" in rels and "u.c" in rels and "b.bin" not in rels
    assert "u.c" in unsafe and "a.c" not in unsafe
    assert total == (tmp_path / "a.c").stat().st_size + (tmp_path / "u.c").stat().st_size


def test_collect_files_exはlargeを除外しtotalに含めずbinary診断を発火(tmp_path):
    from grep_analyzer.walk import collect_files_ex
    from grep_analyzer.diagnostics import Diagnostics
    (tmp_path / "ok.c").write_text("int CODE=1;\n", "utf-8")
    (tmp_path / "big.c").write_text("x" * 5000, "utf-8")              # max 超で除外
    (tmp_path / "b.bin").write_bytes(b"x\x00y")                       # binary skip
    diag = Diagnostics()
    files, total, unsafe = collect_files_ex(
        tmp_path, include=[], exclude=[], follow_symlinks=False,
        max_file_bytes=1000, diag=diag)
    rels = {r for r, _ in files}
    assert rels == {"ok.c"}                                          # large/binary は脱落
    assert total == (tmp_path / "ok.c").stat().st_size               # large は total に含めない
    rendered = diag.render(detail_limit=1000, exempt=frozenset())
    assert "walk_skipped_large" in rendered and "big.c" in rendered  # large 診断
    assert "walk_skipped_binary" in rendered and "b.bin" in rendered # binary 診断
