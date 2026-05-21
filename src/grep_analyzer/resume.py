"""kw 単位 resume の完了判定（完了判定1〜5）。

Related: spec §4
"""

import hashlib
import json
from pathlib import Path

from grep_analyzer import __version__
from grep_analyzer.output_writer import _blob_from_data_rows, _rows_from_part_text


def is_complete(out_dir: Path, keyword: str, opts) -> bool:
    out_dir = Path(out_dir)
    mpath = out_dir / f"{keyword}.manifest.json"
    if not mpath.is_file():                                   # 条件1
        return False
    try:
        m = json.loads(mpath.read_text("utf-8"))
    except (ValueError, OSError):
        return False
    if not isinstance(m, dict):                                # valid JSON だが dict でない破損形（spec §6）
        return False
    enc = m.get("encoding", "utf-8-sig")
    data_rows: list[str] = []
    try:
        for part in m.get("parts", []):
            f = out_dir / part["name"]
            if not f.is_file():                                   # 条件2
                return False
            rows = _rows_from_part_text(f.read_text(enc))
            if len(rows) != part.get("rows"):                     # 条件3
                return False
            data_rows += rows
    except (KeyError, TypeError, UnicodeDecodeError, OSError, LookupError):
        return False
    sha = hashlib.sha256(_blob_from_data_rows(data_rows)).hexdigest()
    if sha != m.get("data_sha256"):                           # 条件4（書込側と同一関数）
        return False
    from grep_analyzer.budget import _ITEMS_PER_MB
    if m.get("tool_version") != __version__:                  # 条件5
        return False
    if m.get("items_per_mb") != _ITEMS_PER_MB:                # 条件5
        return False
    return True
