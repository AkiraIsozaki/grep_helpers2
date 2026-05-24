"""C / Pro*C 用 AST Chaser — field-directed・multi-node 抽出（spec §3.4）。

C と Pro*C は同じ抽出規則を共有する（Pro*C は C のスーパーセット）。
`ASTChaser` プロトコル準拠の `extract_tree` を公開する。
`_AST_CHASERS["c"]` / `_AST_CHASERS["proc"]` 経由で呼び出す。
Pro*C の EXEC SQL 区間は mask_exec_sql で空白化済み（spec §3.5）。
"""

from grep_analyzer.classifiers.ts_classifier import bindings_at_line
from grep_analyzer.model import ChaseSymbols

_AST_BINDING = {"declaration", "field_declaration", "preproc_def",
                "preproc_function_def", "assignment_expression"}


def _declarator_name(node):
    """init/pointer/array declarator を再帰的に剥がし末尾 identifier/field_identifier を返す。"""
    t = node.type
    if t in ("identifier", "field_identifier"):
        return node.text.decode("utf-8", "replace")
    if t in ("init_declarator", "pointer_declarator", "array_declarator"):
        d = node.child_by_field_name("declarator")
        return _declarator_name(d) if d is not None else None
    return None     # function_declarator（関数名・関数ポインタ）等は非抽出


def _decl_names(node, out):
    for ch in node.children:
        if ch.type in ("init_declarator", "pointer_declarator", "array_declarator",
                       "identifier", "field_identifier"):
            nm = _declarator_name(ch)
            if nm is not None:
                out.append(nm)


def _is_const(node) -> bool:
    # tree-sitter-c の type_qualifier は1トークン1ノード（const/volatile/...）
    return any(ch.type == "type_qualifier" and ch.text.decode("utf-8", "replace") == "const"
               for ch in node.children)


def _handle_c(node, consts, vars_):
    t = node.type
    if t in ("preproc_def", "preproc_function_def"):
        nm = node.child_by_field_name("name")
        if nm is not None:
            consts.append(nm.text.decode("utf-8", "replace"))
    elif t in ("declaration", "field_declaration"):
        _decl_names(node, consts if _is_const(node) else vars_)
    elif t == "assignment_expression":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            vars_.append(left.text.decode("utf-8", "replace"))


def extract_tree(language, root, lineno):
    """parse 済 root から C/Pro*C 束縛を field-directed・multi-node 抽出（spec §3.4）。"""
    consts, vars_ = [], []
    for node in bindings_at_line(root, lineno, _AST_BINDING):
        _handle_c(node, consts, vars_)
    const_set = set(consts)
    vars_ = [v for v in vars_ if v not in const_set]
    return ChaseSymbols(tuple(consts), tuple(vars_), (), ())
