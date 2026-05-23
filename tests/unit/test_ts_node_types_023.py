"""0.23 grammar に java/c の分類・snippet 依存ノード型が存在する（rename 検出・spec §4.3）。

golden は「存在する行」しか固定しないため、golden に現れない switch/preproc 等の
ノード型 rename を proactive に検出する（G-A0 三点目）。
"""
import tree_sitter_c
import tree_sitter_java
from tree_sitter import Language

_JAVA_TYPES = (
    "if_statement", "switch_expression",   # Java の switch は switch_expression（switch_statement は無い）
    "field_declaration", "local_variable_declaration", "assignment_expression",
    "return_statement", "try_statement", "try_with_resources_statement",
    "while_statement", "for_statement", "do_statement", "expression_statement",
    "block", "method_declaration", "constructor_declaration", "program",
)
_C_TYPES = (
    "if_statement", "switch_statement", "case_statement", "declaration",
    "preproc_def", "assignment_expression", "return_statement",
    "while_statement", "for_statement", "do_statement", "expression_statement",
    "compound_statement", "function_definition", "translation_unit",
)


def test_java_grammar_023_に必要ノード型が存在する():
    lang = Language(tree_sitter_java.language())
    for t in _JAVA_TYPES:
        assert lang.id_for_node_kind(t, True) is not None, f"java rename: {t}"


def test_c_grammar_023_に必要ノード型が存在する():
    lang = Language(tree_sitter_c.language())
    for t in _C_TYPES:
        assert lang.id_for_node_kind(t, True) is not None, f"c rename: {t}"
