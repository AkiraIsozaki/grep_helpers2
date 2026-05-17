"""既定経路が _ITEMS_PER_MB に不感＝Inv-1 機械保証（spec v4 §7・WS6）。"""

import hashlib
import pytest
from grep_analyzer.cli import main


def _run(tmp_path):
    src = tmp_path / "src"; src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_text("class A{ static final int K=1; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "K.grep").write_text("A.java:1:static final int K\n", "utf-8")
    out = tmp_path / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    return hashlib.sha256((out / "K.tsv").read_bytes()).hexdigest()


def test_既定出力は_items_per_mb値に不感(tmp_path, monkeypatch):
    # 真の能動ガード: 既定定数での出力 sha を基準に、定数を極値へ
    # monkeypatch しても **基準と一致** すること（v=default 比較）。
    ref = _run(tmp_path / "ref")                       # 既定 _ITEMS_PER_MB
    for v in (1, 10 ** 9):
        monkeypatch.setattr("grep_analyzer.budget._ITEMS_PER_MB", v)
        assert _run(tmp_path / f"v{v}") == ref          # 既定経路は定数不感
        monkeypatch.undo()
