"""Java 用 Chaser — 言語別シンボル抽出とリテラルマスク。

`Chaser` プロトコル準拠のモジュールレベル関数を公開する。
chase.py の dispatcher が `_CHASERS["java"]` 経由で呼び出す。
"""

import re

from grep_analyzer.classifiers.ts_classifier import bindings_at_line
from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    JAVA_CONST_RE,
    JAVA_GETSET_RE,
    JAVA_VAR_RE,
)


def mask(line: str) -> str:
    """Java のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["java"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Java の規則で分類抽出する（dialect は無視）。

    static final 修飾子付き宣言を constant、それ以外の代入を var、
    getter/setter を terminal として収集する。
    """
    masked = mask(line)
    consts = tuple(
        g.group(2) for g in JAVA_CONST_RE.finditer(masked)
        if "static" in g.group(1).split() and "final" in g.group(1).split()
    )
    getters = tuple(
        x.group(1) for x in JAVA_GETSET_RE.finditer(masked) if x.group(1)[0] == "g"
    )
    setters = tuple(
        x.group(1) for x in JAVA_GETSET_RE.finditer(masked) if x.group(1)[0] == "s"
    )
    const_set = set(consts)
    vars_ = tuple(
        v for v in (x.group(1) for x in JAVA_VAR_RE.finditer(masked))
        if v not in const_set
    )
    return ChaseSymbols(consts, vars_, getters, setters)


_AST_BINDING = {"local_variable_declaration", "field_declaration", "resource",
                "assignment_expression", "method_invocation", "method_declaration"}
_GETSET_RE = re.compile(r"^(get|set)[A-Z]\w*$")


def _modifier_tokens(node) -> set[str]:
    for ch in node.children:
        if ch.type == "modifiers":
            return {c.text.decode("utf-8", "replace") for c in ch.children if not c.is_named}
    return set()


def _handle_java(node, lineno, consts, vars_, getters, setters):
    t = node.type
    if t in ("local_variable_declaration", "field_declaration"):
        mods = _modifier_tokens(node)
        target = consts if ("static" in mods and "final" in mods) else vars_
        for ch in node.children:
            if ch.type == "variable_declarator":
                nm = ch.child_by_field_name("name")
                if nm is not None and nm.type == "identifier":
                    target.append(nm.text.decode("utf-8", "replace"))
    elif t == "resource":
        nm = node.child_by_field_name("name")
        if nm is not None and nm.type == "identifier":
            vars_.append(nm.text.decode("utf-8", "replace"))
    elif t == "assignment_expression":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            vars_.append(left.text.decode("utf-8", "replace"))
    elif t in ("method_invocation", "method_declaration"):
        nm = node.child_by_field_name("name")
        if nm is not None and nm.start_point[0] == lineno - 1:    # name 行ゲート（spec §3.2）
            name = nm.text.decode("utf-8", "replace")
            if _GETSET_RE.match(name):
                (getters if name[0] == "g" else setters).append(name)


def extract_tree(language, root, lineno):
    """parse 済 root から java 束縛を field-directed・multi-node 抽出（spec §3.3）。"""
    consts, vars_, getters, setters = [], [], [], []
    for node in bindings_at_line(root, lineno, _AST_BINDING):
        _handle_java(node, lineno, consts, vars_, getters, setters)
    const_set = set(consts)
    vars_ = [v for v in vars_ if v not in const_set]
    return ChaseSymbols(tuple(consts), tuple(vars_), tuple(getters), tuple(setters))
