"""input/*.grep の行パース（バイト境界）。

Related: spec §6
"""

import re

_LINE_RE = re.compile(rb"^(?P<path>.*?):(?P<lineno>\d+):(?P<content>.*)$", re.DOTALL)


def parse_grep_line(line: bytes) -> tuple[bytes, int, bytes] | None:
    """`path:lineno:content` を**バイト列のまま**最左の `:<数字>:` 境界で分割する。

    パス部のバイトを保つことで、UTF-8 として不正なファイル名（SJIS 混在等）でも
    呼び出し側が os.fsdecode で FS と一致するパスを復元できる（テキスト復号では
    UTF-8 ファイルシステムへ再エンコードしても元バイトに戻らない＝spec §10.1）。
    復号方針（パス＝fsdecode／content＝文字コード判定）は呼び出し側責務。

    不一致なら None（呼び出し側が diagnostics に回す）。
    """
    m = _LINE_RE.match(line.rstrip(b"\r\n"))
    if m is None:
        return None
    return m.group("path"), int(m.group("lineno")), m.group("content")
