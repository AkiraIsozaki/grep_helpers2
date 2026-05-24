"""AST chaser（python/javascript/typescript/java/c/jsp/proc）field-directed 抽出（spec §6.5・§3.3・§3.4）。"""
from grep_analyzer.classifiers.ts_classifier import parse_tree
from grep_analyzer.model import ChaseSymbols


def _py(text, lineno):
    from grep_analyzer.classifiers.python_chaser import extract_tree
    return extract_tree("python", parse_tree("python", text), lineno)


def test_python_const_var_allcaps():
    cs = _py("XX = 1\ny = f()\n", 1)       # ALL_CAPS は2字以上（単字 X は var＝spec §6.4）
    assert cs.constants == ("XX",) and cs.vars == ()
    cs2 = _py("XX = 1\ny = f()\n", 2)
    assert cs2.vars == ("y",) and cs2.constants == ()


def test_python_tuple_unpack():
    cs = _py("a, b = f()\n", 1)
    assert cs.vars == ("a", "b")


def test_python_multiline_assign():
    cs = _py("MULTI = (\n  1 + 2\n)\n", 2)  # hit on continuation line
    assert cs.constants == ("MULTI",)


def test_python_attribute_subscript_lhs_は抽出しない():
    assert _py("self.x = 1\n", 1).vars == ()
    assert _py("d[k] = 1\n", 1).vars == ()


def test_python_property_getter_setter():
    src = ("class C:\n    @property\n    def val(self):\n        return self._v\n"
           "    @val.setter\n    def val(self, v):\n        self._v = v\n")
    assert _py(src, 3).getters == ("val",)   # decorated_definition spans 2-4
    assert _py(src, 6).setters == ("val",)


def test_python_staticmethod_は無視():
    src = "class C:\n    @staticmethod\n    def m():\n        return 1\n"
    cs = _py(src, 3)
    assert cs.getters == () and cs.setters == ()


def _js(text, lineno):
    from grep_analyzer.classifiers.javascript_chaser import extract_tree
    return extract_tree("javascript", parse_tree("javascript", text), lineno)


def test_js_const_let_var():
    assert _js("const X = 1;\n", 1).constants == ("X",)
    assert _js("let y = 1;\n", 1).vars == ("y",)
    assert _js("var z = 1;\n", 1).vars == ("z",)
    assert _js("a = b;\n", 1).vars == ("a",)


def test_js_destructure():
    assert _js("const {p, q} = o;\n", 1).constants == ("p", "q")
    assert _js("const {a: x} = o;\n", 1).constants == ("x",)   # key a は除外
    assert _js("const {b = 5} = o;\n", 1).constants == ("b",)  # default 値除外
    assert _js("const [m, ...rest] = o;\n", 1).constants == ("m", "rest")


def test_js_field_getter_setter():
    src = ("class C {\n  field = 1;\n  get val() { return 1; }\n"
           "  set val(v) {}\n  method() {}\n}\n")
    assert _js(src, 2).vars == ("field",)
    assert _js(src, 3).getters == ("val",)
    assert _js(src, 4).setters == ("val",)
    assert _js(src, 5).vars == () and _js(src, 5).getters == ()  # 通常メソッドは無視


def test_js_multiline_const():
    assert _js("const MULTI =\n  1 + 2;\n", 2).constants == ("MULTI",)


def _ts(text, lineno, language="typescript"):
    from grep_analyzer.classifiers.typescript_chaser import extract_tree
    return extract_tree(language, parse_tree(language, text), lineno)


def test_ts_readonly_const_field():
    src = "class C {\n  readonly r = 1;\n  private p = 2;\n}\n"
    assert _ts(src, 2).constants == ("r",)
    assert _ts(src, 3).vars == ("p",)


def test_ts_enum_members_constant():
    assert _ts("enum E { A, B }\n", 1).constants == ("A", "B")
    assert _ts("enum E { A = 1, B = 2 }\n", 1).constants == ("A", "B")


def test_ts_generics_型識別子を抽出しない():
    cs = _ts("const m: Map<string, number> = x;\n", 1)
    assert cs.constants == ("m",)            # Map/string/number/x は出ない


def test_ts_interface_type_は抽出しない():
    assert _ts("interface I { x: number; }\n", 1) == ChaseSymbols()
    assert _ts("type T = number;\n", 1) == ChaseSymbols()


def test_tsx_は同規則():
    assert _ts("const App = () => null;\n", 1, language="tsx").constants == ("App",)


def test_js_object_destructure_default():
    assert _js("const {a: x = 5} = o;\n", 1).constants == ("x",)
    assert _js("const {a: {b} = {}} = o;\n", 1).constants == ("b",)


def test_ts_object_destructure_default():
    assert _ts("const {a: x = 5} = o;\n", 1).constants == ("x",)


def test_python_single_line_class_body():
    assert _py("class C: ATTR = 1\n", 1).constants == ("ATTR",)


def test_python_single_line_if_body():
    assert _py("if True: yy = COMPUTED\n", 1).vars == ("yy",)


from grep_analyzer.chase import extract_chase_symbols_tree


def test_angular_ngFor_束縛をAST抽出():
    src = '<li *ngFor="let item of TRACKED">{{item}}</li>\n'
    cs = extract_chase_symbols_tree("angular", src, 1)
    assert "item" in cs.vars


