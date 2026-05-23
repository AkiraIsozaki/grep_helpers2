# track C 埋め込みトラック（JSP / Angular）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** JSP（HTML 内 Java）と Angular（HTML テンプレート内 TS 式）を Pro\*C 逆マスク方式で grep_analyzer に追加し、埋め込みコードのシンボル使用箇所を分類・追跡・snippet 化できるようにする。

**Architecture:** 埋め込みコード区間**以外**を行数保存で空白化したバッファを作り、既存 tree-sitter host grammar（jsp→java / angular→typescript）へ流す（新規 grammar wheel ゼロ）。proc の inline マスク分岐を `host_grammar`/`host_source` ヘルパへ集約し、`parse_tree` 自体が host 変換を行うことで seed/scan/absorb の AST 経路を無改修で angular 対応にする。jsp の chaser は行ベース java_chaser を別キー登録、angular は AST typescript_chaser を流用。

**Tech Stack:** Python 3.12, py-tree-sitter 0.23.2（tree-sitter-java 0.23.5 / tree-sitter-typescript 0.23.2・wheelhouse 同梱済）, pytest。

**正本spec:** `docs/superpowers/specs/2026-05-23-v2-track-c-embedded-design.md`（§番号は本計画の参照先）。

**フェーズ:** C1（共通逆マスク基盤＋jsp＋html パススルー・T1–T11）→ C2（angular・T12–T16）。各フェーズ末で Inv-C 二段ゲート（既存 golden ゼロdiff＋全緑）を通す＝独立マージ可能。

**Inv-C（全タスク共通の不変条件）:** 既存 golden（java/c/proc/sql/shell/perl/groovy/ts/tsx/js/python）を byte 不変に保つ。各タスクのコミット前に `python -m pytest -q` がベースライン（**331 passed, 5 skipped**）以上で緑であること（新規テスト追加分は増える）。

---

## ファイル構成（新規・変更）

| ファイル | 役割 | フェーズ |
|---|---|---|
| `src/grep_analyzer/embed_preprocess.py`（新規） | `host_grammar`/`host_source`/`extract_jsp_java`/`extract_angular_ts`/`jsp_region_span`/`_ANGULAR_RE`。埋め込み写像と逆マスクの集約。proc_preprocess に単方向依存（循環回避） | C1+C2 |
| `src/grep_analyzer/classifiers/ts_classifier.py`（変更） | `_parser`/`classify_ts`/`parse_tree` を host ヘルパ経由に。`_CATEGORY_BY_LANG` に jsp/angular | C1+C2 |
| `src/grep_analyzer/snippet/_ts.py`（変更） | `ts_span` の java/c/proc 分岐を `parse_tree(language,...)`＋`host_grammar` 粒度選択へ集約（二重マスク除去・`_SETS_BY_LANG` 分岐は不変） | C1 |
| `src/grep_analyzer/snippet/__init__.py`（変更） | `build_snippet` に jsp→`jsp_region_span` 分岐 | C1 |
| `src/grep_analyzer/dispatch.py`（変更） | jsp 拡張子＋`.html/.htm` 専用分岐＋`extension_resolves_language` | C1（html）+C2（angular 判定） |
| `src/grep_analyzer/classify.py`（変更） | jsp/angular/html の routing | C1（jsp/html）+C2（angular） |
| `src/grep_analyzer/classifiers/__init__.py`（変更） | `_CHASERS["jsp"]`（C1）/`_AST_CHASERS["angular"]`（C2） | C1+C2 |
| `src/grep_analyzer/stoplist.py`（変更） | `LANG_KEYWORDS` に jsp/html（C1）/angular（C2） | C1+C2 |
| `tests/unit/test_embed_preprocess.py`（新規） | 逆マスク・host ヘルパの単体 | C1+C2 |
| `tests/unit/test_dispatch.py`・`test_classify.py`・`test_chase.py`・`test_snippet.py`（変更） | jsp/angular/html の単体追加 | C1+C2 |
| `tests/golden/cases/{jsp_chain,html_passthrough,angular_chain}/`（新規） | 言語×ref_kind golden | C1+C2 |
| `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`・`docs/superpowers/plans/phase0-gate-result.md`（変更） | track C 完了の master 反映 | C2 |

---

# Phase C1: 共通逆マスク基盤 ＋ jsp ＋ html パススルー

## Task 1: `extract_jsp_java`（JSP 逆マスク）

**Files:**
- Create: `src/grep_analyzer/embed_preprocess.py`
- Test: `tests/unit/test_embed_preprocess.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_embed_preprocess.py
from grep_analyzer.embed_preprocess import extract_jsp_java


def test_jsp_scriptletのjavaを残し他を空白化():
    src = "<html>\n<% int x = foo(); %>\n<p>text</p>\n"
    out = extract_jsp_java(src)
    assert out.count("\n") == src.count("\n")        # 行数保存
    assert "int x = foo();" in out                    # scriptlet java は残る
    assert "<html>" not in out and "text" not in out  # HTML は空白化
    assert "<%" not in out and "%>" not in out         # マーカは空白化


def test_jsp_式と宣言を残す():
    src = "<%= title %>\n<%! private int n; %>\n"
    out = extract_jsp_java(src)
    assert "title" in out
    assert "private int n;" in out


def test_jsp_ELを残しprefixを除去():
    src = "${ user.code }\n${ fn:length(list) }\n"
    out = extract_jsp_java(src)
    assert "user.code" in out
    assert "length(list)" in out
    assert "fn:" not in out                            # prefix 除去


def test_jsp_多バイト混在でも行数保存():
    src = "<%-- 日本語 --%>\n<% String 名前 = TRACKED; %>\n"
    out = extract_jsp_java(src)
    assert out.count("\n") == src.count("\n")          # 復号後 char 単位＝encoding 非依存
    assert "TRACKED" in out and "名前" in out
    assert "日本語" not in out                          # コメントは空白化


def test_jsp_ディレクティブとコメントと標準アクションを空白化():
    src = ('<%@ page import="java.util.*" %>\n'
           "<%-- comment ${secret} --%>\n"
           "<!-- html ${hidden} -->\n"
           '<jsp:useBean id="bean" class="X"/>\n')
    out = extract_jsp_java(src)
    assert out.count("\n") == src.count("\n")
    assert "import" not in out and "secret" not in out
    assert "hidden" not in out and "bean" not in out
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -v`
Expected: FAIL（`ModuleNotFoundError: grep_analyzer.embed_preprocess`）

