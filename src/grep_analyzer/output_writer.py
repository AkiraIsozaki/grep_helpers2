"""出力確定モジュール（spec v4 §2/§3）。

安定ソート→正規化→part分割→各part原子書込→manifest原子確定→孤児クリーン。
正規形は _canonical_data_blob に一元化（書込側=完了判定=Inv-5=テストが共有）。
"""

from grep_analyzer.model import TSV_COLUMNS, Hit, sort_key  # TSV_COLUMNS/sort_key は Task3 で使用
from grep_analyzer.tsv import _sanitize


def _data_line(h: Hit) -> str:
    """1 データ行＝tsv.py:22 と同一バイト列（サニタイズ後タブ結合）。"""
    return "\t".join(_sanitize(c) for c in h.to_row())


def _blob_from_data_rows(data_rows: list[str]) -> bytes:
    """データ行列→正規バイト列（唯一の正規化終端）。書込側・完了判定側が共有。

    末尾改行無・LF 連結・"utf-8"（BOM 無 codec）。spec v4 §3 手順1。
    """
    return "\n".join(data_rows).encode("utf-8")


def _canonical_data_blob(ordered: list[Hit]) -> bytes:
    """ソート済 Hit→正規バイト列。書込側経路（_blob_from_data_rows を共有）。"""
    return _blob_from_data_rows([_data_line(h) for h in ordered])


def _rows_from_part_text(text: str) -> list[str]:
    """part 1 本のデコード済テキストからデータ行列を取り出す。

    書込時 `"\\n".join([header]+data_lines)+"\\n"`（tsv.py:21-23 形式）の厳密逆＝先頭 BOM 除去 → rstrip("\\n")
    → split("\\n") → 先頭ヘッダ 1 行除去。splitlines() は使わない
    （_sanitize 非対象の U+2028/U+0085 等で水増しするため＝spec v4 §3 手順1）。
    decode 済 utf-8-sig は BOM 自動除去だが、防御的に先頭 U+FEFF も剥がす。
    """
    if text and text[0] == "\ufeff":   # 防御的 BOM 除去（明示）
        text = text[1:]
    lines = text.rstrip("\n").split("\n")
    return lines[1:]  # 先頭はヘッダ
