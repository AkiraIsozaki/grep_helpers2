"""任意 ripgrep 一次粗フィルタ。walk の上位集合（.gitignore/

隠し/バイナリを除外しない＝バイナリ境界は walk の _is_binary 単一）。rg
不在/失敗は None＝フィルタ無効（全件走査）。出力不変（除外 relpath は部分
文字列すら持たず automaton 0 ヒット確定）。

Related: spec §8.2
"""

import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from importlib.resources import files as _ir_files
from pathlib import Path

_MACHINE_ALIASES = {
    "aarch64": "aarch64", "arm64": "aarch64",
    "x86_64": "x86_64", "amd64": "x86_64", "AMD64": "x86_64",
}


def _normalize_machine(machine: str) -> str | None:
    """platform.machine() の表記ゆれを同梱ディレクトリ名へ正規化（未知は None）。"""
    return _MACHINE_ALIASES.get(machine)


def _default_vendor_root():
    try:
        return _ir_files("grep_analyzer") / "vendor" / "ripgrep"
    except Exception:
        return None


_VENDOR_ROOT = _default_vendor_root()


def _vendored_rg_path():
    """現 arch の同梱 rg のパス（存在すれば）。未知 arch / 不在は None。"""
    arch = _normalize_machine(platform.machine())
    if arch is None or _VENDOR_ROOT is None:
        return None
    cand = _VENDOR_ROOT / arch / "rg"
    try:
        return cand if cand.is_file() else None
    except Exception:
        return None


def _verify_sha256(rg_path) -> bool:
    """併置 `<rg>.sha256`（16進1行）と実バイトの sha256 を照合。sidecar 不在は False。"""
    from pathlib import Path as _P
    side = _P(str(rg_path) + ".sha256")
    try:
        want = side.read_text(encoding="ascii").strip().split()[0].lower()
        got = hashlib.sha256(_P(rg_path).read_bytes()).hexdigest()
        return got == want
    except (OSError, IndexError):
        return False


_GREP_ANALYZER_RG_ENV = "GREP_ANALYZER_RG"
_RG_CACHE = None
_RG_RESOLVED = False


def _resolve_rg_impl(env, vendored, which):
    """採用順（env→同梱→which）で最初の非 None を返す純選択。"""
    for cand in (env, vendored, which):
        if cand:
            return cand
    return None


def _smoke_ok(rg_path) -> bool:
    """実行可否（X_OK・必要なら chmod）＋ `rg --version` rc=0 スモーク（副作用あり）。"""
    try:
        if not os.access(rg_path, os.X_OK):
            os.chmod(rg_path, 0o755)
        r = subprocess.run([str(rg_path), "--version"], capture_output=True, check=False)
        return r.returncode == 0
    except OSError:
        return False


def _resolve_rg(force: bool = False):
    """env→同梱(sha256照合)→which の順で実行可能な rg を解決（run 単位キャッシュ・副作用あり）。"""
    global _RG_CACHE, _RG_RESOLVED
    if _RG_RESOLVED and not force:
        return _RG_CACHE
    env = os.environ.get(_GREP_ANALYZER_RG_ENV) or None
    vendored = _vendored_rg_path()
    if vendored is not None and not _verify_sha256(vendored):
        vendored = None
    which = shutil.which("rg")
    pool = [env, str(vendored) if vendored else None, which]
    _RG_CACHE = None
    for c in pool:
        if c and _smoke_ok(c):
            _RG_CACHE = c
            break
    _RG_RESOLVED = True
    return _RG_CACHE


def available() -> bool:
    """rg が解決可能か（**副作用フリー**＝存在判定のみ。chmod/スモークを起こさない）。

    True でも prefilter 経路の _resolve_rg() がスモーク失格で None になり得る
    （available は gate ヒント、prefilter が権威）。spec §4.5 準拠で collection
    フェーズから安全に呼べる。
    """
    if os.environ.get(_GREP_ANALYZER_RG_ENV):
        return True
    if _vendored_rg_path() is not None:
        return True
    return shutil.which("rg") is not None


def prefilter(
    root: Path, rel_to_abs: dict[str, Path], symbols: list[str]
) -> set[str] | None:
    """symbols のいずれかの部分文字列を含む relpath 集合（walk 上位集合）を返す。

    rg 不在/失敗は None（呼出側はフィルタ無効＝全 relpath 走査）。symbols 空は空集合。
    -a で rg のバイナリ skip を無効化し walk の _is_binary を唯一の境界に統一。
    """
    rg = _resolve_rg()
    if rg is None:
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
            [rg, "-l", "-F", "-a", "--no-messages", "--no-ignore", "--hidden",
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
