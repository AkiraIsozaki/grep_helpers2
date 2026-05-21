"""スニペット切り出しの境界判定用 regex。

`heuristic_span` が sql / shell のスパン停止条件として参照する。
判定対象はマスク後の行末・句境界・shell 終端構文。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 1
"""

import re

SQL_CLAUSE_RE = re.compile(
    r"\b(WHERE|SET|VALUES|SELECT|FROM|GROUP\s+BY|ORDER\s+BY|HAVING)\b", re.I)

SH_TERMINATOR_RE = re.compile(r"(?:^|\s)(fi|done|esac|breaksw)\b|;")
