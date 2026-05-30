import importlib.util
from pathlib import Path


def _load():
    spec = importlib.util.spec_from_file_location(
        "probe_candidates", "scripts/probe_candidates.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def test_union記号はstoplist適用後のchase記号を含む(tmp_path):
    probe = _load()
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { static final int KCODE = 1; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K.grep").write_text("A.java:1:    static final int KCODE = 1;\n", "utf-8")
    union = probe.compute_initial_union(inp, src)
    assert "KCODE" in union


def test_probe集計は候補総バイトと非utf8割合を返す(tmp_path):
    probe = _load()
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { int KCODE = 1; }\n", "utf-8")
    (src / "B.java").write_bytes("// KCODE 参照".encode("cp932") + b"\n")
    rep = probe.measure(["KCODE"], src)
    assert rep["candidate_files"] >= 1
    assert rep["candidate_bytes"] > 0
    assert 0.0 <= rep["non_utf8_ratio"] <= 1.0