- [ ] **Step 3: 最小実装**

```python
# src/grep_analyzer/embed_preprocess.py
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
_JSP_CODE = re.compile(r"<%[=!]?(.*?)%>", re.DOTALL)      # scriptlet/expr/decl
_EL = re.compile(r"[$#]\{(.*?)\}", re.DOTALL)            # ${...}/#{...}
_EL_PREFIX = re.compile(r"\b[A-Za-z_]\w*:")              # fn: 等


def _blank(text: str) -> str:
    """改行を保ち他を空白へ（長さ保存）。"""
    return "".join("\n" if c == "\n" else " " for c in text)


def extract_jsp_java(source: str) -> str:
    """JSP から java host が読める区間だけ残し他を空白化（行数保存・spec §4.1）。"""
    out = list(_blank(source))
    # コメント/ディレクティブ/標準アクションを先に空白化（マーカ誤検出回避）
    masked = source
    for rx in (_JSP_COMMENT, _HTML_COMMENT, _JSP_DIRECTIVE, _JSP_ACTION):
        masked = rx.sub(lambda m: _blank(m.group(0)), masked)
    # scriptlet/式/宣言の java を復元
    for m in _JSP_CODE.finditer(masked):
        for i in range(m.start(1), m.end(1)):
            out[i] = source[i]
    # EL 内部式を復元し prefix を空白化
    for m in _EL.finditer(masked):
        for i in range(m.start(1), m.end(1)):
            out[i] = source[i]
        inner = source[m.start(1):m.end(1)]
        for pm in _EL_PREFIX.finditer(inner):
            for i in range(m.start(1) + pm.start(), m.start(1) + pm.end()):
                out[i] = " "
    return "".join(out)
```

- [ ] **Step 4: パスを確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -v`
Expected: PASS（5 件）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/embed_preprocess.py tests/unit/test_embed_preprocess.py
git commit -m "feat(embed): extract_jsp_java 逆マスク（JSP scriptlet/式/宣言/EL を残し他を行数保存で空白化・多バイト encoding 非依存）"
```

---

## Task 2: `jsp_region_span`（JSP snippet 用 原ソーススパン）

**Files:**
- Modify: `src/grep_analyzer/embed_preprocess.py`
- Test: `tests/unit/test_embed_preprocess.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_embed_preprocess.py に追記
from grep_analyzer.embed_preprocess import jsp_region_span


def test_jsp_region_span_多行scriptletの行スパン():
    src = "<html>\n<%\n  int x = 1;\n%>\n</html>\n"   # 0:html 1-3:scriptlet
    assert jsp_region_span(src, 3) == (1, 3)           # lineno=3（1始まり）→区間 [1,3]


def test_jsp_region_span_区間外はNone():
    src = "<html>\n<% int x = 1; %>\n<p>t</p>\n"
    assert jsp_region_span(src, 3) is None             # <p> 行は区間外
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py::test_jsp_region_span_多行scriptletの行スパン -v`
Expected: FAIL（`ImportError: cannot import name 'jsp_region_span'`）

- [ ] **Step 3: 最小実装**

```python
# src/grep_analyzer/embed_preprocess.py に追記


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
```

- [ ] **Step 4: パスを確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -v`
Expected: PASS（6 件）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/embed_preprocess.py tests/unit/test_embed_preprocess.py
git commit -m "feat(embed): jsp_region_span（snippet 用に <%…%> ブロックの原ソース行スパンを返す）"
```

---

## Task 3: `host_grammar` / `host_source`（埋め込み写像ヘルパ・proc+jsp）

**Files:**
- Modify: `src/grep_analyzer/embed_preprocess.py`
- Test: `tests/unit/test_embed_preprocess.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_embed_preprocess.py に追記
from grep_analyzer.embed_preprocess import host_grammar, host_source


def test_host_grammar_既存言語は恒等():
    for lang in ("java", "c", "python", "javascript", "typescript", "tsx"):
        assert host_grammar(lang) == lang


def test_host_grammar_埋め込みはホストへ写像():
    assert host_grammar("proc") == "c"
    assert host_grammar("jsp") == "java"


def test_host_source_既存言語は恒等():
    s = "int x = 1;\nfoo();\n"
    for lang in ("java", "c", "python", "javascript", "typescript", "tsx", "html"):
        assert host_source(lang, s) == s


def test_host_source_proc_は_EXEC_SQL_を空白化():
    s = "EXEC SQL SELECT 1 INTO :x FROM dual;\n"
    out = host_source("proc", s)
    assert "SELECT" not in out and out.count("\n") == s.count("\n")


def test_host_source_jsp_は_extract_jsp_java():
    s = "<p><%= title %></p>\n"
    assert host_source("jsp", s) == extract_jsp_java(s)
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -k host_ -v`
Expected: FAIL（`ImportError: cannot import name 'host_grammar'`）

- [ ] **Step 3: 最小実装**

```python
# src/grep_analyzer/embed_preprocess.py に追記（angular は C2 で拡張）
_HOST_GRAMMAR = {"proc": "c", "jsp": "java"}


def host_grammar(language: str) -> str:
    """埋め込み言語→ホスト grammar 名。既存言語は恒等（spec §5）。"""
    return _HOST_GRAMMAR.get(language, language)


def host_source(language: str, source: str) -> str:
    """埋め込み言語→ホストが読める逆マスク済ソース。既存言語は恒等（spec §5）。"""
    if language == "proc":
        return mask_exec_sql(source)
    if language == "jsp":
        return extract_jsp_java(source)
    return source
```

