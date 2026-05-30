import dataclasses

import pytest

from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.pipeline import _default_opts, _effective_use_ripgrep, run
from grep_analyzer.walk import collect_files_ex


def test_effective_明示優先(monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "available", lambda: True)
    assert _effective_use_ripgrep(True, total_bytes=0, threshold=1 << 30) is True
    assert _effective_use_ripgrep(False, total_bytes=10**12, threshold=1 << 30) is False


def test_effective_既定は閾値とrg可否(monkeypatch):
    from grep_analyzer import ripgrep
    monkeypatch.setattr(ripgrep, "available", lambda: True)
    assert _effective_use_ripgrep(None, total_bytes=(1 << 30), threshold=1 << 30) is True
    assert _effective_use_ripgrep(None, total_bytes=(1 << 30) - 1, threshold=1 << 30) is False
    monkeypatch.setattr(ripgrep, "available", lambda: False)
    assert _effective_use_ripgrep(None, total_bytes=10**12, threshold=1 << 30) is False


@pytest.mark.requires_ripgrep
def test_prefilter_onoffでTSV行バイト一致(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { static final int KCODE = 1; int x = KCODE; }\n", "utf-8")
    (src / "B.java").write_text("class B { int y = 0; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    # 出力名は .grep の stem に一致するため KCODE.grep → KCODE.tsv。
    (inp / "KCODE.grep").write_text("A.java:1:    static final int KCODE = 1;\n", "utf-8")

    def runit(flag):
        out = tmp_path / f"out_{flag}"
        opts = dataclasses.replace(_default_opts(), use_ripgrep=flag)
        run(inp, out, src, opts)
        return (out / "KCODE.tsv").read_bytes()
    assert runit(True) == runit(False)


@pytest.mark.requires_ripgrep
def test_unsafe_utf32BOMファイルはprefilterで脱落しない(tmp_path):
    """BOM 付き非ASCII透過 file（rg は raw bytes で ASCII symbol を見つけられない）が
    unsafe 判定で prefilter ON でも走査され、ON/OFF で出力バイト一致することを固定。

    実装メモ: 当初計画は UTF-16-LE BOM だったが、ripgrep 13 は UTF-16 BOM を
    sniff して透過的に UTF-8 へ transcode するため rg が KCODE を発見してしまい
    （脱落せず）rescue 経路を踏まない。UTF-32-LE BOM (\\xff\\xfe\\x00\\x00) は rg が
    transcode せず ASCII symbol を発見できないため、collect_files_ex の unsafe 判定
    （BOM ベース）と組合せて keep ∪ unsafe の rescue を真に検証できる。
    rescue が load-bearing であることを示すため、seed は ASCII の A.java に置き、
    indirect chase が UTF-32 の U.java 内 usage(A.KCODE) に到達する設計にする
    （U.java 自体に seed を置くと direct hit が seed 段で確定し scan を踏まないため）。
    """
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A { static final int KCODE = 1; }\n", "utf-8")
    # 先頭 CJK 多数で chardet が UTF-32 を選ぶ。class 行（KCODE usage）は lineno 2。
    body = "漢" * 5000 + "\nclass U { int x = A.KCODE; }\n"
    (src / "U.java").write_bytes(b"\xff\xfe\x00\x00" + body.encode("utf-32-le"))
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "KCODE.grep").write_text("A.java:1:    static final int KCODE = 1;\n", "utf-8")

    # (1) U.java が unsafe 判定であること（BOM）を直接確認。
    files, _total, unsafe = collect_files_ex(
        src, include=[], exclude=[], follow_symlinks=False,
        max_file_bytes=5_000_000, diag=Diagnostics())
    assert "U.java" in unsafe
    # (2) prefilter ON 時、rg の keep 集合は U.java を含まない（生 UTF-32 バイトに
    #     ASCII "KCODE" が無いため）。rescue が無ければ U.java は脱落する。
    from grep_analyzer import ripgrep
    rel_to_abs = {r: a for r, a in files}
    keep = ripgrep.prefilter(src, rel_to_abs, ["KCODE"])
    assert keep is not None and "U.java" not in keep

    def runit(flag):
        out = tmp_path / f"out_{flag}"
        opts = dataclasses.replace(_default_opts(), use_ripgrep=flag)
        run(inp, out, src, opts)
        return (out / "KCODE.tsv").read_bytes()
    on, off = runit(True), runit(False)
    # (3) unsafe_rels が U.java を rescue するため ON==OFF。indirect:constant の
    #     U.java:2 行が両者に存在する。
    assert on == off
    assert b"U.java" in off and b"indirect" in off
