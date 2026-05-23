"""v2 正規表現トラック言語の統合（perl/groovy/plsql 混在）＋tree-sitter 4言語。"""

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


def test_tree_sitter_langs_pipeline(tmp_path):
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "m.py").write_text("SEED = init()\nDER = SEED + 1\n", "utf-8")
    (src / "a.ts").write_text("enum E { SEED }\nconst x = SEED;\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "SEED.grep").write_text("m.py:1:SEED = init()\na.ts:1:enum E { SEED }\n", "utf-8")
    out = tmp_path / "out"
    assert run(inp, out, src, _default_opts()) == 0
    text = (out / "SEED.tsv").read_text("utf-8-sig")
    assert "python" in text and "typescript" in text
    assert "indirect:constant" in text  # DER (py) または x(ts) の少なくとも一方


def test_angular_inline_template_chase(tmp_path):
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "x.component.ts").write_text(
        "@Component({\n"
        '  template: `\n'
        '    <li *ngFor="let row of TRACKED">\n'      # L3 テンプレ: row 束縛
        "      {{ row.code }}\n"                       # L4 テンプレ: row 使用
        "  `,\n"
        "})\n"
        "export class X { items = init(); }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "TRACKED.grep").write_text(
        'x.component.ts:3:    <li *ngFor="let row of TRACKED">\n', "utf-8")
    out = tmp_path / "out"
    assert run(inp, out, src, _default_opts()) == 0
    tsv = (out / "TRACKED.tsv").read_text("utf-8-sig")
    assert "\ttypescript\t" in tsv               # language 列は typescript（§2.2）
    assert "indirect:var" in tsv                 # row が chase された
    assert "row" in tsv
