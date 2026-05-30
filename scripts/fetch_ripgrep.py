"""ripgrep 14.1.1 を版・URL・sha256 ピンで取得し vendor へ配置する再現取得スクリプト。

オンライン環境で 1 回実行 → 生成物（rg・rg.sha256・LICENSE-MIT・UNLICENSE）をコミットしオフライン再現。
（requirements.lock / gen_requirements_lock.py と同じ「ネットで再生成・オフラインで再現」作法）
"""
import hashlib
import io
import stat
import tarfile
import urllib.request
from pathlib import Path

VERSION = "14.1.1"
# 各 arch: (URL, tarball の sha256, tar 内 rg への相対パス)
TARGETS = {
    "aarch64": (
        f"https://github.com/BurntSushi/ripgrep/releases/download/{VERSION}/"
        f"ripgrep-{VERSION}-aarch64-unknown-linux-gnu.tar.gz",
        "PIN_AARCH64_TARBALL_SHA256",
        f"ripgrep-{VERSION}-aarch64-unknown-linux-gnu/rg",
    ),
    "x86_64": (
        f"https://github.com/BurntSushi/ripgrep/releases/download/{VERSION}/"
        f"ripgrep-{VERSION}-x86_64-unknown-linux-musl.tar.gz",
        "PIN_X86_64_TARBALL_SHA256",
        f"ripgrep-{VERSION}-x86_64-unknown-linux-musl/rg",
    ),
}
VENDOR = Path("src/grep_analyzer/vendor/ripgrep")


def _check_sha256(blob: bytes, expected: str) -> None:
    got = hashlib.sha256(blob).hexdigest()
    if got != expected:
        raise ValueError(f"sha256 mismatch: got {got} want {expected}")


def _fetch_one(arch: str) -> None:
    url, tar_sha, rg_member = TARGETS[arch]
    blob = urllib.request.urlopen(url).read()
    _check_sha256(blob, tar_sha)
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        rg_bytes = tf.extractfile(rg_member).read()
        # rev.2 D: LICENSE-MIT と UNLICENSE の両方を取得し、欠ければ abort
        mit = next((m for m in tf.getmembers() if m.name.endswith("LICENSE-MIT")), None)
        unl = next((m for m in tf.getmembers() if m.name.endswith("UNLICENSE")), None)
        if mit is None or unl is None:
            raise ValueError(f"{arch}: LICENSE-MIT/UNLICENSE が tarball に揃っていない")
        mit_bytes = tf.extractfile(mit).read()
        unl_bytes = tf.extractfile(unl).read()
    outdir = VENDOR / arch
    outdir.mkdir(parents=True, exist_ok=True)
    rg_path = outdir / "rg"
    rg_path.write_bytes(rg_bytes)
    rg_path.chmod(rg_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    (outdir / "rg.sha256").write_text(hashlib.sha256(rg_bytes).hexdigest() + "\n")
    (outdir / "LICENSE-MIT").write_bytes(mit_bytes)
    (outdir / "UNLICENSE").write_bytes(unl_bytes)
    print(f"placed {rg_path} ({len(rg_bytes)} bytes)")


if __name__ == "__main__":
    # rev.2 D: PIN 未充填なら取得前に即 abort（vendor 空配備の静かな無効化を防ぐ）
    for arch, (_, sha, _) in TARGETS.items():
        if sha.startswith("PIN_"):
            raise SystemExit(
                f"{arch}: sha256 が未充填（PIN_...）。オンラインで実値を埋めてから実行")
    for arch in TARGETS:
        _fetch_one(arch)
