"""任意 ripgrep 一次粗フィルタ（spec §8.2）。walk の上位集合（.gitignore/

隠し/バイナリを除外しない＝バイナリ境界は walk の _is_binary 単一）。rg
不在/失敗は None＝フィルタ無効（全件走査）。出力不変（除外 relpath は部分
文字列すら持たず automaton 0 ヒット確定）。
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

_RG = shutil.which("rg")


def available() -> bool:
    """実 ripgrep バイナリが利用可能か。"""
    return _RG is not None


def prefilter(
    root: Path, rel_to_abs: dict[str, Path], symbols: list[str]
) -> set[str] | None:
    """symbols のいずれかの部分文字列を含む relpath 集合（walk 上位集合）を返す。

    rg 不在/失敗は None（呼出側はフィルタ無効＝全 relpath 走査）。symbols 空は空集合。
    -a で rg のバイナリ skip を無効化し walk の _is_binary を唯一の境界に統一。
    """
    if _RG is None:
        return None
    if not symbols:
        return set()
    with tempfile.NamedTemporaryFile("w", suffix=".pat", delete=False,
                                     encoding="utf-8") as pf:
        pf.write("\n".join(symbols))
        pat_path = pf.name
    try:
        proc = subprocess.run(
            [_RG, "-l", "-F", "-a", "--no-messages", "--no-ignore", "--hidden",
             "--no-require-git", "-f", pat_path, "."],
            cwd=str(root), capture_output=True, text=True, check=False)
    except OSError:
        Path(pat_path).unlink(missing_ok=True)
        return None
    Path(pat_path).unlink(missing_ok=True)
    if proc.returncode not in (0, 1):
        return None
    hit = set()
    for ln in proc.stdout.splitlines():
        relpath = ln[2:] if ln.startswith("./") else ln
        if relpath in rel_to_abs:
            hit.add(relpath)
    return hit
