"""Phase 2b 不変条件の総合契約（spec §8.2/§9・既定出力不変と決定性）。"""

import hashlib
from pathlib import Path

import pytest

from grep_analyzer.cli import main


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ static final int K1 = 1; }\n", "utf-8")
    (src / "B.java").write_text("class B{ static final int K2 = K1; }\n", "utf-8")
    (src / "C.java").write_text("class C{ int z2 = K2; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:static final int K1 = 1;\n", "utf-8")
    (inp / "K9.grep").write_text("A.java:1:static final int K1 = 1;\n", "utf-8")
    return src, inp


def _h(tmp_path, src, inp, name, extra, fn="K1.tsv"):
    out = tmp_path / name
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)] + extra) == 0
    return hashlib.sha256((out / fn).read_bytes()).hexdigest()


def test_既定とjobsは完全一致_既定出力不変かつ決定的(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _h(tmp_path, src, inp, "base", [])
    assert _h(tmp_path, src, inp, "j4", ["--jobs", "4"]) == base
    assert _h(tmp_path, src, inp, "base2", []) == base


def test_memory0は2回実行決定的_degrade決定性(tmp_path: Path):
    src, inp = _setup(tmp_path)
    a = _h(tmp_path, src, inp, "m1", ["--memory-limit", "0", "--max-passes", "8"])
    b = _h(tmp_path, src, inp, "m2", ["--memory-limit", "0", "--max-passes", "8"])
    c = _h(tmp_path, src, inp, "m3", ["--memory-limit", "0", "--jobs", "4",
                                      "--max-passes", "8"])
    assert a == b == c


def test_複数keyword_diagnosticsは2回実行で決定的(tmp_path: Path):
    src, inp = _setup(tmp_path)
    o1 = tmp_path / "d1"; o2 = tmp_path / "d2"
    main(["--input", str(inp), "--output", str(o1), "--source-root", str(src)])
    main(["--input", str(inp), "--output", str(o2), "--source-root", str(src)])
    assert (o1 / "diagnostics.txt").read_bytes() == \
           (o2 / "diagnostics.txt").read_bytes()


@pytest.mark.requires_ripgrep
def test_ripgrep有無でTSV完全一致(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _h(tmp_path, src, inp, "norg", [])
    assert _h(tmp_path, src, inp, "rg", ["--use-ripgrep"]) == base
    assert _h(tmp_path, src, inp, "rgj4", ["--use-ripgrep", "--jobs", "4"]) == base
