"""TSV フィールドのサニタイズ規約。

行 / 改ページ分割クラス（\\t \\r \\n \\v \\f U+0085 U+2028 U+2029）を
半角空白 1 個に置換する `sanitize_field` のみを提供する。書込本体は output_writer.py。

Related: spec §9 規約①
"""

# spec §9 サニタイズ規約①: 行/改ページ分割クラスを半角空白1個へ
# （\t \r \n \v \f U+0085 U+2028 U+2029＝spec §11 名指し集合）。
# split("\n")/data_sha256 の決定性コアは不変（U+000A は従来どおり空白化）。
_SANITIZE_MAP = {ord(c): " " for c in "\t\r\n\x0b\x0c\x85  "}


def sanitize_field(cell: str) -> str:
    """フィールド内のタブ・改行・行分割クラスを空白へ置換する（spec §9）。"""
    return cell.translate(_SANITIZE_MAP)