def test_angular_inline_chaser_ngFor():
    src = '@Component({ template: `<li *ngFor="let row of TRACKED">{{row.code}}</li>` })\n'
    cs = extract_chase_symbols_tree("angular_inline", src, 1)
    assert "row" in cs.vars


def _java(text, lineno):
    from grep_analyzer.classifiers.java_chaser import extract_tree
    return extract_tree("java", parse_tree("java", text), lineno)


def test_java_static_final_const_と_var():
    assert _java("class C { static final String K = init(); }\n", 1).constants == ("K",)
    assert _java("class C { int n = 1; }\n", 1).vars == ("n",)
    # 配列・ジェネリクスも const
    assert _java("class C { static final int[] A = x; }\n", 1).constants == ("A",)
    assert _java(
        "class C { private static final Map<String,Integer> M = init(); }\n", 1
    ).constants == ("M",)
    # final のみ（static 無し）は var
    cs = _java("class C { void f(){ final int X = 1; } }\n", 1)
    assert cs.constants == () and cs.vars == ("X",)


def test_java_文字列内の代入様字句は非抽出():
    cs = _java('class C { void f(){ String s = "url=/x"; int n = 1; } }\n', 1)
    assert cs.vars == ("s", "n") and "url" not in cs.vars


def test_java_getter_setter_var_同行multinode():
    cs = _java("class C { void f(){ int count = svc.getName(); obj.setValue(count); } }\n", 1)
    assert cs.vars == ("count",)
    assert cs.getters == ("getName",) and cs.setters == ("setValue",)


def test_java_getter_setter_本体行は過抽出しない():
    src = ("class C {\n"
           "  public String getName() {\n"     # L2 シグネチャ（name 行）
           "    return this.name;\n"           # L3 本体
           "  }\n"
           "}\n")
    assert _java(src, 2).getters == ("getName",)   # name 行は採用
    assert _java(src, 3).getters == ()             # 本体行は過抽出しない


def test_java_field_access_左辺は非抽出():
    cs = _java("class C { void f(){ this.y = 6; total += 1; } }\n", 1)
    assert "y" not in cs.vars            # field_access 左辺は非抽出
    assert cs.vars == ("total",)         # 複合代入は捕捉


def test_java_try_with_resources():
    src = "class C { void f() throws Exception { try (java.io.Reader r = open()) { } } }\n"
    assert _java(src, 1).vars == ("r",)


def test_java_jsp_経由():
    from grep_analyzer.chase import extract_chase_symbols_tree
    assert "x" in extract_chase_symbols_tree("jsp", "<% int x = TRACKED; %>\n", 1).vars
    assert extract_chase_symbols_tree("jsp", "${ TRACKED.code }\n", 1).vars == ()


def _c(text, lineno, language="c"):
    from grep_analyzer.classifiers.c_chaser import extract_tree
    return extract_tree(language, parse_tree(language, text), lineno)


def test_c_define_と_const_と_var():
    assert _c("#define MAX_LEN 10\n", 1).constants == ("MAX_LEN",)
    assert _c("const int FOO = 1;\n", 1).constants == ("FOO",)
    assert _c("int n = 3;\n", 1).vars == ("n",)


def test_c_関数様マクロ_const():
    assert _c("#define SQ(x) ((x)*(x))\n", 1).constants == ("SQ",)


def test_c_ポインタ_複数宣言子_noinit():
    assert _c('char *p = "X";\n', 1).vars == ("p",)
    assert _c("int a = 1, b = 2;\n", 1).vars == ("a", "b")
    assert _c("int x;\n", 1).vars == ("x",)            # no-init も捕捉


def test_c_struct_member_field_declaration():
    src = "struct S { const int K; int *q; int a, b; };\n"
    cs = _c(src, 1)
    assert "K" in cs.constants
    assert cs.vars == ("q", "a", "b")


def test_c_関数宣言名_関数ポインタは非抽出():
    assert _c("int foo(void);\n", 1) .vars == ()
    assert _c("int (*fp)(void) = cb;\n", 1).vars == ()


def test_c_複合代入捕捉():
    assert _c("void f(){ total += x; arr[i] += 1; }\n", 1).vars == ("total",)


def test_c_getter_setterは無し():
    cs = _c("int n = 3;\n", 1)
    assert cs.getters == () and cs.setters == ()


def test_proc_exec_sql内は非抽出_区間外は抽出():
    from grep_analyzer.chase import extract_chase_symbols_tree
    # 単一行 EXEC SQL → mask_exec_sql で空白化
    cs = extract_chase_symbols_tree("proc", "EXEC SQL SELECT c INTO :host FROM t;\n", 1)
    assert cs.vars == () and cs.constants == () and "host" not in cs.vars
    # 区間外の C 宣言は抽出
    src = ("int f(){\n"
           " EXEC SQL UPDATE t SET col = v WHERE id = :h;\n"
           " int after = 1;\n"
           "}\n")
    assert extract_chase_symbols_tree("proc", src, 2).vars == ()       # EXEC SQL 行
    assert extract_chase_symbols_tree("proc", src, 3).vars == ("after",)  # 区間外
