"""TypeScript / TSX AST chaser（JS 規則＋enum/readonly field・spec §6.5）。

JS 規則は javascript_chaser から再利用。tsx は language 引数で grammar 変種を切替
（parse は呼出側＝本モジュールは root のみ受ける）。
"""
from grep_analyzer.classifiers.javascript_chaser import _BINDING as _JS_BINDING
from grep_analyzer.classifiers.javascript_chaser import handle_binding as _handle_js
from grep_analyzer.model import ChaseSymbols

_BINDING = _JS_BINDING | {"public_field_definition", "enum_declaration"}


def _binding_at_line(root, lineno):
    """TS 拡張 _BINDING を用いた最小スパン束縛ノード探索（単一行クラス本体対応）。"""
    target = lineno - 1
    best = None
    best_key = None
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            if node.type in _BINDING:
                key = (node.end_point[0] - node.start_point[0],
                       node.start_byte, node.end_byte, node.type)
                if best_key is None or key < best_key:
                    best, best_key = node, key
            cursor.extend(node.children)
    return best


def _handle_ts(node, consts, vars_, getters, setters):
    t = node.type
    if t == "public_field_definition":
        is_readonly = any(not c.is_named and c.text.decode("utf-8", "replace") == "readonly"
                          for c in node.children)
        name = node.child_by_field_name("name")
        if name is not None and name.type == "property_identifier":
            (consts if is_readonly else vars_).append(name.text.decode("utf-8", "replace"))
    elif t == "enum_declaration":
        body = node.child_by_field_name("body")
        if body is not None:
            for ch in body.children:
                if ch.type == "property_identifier":
                    consts.append(ch.text.decode("utf-8", "replace"))
                elif ch.type == "enum_assignment":
                    nm = ch.child_by_field_name("name")
                    if nm is not None:
                        consts.append(nm.text.decode("utf-8", "replace"))
    else:
        _handle_js(node, consts, vars_, getters, setters)


def extract_tree(language, root, lineno):
    node = _binding_at_line(root, lineno)
    if node is None:
        return ChaseSymbols()
    consts, vars_, getters, setters = [], [], [], []
    _handle_ts(node, consts, vars_, getters, setters)
    return ChaseSymbols(tuple(consts), tuple(vars_), tuple(getters), tuple(setters))
