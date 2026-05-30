"""文字コード判定とフォールバック（spec §10.1）。

chardet の検出は短い/曖昧な入力で結果が揺れる（実測: 短い cp932 を Windows-1252、
`\\xff\\xfe..` を UTF-16 と誤検出）。決定的に検証するため、フォールバック経路の
テストは chardet.detect を stub する（chardet は外部の検出オラクル＝外部I/O境界。
writing-tests.md のモック線引きに合致）。実 chardet 経路は「決して落ちない」契約のみ検証。
"""

import pytest

from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes, decode_with_memo


def test_UTF8は置換なしで復号される():
    text, enc, replaced = decode_bytes("あいう".encode("utf-8"), DEFAULT_FALLBACK)
    assert text == "あいう"
    assert enc == "utf-8"
    assert replaced is False


def test_検出不発時はフォールバック鎖のcp932で復号される(monkeypatch):
    monkeypatch.setattr(
        "grep_analyzer.encoding.chardet.detect", lambda b: {"encoding": None}
    )
    text, enc, replaced = decode_bytes("日本語".encode("cp932"), DEFAULT_FALLBACK)
    assert text == "日本語"
    assert enc == "cp932"
    assert replaced is False


def test_どの厳格復号も不可ならlatin1置換で要確認になる(monkeypatch):
    monkeypatch.setattr(
        "grep_analyzer.encoding.chardet.detect", lambda b: {"encoding": None}
    )
    # \x81 は utf-8 / cp932 / euc-jp すべてで不正 → latin-1 置換へ確定
    text, enc, replaced = decode_bytes(b"\x81", DEFAULT_FALLBACK)
    assert isinstance(text, str)
    assert enc == "latin-1"
    assert replaced is True


def test_実chardet経路でも例外を投げない():
    text, enc, replaced = decode_bytes("日本語".encode("cp932"), DEFAULT_FALLBACK)
    assert isinstance(text, str)  # 誤検出し得るが「決して落ちない」契約のみ検証


@pytest.mark.parametrize("raw", [
    "abc".encode("utf-8"),
    "日本語".encode("cp932"),
    "日本語".encode("euc-jp"),
    b"\xff\xfe\x80",                     # 実測: chardet が UTF-16(decode失敗)を検出→fallback の
                                        # cp932 で復号成功 → enc=cp932, replaced=False（latin-1 ではない）
])
def test_decode_with_memoはdecode_bytesとバイト同値(raw):
    memo = {}
    want = decode_bytes(raw, DEFAULT_FALLBACK)
    got1 = decode_with_memo(memo, "/p/x", raw, DEFAULT_FALLBACK)
    got2 = decode_with_memo(memo, "/p/x", raw, DEFAULT_FALLBACK)   # 2回目=memo hit
    assert got1 == want and got2 == want


def test_decode_with_memoはreplaced経路もhitで同値(monkeypatch):
    """replaced=True（latin-1 置換）の hit 経路を決定的に固定する。

    chardet を None に stub し \x81 を必ず latin-1 置換へ落とす（chardet の揺れに依存しない）。
    memo hit 時の errors='replace' 再 decode が decode_bytes と同一テキストを返すことを確認。
    """
    monkeypatch.setattr(
        "grep_analyzer.encoding.chardet.detect", lambda b: {"encoding": None})
    raw = b"\x81"
    want = decode_bytes(raw, DEFAULT_FALLBACK)
    assert want[2] is True                                        # replaced=True 経路を踏む
    memo = {}
    got1 = decode_with_memo(memo, "/p/z", raw, DEFAULT_FALLBACK)  # miss
    got2 = decode_with_memo(memo, "/p/z", raw, DEFAULT_FALLBACK)  # hit（errors=replace 再現）
    assert got1 == want and got2 == want


def test_decode_with_memoはhit時chardetを呼ばない(monkeypatch):
    import grep_analyzer.encoding as enc
    calls = {"n": 0}
    real = enc.chardet.detect
    monkeypatch.setattr(enc.chardet, "detect",
                        lambda b: calls.__setitem__("n", calls["n"] + 1) or real(b))
    memo = {}
    raw = "あ".encode("euc-jp")          # utf-8 strict 失敗→chardet 経路
    decode_with_memo(memo, "/p/y", raw, DEFAULT_FALLBACK)
    decode_with_memo(memo, "/p/y", raw, DEFAULT_FALLBACK)
    assert calls["n"] == 1               # 2回目は memo hit で chardet 非実行
