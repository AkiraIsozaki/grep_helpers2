"""AST chaser（python/javascript/typescript）field-directed 抽出（spec §6.5）。"""
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
