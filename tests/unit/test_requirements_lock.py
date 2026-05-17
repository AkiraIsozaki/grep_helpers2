"""requirements.lock 整合（ゲート・高速・spec §4.1/WS5）。"""

import hashlib
import re
from pathlib import Path

LOCK = Path("requirements.lock")
WH = Path("wheelhouse")


# spec §4.1 の必須依存（pyproject の dependencies ではなく spec 名で固定。
# pyproject.toml の dependencies は pyahocorasick を欠くため §4.1 名で照合）。
SPEC_4_1_REQUIRED = {
    "tree-sitter", "tree-sitter-java", "tree-sitter-c",
    "pyahocorasick", "chardet"}


def _norm(pkg: str) -> str:
    return pkg.lower().replace("_", "-")


def test_lock各行のhashがwheelhouse実ファイルと一致():
    assert LOCK.is_file(), "requirements.lock 未生成（Step 3 で生成）"
    text = LOCK.read_text("utf-8")
    pairs = re.findall(r"(\S+)==(\S+) --hash=sha256:([0-9a-f]+)", text)
    assert pairs, "lock 形式不正"
    by_hash = {}
    for whl in WH.glob("*.whl"):
        by_hash[hashlib.sha256(whl.read_bytes()).hexdigest()] = whl.name
    for pkg, ver, sha in pairs:
        assert sha in by_hash, f"{pkg}=={ver} のhashがwheelhouseに無い"


def test_lockがspec_4_1必須依存を網羅():
    """spec §4.1/WS5: lock の pkg 集合 ⊇ §4.1 必須依存。"""
    text = LOCK.read_text("utf-8")
    locked = {_norm(p) for p, _, _ in
              re.findall(r"(\S+)==(\S+) --hash=sha256:([0-9a-f]+)", text)}
    missing = {r for r in SPEC_4_1_REQUIRED if _norm(r) not in locked}
    assert not missing, f"spec §4.1 必須依存が lock に欠落: {missing}"
