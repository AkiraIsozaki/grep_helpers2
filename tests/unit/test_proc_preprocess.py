"""Pro*C の EXEC SQL 区間を行数保存して中立化する（spec §7・行番号不変）。"""

from grep_analyzer.proc_preprocess import mask_exec_sql


def test_行数は保存される():
    src = "int a;\nEXEC SQL SELECT 1\n  INTO :x\nFROM t;\nint b;\n"
    out = mask_exec_sql(src)
    assert out.count("\n") == src.count("\n")
    assert out.splitlines()[0] == "int a;"
    assert out.splitlines()[4] == "int b;"


def test_EXEC_SQL区間はC構文を壊さない中立行に置換される():
    src = "EXEC SQL SELECT 1;\n"
    out = mask_exec_sql(src)
    assert "SELECT" not in out
    assert out.endswith("\n")


from grep_analyzer.proc_preprocess import exec_spans


def test_文字列内セミコロンで誤切断しない():
    src = "int x;\nEXEC SQL INSERT INTO t\n  VALUES (';', :y) ;\nint z;\n"
    assert exec_spans(src) == [(1, 2)]


def test_複数EXEC区間とEND_EXEC():
    src = "EXEC SQL A ;\nmid;\nEXEC ORACLE OPTION\nEND-EXEC\n"
    assert exec_spans(src) == [(0, 0), (2, 3)]
