"""tree-sitter による java/c span（spec §9 段1→段2）+ Pro*C EXEC span。

node_at_line で最小内包葉を取り、.parent 上昇で粒度表へ昇格する。
block 等到達は直近 statement。proc は mask_exec_sql 後を解析（行番号保存）。
ERROR/MISSING は**確定した選択ノードの部分木のみ**で判定。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree
from grep_analyzer.proc_preprocess import exec_spans, mask_exec_sql

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


def ts_span(language: str, file_text: str, lineno: int):
    """java/c 選択範囲 [s,e]（0始まり物理行）。取れなければ None（→fallback）。

    段1（node_at_line=最小内包葉・列非依存）→段2（.parent 上昇で粒度表へ
    昇格／block 等到達は直近 statement／無ければ None）。proc は生 EXEC が
    C パースを壊すため mask_exec_sql 後を解析（行番号保存）。
    """
    lang = "c" if language in ("c", "proc") else "java"
    src = mask_exec_sql(file_text) if language == "proc" else file_text
    try:
        root = parse_tree(lang, src)
    except Exception:
        return None
    node = node_at_line(root, lineno)
    if node is None:
        return None
    gran = _GRAN_JAVA if lang == "java" else _GRAN_C
    last_stmt = None
    cur = node
    while cur is not None:
        node_type = cur.type
        if node_type in _STMT:
            last_stmt = cur
        if node_type in gran:
            if _has_error(cur):
                return None
            if node_type in _PAREN_ONLY:
                return _paren_span(cur)
            return (cur.start_point[0], cur.end_point[0])
        if node_type in _BLOCK:
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
    for s, e in exec_spans(file_text):
        if s <= hit <= e:
            return (s, e)
    return None
