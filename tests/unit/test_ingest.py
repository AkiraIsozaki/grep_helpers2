"""grep -rn 行パースの仕様（spec §6）。パス部はバイト境界で保持する。"""

from grep_analyzer.ingest import parse_grep_line


def test_通常行はpath_lineno_contentに分割する():
    assert parse_grep_line(b"src/A.java:42:  if (x)") == (b"src/A.java", 42, b"  if (x)")


def test_最左の数字コロン境界を採用しパス内コロンに耐える():
    assert parse_grep_line(b"C:\\a:10:code") == (b"C:\\a", 10, b"code")


def test_content先頭が数字コロンでも最左境界で切る():
    assert parse_grep_line(b"a.sh:3:5: not a lineno") == (b"a.sh", 3, b"5: not a lineno")


def test_lineno無し行はNoneを返す():
    assert parse_grep_line(b"justtext without colon number") is None


def test_SJIS生バイトのパスを失わない():
    # UTF-8 として不正な SJIS バイトでもパス部のバイトを保つ（呼び出し側が os.fsdecode 用）。
    name = "あ.java".encode("cp932")          # b'\x82\xa0.java'
    assert parse_grep_line(name + b":3:x") == (name, 3, b"x")
