"""requirements.lock 整合（ゲート・高速・spec §4.1/WS5）。"""

import hashlib
import re
from pathlib import Path

LOCK = Path("requirements.lock")
WH = Path("wheelhouse")


# spec §4.1 の必須依存を spec 名で固定（spec が source of truth）。
# pyproject.toml の dependencies は pyahocorasick==2.3.1 を含むよう是正済み
# （aarch64 ピボット時／2026-05-19）だが、照合基準は spec §4.1 名のまま。
SPEC_4_1_REQUIRED = {
    "tree-sitter", "tree-sitter-java", "tree-sitter-c",
    "pyahocorasick", "chardet"}


def _norm(pkg: str) -> str:
    return pkg.lower().replace("_", "-")


def test_lock各行のhashがwheelhouse実ファイルと一致():
    """多アーキ同梱 lock は 1 行に複数 --hash を持つ。全 hash を検証する
    （先頭のみ検証だと aarch64 等2本目の供給網完全性が抜ける）。"""
    assert LOCK.is_file(), "requirements.lock 未生成（Step 3 で生成）"
    by_hash = {hashlib.sha256(whl.read_bytes()).hexdigest(): whl.name
               for whl in WH.glob("*.whl")}
    n = 0
    for line in LOCK.read_text("utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"(\S+)==(\S+)\s+(--hash=sha256:[0-9a-f]+.*)$", line)
        assert m, f"lock 形式不正: {line}"
        pkg, ver, rest = m.groups()
        shas = re.findall(r"sha256:([0-9a-f]+)", rest)
        assert shas, f"{pkg}=={ver} に hash 無し"
        for sha in shas:
            assert sha in by_hash, \
                f"{pkg}=={ver} のhash {sha[:12]}… がwheelhouseに無い"
            n += 1
    assert n >= 1, "lock 行ゼロ"


def test_lockがspec_4_1必須依存を網羅():
    """spec §4.1/WS5: lock の pkg 集合 ⊇ §4.1 必須依存。"""
    text = LOCK.read_text("utf-8")
    locked = {_norm(p) for p, _, _ in
              re.findall(r"(\S+)==(\S+) --hash=sha256:([0-9a-f]+)", text)}
    missing = {r for r in SPEC_4_1_REQUIRED if _norm(r) not in locked}
    assert not missing, f"spec §4.1 必須依存が lock に欠落: {missing}"


# gen_requirements_lock.py と同一の wheel 命名規則（逆方向検査・再生成検査で共有）。
_WHL_RE = re.compile(r"([A-Za-z0-9_.]+)-([0-9][^-]*)-")


def test_wheelhouse全wheelがlockに収録される_供給網汚染検知():
    """逆方向（wheel→lock）の完全性。lock→wheel の片方向だけだと
    lock 未記載 wheel の混入（供給網汚染）を検知できない。命名規則に
    合致する全 wheel の sha が lock のどこかに在ることを要求する。"""
    lock_hashes = set(re.findall(r"sha256:([0-9a-f]+)", LOCK.read_text("utf-8")))
    orphans = []
    for whl in sorted(WH.glob("*.whl")):
        if not _WHL_RE.match(whl.name):  # gen script が skip する命名は対象外
            continue
        sha = hashlib.sha256(whl.read_bytes()).hexdigest()
        if sha not in lock_hashes:
            orphans.append(whl.name)
    assert not orphans, f"lock 未記載の wheel が wheelhouse に存在: {orphans}"


def test_lockはwheelhouseから決定的に再生成した内容とbyte一致():
    """gen_requirements_lock.py の決定性ガード＋committed lock との
    ドリフト検知。スクリプトと同一アルゴリズムで期待 lock を再構成し、
    committed ファイルと byte 一致を要求（並び順・集約・改行を固定）。"""
    by_pkg: dict[str, dict[str, list[str]]] = {}
    for whl in sorted(WH.glob("*.whl")):
        m = _WHL_RE.match(whl.name)
        if not m:
            continue
        pkg = m.group(1).replace("_", "-")
        ver = m.group(2)
        sha = hashlib.sha256(whl.read_bytes()).hexdigest()
        by_pkg.setdefault(pkg, {}).setdefault(ver, []).append(sha)
    lines = []
    for pkg in sorted(by_pkg):
        vers = by_pkg[pkg]
        assert len(vers) == 1, f"完全ピン違反: {pkg} -> {sorted(vers)}"
        ver, shas = next(iter(vers.items()))
        hashes = " ".join(f"--hash=sha256:{h}" for h in sorted(set(shas)))
        lines.append(f"{pkg}=={ver} {hashes}")
    expected = "\n".join(lines) + "\n"
    assert LOCK.read_text("utf-8") == expected, \
        "requirements.lock が wheelhouse から再生成した内容と不一致" \
        "（gen_requirements_lock.py 再実行で同期すること）"
