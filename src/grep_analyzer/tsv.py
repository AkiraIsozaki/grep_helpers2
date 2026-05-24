"""TSV フィールドのサニタイズ規約。

全制御文字（C0 U+0000–001F / DEL U+007F / C1 U+0080–009F）と
行/改ページ分割（U+2028 U+2029）を半角空白 1 個へ置換する `sanitize_field` を
提供する。書込本体は output_writer.py。

Related: spec §9 規約①
"""

# spec §9 サニタイズ規約①: 全制御文字＋ U+2028/U+2029 を半角空白1個へ。
# 旧集合（\t \r \n \v \f U+0085 U+2028 U+2029）を包含（C0⊂新集合・U+0085 は C1）。
# split("\n")/data_sha256 の決定性コアは不変（U+000A は従来どおり空白化）。
_SANITIZE_MAP = {c: " " for c in range(0x00, 0x20)}   # C0 制御
_SANITIZE_MAP[0x7F] = " "                             # DEL
_SANITIZE_MAP.update({c: " " for c in range(0x80, 0xA0)})  # C1 制御（U+0085 含む）
_SANITIZE_MAP[0x2028] = " "                           # LINE SEPARATOR
_SANITIZE_MAP[0x2029] = " "                           # PARAGRAPH SEPARATOR


def sanitize_field(cell: str) -> str:
    """フィールド内の全制御文字・行分割クラスを空白へ置換する（spec §9）。"""
    return cell.translate(_SANITIZE_MAP)
