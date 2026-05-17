"""corpus_gen 決定性（同一シード同一木・spec v4 §4 WS6・既定ゲート非perf）。"""

import hashlib
from tests.perf.corpus_gen import generate


def _digest(root):
    items = sorted(p.relative_to(root).as_posix()
                   for p in root.rglob("*") if p.is_file())
    h = hashlib.sha256()
    for rel in items:
        h.update(rel.encode()); h.update((root / rel).read_bytes())
    return h.hexdigest()


def test_同一シードで同一木(tmp_path):
    a = tmp_path / "a"; b = tmp_path / "b"
    generate(a, seed=42, n_files=20)
    generate(b, seed=42, n_files=20)
    assert _digest(a) == _digest(b)
    c = tmp_path / "c"; generate(c, seed=43, n_files=20)
    assert _digest(c) != _digest(a)
