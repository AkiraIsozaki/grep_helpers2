"""決定的ツリー走査。relpath 昇順・glob・サイズ/バイナリ skip・

生成コード既定除外・symlink は既定で辿らず realpath 重複排除。走査順非依存決定的。

Related: spec §8.2
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
    rel_segs = relpath.split("/")
    pat_segs = pat.split("/")

    def match_segments(rel_idx: int, pat_idx: int) -> bool:
        if pat_idx == len(pat_segs):
            return rel_idx == len(rel_segs)
        if pat_segs[pat_idx] == "**":
            return any(match_segments(k, pat_idx + 1)
                       for k in range(rel_idx, len(rel_segs) + 1))
        if rel_idx == len(rel_segs):
            return False
        return (fnmatch.fnmatch(rel_segs[rel_idx], pat_segs[pat_idx])
                and match_segments(rel_idx + 1, pat_idx + 1))

    return match_segments(0, 0)


def _match_any(relpath: str, patterns: list[str]) -> bool:
    base = relpath.rsplit("/", 1)[-1]
    for p in patterns:
        if _match_one(relpath, p) or ("/" not in p and fnmatch.fnmatch(base, p)):
            return True
    return False


def is_contained_relpath(relpath: str) -> bool:
    """relpath が source_root 配下に収まる安全な相対パスか。

    絶対パス・空・`..` を含むパスを拒否する（パストラバーサル／絶対パス注入の防御）。
    """
    if not relpath or os.path.isabs(relpath):
        return False
    return ".." not in Path(relpath).parts


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
    visited_dirs: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        if follow_symlinks:
            # ディレクトリ symlink 循環の無限再帰を枝刈り（os.walk は検出しない）。
            real_dir = os.path.realpath(dirpath)
            if real_dir in visited_dirs:
                dirnames[:] = []
                continue
            visited_dirs.add(real_dir)
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
