"""Python AST chaser（field-directed・spec §6.3/§6.5）。

ASTChaser: extract_tree(language, root, lineno) → ChaseSymbols。parse は呼出側。
束縛導入ノードへ climb し、name:/left: フィールドのみから名を抽出（RHS/型は読まない）。
"""
import re

from grep_analyzer.classifiers.ts_classifier import binding_at_line
from grep_analyzer.model import ChaseSymbols

_BINDING = {"assignment", "augmented_assignment", "decorated_definition"}
_CONST_RE = re.compile(r"^[A-Z_][A-Z0-9_]+$")


def _names_from_target(node, consts, vars_):
    t = node.type
    if t == "identifier":
        name = node.text.decode("utf-8", "replace")
        (consts if _CONST_RE.match(name) else vars_).append(name)
    elif t in ("pattern_list", "tuple_pattern", "list_pattern"):
        for ch in node.children:
            if ch.is_named:
                _names_from_target(ch, consts, vars_)
    elif t == "list_splat_pattern":
        for ch in node.children:
            if ch.type == "identifier":
                vars_.append(ch.text.decode("utf-8", "replace"))
    # attribute(self.x) / subscript(d[k]) は束縛でない＝抽出せず（spec §8）


def _from_assignment(node, consts, vars_):
    left = node.child_by_field_name("left")
    if left is not None:
        _names_from_target(left, consts, vars_)
    right = node.child_by_field_name("right")
    while right is not None and right.type == "assignment":  # chained a = b = 1
        l2 = right.child_by_field_name("left")
        if l2 is not None:
            _names_from_target(l2, consts, vars_)
        right = right.child_by_field_name("right")


def _from_decorated(node, getters, setters):
    defn = node.child_by_field_name("definition")
    if defn is None or defn.type != "function_definition":
        return
    name_node = defn.child_by_field_name("name")
    if name_node is None:
        return
    name = name_node.text.decode("utf-8", "replace")
    for ch in node.children:
        if ch.type != "decorator":
            continue
        expr = next((c for c in ch.children if c.is_named), None)
        if expr is None:
            continue
        if expr.type == "identifier" and expr.text.decode("utf-8", "replace") == "property":
            getters.append(name)
            return
        if expr.type == "attribute":
            attr = expr.child_by_field_name("attribute")
            if attr is not None and attr.text.decode("utf-8", "replace") == "setter":
                setters.append(name)
                return


def extract_tree(language, root, lineno):
    node = binding_at_line(root, lineno, _BINDING)
    if node is None:
        return ChaseSymbols()
    consts, vars_, getters, setters = [], [], [], []
    if node.type == "decorated_definition":
        _from_decorated(node, getters, setters)
    else:
        _from_assignment(node, consts, vars_)
    return ChaseSymbols(tuple(consts), tuple(vars_), tuple(getters), tuple(setters))
