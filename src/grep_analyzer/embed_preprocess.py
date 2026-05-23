"""埋め込みトラック（JSP/Angular）の逆マスク＋ホスト写像（spec §3〜§5）。

proc の長さ保存空白化（proc_preprocess._blank_literals）と同型の逆マスク。
保証する不変量は行数（改行位置）保存のみ＝lineno 写像に必須。
proc_preprocess へ単方向依存（循環回避）。
"""

import re

from grep_analyzer.proc_preprocess import mask_exec_sql

_JSP_COMMENT = re.compile(r"<%--.*?--%>", re.DOTALL)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_JSP_DIRECTIVE = re.compile(r"<%@.*?%>", re.DOTALL)
_JSP_ACTION = re.compile(r"</?jsp:[^>]*?/?>", re.DOTALL)
_JSP_CODE = re.compile(r"<%[=!]?(.*?)%>", re.DOTALL)
_EL = re.compile(r"[$#]\{(.*?)\}", re.DOTALL)
# JSTL 関数接頭辞（fn: 等）除去。best-effort（spec §3.4/§6）＝EL 内の URL
# プロトコル `http:` や空白なし三項 `a?b:c` の `b:` も除去しうる（稀・許容）。
_EL_PREFIX = re.compile(r"\b[A-Za-z_]\w*:")


def _blank(text: str) -> str:
    """改行を保ち他を空白へ（長さ保存）。"""
    return "".join("\n" if c == "\n" else " " for c in text)


def extract_jsp_java(source: str) -> str:
    """JSP から java host が読める区間だけ残し他を空白化（行数保存・spec §4.1）。"""
    out = list(_blank(source))
    masked = source
    for rx in (_JSP_COMMENT, _HTML_COMMENT, _JSP_DIRECTIVE, _JSP_ACTION):
        masked = rx.sub(lambda m: _blank(m.group(0)), masked)
    for m in _JSP_CODE.finditer(masked):
        for i in range(m.start(1), m.end(1)):
            out[i] = source[i]
    for m in _EL.finditer(masked):
        for i in range(m.start(1), m.end(1)):
            out[i] = source[i]
        inner = source[m.start(1):m.end(1)]
        for pm in _EL_PREFIX.finditer(inner):
            for i in range(m.start(1) + pm.start(), m.start(1) + pm.end()):
                out[i] = " "
    return "".join(out)


def jsp_region_span(file_text: str, lineno: int):
    """ヒット行を含む <%…%> 系ブロックの原ソース行スパン [s,e]（0始まり）。

    区間外は None（呼出側で1行フォールバック・spec §4.3）。区間検出は
    extract_jsp_java と同一の _JSP_CODE 正規表現を共有（非貪欲・§4.4 既知限界）。
    """
    hit = lineno - 1
    for m in _JSP_CODE.finditer(file_text):
        start = file_text.count("\n", 0, m.start())
        end = file_text.count("\n", 0, m.end())
        if start <= hit <= end:
            return (start, end)
    return None


# Angular 固有束縛マーカ（{{ 単独は Vue/Handlebars と重複し過検出のため含めない・spec §5 #1）
_ANGULAR_RE = re.compile(
    r"""\*ng[\w-]+|\[\(?[\w.$-]+\)?\]\s*=|\([\w.$-]+\)\s*=|routerLink|formControl|ngModel""")

_NG_INTERP = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
# [prop]= / [(two-way)]= / (event)= / *dir=  の属性。値は " か ' で囲まれる。
_NG_ATTR = re.compile(
    r"""(?:\[\(?[\w.$-]+\)?\]|\([\w.$-]+\)|\*[\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.DOTALL)
_NG_PIPE = re.compile(r"(?<!\|)\|(?!\|)")               # 単一 | （|| は除外）


def _ng_normalize(expr: str) -> str:
    """式断片の best-effort 正規化（spec §3.4）。長さは概ね保つが ngFor の of→= は1縮む。"""
    head = expr.split(";", 1)[0]
    head = re.sub(r"\bof\b", "=", head)
    m = _NG_PIPE.search(head)
    if m is not None:
        head = head[:m.start()]
    return head


def extract_angular_ts(source: str) -> str:
    """Angular テンプレから typescript host が読める式だけ残す（行数保存・spec §4.2）。"""
    out = list(_blank(source))
    masked = _HTML_COMMENT.sub(lambda m: _blank(m.group(0)), source)

    def _emit(raw_start: int, raw_expr: str):
        # norm が raw_expr より短い場合（of→= 縮約・パイプ除去）、残余位置は
        # out 初期化済みの空白のまま＝意図的（行数は不変・spec §4 不変量）。
        norm = _ng_normalize(raw_expr)
        for j, ch in enumerate(norm):
            if raw_start + j < len(out):
                out[raw_start + j] = ch

    for m in _NG_INTERP.finditer(masked):
        _emit(m.start(1), source[m.start(1):m.end(1)])
    for m in _NG_ATTR.finditer(masked):
        gi = 1 if m.group(1) is not None else 2
        _emit(m.start(gi), source[m.start(gi):m.end(gi)])
    return "".join(out)


# .component.ts の inline angular template（template: `...`）検出。
# templateUrl: は `template` の後に Url が続き `\s*:` に非マッチ。
# styles: [`...`] も `\btemplate\s*:` に非マッチ。best-effort（spec §6）。
_INLINE_TEMPLATE = re.compile(r"\btemplate\s*:\s*`(.*?)`", re.DOTALL)


def inline_template_spans(ts_source: str) -> list[tuple[int, int]]:
    """inline template 内容（group1）の行スパン [(s,e)]（0始まり・spec §3.2）。"""
    return [(ts_source.count("\n", 0, m.start(1)), ts_source.count("\n", 0, m.end(1)))
            for m in _INLINE_TEMPLATE.finditer(ts_source)]


def extract_inline_angular(ts_source: str) -> str:
    """inline template 領域のみ angular 式を残し他を空白化（行数保存・spec §3.3）。"""
    kept = list(_blank(ts_source))
    for m in _INLINE_TEMPLATE.finditer(ts_source):
        for i in range(m.start(1), m.end(1)):
            kept[i] = ts_source[i]
    return extract_angular_ts("".join(kept))


def effective_language(file_language: str, file_text: str, lineno: int) -> str:
    """ヒット行の実効言語（spec §2/§3.4）。typescript の inline template 行のみ
    angular_inline、他は file_language 恒等（高速短絡）。"""
    if file_language != "typescript":
        return file_language
    hit = lineno - 1
    for s, e in inline_template_spans(file_text):
        if s <= hit <= e:
            return "angular_inline"
    return "typescript"


_HOST_GRAMMAR = {"proc": "c", "jsp": "java", "angular": "typescript",
                 "angular_inline": "typescript"}


def host_grammar(language: str) -> str:
    """埋め込み言語→ホスト grammar 名。既存言語は恒等（spec §5）。"""
    return _HOST_GRAMMAR.get(language, language)


def host_source(language: str, source: str) -> str:
    """埋め込み言語→ホストが読める逆マスク済ソース。既存言語は恒等（spec §5）。"""
    if language == "proc":
        return mask_exec_sql(source)
    if language == "jsp":
        return extract_jsp_java(source)
    if language == "angular":
        return extract_angular_ts(source)
    if language == "angular_inline":
        return extract_inline_angular(source)
    return source
