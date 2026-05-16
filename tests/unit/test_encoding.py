"""文字コード判定とフォールバック（spec §10.1）。

chardet の検出は短い/曖昧な入力で結果が揺れる（実測: 短い cp932 を Windows-1252、
`\\xff\\xfe..` を UTF-16 と誤検出）。決定的に検証するため、フォールバック経路の
テストは chardet.detect を stub する（chardet は外部の検出オラクル＝外部I/O境界。
writing-tests.md のモック線引きに合致）。実 chardet 経路は「決して落ちない」契約のみ検証。
"""

from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes


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
