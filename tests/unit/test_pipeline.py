"""Ingest→dispatch→classify→TSV の direct-only パイプライン（spec §15 フェーズ1）。"""

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
    assert row["file"] == "A.java"
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
