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
