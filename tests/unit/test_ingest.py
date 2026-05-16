"""grep -rn 行パースの仕様（spec §6）。"""

from grep_analyzer.ingest import parse_grep_line


def test_通常行はpath_lineno_contentに分割する():
    assert parse_grep_line("src/A.java:42:  if (x)") == ("src/A.java", 42, "  if (x)")


def test_最左の数字コロン境界を採用しパス内コロンに耐える():
    assert parse_grep_line("C:\\a:10:code") == ("C:\\a", 10, "code")


def test_content先頭が数字コロンでも最左境界で切る():
    assert parse_grep_line("a.sh:3:5: not a lineno") == ("a.sh", 3, "5: not a lineno")


def test_lineno無し行はNoneを返す():
    assert parse_grep_line("justtext without colon number") is None
