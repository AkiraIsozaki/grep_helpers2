"""既定経路が _ITEMS_PER_MB に不感＝Inv-1 機械保証（spec v4 §7・WS6）。

再ベースライン理由A（spec v9 §9: file 列 {source_root.resolve()}/rel 絶対化）:
旧版は ref/v1/v1e9 を別々の tmp サブディレクトリで実行していたが、file 列が
絶対パス化したことで「定数の差」ではなく「ディレクトリ名の差」だけで sha が
変わってしまう。Inv-1 の検証意図（既定経路は _ITEMS_PER_MB に不感）を保つには
**同一ディレクトリ**で実行し file 絶対パスを固定して定数のみを変数化する。
"""

import hashlib
import shutil
import pytest
from grep_analyzer.cli import main


def _run(base):
    # 同一 base を毎回クリーンに再生成（file 絶対パスを ref/v 間で一致させる）
    if base.exists():
        shutil.rmtree(base)
    src = base / "src"; src.mkdir(parents=True, exist_ok=True)
    (src / "A.java").write_text("class A{ static final int K=1; }\n", "utf-8")
    inp = base / "input"; inp.mkdir(parents=True, exist_ok=True)
    (inp / "K.grep").write_text("A.java:1:static final int K\n", "utf-8")
    out = base / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    return hashlib.sha256((out / "K.tsv").read_bytes()).hexdigest()


def test_既定出力は_items_per_mb値に不感(tmp_path, monkeypatch):
    # 真の能動ガード: 既定定数での出力 sha を基準に、定数を極値へ
    # monkeypatch しても **基準と一致** すること（v=default 比較）。
    # 理由A: 同一ディレクトリで実行し file 絶対パスを固定（定数のみが変数）。
    base = tmp_path / "inv1"
    ref = _run(base)                                       # 既定 _ITEMS_PER_MB
    for v in (1, 10 ** 9):
        monkeypatch.setattr("grep_analyzer.budget._ITEMS_PER_MB", v)
        assert _run(base) == ref                            # 既定経路は定数不感
        monkeypatch.undo()