- [ ] **Step 4: パスを確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -v`
Expected: PASS（12 件）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/embed_preprocess.py tests/unit/test_embed_preprocess.py
git commit -m "feat(embed): host_grammar/host_source（埋め込み写像ヘルパ・proc/jsp・既存言語は恒等）"
```

---

## Task 4: `ts_classifier` を host ヘルパ経由に（proc 挙動保存リファクタ）

**Files:**
- Modify: `src/grep_analyzer/classifiers/ts_classifier.py:14`（import）, `:76-79`（`_parser`）, `:127-137`（`classify_ts`）, `:140-142`（`parse_tree`）

- [ ] **Step 1: 既存テストが緑であることを確認（リファクタ前ベースライン）**

Run: `python -m pytest tests/unit/test_ts_classifier.py tests/unit/test_classify.py tests/unit/test_proc_preprocess.py -q`
Expected: PASS（全件）

- [ ] **Step 2: import を差し替える**

`src/grep_analyzer/classifiers/ts_classifier.py` の14行目を変更:

```python
# 変更前: from grep_analyzer.proc_preprocess import mask_exec_sql
from grep_analyzer.embed_preprocess import host_grammar, host_source
```

- [ ] **Step 3: `_parser`/`classify_ts`/`parse_tree` を host ヘルパ経由に**

```python
def _parser(language: str) -> Parser:
    return Parser(_LANGS[host_grammar(language)])


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
```

- [ ] **Step 4: 既存テスト全緑（proc/既存 AST 言語ゼロ挙動変化）を確認**

Run: `python -m pytest tests/unit/test_ts_classifier.py tests/unit/test_classify.py tests/unit/test_proc_preprocess.py tests/unit/test_snippet.py tests/unit/test_ast_chaser.py tests/golden -q`
Expected: PASS（全件・proc/java/c/python/js/ts/tsx の golden ゼロdiff）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py
git commit -m "refactor(ts_classifier): _parser/classify_ts/parse_tree を host_grammar/host_source 経由に集約（proc 挙動保存・parse_tree が host 変換を担う）"
```

---

## Task 5: `ts_span` の proc 分岐を `parse_tree` 一本へ集約

**Files:**
- Modify: `src/grep_analyzer/snippet/_ts.py:10-11`（import）, `:77-88`（`ts_span` 前半分岐）

- [ ] **Step 1: 既存 snippet テストが緑であることを確認**

Run: `python -m pytest tests/unit/test_snippet.py -q`
Expected: PASS（全件）

- [ ] **Step 2: import を整理（mask_exec_sql 不要に・exec_spans は proc_exec_span が使用）**

`src/grep_analyzer/snippet/_ts.py` の10-11行目:

```python
from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree
from grep_analyzer.embed_preprocess import host_grammar
from grep_analyzer.proc_preprocess import exec_spans
```

- [ ] **Step 3: `ts_span` の java/c/proc 分岐を集約（二重マスク除去）**

`ts_span` 内の先頭分岐（現 79-86 行）を次へ置換。`_SETS_BY_LANG` 分岐（python/js/ts/tsx）は**変更しない**:

```python
def ts_span(language: str, file_text: str, lineno: int):
    """選択範囲 [s,e]（0始まり物理行）。取れなければ None（→fallback）。spec §9。"""
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
        root = parse_tree(parse_lang, src)
    except Exception:
        return None
    # 以降（node_at_line 〜 last_stmt 返却）は不変
    ...
```

- [ ] **Step 4: proc snippet ゼロdiff を確認（named regression）**

Run: `python -m pytest tests/unit/test_snippet.py tests/golden -q`
Expected: PASS（特に proc_exec_snippet / proc_direct golden がゼロdiff・`ts_span("proc",..)` 系 unit 緑）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/snippet/_ts.py
git commit -m "refactor(snippet): ts_span の proc inline mask を parse_tree へ集約（二重マスク除去・_SETS_BY_LANG 分岐は不変・proc golden ゼロdiff）"
```

---

## Task 6: dispatch に jsp 拡張子＋`.html/.htm`→html を追加

**Files:**
- Modify: `src/grep_analyzer/dispatch.py:9-24`（`_EXT_MAP`）, `:76-100`（`detect_language`）, `:103-109`（`extension_resolves_language`）
- Test: `tests/unit/test_dispatch.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_dispatch.py に追記
from grep_analyzer.dispatch import detect_language, extension_resolves_language


def test_jsp_拡張子():
    for ext in (".jsp", ".jspf", ".jspx", ".tag", ".tagx"):
        assert detect_language(f"a{ext}", "<% int x; %>", {}) == "jsp"


def test_html_はC1ではhtmlパススルー():
    assert detect_language("a.html", "<div>{{x}}</div>", {}) == "html"
    assert detect_language("a.htm", "<p>static</p>", {}) == "html"


def test_html_拡張子はextension_resolves():
    assert extension_resolves_language("a.html", {}) is True
    assert extension_resolves_language("a.jsp", {}) is True
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_dispatch.py -k "jsp or html" -v`
Expected: FAIL（jsp は `c` 等にフォールバック／html 同様）

- [ ] **Step 3: `_EXT_MAP` に jsp を追加**

`src/grep_analyzer/dispatch.py` の `_EXT_MAP`（24行目 `".py": "python",` の後）に追加:

```python
    ".jsp": "jsp", ".jspf": "jsp", ".jspx": "jsp", ".tag": "jsp", ".tagx": "jsp",
```

- [ ] **Step 4: `detect_language` に `.html/.htm` 専用分岐を追加**

`detect_language` の proc 分岐（現 `if lang in ("c", "proc") or ext == ".h":` ブロック）直後、`if lang is not None:` の**前**に挿入:

```python
    if ext in (".html", ".htm"):
        return "html"          # C1: パススルー（C2 で _ANGULAR_RE 判定に差し替え）
```

- [ ] **Step 5: `extension_resolves_language` に `.html/.htm` を追加**

```python
def extension_resolves_language(path: str, lang_map: dict[str, str]) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in lang_map or ext in _EXT_MAP or ext in (".html", ".htm")
```

- [ ] **Step 6: パスを確認**

