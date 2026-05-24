"""tree-sitter による java/c span（段1→段2）+ Pro*C EXEC span。

node_at_line で最小内包葉を取り、.parent 上昇で粒度表へ昇格する。
block 等到達は直近 statement。proc は parse_tree 内 host_source 経由で解析（行番号保存）。
ERROR/MISSING は**確定した選択ノードの部分木のみ**で判定。

Related: spec §9
"""

from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree
from grep_analyzer.embed_preprocess import host_grammar
from grep_analyzer.proc_preprocess import exec_spans

# tree-sitter 0.21 系のノード型集合（spec §9 表「ts_span 粒度」と対応）。
# tree-sitter ライブラリ版更新時はこれらの集合を再点検する。
_GRAN_JAVA = {"if_statement", "while_statement", "for_statement",
              "switch_expression", "switch_statement",
              "try_statement", "try_with_resources_statement",
              "local_variable_declaration", "field_declaration",
              "return_statement", "expression_statement", "do_statement"}
_GRAN_C = {"if_statement", "while_statement", "for_statement",
           "switch_statement", "case_statement", "declaration",
           "expression_statement", "return_statement", "do_statement"}
_PAREN_ONLY = {"if_statement", "while_statement", "switch_statement",
               "switch_expression", "for_statement"}
_STMT = {"expression_statement", "declaration", "local_variable_declaration",
         "field_declaration", "return_statement"}
_BLOCK = {"block", "compound_statement", "program", "translation_unit",
          "method_declaration", "function_definition",
          "constructor_declaration"}

# 新言語の粒度集合（spec §7）。複合文(if/while/for/match)は粒度に含めず、
# ヒット時は 1 行フォールバック（python は paren 条件が無いため）。
_GRAN_PY = {"return_statement", "expression_statement",
            "import_statement", "import_from_statement"}
_STMT_PY = _GRAN_PY
_BLOCK_PY = {"block", "module"}
_GRAN_JS = {"lexical_declaration", "variable_declaration",
            "if_statement", "while_statement", "for_statement", "switch_statement",
            "return_statement", "expression_statement",
            "field_definition", "method_definition", "public_field_definition"}
_STMT_JS = {"lexical_declaration", "variable_declaration",
            "return_statement", "expression_statement",
            "field_definition", "method_definition", "public_field_definition"}
_BLOCK_JS = {"statement_block", "class_body", "program",
             "function_declaration", "method_definition", "arrow_function"}
_PAREN_JS = {"if_statement", "while_statement", "switch_statement", "for_statement"}

_SETS_BY_LANG = {
    "python": (_GRAN_PY, _STMT_PY, _BLOCK_PY, frozenset()),
    "javascript": (_GRAN_JS, _STMT_JS, _BLOCK_JS, _PAREN_JS),
    "typescript": (_GRAN_JS, _STMT_JS, _BLOCK_JS, _PAREN_JS),
    "tsx": (_GRAN_JS, _STMT_JS, _BLOCK_JS, _PAREN_JS),
}


def _paren_span(node) -> tuple[int, int]:
    """( 〜対応 ) の物理行スパン（spec §9 表）。AST 子で取得（文字列内括弧に頑健）。"""
    for ch in node.children:
        if ch.type == "parenthesized_expression":
            return (ch.start_point[0], ch.end_point[0])
    lparen = next((c for c in node.children if c.type == "("), None)
    rparens = [c for c in node.children if c.type == ")"]
    if lparen is not None and rparens:
        return (lparen.start_point[0], rparens[-1].end_point[0])
    return (node.start_point[0], node.end_point[0])


def _has_error(node) -> bool:
    """ERROR/MISSING 判定。`has_error` は子孫包含の真偽（py-tree-sitter 0.21）。

    判定は**選択ノードの部分木のみ**（祖先遡上しない＝ファイル内の無関係な
    エラーで健全行を捨てない・部分木継続）。
    """
    return node.is_missing or node.type == "ERROR" or node.has_error


def ts_span(language: str, file_text: str, lineno: int, cache: dict | None = None):
    """選択範囲 [s,e]（0始まり物理行）。取れなければ None（→fallback）。spec §9。

    `cache` は parse_tree と共有するファイル単位のパース木辞書（同一ファイルの
    classify/snippet/別行で再 parse を防ぐ）。
    """
    if language in ("java", "c", "proc"):
        gran = _GRAN_JAVA if host_grammar(language) == "java" else _GRAN_C
        stmt, block, paren, parse_lang = _STMT, _BLOCK, _PAREN_ONLY, language
        src = file_text                       # マスクは parse_tree 内 host_source の1回のみ
    elif language in _SETS_BY_LANG:
        gran, stmt, block, paren = _SETS_BY_LANG[language]
        src, parse_lang = file_text, language
    else:
        return None
    try:
        root = parse_tree(parse_lang, src, cache=cache)
    except Exception:
        return None
    node = node_at_line(root, lineno)
    if node is None:
        return None
    last_stmt = None
    cur = node
    while cur is not None:
        nt = cur.type
        if nt in stmt:
            last_stmt = cur
        if nt in gran:
            if _has_error(cur):
                return None
            if nt in paren:
                return _paren_span(cur)
            return (cur.start_point[0], cur.end_point[0])
        if nt in block:
            if last_stmt is None or _has_error(last_stmt):
                return None
            return (last_stmt.start_point[0], last_stmt.end_point[0])
        cur = cur.parent
    if last_stmt is None or _has_error(last_stmt):
        return None
    return (last_stmt.start_point[0], last_stmt.end_point[0])


def proc_exec_span(file_text: str, lineno: int):
    """Pro*C EXEC SQL 区間にヒットがあれば、生 EXEC 行のスパン [s,e] を返す。

    区間外は None。proc 言語で `ts_span("proc", ...)` の前段に呼ばれ、
    EXEC 区間の整列を優先する。

    Related: spec §7 (Pro*C 取扱), §9 (snippet)
    """
    hit = lineno - 1
    for span_start, span_end in exec_spans(file_text):
        if span_start <= hit <= span_end:
            return (span_start, span_end)
    return None
