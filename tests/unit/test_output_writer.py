"""output_writer の正規化関数（spec v4 §3 手順1・Inv-5）。"""

from grep_analyzer.model import Hit, TSV_COLUMNS
from grep_analyzer.output_writer import (
    _blob_from_data_rows, _canonical_data_blob, _data_line,
    _rows_from_part_text)


def _hit(file, lineno, snippet):
    return Hit(keyword="K", language="java", file=file, lineno=lineno,
               ref_kind="direct", category="c", category_sub="",
               usage_summary="u", via_symbol="", chain="ch",
               snippet=snippet, encoding="utf-8", confidence="low")


def test_canonical_blob_はsanitize後_split改行で安定():
    # sanitize_field は \t \r \n のみ空白化（U+2028 非対象）。split("\n") 固定ゆえ
    # U+2028 で水増しせず、かつ snippet 内タブは sanitize_field で空白化される。
    h = _hit("a.java", 1, "x y\tz")
    blob = _canonical_data_blob([h])
    assert blob.count(b"\n") == 0          # 1 データ行（U+2028 で割れない）
    assert blob == _data_line(h).encode("utf-8")          # sanitize 適用形と一致
    assert "\t" not in _data_line(h).split("\t", 12)[-1]  # snippet タブ空白化


def test_canonical_blob_末尾改行を含めない_空はゼロ長():
    assert _canonical_data_blob([]) == b""
    one = _canonical_data_blob([_hit("a", 1, "s")])
    assert not one.endswith(b"\n")


def test_書込側と完了判定側が同一関数_blob_from_data_rows_を共有():
    rows = [_hit("a", 1, "p"), _hit("b", 2, "q\tr")]
    blob = _canonical_data_blob(rows)
    # 先頭BOM＋ヘッダ＋sanitize後データ＋末尾改行（単一 part 相当）
    body = "﻿" + "\t".join(TSV_COLUMNS) + "\n" + "\n".join(
        _data_line(r) for r in rows) + "\n"
    data_rows = _rows_from_part_text(body)         # BOM/ヘッダ除去込み
    assert _blob_from_data_rows(data_rows) == blob  # 書込側と同一関数で一致


import json
from grep_analyzer.fixedpoint import EngineOptions
from grep_analyzer.output_writer import finalize


def _opts(**kw):
    base = dict(max_depth=10, min_specificity=2, stoplist_path=None,
                lang_map={}, include=[], exclude=[], jobs=1,
                follow_symlinks=False, max_file_bytes=5_000_000,
                max_symbols=100_000, max_paths=1000)
    base.update(kw)
    return EngineOptions(**base)


def _mk(n):
    return [_hit(f"f{i:05d}.java", i, f"s{i}") for i in range(n)]


def test_canonical_blob_サロゲート文字でも落ちずreplaceで潰れる():
    # surrogateescape 由来の孤立サロゲート（FS 走査由来の indirect パス等）を
    # 含む Hit でも data_sha256 用 encode が落ちない（strict UTF-8 だと crash）。
    h = _hit("a_\udc95.java", 1, "s")
    blob = _canonical_data_blob([h])
    assert b"a_?.java" in blob          # replace で "?" に潰れる


def test_finalize_サロゲートkeywordでもmanifestが落ちない(tmp_path):
    # keyword（=.grep ファイル名）にサロゲートが混じっても manifest json encode が
    # 落ちず、純UTF-8で読み戻せる。
    finalize(tmp_path, "K_\udc95", [], _opts())
    mfiles = list(tmp_path.glob("*.manifest.json"))
    assert mfiles
    m = json.loads(mfiles[0].read_text("utf-8"))   # 純UTF-8で復号できる
    assert m["keyword"] == "K_?"


def test_n0は単一ファイル_ヘッダのみ(tmp_path):
    finalize(tmp_path, "K", [], _opts())
    assert (tmp_path / "K.tsv").exists()
    assert not list(tmp_path.glob("K.part*"))
    m = json.loads((tmp_path / "K.manifest.json").read_text("utf-8"))
    assert m["total_rows"] == 0
    assert m["parts"] == [{"name": "K.tsv", "rows": 0}]


def test_n等しいLは単一_Lプラス1で2part_ゼロ詰め(tmp_path):
    finalize(tmp_path, "A", _mk(3), _opts(max_rows_per_part=3))
    assert (tmp_path / "A.tsv").exists()              # n==L → 単一
    finalize(tmp_path, "B", _mk(4), _opts(max_rows_per_part=3))
    names = sorted(p.name for p in tmp_path.glob("B.part*"))
    assert names == ["B.part01.tsv", "B.part02.tsv"]  # nparts=2 width=2
    assert not (tmp_path / "B.tsv").exists()


def test_part9はwidth2_part09(tmp_path):
    finalize(tmp_path, "N", _mk(9), _opts(max_rows_per_part=1))
    names = sorted(p.name for p in tmp_path.glob("N.part*"))
    assert names[0] == "N.part01.tsv" and names[-1] == "N.part09.tsv"
    assert "N.part9.tsv" not in names and len(names) == 9   # width=max(2,..)


def test_part100はwidth3_part001(tmp_path):
    finalize(tmp_path, "C", _mk(100), _opts(max_rows_per_part=1))
    names = sorted(p.name for p in tmp_path.glob("C.part*"))
    assert names[0] == "C.part001.tsv" and names[-1] == "C.part100.tsv"
    assert len(names) == 100


def test_連結データ_単一同値_Inv5(tmp_path):
    rows = _mk(7)
    finalize(tmp_path, "S", rows, _opts(max_rows_per_part=1000))   # 単一
    finalize(tmp_path, "M", rows, _opts(max_rows_per_part=3))      # 3 part
    single = _rows_from_part_text((tmp_path / "S.tsv").read_text("utf-8-sig"))
    multi = []
    for p in sorted(tmp_path.glob("M.part*")):
        multi += _rows_from_part_text(p.read_text("utf-8-sig"))
    assert single == multi
    assert "\n".join(multi).encode("utf-8") == _canonical_data_blob(
        sorted(rows, key=__import__("grep_analyzer.model",
               fromlist=["sort_key"]).sort_key))


def test_BOMはutf8sigのみ(tmp_path):
    finalize(tmp_path, "U", _mk(1), _opts(output_encoding="utf-8-sig"))
    assert (tmp_path / "U.tsv").read_bytes().startswith(b"\xef\xbb\xbf")
    finalize(tmp_path, "P", _mk(1), _opts(output_encoding="utf-8"))
    assert not (tmp_path / "P.tsv").read_bytes().startswith(b"\xef\xbb\xbf")


def test_孤児partクリーンアップ(tmp_path):
    finalize(tmp_path, "O", _mk(100), _opts(max_rows_per_part=1))  # 100 part(3桁)
    finalize(tmp_path, "O", _mk(2), _opts(max_rows_per_part=1))    # 2 part(2桁)
    remaining = sorted(p.name for p in tmp_path.glob("O.*"))
    assert remaining == ["O.manifest.json", "O.part01.tsv", "O.part02.tsv"]