Run: `python -m pytest tests/unit/test_dispatch.py -v`
Expected: PASS（既存＋新規）

- [ ] **Step 7: コミット**

```bash
git add src/grep_analyzer/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat(dispatch): jsp 拡張子（.jsp/.jspf/.jspx/.tag/.tagx）＋ .html/.htm→html パススルー（C1）"
```

---

## Task 7: classify に jsp/html routing と category マップ

**Files:**
- Modify: `src/grep_analyzer/classifiers/ts_classifier.py:69-73`（`_CATEGORY_BY_LANG`）, `src/grep_analyzer/classify.py:25-35`
- Test: `tests/unit/test_classify.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_classify.py に追記
from grep_analyzer.classify import classify_hit


def test_jsp_classify_各category():
    # if→比較・宣言→宣言・代入→代入・return→return
    src_if = "<% if (a > b) { } %>\n"
    assert classify_hit("jsp", "", src_if, 1, src_if)[0] == "比較"
    src_decl = "<%! private int n; %>\n"
    assert classify_hit("jsp", "", src_decl, 1, src_decl)[0] == "宣言"
    src_ret = "<% return v; %>\n"
    assert classify_hit("jsp", "", src_ret, 1, src_ret)[0] == "return"


def test_jsp_式とELはその他():
    src_expr = "<%= title %>\n"
    assert classify_hit("jsp", "", src_expr, 1, src_expr)[0] == "その他"
    src_el = "${ user.code }\n"
    assert classify_hit("jsp", "", src_el, 1, src_el)[0] == "その他"


def test_html_は常にその他_high():
    assert classify_hit("html", "", "<p>x</p>\n", 1, "<p>x</p>") == ("その他", "high")
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_classify.py -k "jsp or html" -v`
Expected: FAIL（jsp が routing 未対応で KeyError／html 未対応）

- [ ] **Step 3: `_CATEGORY_BY_LANG` に jsp を追加**

`src/grep_analyzer/classifiers/ts_classifier.py` の `_CATEGORY_BY_LANG`（69-73行）に jsp 行を追加（angular は C2）:

```python
_CATEGORY_BY_LANG = {
    "java": _CATEGORY_JAVAC, "c": _CATEGORY_JAVAC, "proc": _CATEGORY_JAVAC,
    "jsp": _CATEGORY_JAVAC,
    "python": _CATEGORY_PY, "javascript": _CATEGORY_JS,
    "typescript": _CATEGORY_TS, "tsx": _CATEGORY_TS,
}
```

- [ ] **Step 4: `classify.py` に jsp/html routing を追加**

`src/grep_analyzer/classify.py:25` の分岐を変更:

```python
    if language in ("java", "c", "proc", "python", "javascript", "typescript",
                    "tsx", "jsp"):
        return classify_ts(language, file_text, lineno)
    if language == "html":
        return ("その他", "high")
    if language == "sql":
        return classify_sql(content)
```

- [ ] **Step 5: パスを確認**

Run: `python -m pytest tests/unit/test_classify.py -v`
Expected: PASS（既存＋新規）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py src/grep_analyzer/classify.py tests/unit/test_classify.py
git commit -m "feat(classify): jsp→classify_ts(java マップ)・html→定数その他 の routing 追加（method 宣言はその他＝category 表不変）"
```

---

## Task 8: jsp chaser 別キー登録＋stoplist（jsp/html）

**Files:**
- Modify: `src/grep_analyzer/classifiers/__init__.py:21-24`（`_CHASERS`）, `src/grep_analyzer/stoplist.py:54-57`（`LANG_KEYWORDS`）
- Test: `tests/unit/test_chase.py`, `tests/unit/test_stoplist.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_chase.py に追記
from grep_analyzer.chase import (extract_chase_symbols,
                                 extract_chase_symbols_from_root,
                                 extract_chase_symbols_tree)


def test_jsp_行ベースchaserが代入左辺を抽出():
    cs = extract_chase_symbols("jsp", "", "<% int x = TRACKED; %>")
    assert "x" in cs.vars


def test_jsp_ELは束縛なし():
    cs = extract_chase_symbols("jsp", "", "${ TRACKED.code }")
    assert cs.vars == () and cs.constants == ()


def test_html_はchase非発火():
    assert extract_chase_symbols("html", "", "x = TRACKED").vars == ()
    assert extract_chase_symbols_tree("html", "x = TRACKED\n", 1).vars == ()
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_chase.py -k "jsp or html" -v`
Expected: FAIL（`extract_chase_symbols("jsp",...)` が空＝`_CHASERS` 未登録）

- [ ] **Step 3: `_CHASERS` に jsp を登録**

`src/grep_analyzer/classifiers/__init__.py` の `_CHASERS`（21-24行）に jsp を追加:

```python
_CHASERS: dict[str, Chaser] = {
    "java": java_chaser, "c": c_chaser, "proc": c_chaser, "shell": shell_chaser,
    "sql": sql_chaser, "perl": perl_chaser, "groovy": groovy_chaser,
    "jsp": java_chaser,
}
```

- [ ] **Step 4: `LANG_KEYWORDS` に jsp/html を追加**

`src/grep_analyzer/stoplist.py`、`_TS_KW` 定義（53行）の後に追加し `LANG_KEYWORDS`（54-57行）へ反映:

```python
_JSP_KW = _JAVA_KW | frozenset(
    "page import include taglib c fn empty true false null instanceof".split())
LANG_KEYWORDS: dict[str, frozenset[str]] = {
    "java": _JAVA_KW, "c": _C_KW, "proc": _C_KW, "sql": _SQL_KW, "shell": _SHELL_KW,
    "perl": _PERL_KW, "groovy": _GROOVY_KW,
    "python": _PYTHON_KW, "javascript": _JS_KW, "typescript": _TS_KW, "tsx": _TS_KW,
    "jsp": _JSP_KW, "html": frozenset()}
```

- [ ] **Step 5: stoplist テストを追記**

```python
# tests/unit/test_stoplist.py に追記
from grep_analyzer.stoplist import LANG_KEYWORDS


