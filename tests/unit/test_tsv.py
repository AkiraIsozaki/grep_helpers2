"""TSV出力: 決定的ソート・タブ改行サニタイズ・原子的書込・BOM規則（spec §9/§10.3）。"""

from pathlib import Path

from grep_analyzer.model import Hit
from grep_analyzer.tsv import write_tsv


def _h(file, lineno, snippet="s"):
    return Hit("K", "java", file, lineno, "direct", "比較", "", "u", "", f"K@{file}:{lineno}", snippet, "utf-8", "high")


def test_出力はヘッダ付きで決定的にソートされる(tmp_path: Path):
    out = tmp_path / "K.tsv"
    write_tsv(out, [_h("b.java", 1), _h("a.java", 2)], "utf-8-sig")
    raw = out.read_bytes()
    assert raw[:3] == b"\xef\xbb\xbf"  # UTF-8 BOM
    rows = raw.decode("utf-8-sig").splitlines()
    assert rows[0].split("\t")[0] == "keyword"
    assert rows[1].split("\t")[2] == "a.java"
    assert rows[2].split("\t")[2] == "b.java"


def test_非UTF8出力ではBOMを付けない(tmp_path: Path):
    out = tmp_path / "K.tsv"
    write_tsv(out, [_h("a.java", 1)], "cp932")
    assert out.read_bytes()[:3] != b"\xef\xbb\xbf"


def test_セル内タブと改行は空白化され列数が保たれる(tmp_path: Path):
    from grep_analyzer.model import TSV_COLUMNS

    out = tmp_path / "K.tsv"
    write_tsv(out, [_h("a.java", 1, snippet="x\ty\nz")], "utf-8-sig")
    data_row = out.read_text("utf-8-sig").splitlines()[1]
    cells = data_row.split("\t")
    assert len(cells) == len(TSV_COLUMNS)  # サニタイズで列がズレない
    assert cells[TSV_COLUMNS.index("snippet")] == "x y z"
