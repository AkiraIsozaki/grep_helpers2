"""tree-sitter による Java/C/Pro*C 分類。py-tree-sitter 0.21 API に依存。

Related: spec §7
"""

import tree_sitter_c
import tree_sitter_java
from tree_sitter import Language, Parser

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.proc_preprocess import mask_exec_sql

# py-tree-sitter 0.21.3 の Language.__init__ は (ptr, name) の2引数必須。
# tree_sitter_<lang>.language() は int ポインタを返す（spec §4.1 ロード規約）。
_JAVA = Language(tree_sitter_java.language(), "java")
_C = Language(tree_sitter_c.language(), "c")

# ノード型 → 共通上位カテゴリ（spec §7 の判定軸の最小集合）。
# 決定的基盤が目的（分類精度は handcrafted の領分・spec §11）。
# 内側から外へ climb して最初に一致した「文レベル」ノードのカテゴリを採る。
# argument_list / init_declarator は包含関係で if/宣言 と衝突するため意図的に含めない。
_CATEGORY_BY_NODE = {
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


def _parser(language: str) -> Parser:
    # "proc" を含む非 Java 言語は tree-sitter-c で解析する（spec §7 Pro*C 前処理方式）。
    p = Parser()
    p.set_language(_JAVA if language == "java" else _C)
    return p


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


def classify_ts(language: str, source: str, lineno: int) -> ClassifyResult:
    """ファイル全体を AST 解析し、対象行を含む構文要素から分類する。"""
    src = mask_exec_sql(source) if language == "proc" else source
    tree = _parser(language).parse(src.encode("utf-8"))
    node = node_at_line(tree.root_node, lineno)
    while node is not None:
        cat = _CATEGORY_BY_NODE.get(node.type)
        if cat is not None:
            return (cat, "high")
        node = node.parent
    return ("その他", "high")


def parse_tree(language: str, source: str):
    """snippet 用: ソースを parse し root_node を返す（lang は "java"/"c"）。"""
    return _parser(language).parse(source.encode("utf-8")).root_node
