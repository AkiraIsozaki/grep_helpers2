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
    # _sanitize は \t \r \n のみ空白化（U+2028 非対象）。split("\n") 固定ゆえ
    # U+2028 で水増しせず、かつ snippet 内タブは _sanitize で空白化される。
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