def test_jsp_html_keyword_登録():
    assert "page" in LANG_KEYWORDS["jsp"] and "class" in LANG_KEYWORDS["jsp"]
    assert LANG_KEYWORDS["html"] == frozenset()
```

- [ ] **Step 6: パスを確認**

Run: `python -m pytest tests/unit/test_chase.py tests/unit/test_stoplist.py -v`
Expected: PASS（既存＋新規）

- [ ] **Step 7: コミット**

```bash
git add src/grep_analyzer/classifiers/__init__.py src/grep_analyzer/stoplist.py tests/unit/test_chase.py tests/unit/test_stoplist.py
git commit -m "feat(chase+stoplist): jsp を行ベース java_chaser に別キー登録・jsp/html の LANG_KEYWORDS 追加（html は chase 非発火）"
```

---

## Task 9: build_snippet に jsp region span 分岐

**Files:**
- Modify: `src/grep_analyzer/snippet/__init__.py:12`（import）, `:43-50`（`build_snippet` 分岐）
- Test: `tests/unit/test_snippet.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_snippet.py に追記
from grep_analyzer.snippet import build_snippet


def test_jsp_snippet_多行scriptletはregion_span():
    src = "<html>\n<%\n  int x = 1;\n%>\n</html>\n"
    out = build_snippet("jsp", "", src, 3)            # scriptlet 内ヒット
    assert "int x = 1;" in out                          # 区間が含まれる


def test_html_snippetは1行():
    src = "<p>line1</p>\n<p>TRACKED</p>\n<p>line3</p>\n"
    out = build_snippet("html", "", src, 2)
    assert "TRACKED" in out and "line1" not in out and "line3" not in out
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_snippet.py -k "jsp_snippet or html_snippet" -v`
Expected: FAIL（jsp が tree-sitter 分岐に無く1行になる＝多行 region span 不成立）

- [ ] **Step 3: import と分岐を追加**

`src/grep_analyzer/snippet/__init__.py:12` の import:

```python
from grep_analyzer.snippet._ts import proc_exec_span, ts_span
from grep_analyzer.embed_preprocess import jsp_region_span
```

`build_snippet` の分岐（43-50行）に jsp を追加（angular/html は分岐を**足さず** 51行の1行フォールバックへ素通し）:

```python
    if language in ("java", "c", "python", "javascript", "typescript", "tsx"):
        span = ts_span(language, file_text, lineno)
    elif language == "proc":
        span = proc_exec_span(file_text, lineno)
        if span is None:
            span = ts_span("proc", file_text, lineno)
    elif language == "jsp":
        span = jsp_region_span(file_text, lineno)
    elif language in ("sql", "shell", "perl", "groovy"):
        span = heuristic_span(lines, hit, language)
```

- [ ] **Step 4: パスを確認**

Run: `python -m pytest tests/unit/test_snippet.py -v`
Expected: PASS（既存＋新規）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/snippet/__init__.py tests/unit/test_snippet.py
git commit -m "feat(snippet): jsp は jsp_region_span（1段・原ソース <%…%> スパン）・angular/html は1行フォールバック"
```

---

## Task 10: jsp / html golden ケース（end-to-end）

**Files:**
- Create: `tests/golden/cases/jsp_chain/{src/page.jsp,input/TRACKED.grep,expected/TRACKED.tsv}`
- Create: `tests/golden/cases/html_passthrough/{src/p.html,input/TRACKED.grep,expected/TRACKED.tsv}`

- [ ] **Step 1: jsp_chain ケースの src/input を作る**

`tests/golden/cases/jsp_chain/src/page.jsp`（direct 各 category＋indirect 多ホップ）:

```jsp
<%
  String TRACKED = init();
  String alias = TRACKED;
  if (alias != null) { out.println(alias); }
%>
<p><%= alias %></p>
```

`tests/golden/cases/jsp_chain/input/TRACKED.grep`:

```
page.jsp:2:  String TRACKED = init();
```

- [ ] **Step 2: html_passthrough ケースの src/input を作る**

`tests/golden/cases/html_passthrough/src/p.html`（補間のみ＝Angular 固有マーカ無し→html。直接ヒット生存を spec §8 で固定）:

```html
<p>{{ TRACKED }} here</p>
```

`tests/golden/cases/html_passthrough/input/TRACKED.grep`:

```
p.html:1:<p>{{ TRACKED }} here</p>
```

- [ ] **Step 3: 生成して内容を検証（手動レビュー）**

Run（jsp_chain を生成して目視）:
```bash
python -c "
from pathlib import Path
from grep_analyzer.pipeline import run, _default_opts
import tempfile, sys
case = Path('tests/golden/cases/jsp_chain')
out = Path(tempfile.mkdtemp())
run(case/'input', out, case/'src', _default_opts())
print((out/'TRACKED.tsv').read_text('utf-8-sig'))
"
```
Expected（検証ポイント）: `TRACKED` の direct 行が language=`jsp`、`alias`（indirect:var）が hop2 で現れる、`if` 行 category=`比較`、snippet が scriptlet を含む。html は language=`html`・category=`その他`・indirect 行なし。

- [ ] **Step 4: 検証済み出力を expected/ へスナップショット（{SOURCE_ROOT} 正規化）**

Run（両ケース。`file` 列の絶対 src パスを `{SOURCE_ROOT}` へ各行先頭1回置換＝§11 機構）:
```bash
python -c "
from pathlib import Path
from grep_analyzer.pipeline import run, _default_opts
import tempfile
for name in ('jsp_chain','html_passthrough'):
    case = Path('tests/golden/cases')/name
    out = Path(tempfile.mkdtemp())
    run(case/'input', out, case/'src', _default_opts())
    sr = str((case/'src').resolve())
    (case/'expected').mkdir(exist_ok=True)
    for tsv in out.glob('*.tsv'):
        txt = ''.join((ln.replace(sr+'/', '{SOURCE_ROOT}/', 1) if (sr+'/') in ln else ln)
                      for ln in tsv.read_text('utf-8-sig').splitlines(keepends=True))
        (case/'expected'/tsv.name).write_text(txt, 'utf-8')
        print(name, tsv.name, 'snapshotted')
"
```

