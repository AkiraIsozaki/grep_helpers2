"""tree-sitter による Java/C/Pro*C 分類。py-tree-sitter 0.23 API に依存。

Related: spec §7
"""

import tree_sitter_c
import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.embed_preprocess import host_grammar, host_source

# py-tree-sitter 0.23: Language(capsule) 1引数 / Parser(lang) コンストラクタ。
# tree_sitter_<lang>.language() は PyCapsule を返す（0.21 の int から変更）。
_LANGS = {
    "java": Language(tree_sitter_java.language()),
    "c": Language(tree_sitter_c.language()),
    "python": Language(tree_sitter_python.language()),
    "javascript": Language(tree_sitter_javascript.language()),
    "typescript": Language(tree_sitter_typescript.language_typescript()),
    "tsx": Language(tree_sitter_typescript.language_tsx()),
}

# ノード型 → 共通上位カテゴリ（spec §7 の判定軸の最小集合）。
# 決定的基盤が目的（分類精度は handcrafted の領分・spec §11）。
# 内側から外へ climb して最初に一致した「文レベル」ノードのカテゴリを採る。
# argument_list / init_declarator は包含関係で if/宣言 と衝突するため意図的に含めない。
_CATEGORY_JAVAC = {
    "if_statement": "比較",
    "switch_statement": "分岐",
    "switch_expression": "分岐",
    "field_declaration": "宣言",
    "local_variable_declaration": "宣言",
    "declaration": "宣言",
    "preproc_def": "宣言",
    "assignment_expression": "代入",
    "return_statement": "return",
}
_CATEGORY_PY = {
    "if_statement": "比較",
    "match_statement": "分岐",
    "assignment": "代入",
    "augmented_assignment": "代入",
    "return_statement": "return",
    "import_statement": "宣言",
    "import_from_statement": "宣言",
}
_CATEGORY_JS = {
    "if_statement": "比較",
    "switch_statement": "分岐",
    "lexical_declaration": "宣言",
    "variable_declaration": "宣言",
    "field_definition": "宣言",
    "import_statement": "宣言",
    "assignment_expression": "代入",
    "augmented_assignment_expression": "代入",
    "return_statement": "return",
}
_CATEGORY_TS = {
    **_CATEGORY_JS,
    "enum_declaration": "宣言",
    "interface_declaration": "宣言",
    "type_alias_declaration": "宣言",
    "public_field_definition": "宣言",
}
_CATEGORY_BY_LANG = {
    "java": _CATEGORY_JAVAC, "c": _CATEGORY_JAVAC, "proc": _CATEGORY_JAVAC,
    "python": _CATEGORY_PY, "javascript": _CATEGORY_JS,
    "typescript": _CATEGORY_TS, "tsx": _CATEGORY_TS,
}


def _parser(language: str) -> Parser:
    return Parser(_LANGS[host_grammar(language)])


def node_at_line(root, lineno: int):
    """対象行（lineno は1始まり=内部で-1）を内包する最小ノードを決定的に返す。

    同スパンの曖昧さを除くため、`(行スパン, start_byte, end_byte, ノード型)` の最小で
    一意に選ぶ（走査順に依存しない決定的な全順序・spec §9 決定性）。
    classify_ts（内部）と snippet/_ts.py（公開）が共有する。
    """
    target = lineno - 1
    best = None
    best_key = None
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            key = (node.end_point[0] - node.start_point[0], node.start_byte, node.end_byte, node.type)
            if best_key is None or key < best_key:
                best, best_key = node, key
            cursor.extend(node.children)
    return best


def binding_at_line(root, lineno: int, binding_types):
    """対象行を内包し、かつ binding_types に属する最小スパンノードを決定的に返す。

    node_at_line と同じ全順序キー (行スパン, start_byte, end_byte, 型) で一意選択。
    単一行クラス本体など「行内の最左最小葉から climb」では到達できない束縛
    （例 `class C { get x() {} }` / `class C: ATTR = 1`）を直接拾うため、
    AST chaser が node_at_line+climb の代わりに使う。該当なしは None。
    """
    target = lineno - 1
    best = None
    best_key = None
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            if node.type in binding_types:
                key = (node.end_point[0] - node.start_point[0], node.start_byte,
                       node.end_byte, node.type)
                if best_key is None or key < best_key:
                    best, best_key = node, key
            cursor.extend(node.children)
    return best


def classify_ts(language: str, source: str, lineno: int) -> ClassifyResult:
    """ファイル全体を AST 解析し、対象行を含む構文要素から分類する。"""
    src = host_source(language, source)
    tree = _parser(language).parse(src.encode("utf-8"))
    node = node_at_line(tree.root_node, lineno)
    while node is not None:
        cat = _CATEGORY_BY_LANG[language].get(node.type)
        if cat is not None:
            return (cat, "high")
        node = node.parent
    return ("その他", "high")


def parse_tree(language: str, source: str):
    """ソースを host_source で逆マスク後 parse し root_node を返す（spec §5 適用点2）。"""
    return _parser(language).parse(host_source(language, source).encode("utf-8")).root_node
