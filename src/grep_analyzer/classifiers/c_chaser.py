"""C / Pro*C 用 Chaser — 言語別シンボル抽出とリテラルマスク。

C と Pro*C は同じ抽出規則を共有する（Pro*C は C のスーパーセット）。
chase.py の dispatcher が `_CHASERS["c"]` / `_CHASERS["proc"]` 経由で呼び出す。
Pro*C のホスト変数 `:var` は追跡投入しない（spec §8.1 手順1 外部・ホスト境界）。
"""

from grep_analyzer.classifiers.ts_classifier import bindings_at_line
from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    C_CONST_RE,
    C_DEFINE_RE,
    C_VAR_RE,
)


def mask(line: str) -> str:
    """C / Pro*C のリテラル / コメントを同字数空白に置換する。

    呼び出し元の dispatcher が `language` で `_CHASERS["c"]` と `_CHASERS["proc"]`
    を切り替えるが、現行 spec では両者の MASK パターンは完全同一。
    """
    pattern = MASK_PATTERNS["c"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に C / Pro*C の規則で分類抽出する（dialect は無視）。

    `#define` と `const ... var =` を constant、それ以外の代入を var として収集。
    """
    masked = mask(line)
    consts = tuple(x.group(1) for x in C_DEFINE_RE.finditer(masked)) + tuple(
        x.group(1) for x in C_CONST_RE.finditer(masked)
    )
    const_set = set(consts)
    vars_ = tuple(
        v for v in (x.group(1) for x in C_VAR_RE.finditer(masked))
        if v not in const_set and v != "const"
    )
    return ChaseSymbols(consts, vars_, (), ())


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
