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


# B-2: mask_exec_sql の区間検出をリテラル空白化コピーに統一（文字列内 ; 誤切断）。


def test_リテラル内セミコロンで区間が途中切断されない():
    src = (
        "int a = 1;\n"
        "EXEC SQL UPDATE t SET note = 'has;semicolon'\n"
        "  WHERE id = :id;\n"
        "int b = 2;\n"
    )
    masked = mask_exec_sql(src)
    # EXEC 区間（2-3行目）は完全に空行化され残骸 SQL が残らない。
    # （"WHERE"/"semicolon" はリテラル ; 以降の残骸＝fix 前は残る＝load-bearing）
    assert "WHERE" not in masked
    assert "semicolon" not in masked
    # 区間外の C コードは保持
    assert "int a = 1;" in masked
    assert "int b = 2;" in masked
    # 行番号保存（総行数不変）
    assert masked.count("\n") == src.count("\n")


def test_exec_spansとmask_exec_sqlが同一区間を見る():
    src = "EXEC SQL SELECT x INTO :v FROM t WHERE c = 'a;b';\n"
    assert exec_spans(src) == [(0, 0)]
    assert "SELECT" not in mask_exec_sql(src)


def test_通常のexec_sqlは従来どおり空行化():
    src = "EXEC SQL SELECT 1 INTO :x FROM dual;\nint y = 0;\n"
    masked = mask_exec_sql(src)
    assert "SELECT" not in masked
    assert "int y = 0;" in masked
    assert masked.count("\n") == src.count("\n")
