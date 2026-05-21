"""決定的ツリー走査（spec §8.2）。relpath 昇順・glob・サイズ/バイナリ skip・

生成コード既定除外・symlink は既定で辿らず realpath 重複排除。走査順非依存決定的。
"""

import fnmatch
import os
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.diagnostics import Diagnostics

# v1 言語スコープ(spec §2.3: Java/C/Pro*C/SQL/Shell)整合の保守的既定。
# Python/JS 生成物は v1 言語外のため含めない。spec §8.2 は具体非列挙＝実装委任。
DEFAULT_EXCLUDE: tuple[str, ...] = (
    "**/target/**", "**/build/**", "**/generated/**", "**/.git/**")


def _match_one(relpath: str, pat: str) -> bool:
    rseg = relpath.split("/")
    pseg = pat.split("/")

    def m(ri: int, pi: int) -> bool:
        if pi == len(pseg):
            return ri == len(rseg)
        if pseg[pi] == "**":
            return any(m(k, pi + 1) for k in range(ri, len(rseg) + 1))
        if ri == len(rseg):
            return False
        return fnmatch.fnmatch(rseg[ri], pseg[pi]) and m(ri + 1, pi + 1)

    return m(0, 0)


def _match_any(relpath: str, patterns: list[str]) -> bool:
    base = relpath.rsplit("/", 1)[-1]
    for p in patterns:
        if _match_one(relpath, p) or ("/" not in p and fnmatch.fnmatch(base, p)):
            return True
    return False


def _is_binary(path: Path) -> bool:
    with open(path, "rb") as f:
        return b"\x00" in f.read(8192)


def walk_files(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics,
) -> Iterator[tuple[str, Path]]:
    """root 配下の通常ファイルを relpath 昇順で yield（spec §8.2）。"""
    root = Path(root)
    seen_real: dict[str, str] = {}
    candidates: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        dirnames.sort()
        for name in sorted(filenames):
            abspath = Path(dirpath) / name
            relpath = abspath.relative_to(root).as_posix()
            if abspath.is_symlink() and not follow_symlinks:
                diag.add("symlink_skipped", relpath)
                continue
            if _match_any(relpath, exclude):
                diag.add("walk_excluded", relpath)
                continue
            if include and not _match_any(relpath, include):
                continue
            candidates.append((relpath, abspath))
    for relpath, abspath in sorted(candidates):
        try:
            if abspath.stat().st_size > max_file_bytes:
                diag.add("walk_skipped_large", relpath)
                continue
            if _is_binary(abspath):
                diag.add("walk_skipped_binary", relpath)
                continue
            real = os.path.realpath(abspath)
        except OSError:
            diag.add("walk_unreadable", relpath)
            continue
        if real in seen_real:
            diag.add("symlink_dedup", f"{relpath} -> {seen_real[real]}")
            continue
        seen_real[real] = relpath
        yield relpath, abspath


def collect_files(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics,
) -> list[tuple[str, Path]]:
    """walk_files を一度だけ materialize し relpath 昇順の list を返す。

    走査・診断は1回（pipeline が keyword 横断で共有＝診断重複解消・§8.2）。
    """
    return list(walk_files(
        root, include=include, exclude=exclude, follow_symlinks=follow_symlinks,
        max_file_bytes=max_file_bytes, diag=diag))
