"""出力確定モジュール。

安定ソート→正規化→part分割→各part原子書込→manifest原子確定→孤児クリーン。
正規形は _canonical_data_blob に一元化（書込側=完了判定=テストが共有）。

Related: spec §2, §3
"""

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path

from grep_analyzer import __version__
from grep_analyzer.model import TSV_COLUMNS, Hit, sort_key
from grep_analyzer.tsv import sanitize_field


def _data_line(h: Hit) -> str:
    """1 データ行を生成する（tsv.sanitize_field 適用後にタブ結合）。"""
    return "\t".join(sanitize_field(c) for c in h.to_row())


def _blob_from_data_rows(data_rows: list[str]) -> bytes:
    """データ行列→正規バイト列（唯一の正規化終端）。書込側・完了判定側が共有。

    末尾改行無・LF 連結・"utf-8"（BOM 無 codec）。spec §3 手順1。
    surrogate（FS 走査由来パス等）は errors="replace" で潰す＝_part_bytes と同規約に
    揃え、書込側 sha・完了判定側 sha・TSV 実体の round-trip を一致させる。
    """
    return "\n".join(data_rows).encode("utf-8", errors="replace")


def _canonical_data_blob(ordered: list[Hit]) -> bytes:
    """ソート済 Hit→正規バイト列。書込側経路（_blob_from_data_rows を共有）。"""
    return _blob_from_data_rows([_data_line(h) for h in ordered])


def _rows_from_part_text(text: str) -> list[str]:
    """part 1 本のデコード済テキストからデータ行列を取り出す。

    書込時 `"\\n".join([header]+data_lines)+"\\n"`（_part_bytes の整形）の厳密逆＝先頭 BOM 除去 → rstrip("\\n")
    → split("\\n") → 先頭ヘッダ 1 行除去。splitlines() は使わない
    （sanitize_field 非対象の U+2028/U+0085 等で水増しするため＝spec §3 手順1）。
    decode 済 utf-8-sig は BOM 自動除去だが、防御的に先頭 U+FEFF も剥がす。
    """
    if text and text[0] == "\ufeff":   # 防御的 BOM 除去（明示）
        text = text[1:]
    lines = text.rstrip("\n").split("\n")
    return lines[1:]  # 先頭はヘッダ


def _atomic_write(path: "Path", data: bytes) -> None:
    """唯一の原子書込プリミティブ（mkstemp->fsync->os.replace で不可分置換）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def _fsync_dir(d: "Path") -> None:
    fd = os.open(str(d), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _part_bytes(header: str, data_rows: list[str], encoding: str) -> bytes:
    return ("\n".join([header] + data_rows) + "\n").encode(
        encoding, errors="replace")


def _write_manifest(out_dir: "Path", keyword: str, manifest: dict) -> None:
    """manifest を原子確定（②フェーズ・テストの monkeypatch フック点）。"""
    # keyword（=.grep 名）に surrogate が混じっても落とさない（errors="replace"）。
    # ensure_ascii=False は surrogate を str のまま残すため strict だと encode で倒れる。
    blob = json.dumps(manifest, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")).encode("utf-8", errors="replace")
    _atomic_write(out_dir / f"{keyword}.manifest.json", blob)


def finalize(out_dir: "Path", keyword: str, rows: "list[Hit]", opts) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=sort_key)
    n = len(ordered)
    L = opts.max_rows_per_part
    nparts = 1 if n <= L else math.ceil(n / L)
    width = max(2, len(str(nparts)))
    header = "\t".join(TSV_COLUMNS)
    enc = opts.output_encoding
    data_sha = hashlib.sha256(_canonical_data_blob(ordered)).hexdigest()

    parts_meta = []
    if nparts == 1:
        name = f"{keyword}.tsv"
        rows_lines = [_data_line(h) for h in ordered]
        _atomic_write(out_dir / name, _part_bytes(header, rows_lines, enc))
        parts_meta.append({"name": name, "rows": n})
    else:
        for i in range(nparts):
            chunk = ordered[i * L:(i + 1) * L]
            name = f"{keyword}.part{i + 1:0{width}d}.tsv"
            _atomic_write(out_dir / name,
                          _part_bytes(header, [_data_line(h) for h in chunk], enc))
            parts_meta.append({"name": name, "rows": len(chunk)})

    manifest = {
        "schema_version": 1, "keyword": keyword, "encoding": enc,
        "total_rows": n, "data_sha256": data_sha,
        "tool_version": __version__,
        "items_per_mb": __import__(
            "grep_analyzer.budget", fromlist=["_ITEMS_PER_MB"])._ITEMS_PER_MB,
        "parts": parts_meta, "tool": "grep_analyzer", "spec_phase": "3",
    }
    _write_manifest(out_dir, keyword, manifest)   # ②フェーズ
    _fsync_dir(out_dir)

    # 手順5: manifest 確定後に孤児削除（有効出力を新出力出現前に破壊しない）
    keep = {p["name"] for p in parts_meta} | {f"{keyword}.manifest.json"}
    for p in list(out_dir.glob(f"{keyword}.tsv")) + \
            list(out_dir.glob(f"{keyword}.part*.tsv")):
        if p.name not in keep:
            p.unlink()
