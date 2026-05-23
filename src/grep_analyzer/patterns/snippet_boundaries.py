"""スニペット切り出しの境界判定用 regex。

`heuristic_span` が sql / shell / perl / groovy のスパン停止条件として参照する。
判定対象はマスク後の行末・句境界・shell 終端構文。
"""

import re

SQL_CLAUSE_RE = re.compile(
    r"\b(WHERE|SET|VALUES|SELECT|FROM|GROUP\s+BY|ORDER\s+BY|HAVING)\b", re.I)

SH_TERMINATOR_RE = re.compile(r"(?:^|\s)(fi|done|esac|breaksw)\b|;")

PERL_TERMINATOR_RE = re.compile(r";|}|^\s*sub\b", re.IGNORECASE)
GROOVY_TERMINATOR_RE = re.compile(r";|}|^\s*(?:class|def)\b", re.IGNORECASE)
