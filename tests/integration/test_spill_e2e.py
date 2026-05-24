"""C-1: spill 経路を出力非空のまま通し、spill 有/無のバイト同値を凍結する。"""

import dataclasses

from grep_analyzer.pipeline import _default_opts, run


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    # 定数→変数→使用の多ホップ（別行・min_specificity>=2 を満たす長い識別子）で
    # indirect:constant / indirect:var を複数生む構成＝来歴エッジ>0（spill 経由を要する）。
    (src / "C.java").write_text(
        "class C {\n"
        "  static final int THRESHOLD = 1;\n"
        "  int limit = THRESHOLD;\n"
        "  int total = limit;\n"
        "}\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "THRESHOLD.grep").write_text(
        "C.java:2:  static final int THRESHOLD = 1;\n", "utf-8")
    return src, inp


def test_spill経由でも出力は非空かつspillなしとバイト同値(tmp_path):
    src, inp = _setup(tmp_path)
    base = dataclasses.replace(_default_opts(), spill_dir=tmp_path / "spill")
    (tmp_path / "spill").mkdir()

    out_no = tmp_path / "no"
    assert run(input_dir=inp, output_dir=out_no, source_root=src, opts=base) == 0
    bytes_no = (out_no / "THRESHOLD.tsv").read_bytes()

    out_sp = tmp_path / "sp"
    spilled = dataclasses.replace(base, force_spill=1)        # 1 エッジ目から spill
    assert run(input_dir=inp, output_dir=out_sp, source_root=src, opts=spilled) == 0
    bytes_sp = (out_sp / "THRESHOLD.tsv").read_bytes()

    # 出力は非空（indirect 行が存在）かつ spill 有無でバイト同値
    assert b"indirect" in bytes_no
    assert bytes_sp == bytes_no
