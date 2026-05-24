"""C-2: resume 完了 kw に対し finalize が呼ばれない（実スキップ）ことを spy で検証。"""

from grep_analyzer import pipeline
from grep_analyzer.cli import main


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ static final int K1=1; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:static final int K1=1;\n", "utf-8")
    return src, inp


def test_resume完了kwはfinalizeを呼ばない(tmp_path, monkeypatch):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0                                    # 1回目で完了

    calls: list[str] = []
    real_finalize = pipeline.output_writer.finalize

    def _spy(output_dir, keyword, rows, opts):
        calls.append(keyword)
        return real_finalize(output_dir, keyword, rows, opts)

    monkeypatch.setattr(pipeline.output_writer, "finalize", _spy)
    assert main(a + ["--resume"]) == 0                     # 2回目は resume
    assert calls == []                                     # 完了 kw は finalize 非呼出＝実スキップ


def test_未完了kwはresumeでも再処理される(tmp_path, monkeypatch):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0
    (out / "K1.manifest.json").unlink()                    # 完了痕跡を消す

    calls: list[str] = []
    real_finalize = pipeline.output_writer.finalize
    monkeypatch.setattr(pipeline.output_writer, "finalize",
                        lambda *x: (calls.append(x[1]), real_finalize(*x))[1])
    assert main(a + ["--resume"]) == 0
    assert calls == ["K1"]                                 # manifest 無し→再処理される