- [ ] **Step 5: golden テストが緑であることを確認**

Run: `python -m pytest tests/golden -q`
Expected: PASS（jsp_chain / html_passthrough を含む全 golden 緑）

- [ ] **Step 6: コミット**

```bash
git add tests/golden/cases/jsp_chain tests/golden/cases/html_passthrough
git commit -m "test(golden): jsp_chain（direct 各category＋indirect 多ホップ）／html_passthrough（その他・chase なし）"
```

---

## Task 11: C1 ゲート（Inv-C 二段＋全緑）

**Files:** なし（検証のみ）

- [ ] **Step 1: 全テストを実行**

Run: `python -m pytest -q`
Expected: PASS（331 passed, 5 skipped のベースライン＋本フェーズ追加分。**既存 golden ゼロdiff**＝proc/java/c/sql/shell/perl/groovy/ts/tsx/js/python 不変）

- [ ] **Step 2: host 写像の恒等 smoke を確認**

Run:
```bash
python -c "
from grep_analyzer.embed_preprocess import host_grammar, host_source
s='int x=1;\nEXEC SQL X;\n'
for l in ('java','c','python','javascript','typescript','tsx'):
    assert host_grammar(l)==l and host_source(l,s)==s, l
print('identity OK')
"
```
Expected: `identity OK`

- [ ] **Step 3: C1 完了タグコミット（任意）**

```bash
git commit --allow-empty -m "chore(track-c): Phase C1（共通逆マスク基盤＋jsp＋html）完了・Inv-C ゼロdiff 全緑"
```

---

# Phase C2: Angular

## Task 12: `extract_angular_ts`（Angular 逆マスク）

**Files:**
- Modify: `src/grep_analyzer/embed_preprocess.py`
- Test: `tests/unit/test_embed_preprocess.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_embed_preprocess.py に追記
from grep_analyzer.embed_preprocess import extract_angular_ts


def test_angular_補間とバインディングの式を残す():
    src = '<p>{{ user.code }}</p>\n<a [href]="url">x</a>\n'
    out = extract_angular_ts(src)
    assert out.count("\n") == src.count("\n")
    assert "user.code" in out and "url" in out
    assert "<p>" not in out and "href" not in out


def test_angular_ngFor_を_let_X_eq_Y_に正規化():
    src = '<li *ngFor="let item of items; trackBy: t">x</li>\n'
    out = extract_angular_ts(src)
    assert "let item" in out and "items" in out
    assert " of " not in out and "trackBy" not in out   # of→=・; 以降除去


def test_angular_パイプ右辺を除去():
    src = "<p>{{ value | currency }}</p>\n"
    out = extract_angular_ts(src)
    assert "value" in out and "currency" not in out


def test_angular_HTMLコメント内の式は空白化():
    src = "<!-- {{ secret }} -->\n"
    out = extract_angular_ts(src)
    assert "secret" not in out
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -k angular -v`
Expected: FAIL（`ImportError: cannot import name 'extract_angular_ts'`）

- [ ] **Step 3: 最小実装**

```python
# src/grep_analyzer/embed_preprocess.py に追記
_NG_INTERP = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)
# [prop]= / [(two-way)]= / (event)= / *dir=  の属性。値は " か ' で囲まれる。
_NG_ATTR = re.compile(
    r"""(?:\[\(?[\w.$-]+\)?\]|\([\w.$-]+\)|\*[\w-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""",
    re.DOTALL)
_NG_PIPE = re.compile(r"(?<!\|)\|(?!\|)")               # 単一 | （|| は除外）


def _ng_normalize(expr: str) -> str:
    """式断片の best-effort 正規化（spec §3.4）。長さは概ね保つが ngFor の of→= は1縮む。"""
    # *ngFor: 最初の ; 以降を除去し of→=
    head = expr.split(";", 1)[0]
    head = re.sub(r"\bof\b", "=", head)
    # パイプ右辺を除去（左辺式のみ）
    m = _NG_PIPE.search(head)
    if m is not None:
        head = head[:m.start()]
    return head


def extract_angular_ts(source: str) -> str:
    """Angular テンプレから typescript host が読める式だけ残す（行数保存・spec §4.2）。"""
    out = list(_blank(source))
    masked = _HTML_COMMENT.sub(lambda m: _blank(m.group(0)), source)  # コメント内式を除外

    def _emit(raw_start: int, raw_expr: str):
        norm = _ng_normalize(raw_expr)
        for j, ch in enumerate(norm):
            if raw_start + j < len(out):
                out[raw_start + j] = ch
        # 正規化で縮んだ残余は空白のまま（行数は不変）

    for m in _NG_INTERP.finditer(masked):
        _emit(m.start(1), source[m.start(1):m.end(1)])
    for m in _NG_ATTR.finditer(masked):
        gi = 1 if m.group(1) is not None else 2
        _emit(m.start(gi), source[m.start(gi):m.end(gi)])
    return "".join(out)
```

- [ ] **Step 4: パスを確認**

Run: `python -m pytest tests/unit/test_embed_preprocess.py -k angular -v`
Expected: PASS（4 件）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/embed_preprocess.py tests/unit/test_embed_preprocess.py
git commit -m "feat(embed): extract_angular_ts 逆マスク（補間/束縛/イベント/*ngFor の TS 式を残す・of→= 正規化・パイプ/HTMLコメント除去）"
```

---

## Task 13: angular の配線（host 写像・category・AST chaser・classify・stoplist）

**Files:**
- Modify: `src/grep_analyzer/embed_preprocess.py`（`_HOST_GRAMMAR`/`host_source`）, `classifiers/ts_classifier.py:69-73`（`_CATEGORY_BY_LANG`）, `classifiers/__init__.py:26-31`（`_AST_CHASERS`）, `classify.py:25`（routing）, `stoplist.py:54-57`（`LANG_KEYWORDS`）
- Test: `tests/unit/test_classify.py`, `tests/unit/test_ast_chaser.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_classify.py に追記
def test_angular_classify():
    src = '<p>{{ user.code }}</p>\n'
    assert classify_hit("angular", "", src, 1, src)[0] == "その他"
    src2 = '<button (click)="x = 1">b</button>\n'
    assert classify_hit("angular", "", src2, 1, src2)[0] == "代入"


