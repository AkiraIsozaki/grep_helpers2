"""TSV出力（spec §9）。決定的全順序ソート・サニタイズ・原子的書込・BOM規則。"""

import os
import tempfile
from pathlib import Path

from grep_analyzer.model import TSV_COLUMNS, Hit, sort_key


def _sanitize(cell: str) -> str:
    """フィールド内のタブ・改行を空白に置換する（spec §9）。"""
    return cell.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def write_tsv(path: Path, hits: list[Hit], encoding: str) -> None:
    """hits を決定的にソートし、一時ファイル→fsync→rename で原子的に書き出す。

    encoding が "utf-8-sig" のときのみ BOM を付与（非UTF-8は付けない・spec §9）。
    """
    ordered = sorted(hits, key=sort_key)
    lines = ["\t".join(TSV_COLUMNS)]
    lines += ["\t".join(_sanitize(c) for c in h.to_row()) for h in ordered]
    data = ("\n".join(lines) + "\n").encode(encoding, errors="replace")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)  # rename 済みのみ完了（spec §10.3）
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
