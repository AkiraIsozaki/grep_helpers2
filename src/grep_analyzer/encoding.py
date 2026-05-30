"""文字コード判定と決定的フォールバック鎖。decodeで絶対に落とさない。

Related: spec §10.1
"""

import chardet

# spec §10.1: utf-8 → 検出結果 → cp932/euc-jp → latin-1（置換・最終手段）
DEFAULT_FALLBACK = ["cp932", "euc-jp", "latin-1"]


def decode_bytes(data: bytes, fallback_chain: list[str]) -> tuple[str, str, bool]:
    """(text, 使用エンコーディング, 置換が発生したか) を返す。

    手順: ① utf-8 厳格 → ② chardet 検出（全バイト1回）→ ③ fallback_chain 順に厳格 →
    ④ latin-1 + replace（必ず成功・置換フラグ True）。

    短い/曖昧な入力では chardet が誤検出し得る（spec §10.1 の既知の限界）。
    その場合も例外は出さず、置換発生時は encoding 列＋diagnostics の「要確認」で
    顕在化させる（呼び出し側責務）。
    """
    try:
        return data.decode("utf-8"), "utf-8", False
    except UnicodeDecodeError:
        pass

    detected = chardet.detect(data).get("encoding")
    if detected:
        try:
            return data.decode(detected), detected.lower(), False
        except (UnicodeDecodeError, LookupError):
            pass

    for enc in fallback_chain[:-1]:
        try:
            return data.decode(enc), enc, False
        except (UnicodeDecodeError, LookupError):
            continue

    last = fallback_chain[-1]
    return data.decode(last, errors="replace"), last, True


def decode_with_memo(memo: dict, abspath: str, data: bytes, fallback_chain):
    """decode_bytes の純粋メモ化。memo[abspath]=(enc,replaced) を再利用し chardet を回避。

    memo hit 時は保存済み (enc, replaced) で再 decode（errors ポリシーを replaced で一致させ
    decode_bytes と同一テキストを得る）。codec 名非等価/再 decode 失敗は安全側に再計算へ降格。
    """
    hit = memo.get(abspath)
    if hit is not None:
        enc, replaced = hit
        try:
            return data.decode(enc, errors="replace" if replaced else "strict"), enc, replaced
        except (LookupError, UnicodeDecodeError):
            pass                              # codec名非等価等の保険＝再計算へ降格
    text, enc, replaced = decode_bytes(data, fallback_chain)
    memo[abspath] = (enc, replaced)
    return text, enc, replaced
