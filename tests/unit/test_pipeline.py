"""Ingest→dispatch→classify→TSV の direct-only パイプライン（spec §15 フェーズ1）。"""

import os
from pathlib import Path

from grep_analyzer.pipeline import run


def test_grepヒットを分類してキーワード毎TSVを出力する(tmp_path: Path):
    src_root = tmp_path / "src"
    src_root.mkdir()
    (src_root / "A.java").write_text(
        'class A {\n void m(){\n  if (s.equals("STATUS_OK")) {}\n }\n}\n', "utf-8"
    )
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "STATUS_OK.grep").write_text("A.java:3:  if (s.equals(\"STATUS_OK\")) {}\n", "utf-8")
    out = tmp_path / "out"

    rc = run(input_dir=inp, output_dir=out, source_root=src_root)

    assert rc == 0
    tsv = (out / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()
    cols = tsv[0].split("\t")
    row = dict(zip(cols, tsv[1].split("\t")))
    assert row["keyword"] == "STATUS_OK"
    assert row["language"] == "java"
    # 再ベースライン理由A: file 列は spec v9 §9 で {source_root.resolve()}/rel へ絶対化
    assert row["file"] == f"{Path(src_root).resolve()}/A.java"
    assert row["lineno"] == "3"
    assert row["ref_kind"] == "direct"
    assert row["category"] == "比較"
    assert row["confidence"] == "high"
    assert row["chain"] == "STATUS_OK@A.java:3"
    assert (out / "diagnostics.txt").exists()


def test_壊れたgrep行は捨てず診断に回る(tmp_path: Path):
    (tmp_path / "src").mkdir()
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "K.grep").write_text("this line has no lineno\n", "utf-8")
    out = tmp_path / "out"
    rc = run(input_dir=inp, output_dir=out, source_root=tmp_path / "src")
    assert rc == 0
    assert "bad_grep_line" in (out / "diagnostics.txt").read_text("utf-8")
    assert (out / "K.tsv").exists()


def test_SJIS混在ファイル名でも診断書き込みが落ちない(tmp_path: Path):
    # SJIS(cp932) でエンコードした日本語名のソースを生バイトで作る。Linux では
    # os.walk が surrogateescape でデコードし、relpath str に孤立サロゲートが混じる。
    # これが diagnostics.txt の strict UTF-8 書き込みで落ちていた（surrogates not allowed）。
    src_root = tmp_path / "src"
    src_root.mkdir()
    raw = b"bin_" + "表".encode("cp932") + b".dat"      # \x95 が UTF-8 として不正
    with open(os.path.join(os.fsencode(src_root), raw), "wb") as f:
        f.write(b"\x00\x01\x02")                          # binary → walk_skipped_binary
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "K.grep").write_text("x:1:y\n", "utf-8")
    out = tmp_path / "out"

    rc = run(input_dir=inp, output_dir=out, source_root=src_root)

    assert rc == 0
    data = (out / "diagnostics.txt").read_text("utf-8")    # 純UTF-8で読み戻せる
    assert "walk_skipped_binary" in data
    assert "\\udc" in data                                  # backslashreplace で可視化


def test_SJIS名ソースでもis_fileが当たりヒット行が出る(tmp_path: Path):
    # grep 出力のパスは生 SJIS バイト。os.fsdecode で FS 一致させ、missing_source 脱落
    # （＝ヘッダのみ TSV）を防ぐ。パス文字列のテキスト復号では UTF-8 FS と一致しない。
    src = tmp_path / "src"
    src.mkdir()
    name = "あ.java".encode("cp932")                    # b'\x82\xa0.java'（UTF-8 不正）
    java = 'class A {\n void m(){\n  if (s.equals("STATUS_OK")) {}\n }\n}\n'
    with open(os.path.join(os.fsencode(src), name), "wb") as f:
        f.write(java.encode("cp932"))
    inp = tmp_path / "in"
    inp.mkdir()
    (inp / "STATUS_OK.grep").write_bytes(
        name + b':3:  if (s.equals("STATUS_OK")) {}\n')
    out = tmp_path / "out"

    rc = run(input_dir=inp, output_dir=out, source_root=src)

    assert rc == 0
    tsv = (out / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()
    assert len(tsv) == 2                                  # ヘッダ + データ1行（脱落しない）
    row = dict(zip(tsv[0].split("\t"), tsv[1].split("\t")))
    assert row["language"] == "java"
    assert row["category"] == "比較"
    assert row["lineno"] == "3"
    assert "missing_source" not in (out / "diagnostics.txt").read_text("utf-8")


def test_file列は絶対_chainは相対_snippetは構文単位(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text(
        'class A {\n  static final String K =\n    "K";\n}\n', "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("A.java:2:  static final String K =\n", "utf-8")
    out = tmp_path / "out"
    assert run(inp, out, src) == 0
    cells = (out / "K.tsv").read_text("utf-8-sig").splitlines()[1].split("\t")
    resolved = str(Path(src).resolve())
    assert cells[2] == f"{resolved}/A.java"                  # file 絶対
    assert cells[9] == "K@A.java:2"                           # chain 相対維持
    assert cells[10] == '  static final String K = \\n     "K";'  # snippet 多行
