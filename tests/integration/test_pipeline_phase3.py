"""pipeline の resume スキップ＋既定 byte 不変（spec v4 §3・Inv-1/Inv-7）。"""

import hashlib
from grep_analyzer.cli import main


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ static final int K1=1; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:static final int K1=1;\n", "utf-8")
    return src, inp


def test_既定でmanifest生成されTSVは従来と同名(tmp_path):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    assert (out / "K1.tsv").exists()
    assert (out / "K1.manifest.json").exists()


def test_resumeで完了kwをスキップ_バイト不変(tmp_path):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0
    sha1 = hashlib.sha256((out / "K1.tsv").read_bytes()).hexdigest()
    assert main(a + ["--resume"]) == 0
    assert hashlib.sha256((out / "K1.tsv").read_bytes()).hexdigest() == sha1
