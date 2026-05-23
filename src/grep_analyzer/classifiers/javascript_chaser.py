"""JavaScript AST chaser（field-directed・spec §6.5）。

`handle_binding` / `_BINDING` は typescript_chaser から再利用される（DRY）。
"""
from grep_analyzer.classifiers.ts_classifier import binding_at_line
from grep_analyzer.model import ChaseSymbols

_BINDING = {"lexical_declaration", "variable_declaration",
            "assignment_expression", "augmented_assignment_expression",
            "field_definition", "method_definition"}


def _names_from_pattern(node, out):
    t = node.type
    if t in ("identifier", "shorthand_property_identifier_pattern"):
        out.append(node.text.decode("utf-8", "replace"))
    elif t == "object_pattern":
        for ch in node.children:
            if ch.type == "shorthand_property_identifier_pattern":
                out.append(ch.text.decode("utf-8", "replace"))
            elif ch.type == "pair_pattern":
                val = ch.child_by_field_name("value")
                if val is not None:
                    _names_from_pattern(val, out)        # key: は読まない
            elif ch.type == "object_assignment_pattern":
                left = ch.child_by_field_name("left")
                if left is not None:
                    _names_from_pattern(left, out)        # default 値 right: は読まない
            elif ch.type == "rest_pattern":
                for c in ch.children:
                    if c.type == "identifier":
                        out.append(c.text.decode("utf-8", "replace"))
    elif t == "assignment_pattern":
        left = node.child_by_field_name("left")
        if left is not None:
            _names_from_pattern(left, out)
    elif t == "array_pattern":
        for ch in node.children:
            if ch.type == "identifier":
                out.append(ch.text.decode("utf-8", "replace"))
            elif ch.type in ("object_pattern", "array_pattern"):
                _names_from_pattern(ch, out)
            elif ch.type == "assignment_pattern":
                left = ch.child_by_field_name("left")
                if left is not None:
                    _names_from_pattern(left, out)
            elif ch.type == "rest_pattern":
                for c in ch.children:
                    if c.type == "identifier":
                        out.append(c.text.decode("utf-8", "replace"))


def _declarators(decl, is_const, consts, vars_):
    target = consts if is_const else vars_
    for ch in decl.children:
        if ch.type != "variable_declarator":
            continue
        name = ch.child_by_field_name("name")
        if name is not None:
            _names_from_pattern(name, target)


def handle_binding(node, consts, vars_, getters, setters):
    t = node.type
    if t == "lexical_declaration":
        is_const = any(not c.is_named and c.text.decode("utf-8", "replace") == "const"
                       for c in node.children)
        _declarators(node, is_const, consts, vars_)
    elif t == "variable_declaration":
        _declarators(node, False, consts, vars_)
    elif t in ("assignment_expression", "augmented_assignment_expression"):
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            vars_.append(left.text.decode("utf-8", "replace"))
    elif t == "field_definition":
        prop = node.child_by_field_name("property")
        if prop is not None and prop.type in ("property_identifier", "private_property_identifier"):
            vars_.append(prop.text.decode("utf-8", "replace"))
    elif t == "method_definition":
        kind = None
        for c in node.children:
            if not c.is_named and c.text.decode("utf-8", "replace") in ("get", "set"):
                kind = c.text.decode("utf-8", "replace")
                break
        name = node.child_by_field_name("name")
        if kind and name is not None and name.type == "property_identifier":
            (getters if kind == "get" else setters).append(name.text.decode("utf-8", "replace"))


def extract_tree(language, root, lineno):
    node = binding_at_line(root, lineno, _BINDING)
    if node is None:
        return ChaseSymbols()
    consts, vars_, getters, setters = [], [], [], []
    handle_binding(node, consts, vars_, getters, setters)
    return ChaseSymbols(tuple(consts), tuple(vars_), tuple(getters), tuple(setters))
