from grep_analyzer.snippet import clamp_lines


def test_上限内はそのまま連結():
    assert clamp_lines(["a", "b", "c"], 1) == "a \\n b \\n c"


def test_行数上限超過は上下対称縮約し上下マーカ():
    lines = [f"L{i}" for i in range(11)]   # 0..10, hit=5
    assert clamp_lines(lines, 5, line_max=3) == \
        "…(+4上行省略)L4 \\n L5 \\n L6…(+4下行省略)"


def test_ヒット行単独が文字数上限超過はコードポイント切詰():
    assert clamp_lines(["x" * 50], 0, char_max=10) == "x" * 9 + "…"


def test_片側範囲端到達後は反対側のみ継続():
    assert clamp_lines(["A", "B", "C", "D", "E"], 1, line_max=3) == \
        "A \\n B \\n C…(+2下行省略)"


from grep_analyzer.snippet import heuristic_span


def test_sql_whereから上下を句_文末境界まで():
    lines = ["SELECT * FROM t", "WHERE a = 1", "  AND b = 2",
             "  AND c = 3;", "ORDER BY a"]
    assert heuristic_span(lines, 2, "sql") == (1, 3)


def test_shell_文終端fiで停止():
    lines = ["if [ $x -eq 1 ]; then", "  echo hi", "fi", "next"]
    assert heuristic_span(lines, 1, "shell") == (0, 2)


def test_境界未検出でも有限():
    s, e = heuristic_span(["x = ("] + ["  + 1"] * 50, 0, "sql")
    assert (e - s + 1) <= 12


from grep_analyzer.snippet import ts_span


def test_java_単純文は当該statement物理行スパン():
    assert ts_span("java", "class A {\n  int x =\n    1 + 2;\n}\n", 2) == (1, 2)


def test_java_if条件部のみ本体非包含():
    src = "class A { void m(int s){\n  if (s\n      == 1) {\n    g();\n  }\n}}\n"
    assert ts_span("java", src, 2) == (1, 2)


def test_同一行複数statementは行頭statement_列非依存():
    assert ts_span("java", "class A { void m(){\n a(); b(); c();\n}}\n", 2) == (1, 1)


def test_if条件に文字列内括弧があっても条件部のみ():
    src = ('class A{ void m(String s){\n if (s.equals(")")\n'
           '   || s.isEmpty()) {\n  g();\n }\n}}\n')
    assert ts_span("java", src, 2) == (1, 2)


def test_parse不能はNone():
    assert ts_span("java", "@@@@@\n", 1) is None


def test_無関係エラーがあっても健全行はスパン維持_祖先遡上しない():
    # 3行目のみ破損。2行目の宣言は健全 → None でなくその行スパン
    assert ts_span("java", "class A{\n int ok = 1;\n void @@@ broken\n}\n", 2) \
        == (1, 1)


def test_選択文の内部にエラーがあればNone():
    assert ts_span("c", "int f(){\n int x = (1 +\n}\n", 2) is None


def test_proc_非EXEC_C文はmask後にCノード規則():
    # 生 EXEC が C パースを壊さない（mask_exec_sql 後・行番号保存）
    assert ts_span("proc", "int g = 1\n  + 2;\nEXEC SQL SELECT 1 ;\n", 1) \
        == (0, 1)


from grep_analyzer.snippet import proc_exec_span


def test_proc_exec_spanは原ソース行スパン():
    src = "int x;\nEXEC SQL SELECT 1\n  INTO :a FROM dual ;\n"
    assert proc_exec_span(src, 2) == (1, 2)
    assert proc_exec_span(src, 1) is None


from grep_analyzer.snippet import build_snippet


def test_java_複数行宣言を1セルへ連結():
    src = "class A {\n  int x =\n    1 + 2;\n}\n"
    assert build_snippet("java", "bourne", src, 2) == "  int x = \\n     1 + 2;"


def test_java_if条件行スパン_行末ブレース同居_本体後続行非包含():
    # ts_span (1,2)。行単位切出のため行2末尾の ` {` は同一物理行ゆえ含む。
    # 本体 g(); 等の後続行は非包含（spec §9 表）。
    src = "class A{ void m(int s){\n  if (s\n      == 1) {\n    g();\n  }\n}}\n"
    assert build_snippet("java", "bourne", src, 2) == "  if (s \\n       == 1) {"


def test_sql_複数条件whereを連結():
    src = "SELECT *\nFROM t\nWHERE a=1\n  AND b=2;\n"
    assert "WHERE a=1 \\n   AND b=2;" in build_snippet("sql", "bourne", src, 3)


def test_proc_EXEC区間は原ソース行():
    src = "int x;\nEXEC SQL SELECT 1\n  INTO :a FROM dual ;\nint z;\n"
    assert build_snippet("proc", "bourne", src, 2) == \
        "EXEC SQL SELECT 1 \\n   INTO :a FROM dual ;"


def test_parse不能javaは最後ヒット1行():
    assert build_snippet("java", "bourne", "@@@@@\n", 1) == "@@@@@"


def test_区切り衝突はバックスラッシュ二重化_サニタイズ後():
    # ソース行に ' \n ' 4文字並びが出現 → \ を \\ へ。タブは空白化(規約①)
    src = "a \\n b\tc\n"
    assert build_snippet("shell", "bourne", src, 1) == "a \\\\n b c"


def test_python_複数行代入スパン():
    from grep_analyzer.snippet import ts_span
    assert ts_span("python", "X = (\n  1 + 2\n)\n", 1) == (0, 2)


def test_python_単純文1行():
    from grep_analyzer.snippet import ts_span
    assert ts_span("python", "a = 1\nb = 2\n", 1) == (0, 0)


def test_js_複数行宣言スパン():
    from grep_analyzer.snippet import ts_span
    assert ts_span("javascript", "const X =\n  1 + 2;\n", 1) == (0, 1)


def test_build_snippet_python():
    from grep_analyzer.snippet import build_snippet
    s = build_snippet("python", "bourne", "X = (\n  1 + 2\n)\n", 1)
    assert "X = (" in s


def test_jsp_snippet_多行scriptletはregion_span():
    src = "<html>\n<%\n  int x = 1;\n%>\n</html>\n"
    out = build_snippet("jsp", "", src, 3)
    assert "int x = 1;" in out


def test_html_snippetは1行():
    src = "<p>line1</p>\n<p>TRACKED</p>\n<p>line3</p>\n"
    out = build_snippet("html", "", src, 2)
    assert "TRACKED" in out and "line1" not in out and "line3" not in out


def test_build_snippet_inline_template行は1行():
    # const 宣言で包むと未 routing 時 ts_span が宣言全体（巨大スパン）を返すため
    # routing（angular_inline→1行）の効果を観測できる（@Component デコレータ形は
    # ts_span が None を返し元から1行＝routing 効果が出ない・spec §7 巨大スパン回避）。
    src = ('export const C = defineComponent({\n'   # 1
           '  template: `\n'                         # 2
           '    <p>{{ TRACKED }}</p>\n'             # 3 (hit)
           '  `,\n'                                  # 4
           '});\n')                                  # 5
    out = build_snippet("typescript", "", src, 3)
    assert "TRACKED" in out
    assert "defineComponent" not in out             # 宣言全体の巨大スパンにならない＝routing 効果
