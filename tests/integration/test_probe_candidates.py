import importlib.util
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/integration/* → repo root


def _load():
    spec = importlib.util.spec_from_file_location(
        "probe_candidates", str(_REPO_ROOT / "scripts" / "probe_candidates.py"))
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


def test_非ast経路はgrep内容ではなくファイル行から記号を抽出する(tmp_path):
    # on-disk のファイル行は MYVAR=42（shell chaser が MYVAR を surface する）。
    # .grep 内容は stale/truncated で MYVAR を含まない。union が FILE 行を反映する
    # ことを確認し、FIX 1（.grep 内容→ファイル行）の回帰を捕捉する。
    probe = _load()
    src = tmp_path / "src"; src.mkdir()
    (src / "s.sh").write_text("MYVAR=42\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "S.grep").write_text("s.sh:1:STALE_TRUNCATED_LINE\n", "utf-8")
    union = probe.compute_initial_union(inp, src)
    assert "MYVAR" in union
    assert "STALE_TRUNCATED_LINE" not in union


def test_prefilterがNoneなら全ファイルフォールバック(tmp_path, monkeypatch):
    probe = _load()
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { int KCODE = 1; }\n", "utf-8")
    (src / "B.java").write_text("class B {}\n", "utf-8")
    monkeypatch.setattr(probe.ripgrep, "prefilter", lambda *a, **k: None)
    rep = probe.measure(["KCODE"], src)
    assert rep["candidate_files"] == 2