# tests/unit/test_ast_chaser.py に追記
from grep_analyzer.chase import extract_chase_symbols_tree


def test_angular_ngFor_束縛をAST抽出():
    src = '<li *ngFor="let item of TRACKED">{{item}}</li>\n'
    cs = extract_chase_symbols_tree("angular", src, 1)
    assert "item" in cs.vars            # of→= 正規化後 ts が item を束縛抽出
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_classify.py::test_angular_classify tests/unit/test_ast_chaser.py::test_angular_ngFor_束縛をAST抽出 -v`
Expected: FAIL（angular 未配線）

- [ ] **Step 3: `host_source`/`_HOST_GRAMMAR` に angular を追加**

`src/grep_analyzer/embed_preprocess.py`:

```python
_HOST_GRAMMAR = {"proc": "c", "jsp": "java", "angular": "typescript"}


def host_source(language: str, source: str) -> str:
    if language == "proc":
        return mask_exec_sql(source)
    if language == "jsp":
        return extract_jsp_java(source)
    if language == "angular":
        return extract_angular_ts(source)
    return source
```

- [ ] **Step 4: `_CATEGORY_BY_LANG` に angular（typescript マップ）を追加**

`src/grep_analyzer/classifiers/ts_classifier.py` の `_CATEGORY_BY_LANG`:

```python
    "jsp": _CATEGORY_JAVAC, "angular": _CATEGORY_TS,
```

- [ ] **Step 5: `_AST_CHASERS` に angular を追加**

`src/grep_analyzer/classifiers/__init__.py` の `_AST_CHASERS`（26-31行）に1行:

```python
_AST_CHASERS: dict[str, ASTChaser] = {
    "python": python_chaser,
    "javascript": javascript_chaser,
    "typescript": typescript_chaser,
    "tsx": typescript_chaser,
    "angular": typescript_chaser,
}
```

- [ ] **Step 6: `classify.py` の routing に angular を追加**

```python
    if language in ("java", "c", "proc", "python", "javascript", "typescript",
                    "tsx", "jsp", "angular"):
        return classify_ts(language, file_text, lineno)
```

- [ ] **Step 7: `stoplist.py` に angular を追加**

`src/grep_analyzer/stoplist.py`（`_JSP_KW` の後）:

```python
_ANGULAR_KW = _TS_KW | frozenset(
    "ngIf ngFor ngSwitch ngClass ngStyle ngModel let of trackBy async $event".split())
```
`LANG_KEYWORDS` に `"angular": _ANGULAR_KW,` を追加。

- [ ] **Step 8: パスを確認**

Run: `python -m pytest tests/unit/test_classify.py tests/unit/test_ast_chaser.py -v`
Expected: PASS（既存＋新規）

- [ ] **Step 9: コミット**

```bash
git add src/grep_analyzer/embed_preprocess.py src/grep_analyzer/classifiers/ts_classifier.py src/grep_analyzer/classifiers/__init__.py src/grep_analyzer/classify.py src/grep_analyzer/stoplist.py tests/unit/test_classify.py tests/unit/test_ast_chaser.py
git commit -m "feat(angular): host 写像・category(TS)・_AST_CHASERS(typescript_chaser)・classify routing・stoplist を配線（seed/scan/absorb は無改修で AST 経路へ）"
```

---

## Task 14: dispatch の `.html/.htm` を Angular ヒューリスティックへ

**Files:**
- Modify: `src/grep_analyzer/embed_preprocess.py`（`_ANGULAR_RE`）, `src/grep_analyzer/dispatch.py`（`.html/.htm` 分岐・import）
- Test: `tests/unit/test_dispatch.py`

- [ ] **Step 1: 失敗するテストを書く**

```python
# tests/unit/test_dispatch.py に追記（既存 test_html_はC1ではhtmlパススルー は削除/置換）
def test_html_angular_マーカで_angular():
    assert detect_language("a.html", '<li *ngFor="let x of xs"></li>', {}) == "angular"
    assert detect_language("a.html", '<a [href]="u">x</a>', {}) == "angular"
    assert detect_language("a.html", '<button (click)="f()">b</button>', {}) == "angular"


