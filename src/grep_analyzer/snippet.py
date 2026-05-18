"""snippet 切り出し（spec §9「snippet 切り出し規則」/ §7 Pro*C）。

物理行 = _phys(file_text)（0始まり）。hit = lineno-1。全関数は
走査順非依存・決定的（spec §9 golden 前提）。本ファイルのアルゴリズムは
実環境実行で検証済。
"""

import re
from grep_analyzer.chase import mask_literals
from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree
from grep_analyzer.proc_preprocess import mask_exec_sql

SEP = " \\n "          # spec §9 区切り: U+0020 U+005C U+006E U+0020
ELL = "…"          # U+2026
LINE_MAX = 12
CHAR_MAX = 800


def _phys(file_text: str) -> list[str]:
    """物理行配列。末尾改行由来の人工空要素を1個だけ除去（spec §9 物理行定義）。"""
    lines = file_text.split("\n")
    if file_text.endswith("\n") and lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def _render(rows: list[str], top_k: int, bot_k: int) -> str:
    body = SEP.join(rows)
    if top_k:
        body = f"{ELL}(+{top_k}上行省略)" + body
    if bot_k:
        body = body + f"{ELL}(+{bot_k}下行省略)"
    return body


def clamp_lines(lines: list[str], hit: int, line_max: int = LINE_MAX,
                char_max: int = CHAR_MAX) -> str:
    """選択範囲 lines をヒット中心に縮約（spec §9「上限と切り詰め」擬似コード）。

    hit は lines 内 0 始まり index。lines は連結前に呼び出し側で
    サニタイズ＋区切り衝突エスケープ済（build_snippet が責務）。
    """
    s, e = 0, len(lines) - 1
    hit_text = lines[hit]
    out = ([hit_text[:char_max - 1] + ELL] if len(hit_text) > char_max
           else [hit_text])
    up, dn = hit - 1, hit + 1
    while True:
        if len(out) >= line_max:
            break
        progressed = False
        if up >= s:
            cand = [lines[up]] + out
            ra = (up - 1) - s + 1 if (up - 1) >= s else 0
            rb = e - dn + 1 if dn <= e else 0
            if len(cand) <= line_max and len(_render(cand, ra, rb)) <= char_max:
                out, up, progressed = cand, up - 1, True
        if len(out) >= line_max:
            break
        if dn <= e:
            cand = out + [lines[dn]]
            ra = up - s + 1 if up >= s else 0
            rb = e - (dn + 1) + 1 if (dn + 1) <= e else 0
            if len(cand) <= line_max and len(_render(cand, ra, rb)) <= char_max:
                out, dn, progressed = cand, dn + 1, True
        if not progressed:
            break
    top_k = up - s + 1 if up >= s else 0
    bot_k = e - dn + 1 if dn <= e else 0
    return _render(out, top_k, bot_k)


_SQL_CLAUSE = re.compile(
    r"\b(WHERE|SET|VALUES|SELECT|FROM|GROUP\s+BY|ORDER\s+BY|HAVING)\b", re.I)
_SH_END = re.compile(r"(?:^|\s)(fi|done|esac|breaksw)\b|;")


def _balanced(t: str) -> bool:
    d = 0
    for c in t:
        if c in "([{":
            d += 1
        elif c in ")]}":
            d -= 1
    return d == 0 and t.count("'") % 2 == 0 and t.count('"') % 2 == 0


def heuristic_span(lines: list[str], hit: int, language: str) -> tuple[int, int]:
    """sql/shell の決定的境界（spec §9）。mask_literals を行ごと適用し誤爆防止。

    ヒット行自身は停止判定しない。各方向1行ずつ移動し、移動先が
    停止条件（行末\\ 無・括弧/クオートバランス・SQL は ; か句境界 /
    shell は ;/fi/done/esac/breaksw）ならその行を含めて停止。heredoc は
    mask 非対応＝§8.4 境界、LINE_MAX で必ず有限停止。
    """
    m = [mask_literals(language, ln) for ln in lines]

    def stop(i: int) -> bool:
        x = m[i]
        if x.rstrip().endswith("\\"):
            return False
        if not _balanced(x):
            return False
        if language == "sql":
            return x.rstrip().endswith(";") or bool(_SQL_CLAUSE.search(x))
        return bool(_SH_END.search(x))

    s = hit
    for _ in range(LINE_MAX - 1):
        if s == 0:
            break
        s -= 1
        if stop(s):
            break
    e = hit
    for _ in range(LINE_MAX - 1):
        if e == len(lines) - 1:
            break
        e += 1
        if stop(e):
            break
        if (e - s + 1) >= LINE_MAX:
            break
    return s, e


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
    """spec §9 表「( 〜対応 ) の物理行スパン」。AST 子で取得（文字列内括弧に頑健）。"""
    for ch in node.children:
        if ch.type == "parenthesized_expression":
            return (ch.start_point[0], ch.end_point[0])
    lp = next((c for c in node.children if c.type == "("), None)
    rps = [c for c in node.children if c.type == ")"]
    if lp is not None and rps:
        return (lp.start_point[0], rps[-1].end_point[0])
    return (node.start_point[0], node.end_point[0])


def _err(node) -> bool:
    """spec §9 v9: ERROR/MISSING 判定は**選択ノードの部分木のみ**（祖先遡上
    しない＝ファイル内の無関係なエラーで健全行を捨てない・§10.3 部分木継続）。
    `has_error` は子孫包含の真偽（py-tree-sitter 0.21）。"""
    return node.is_missing or node.type == "ERROR" or node.has_error


def ts_span(language: str, file_text: str, lineno: int):
    """java/c 選択範囲 [s,e]（0始まり物理行）。取れなければ None（→fallback）。

    spec §9 段1（node_at_line=最小内包葉・列非依存）→段2（.parent 上昇で
    粒度表へ昇格／block 等到達は直近 statement／無ければ None）。proc は
    生 EXEC が C パースを壊すため mask_exec_sql 後を解析（行番号保存）。
    ERROR/MISSING は**確定した選択ノードの部分木のみ**で判定。
    """
    lang = "c" if language in ("c", "proc") else "java"
    src = mask_exec_sql(file_text) if language == "proc" else file_text
    try:
        root = parse_tree(lang, src)
    except Exception:
        return None
    n = node_at_line(root, lineno)
    if n is None:
        return None
    gran = _GRAN_JAVA if lang == "java" else _GRAN_C
    last_stmt = None
    cur = n
    while cur is not None:
        t = cur.type
        if t in _STMT:
            last_stmt = cur
        if t in gran:
            if _err(cur):
                return None
            if t in _PAREN_ONLY:
                return _paren_span(cur)
            return (cur.start_point[0], cur.end_point[0])
        if t in _BLOCK:
            if last_stmt is None or _err(last_stmt):
                return None
            return (last_stmt.start_point[0], last_stmt.end_point[0])
        cur = cur.parent
    if last_stmt is None or _err(last_stmt):
        return None
    return (last_stmt.start_point[0], last_stmt.end_point[0])


from grep_analyzer.proc_preprocess import exec_spans


def proc_exec_span(file_text: str, lineno: int):
    """hit が EXEC 区間に含まれれば原ソース行スパン [s,e]、なければ None。"""
    hit = lineno - 1
    for s, e in exec_spans(file_text):
        if s <= hit <= e:
            return (s, e)
    return None
