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