def test_html_マーカ無しと補間のみは_html():
    assert detect_language("a.html", "<p>static</p>", {}) == "html"
    assert detect_language("a.html", "<p>{{x}}</p>", {}) == "html"  # {{ 単独は angular にしない
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_dispatch.py -k "angular or マーカ無し" -v`
Expected: FAIL（現状 `.html`→常に html）

- [ ] **Step 3: `_ANGULAR_RE` を embed_preprocess に追加**

`src/grep_analyzer/embed_preprocess.py`（Angular 固有マーカ優先・`{{` 単独は含めない）:

```python
# Angular 固有束縛マーカ（{{ 単独は Vue/Handlebars と重複し過検出のため含めない・spec §5 #1）
_ANGULAR_RE = re.compile(
    r"""\*ng[\w-]+|\[\(?[\w.$-]+\)?\]\s*=|\([\w.$-]+\)\s*=|routerLink|formControl|ngModel""")
```

- [ ] **Step 4: dispatch の `.html/.htm` 分岐を差し替える**

`src/grep_analyzer/dispatch.py` 冒頭に import を追加:

```python
from grep_analyzer.embed_preprocess import _ANGULAR_RE
```

`detect_language` の `.html/.htm` 分岐（Task 6 で入れた行）を置換:

```python
    if ext in (".html", ".htm"):
        return "angular" if _ANGULAR_RE.search(content_sample) else "html"
```

- [ ] **Step 5: パスを確認**

Run: `python -m pytest tests/unit/test_dispatch.py -v`
Expected: PASS（既存＋新規・両方向）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/embed_preprocess.py src/grep_analyzer/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat(dispatch): .html/.htm を _ANGULAR_RE 内容ヒューリスティックで angular/html へ（Angular 固有マーカ優先・{{ 単独は html）"
```

---

## Task 15: angular golden ケース（direct＋テンプレ内多ホップ）

**Files:**
- Create: `tests/golden/cases/angular_chain/{src/app.component.html,input/TRACKED.grep,expected/TRACKED.tsv}`

- [ ] **Step 1: src/input を作る**

`tests/golden/cases/angular_chain/src/app.component.html`（direct＋`*ngFor` 由来の多ホップ。**`*ngFor` 束縛行と `{{ row.code }}` 消費行を別行にする**＝同一行だと `row` の indirect 行が `is_seed_location` で seed 行と衝突して除外され多ホップを実証できない・spec §6「angular は単行前提」・plan レビュー実証済）:

```html
<ul>
  <li *ngFor="let row of TRACKED">
    {{ row.code }}
  </li>
</ul>
<p [title]="TRACKED.length">count</p>
```

`tests/golden/cases/angular_chain/input/TRACKED.grep`（TRACKED は 2 行目と 6 行目）:

```
app.component.html:2:  <li *ngFor="let row of TRACKED">
app.component.html:6:<p [title]="TRACKED.length">count</p>
```

- [ ] **Step 2: 生成して内容を検証（手動レビュー）**

Run:
```bash
python -c "
from pathlib import Path
from grep_analyzer.pipeline import run, _default_opts
import tempfile
case = Path('tests/golden/cases/angular_chain')
out = Path(tempfile.mkdtemp())
run(case/'input', out, case/'src', _default_opts())
print((out/'TRACKED.tsv').read_text('utf-8-sig'))
"
```
Expected: language=`angular`、`TRACKED` direct 2 行、`row`（indirect:var・`*ngFor` 由来）が hop2 で現れ `{{ row.code }}` 行を参照、category は その他/代入 系。

- [ ] **Step 3: expected/ へスナップショット（{SOURCE_ROOT} 正規化）**

Run:
```bash
python -c "
from pathlib import Path
from grep_analyzer.pipeline import run, _default_opts
import tempfile
case = Path('tests/golden/cases/angular_chain')
out = Path(tempfile.mkdtemp())
run(case/'input', out, case/'src', _default_opts())
sr = str((case/'src').resolve())
(case/'expected').mkdir(exist_ok=True)
for tsv in out.glob('*.tsv'):
    txt = ''.join((ln.replace(sr+'/', '{SOURCE_ROOT}/', 1) if (sr+'/') in ln else ln)
                  for ln in tsv.read_text('utf-8-sig').splitlines(keepends=True))
    (case/'expected'/tsv.name).write_text(txt, 'utf-8')
    print(tsv.name, 'snapshotted')
"
```

- [ ] **Step 4: golden テスト緑を確認**

Run: `python -m pytest tests/golden -q`
Expected: PASS（angular_chain を含む全 golden 緑）

- [ ] **Step 5: コミット**

```bash
git add tests/golden/cases/angular_chain
git commit -m "test(golden): angular_chain（direct＋*ngFor 由来 row のテンプレ内多ホップ）"
```

---

## Task 16: C2 ゲート＋master 反映

**Files:**
- Modify: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（§57/§386/§15 フェーズ/§8.4）, `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テストを実行（Inv-C 二段ゲート）**

Run: `python -m pytest -q`
Expected: PASS（既存 golden ゼロdiff＋全緑。jsp_chain/html_passthrough/angular_chain 追加分を含む）

- [ ] **Step 2: 文字コード直交（レガシー JSP SJIS）の手動確認**

Run:
```bash
python -c "
from grep_analyzer.embed_preprocess import extract_jsp_java
s = '<%-- 日本語コメント --%>\n<% String 名前 = TRACKED; %>\n'
out = extract_jsp_java(s)
assert out.count(chr(10)) == s.count(chr(10))   # 行数保存（多バイト混在）
assert 'TRACKED' in out
print('encoding char-unit OK')
"
```
Expected: `encoding char-unit OK`

- [ ] **Step 3: master spec を更新**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` に反映（spec §9）:
- §57: track C（JSP/Angular）完了を追記（参照: 本差分設計書＋実装計画）。
- §386: 「残り言語: track C は後続」→「track C 完了。v2 ロードマップ（B→A→C）完遂」。
- §15 フェーズ: 「フェーズ7（v2 埋め込みトラック C・完了済）」を追加（完了基準＝Inv-C＋jsp/html/angular golden＋全緑、新規 wheel ゼロ）。
- §8.4: 本差分設計書 §6 の既知限界を追加。
- §14 後続候補: Angular inline template の式抽出、既存 java/c/jsp chaser の AST 化統一を明記。

`docs/superpowers/plans/phase0-gate-result.md`: 「track C は新規 grammar wheel 不要・G1 自動充足（java/typescript は track A で同梱済）」を1行追補。

- [ ] **Step 4: テスト件数ベースラインを確認**

Run: `python -m pytest -q | tail -1`
Expected: 新ベースライン（例: `34X passed, 5 skipped`）を記録。master §「テスト件数ベースライン」を新値へ更新。

- [ ] **Step 5: コミット**

```bash
git add docs/superpowers/specs/2026-05-16-grep-analyzer-design.md docs/superpowers/plans/phase0-gate-result.md
git commit -m "docs(master): track C（JSP/Angular）完了反映 — v2 ロードマップ B→A→C 完遂・§8.4 既知限界・テスト件数ベースライン更新"
```

---

## 完了基準（spec §9 / Inv-C）
- 全テスト緑（既存 golden ゼロdiff＝Inv-C ＋ jsp_chain/html_passthrough/angular_chain 新規 golden）。
- 新規 grammar wheel ゼロ（`requirements.lock` 不変）。
- jsp（行ベース java_chaser・region snippet）／angular（AST typescript_chaser・`*ngFor` of→= 正規化）／html（パススルー）が dispatch→classify→chase→snippet→fixedpoint を end-to-end で通る。
- proc 挙動保存（host_grammar/host_source 集約後も proc golden byte 不変）。
