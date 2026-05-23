"""v2 正規表現トラック言語の統合（perl/groovy/plsql 混在）。"""

from grep_analyzer.pipeline import _default_opts, run


def test_perl_groovy_plsql混在を1実行で処理する(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.pl").write_text('my $CODE = "X";\n', "utf-8")
    (src / "b.groovy").write_text('def CODE = "X"\n', "utf-8")
    (src / "c.pkb").write_text("v_CODE VARCHAR2(10) := 'X';\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "CODE.grep").write_text(
        'a.pl:1:my $CODE = "X";\nb.groovy:1:def CODE = "X"\n'
        "c.pkb:1:v_CODE VARCHAR2(10) := 'X';\n", "utf-8")
    out = tmp_path / "out"
    assert run(input_dir=inp, output_dir=out, source_root=src, opts=_default_opts()) == 0
    tsv = (out / "CODE.tsv").read_text("utf-8-sig")
    assert "\tperl\t" in tsv and "\tgroovy\t" in tsv and "\tsql\t" in tsv
