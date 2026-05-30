"""任意 ripgrep 一次粗フィルタ。walk の上位集合（.gitignore/

隠し/バイナリを除外しない＝バイナリ境界は walk の _is_binary 単一）。rg
不在/失敗は None＝フィルタ無効（全件走査）。出力不変（除外 relpath は部分
文字列すら持たず automaton 0 ヒット確定）。

Related: spec §8.2
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

_MACHINE_ALIASES = {
    "aarch64": "aarch64", "arm64": "aarch64",
    "x86_64": "x86_64", "amd64": "x86_64", "AMD64": "x86_64",
}


def _normalize_machine(machine: str) -> str | None:
    """platform.machine() の表記ゆれを同梱ディレクトリ名へ正規化（未知は None）。"""
    return _MACHINE_ALIASES.get(machine)


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
    # rg は **生バイト** を -F 検索するが、symbol は **復号テキスト** 由来。非 ASCII の
    # symbol は非 UTF-8 ファイル（cp932/euc-jp 等）でバイト不一致となり、automaton が
    # 復号テキスト上でヒットするファイルを rg が取りこぼす＝出力不変違反になる。ASCII
    # symbol は cp932/euc-jp/latin-1/utf-8 で同一バイトゆえ rg は安全な上位集合。よって
    # 非 ASCII symbol を含む hop は prefilter を無効化（None＝全件走査）して出力を保証する。
    if not all(s.isascii() for s in symbols):
        return None
    with tempfile.NamedTemporaryFile("w", suffix=".pat", delete=False,
                                     encoding="utf-8") as pf:
        pf.write("\n".join(symbols))
        pat_path = pf.name
    try:
        # text=False（bytes 出力）: SJIS 等の非 UTF-8 ファイル名を rg が生バイトで出力する
        # ため、text=True だと communicate の UTF-8 デコードで全体が落ちる。bytes で受け
        # os.fsdecode（FS codec＋surrogateescape）で walk.py の relpath 表現と一致させる。
        proc = subprocess.run(
            [_RG, "-l", "-F", "-a", "--no-messages", "--no-ignore", "--hidden",
             "--no-require-git", "-f", pat_path, "."],
            cwd=str(root), capture_output=True, check=False)
    except OSError:
        Path(pat_path).unlink(missing_ok=True)
        return None
    Path(pat_path).unlink(missing_ok=True)
    if proc.returncode not in (0, 1):
        return None
    hit = set()
    for raw in proc.stdout.split(b"\n"):
        if not raw:
            continue
        if raw.startswith(b"./"):
            raw = raw[2:]
        relpath = os.fsdecode(raw)
        if relpath in rel_to_abs:
            hit.add(relpath)
    return hit
