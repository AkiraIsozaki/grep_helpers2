"""input/*.grep の行パース（spec §6）。"""

import re

_LINE_RE = re.compile(r"^(?P<path>.*?):(?P<lineno>\d+):(?P<content>.*)$", re.DOTALL)


def parse_grep_line(line: str) -> tuple[str, int, str] | None:
    """`path:lineno:content` を最左の `:<数字>:` 境界で分割する。

    不一致なら None（呼び出し側が diagnostics に回す）。
    """
    m = _LINE_RE.match(line.rstrip("\n"))
    if m is None:
        return None
    return m.group("path"), int(m.group("lineno")), m.group("content")
