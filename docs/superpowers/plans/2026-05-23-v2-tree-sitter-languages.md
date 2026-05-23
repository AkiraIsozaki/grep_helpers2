# v2 tree-sitter トラック（A: TS/TSX/JS/Python）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** grep_analyzer に TypeScript / TSX / JavaScript / Python を tree-sitter トラックで追加する（classify=AST high、chaser=AST field-directed・複数行）。

**Architecture:** 2フェーズ。**Phase A0**＝tree-sitter ランタイム＋全 grammar を 0.21.3→0.23.x へ移行し、既存 golden を byte 不変に保つ（独立マージ可能ゲート G-A0）。**Phase A1**＝4言語を追加（dispatch/stoplist/classify/chaser/fixedpoint抽出経路/snippet/golden）。chaser は新4言語専用に「束縛導入ノードの name:/left: フィールドのみ」を AST から決定的抽出（方式A=worker で file 単位1パース）。

**Tech Stack:** Python 3.12、tree-sitter 0.23.2＋grammar（java 0.23.5 / c 0.23.4 / python 0.23.6 / javascript 0.23.1 / typescript 0.23.2）、pytest、wheelhouse オフライン（aarch64+x86_64）。

**正本 spec:** `docs/superpowers/specs/2026-05-23-v2-tree-sitter-languages-design.md`（§番号は本書から参照）。

**作業ブランチ:** main 直接（ソロプロジェクト方針）。各タスク末でコミット。

---

## File Structure（変更・新規ファイルと責務）

- `pyproject.toml` / `requirements.lock` / `wheelhouse/`（変更）— 依存ピンを 0.23.x へ。lock は `scripts/gen_requirements_lock.py` で再生成。
- `src/grep_analyzer/classifiers/ts_classifier.py`（変更）— 0.23 API 適合＋6言語の Language ロード＋言語別 `_CATEGORY_BY_LANG`。
- `src/grep_analyzer/classify.py`（変更）— `classify_ts` 分岐に4言語追加。
- `src/grep_analyzer/dispatch.py`（変更）— 拡張子＋シェバン。
- `src/grep_analyzer/stoplist.py`（変更）— `LANG_KEYWORDS` に4言語。
- `src/grep_analyzer/classifiers/base.py`（変更）— `ASTChaser` Protocol。
- `src/grep_analyzer/classifiers/python_chaser.py` / `javascript_chaser.py` / `typescript_chaser.py`（新規）— AST field-directed 抽出。
- `src/grep_analyzer/classifiers/__init__.py`（変更）— `_AST_CHASERS` レジストリ。
- `src/grep_analyzer/chase.py`（変更）— `extract_chase_symbols_tree` / `extract_chase_symbols_from_root`。
- `src/grep_analyzer/fixedpoint/_scan.py` / `_ingest.py` / `_seed.py`（変更）— `kinds_of(cs)`・`ingest_one` 新契約・worker AST 抽出・`found` 4-tuple。
- `src/grep_analyzer/snippet/_ts.py` / `snippet/__init__.py`（変更）— 言語別粒度集合＋`build_snippet` 分岐。
- `tests/unit/*` / `tests/golden/cases/*` / `tests/integration/test_v2_langs.py`（変更・新規）。

---

# Phase A0 — ランタイム移行（独立マージ可能・ゲート G-A0）

## Task 0: ベースライン記録

**Files:** なし（確認のみ）

- [ ] **Step 1: 全テストを実行し緑数を記録**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: 全 PASS（例: `288 passed, 5 skipped`）。この数を控える（後続の回帰判定の基準）。

- [ ] **Step 2: tree-sitter 現行版を確認**

Run: `python -c "import tree_sitter, tree_sitter_java, tree_sitter_c; print('ok')"`
Expected: `ok`（現行 0.21.3 系）。

---

## Task 1: 依存を 0.23.x へ（wheelhouse / lock / pyproject）

**Files:**
- Modify: `wheelhouse/`（古い tree-sitter 0.21 wheel 削除・0.23 wheel 追加）
- Modify: `requirements.lock`（`scripts/gen_requirements_lock.py` で再生成）
- Modify: `pyproject.toml:9-15`

- [ ] **Step 1: 0.23 wheel を両アーキで wheelhouse へダウンロード**

```bash
cd /workspaces/grep_helpers2
dl() { pip download --no-deps --only-binary=:all: \
  --platform manylinux_2_17_aarch64 --platform manylinux2014_aarch64 \
  --platform manylinux_2_17_x86_64 --platform manylinux2014_x86_64 \
  --platform manylinux_2_5_x86_64 --platform manylinux1_x86_64 \
  --python-version 312 --implementation cp --abi abi3 --abi cp312 \
  "$1" -d wheelhouse; }
dl "tree-sitter==0.23.2"
dl "tree-sitter-java==0.23.5"
dl "tree-sitter-c==0.23.4"
dl "tree-sitter-python==0.23.6"
dl "tree-sitter-javascript==0.23.1"
dl "tree-sitter-typescript==0.23.2"
```
Note: 1 コマンドで複数 `--platform` を渡すと pip は各アーキ wheel を取得する（aarch64＋x86_64 両方が wheelhouse に入る）。

- [ ] **Step 2: 古い 0.21 系 wheel を削除**

```bash
rm -f wheelhouse/tree_sitter-0.21.3-*.whl \
      wheelhouse/tree_sitter_java-0.21.0-*.whl \
      wheelhouse/tree_sitter_c-0.21.4-*.whl
ls wheelhouse | grep -E "tree_sitter" | sort
```
Expected: tree_sitter 0.23.2 / java 0.23.5 / c 0.23.4 / python 0.23.6 / javascript 0.23.1 / typescript 0.23.2 が各2アーキ（計12 wheel）。0.21 系が残っていないこと。

- [ ] **Step 3: lock を決定的再生成**

Run: `python scripts/gen_requirements_lock.py`
Expected: `requirements.lock 生成: N packages / M wheels`（完全ピン違反エラーが出ないこと）。

- [ ] **Step 4: pyproject のピンを更新**

`pyproject.toml` の `dependencies` を以下へ（`src/grep_analyzer` の `dependencies` ブロック）:
```toml
dependencies = [
    "tree-sitter==0.23.2",
    "tree-sitter-java==0.23.5",
    "tree-sitter-c==0.23.4",
    "tree-sitter-python==0.23.6",
    "tree-sitter-javascript==0.23.1",
    "tree-sitter-typescript==0.23.2",
    "chardet==5.2.0",
    "pyahocorasick==2.3.1",
]
```

- [ ] **Step 5: 開発環境へ新 wheel を導入**

```bash
pip install --no-index --find-links wheelhouse --force-reinstall --no-deps \
  tree-sitter==0.23.2 tree-sitter-java==0.23.5 tree-sitter-c==0.23.4 \
  tree-sitter-python==0.23.6 tree-sitter-javascript==0.23.1 tree-sitter-typescript==0.23.2
python -c "import tree_sitter, tree_sitter_python, tree_sitter_typescript; print('0.23 ok')"
```
Expected: `0.23 ok`。

- [ ] **Step 6: lock 整合テスト**

Run: `python -m pytest tests/unit/test_requirements_lock.py -q`
Expected: PASS（lock↔wheelhouse の byte 一致・全 hash 存在・孤児 wheel なし・spec §4.1 網羅）。

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml requirements.lock wheelhouse
git commit -m "build(deps): tree-sitter 0.21.3→0.23.x へ移行（python/js/ts grammar 追加・多アーキ wheel）"
```

---

## Task 2: ts_classifier の 0.23 API 適合（java/c のみ）

**Files:**
- Modify: `src/grep_analyzer/classifiers/ts_classifier.py:6-39`

- [ ] **Step 1: 既存 tree-sitter テストが現状緑なことを確認（移行前基準）**

Run: `python -m pytest tests/unit/test_ts_classifier.py tests/unit/test_snippet.py -q`
Expected: この時点では **FAIL する可能性が高い**（0.23 をインストール済みなので 0.21 API `Language(ptr,name)`/`set_language` が壊れている）。失敗内容が API 不整合（`TypeError`/`AttributeError`）であることを確認。

- [ ] **Step 2: 0.23 API へ移行**

`ts_classifier.py` の冒頭（import〜`_parser`）を以下へ置換:
```python
import tree_sitter_c
import tree_sitter_java
from tree_sitter import Language, Parser

from grep_analyzer.classifiers.base import ClassifyResult
from grep_analyzer.proc_preprocess import mask_exec_sql

# py-tree-sitter 0.23: Language(capsule) 1引数 / Parser(lang) コンストラクタ。
# tree_sitter_<lang>.language() は PyCapsule を返す（0.21 の int から変更）。
_LANGS = {
    "java": Language(tree_sitter_java.language()),
    "c": Language(tree_sitter_c.language()),
}
```
`_JAVA`/`_C` の2行（旧 line 15-16）は削除。`_parser` を以下へ置換:
```python
def _parser(language: str) -> Parser:
    # "proc" を含む非 Java 言語は tree-sitter-c で解析（spec §7 Pro*C 前処理）。
    key = "c" if language in ("c", "proc") else language
    return Parser(_LANGS[key])
```
`_CATEGORY_BY_NODE`・`node_at_line`・`classify_ts`・`parse_tree` は本タスクでは不変。あわせてモジュール冒頭 docstring の「py-tree-sitter 0.21 API に依存」を「0.23 API に依存」へ更新する。

- [ ] **Step 3: tree-sitter テスト緑を確認**

Run: `python -m pytest tests/unit/test_ts_classifier.py tests/unit/test_snippet.py -q`
Expected: 全 PASS。

- [ ] **Step 4: Commit**

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py
git commit -m "refactor(ts_classifier): py-tree-sitter 0.23 API 適合（Language(capsule)/Parser(lang)・_LANGS マップ）"
```

---

## Task 3: ゲート G-A0（golden ゼロdiff＋全緑＋ノード型存在 smoke）

**Files:**
- Create: `tests/unit/test_ts_node_types_023.py`

- [ ] **Step 1: ノード型存在 smoke を書く（失敗ファースト）**

`tests/unit/test_ts_node_types_023.py`:
```python
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
```

- [ ] **Step 2: smoke を実行**

Run: `python -m pytest tests/unit/test_ts_node_types_023.py -q`
Expected: PASS（全ノード型が 0.23 に存在）。万一 FAIL なら当該ノード型が rename されている→`ts_classifier._CATEGORY_BY_NODE` と `snippet/_ts.py` の集合を差分吸収（機能不変）してから再実行。

- [ ] **Step 3: G-A0 ゲート＝既存 golden＋全テスト緑（expected 無編集）**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 全 PASS（expected ファイルを一切編集していないこと＝再生成 diff ゼロ）＋全体が Task 0 と同数＋新 smoke 2件。回帰ゼロ。

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_ts_node_types_023.py
git commit -m "test(gate): G-A0 ノード型存在 smoke（0.23 rename 検出・golden 死角補完）"
```

---

# Phase A1 — 4言語追加（A0 緑の 0.23 基盤上に積む）

## Task 4: dispatch（拡張子＋シェバン）

**Files:**
- Modify: `src/grep_analyzer/dispatch.py:9-30`
- Test: `tests/unit/test_dispatch.py`

- [ ] **Step 1: 失敗テストを追記**

`tests/unit/test_dispatch.py` の末尾に追記（既存ファイル・先頭の import は流用）:
```python
def test_ts_tsx_js_py拡張子を解決する():
    from grep_analyzer.dispatch import detect_language
    assert detect_language("a.ts", "", {}) == "typescript"
    assert detect_language("a.tsx", "", {}) == "tsx"
    assert detect_language("a.js", "", {}) == "javascript"
    assert detect_language("a.mjs", "", {}) == "javascript"
    assert detect_language("a.jsx", "", {}) == "javascript"
    assert detect_language("a.py", "", {}) == "python"


def test_shebang_node_python_を解決する():
    from grep_analyzer.dispatch import detect_language, shebang_language
    assert detect_language("noext", "#!/usr/bin/env node\n", {}) == "javascript"
    assert detect_language("noext2", "#!/usr/bin/python3\n", {}) == "python"
    assert shebang_language("#!/usr/bin/env node\n") == "javascript"
    assert shebang_language("#!/usr/bin/python3\n") == "python"
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_dispatch.py -k "ts_tsx_js_py or shebang_node_python" -q`
Expected: FAIL（typescript 等を返さない）。

- [ ] **Step 3: dispatch.py を更新**

`_EXT_MAP`（line 9-20）の末尾要素に追記:
```python
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".py": "python",
```
`_SHEBANG_LANG`（line 27-30）へ追記:
```python
_SHEBANG_LANG = {
    "sh": "shell", "bash": "shell", "ksh": "shell", "dash": "shell",
    "csh": "shell", "tcsh": "shell", "perl": "perl", "groovy": "groovy",
    "node": "javascript", "python": "python",
}
```
（`detect_language` の手順は不変＝拡張子で typescript/tsx/javascript/python が `lang is not None` 分岐へ落ち、そのまま返る。）

- [ ] **Step 4: 実行して PASS＋回帰なし**

Run: `python -m pytest tests/unit/test_dispatch.py -q`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat(dispatch): TS/TSX/JS/Python の拡張子＋シェバン(node/python)を解決"
```

---

## Task 5: stoplist（予約語）

**Files:**
- Modify: `src/grep_analyzer/stoplist.py:34-44`
- Test: `tests/unit/test_stoplist.py`

- [ ] **Step 1: 失敗テストを追記**

`tests/unit/test_stoplist.py` 末尾に追記:
```python
def test_新言語の予約語がLANG_KEYWORDSに登録される():
    from grep_analyzer.stoplist import LANG_KEYWORDS
    for lang in ("python", "javascript", "typescript", "tsx"):
        assert lang in LANG_KEYWORDS
    assert "class" in LANG_KEYWORDS["python"]
    assert "const" in LANG_KEYWORDS["javascript"]
    assert "interface" in LANG_KEYWORDS["typescript"]


def test_予約語はadmitで棄却される():
    from grep_analyzer.stoplist import admit, SymbolPolicy
    pol = SymbolPolicy(min_specificity=2, user_stoplist=frozenset())
    res = admit(["const", "myVar"], "javascript", pol)
    assert res.accepted == ["myVar"]
    assert ("const", "keyword") in res.rejected
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_stoplist.py -k "新言語 or 予約語はadmit" -q`
Expected: FAIL（KeyError / const 未棄却）。

- [ ] **Step 3: stoplist.py を更新**

`_GROOVY_KW` の後（line 41 の後）に追加:
```python
_PYTHON_KW = frozenset(
    "False None True and as assert async await break class continue def del elif else "
    "except finally for from global if import in is lambda nonlocal not or pass raise "
    "return try while with yield match case self print".split())
_JS_KW = frozenset(
    "break case catch class const continue debugger default delete do else export extends "
    "finally for function if import in instanceof new return super switch this throw try "
    "typeof var void while with yield let static get set of async await null true false "
    "undefined console".split())
_TS_KW = _JS_KW | frozenset(
    "interface type enum namespace declare abstract implements readonly public private "
    "protected as is keyof infer any unknown never number string boolean object".split())
```
`LANG_KEYWORDS`（line 42-44）へキー追加:
```python
LANG_KEYWORDS: dict[str, frozenset[str]] = {
    "java": _JAVA_KW, "c": _C_KW, "proc": _C_KW, "sql": _SQL_KW, "shell": _SHELL_KW,
    "perl": _PERL_KW, "groovy": _GROOVY_KW,
    "python": _PYTHON_KW, "javascript": _JS_KW, "typescript": _TS_KW, "tsx": _TS_KW}
```

- [ ] **Step 4: PASS＋回帰なし**

Run: `python -m pytest tests/unit/test_stoplist.py -q`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/stoplist.py tests/unit/test_stoplist.py
git commit -m "feat(stoplist): python/javascript/typescript/tsx の予約語 frozenset 追加"
```

---

## Task 6: classify（grammar ロード＋言語別 category＋ルーティング）

**Files:**
- Modify: `src/grep_analyzer/classifiers/ts_classifier.py`
- Modify: `src/grep_analyzer/classify.py:25-26`
- Test: `tests/unit/test_ts_classifier.py`

- [ ] **Step 1: 失敗テストを追記**

`tests/unit/test_ts_classifier.py` 末尾に追記:
```python
def test_python_category():
    assert classify_ts("python", "X = 1\n", 1) == ("代入", "high")
    assert classify_ts("python", "if a == b:\n    pass\n", 1) == ("比較", "high")
    assert classify_ts("python", "from x import y\n", 1) == ("宣言", "high")
    assert classify_ts("python", "def f():\n    return z\n", 2) == ("return", "high")


def test_javascript_category():
    assert classify_ts("javascript", "const X = 1;\n", 1) == ("宣言", "high")
    assert classify_ts("javascript", "a = b;\n", 1) == ("代入", "high")
    assert classify_ts("javascript", "switch (x) { case 1: break; }\n", 1) == ("分岐", "high")


def test_typescript_category():
    assert classify_ts("typescript", "enum E { A, B }\n", 1) == ("宣言", "high")
    assert classify_ts("typescript", "interface I { x: number; }\n", 1) == ("宣言", "high")


def test_tsx_category():
    assert classify_ts("tsx", "const App = () => <div>{x}</div>;\n", 1) == ("宣言", "high")
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_ts_classifier.py -k "python_category or javascript_category or typescript_category or tsx_category" -q`
Expected: FAIL（KeyError: `_LANGS["python"]` 等）。

- [ ] **Step 3: ts_classifier に grammar と言語別 category を追加**

import 群（旧 6-8 行）を以下へ:
```python
import tree_sitter_c
import tree_sitter_java
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser
```
`_LANGS` を以下へ拡張:
```python
_LANGS = {
    "java": Language(tree_sitter_java.language()),
    "c": Language(tree_sitter_c.language()),
    "python": Language(tree_sitter_python.language()),
    "javascript": Language(tree_sitter_javascript.language()),
    "typescript": Language(tree_sitter_typescript.language_typescript()),
    "tsx": Language(tree_sitter_typescript.language_tsx()),
}
```
既存 `_CATEGORY_BY_NODE`（java/c 共有）を `_CATEGORY_JAVAC` に**改名**し（中身不変）、言語別マップを追加:
```python
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
```
`classify_ts` 内の `cat = _CATEGORY_BY_NODE.get(node.type)` を `cat = _CATEGORY_BY_LANG[language].get(node.type)` へ。`classify_ts` の `src = mask_exec_sql(source) if language == "proc" else source` は不変。

- [ ] **Step 4: classify.py のルーティング追加**

`classify.py:25` を以下へ:
```python
    if language in ("java", "c", "proc", "python", "javascript", "typescript", "tsx"):
        return classify_ts(language, file_text, lineno)
```

- [ ] **Step 5: PASS＋java/c 回帰なし**

Run: `python -m pytest tests/unit/test_ts_classifier.py tests/unit/test_classify.py tests/golden -q`
Expected: 全 PASS（java/c golden byte 不変＝Inv-A）。

- [ ] **Step 6: Commit**

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py src/grep_analyzer/classify.py tests/unit/test_ts_classifier.py
git commit -m "feat(classify): TS/TSX/JS/Python の AST category 判定（言語別 _CATEGORY_BY_LANG）"
```

---

## Task 7: ASTChaser プロトコル

**Files:**
- Modify: `src/grep_analyzer/classifiers/base.py`

- [ ] **Step 1: base.py に Protocol を追加**

`base.py` 末尾に追記:
```python
class ASTChaser(Protocol):
    """AST 言語 chaser の抽出 IF（spec §6.6）。

    parse は呼出側（chase.py / worker）。本 IF は parse 済 root から
    束縛名のみ（name:/left: フィールド）を field-directed に抽出する。
    `language` は ts/tsx の grammar 変種・束縛規則の選択に使う。
    """

    extract_tree: Callable[[str, object, int], ChaseSymbols]
    """(language, root, lineno) → ChaseSymbols。root は parse 済 root_node。"""
```

- [ ] **Step 2: import 健全性を確認**

Run: `python -c "from grep_analyzer.classifiers.base import ASTChaser; print('ok')"`
Expected: `ok`。

- [ ] **Step 3: Commit**

```bash
git add src/grep_analyzer/classifiers/base.py
git commit -m "feat(base): ASTChaser Protocol（extract_tree(language, root, lineno)）"
```

---

## Task 8: python_chaser（AST field-directed）

**Files:**
- Create: `src/grep_analyzer/classifiers/python_chaser.py`
- Test: `tests/unit/test_ast_chaser.py`

- [ ] **Step 1: 失敗テストを書く**

`tests/unit/test_ast_chaser.py`（新規）:
```python
"""AST chaser（python/javascript/typescript）field-directed 抽出（spec §6.5）。"""
from grep_analyzer.classifiers.ts_classifier import parse_tree
from grep_analyzer.model import ChaseSymbols


def _py(text, lineno):
    from grep_analyzer.classifiers.python_chaser import extract_tree
    return extract_tree("python", parse_tree("python", text), lineno)


def test_python_const_var_allcaps():
    cs = _py("XX = 1\ny = f()\n", 1)       # ALL_CAPS は2字以上（単字 X は var＝spec §6.4）
    assert cs.constants == ("XX",) and cs.vars == ()
    cs2 = _py("XX = 1\ny = f()\n", 2)
    assert cs2.vars == ("y",) and cs2.constants == ()


def test_python_tuple_unpack():
    cs = _py("a, b = f()\n", 1)
    assert cs.vars == ("a", "b")


def test_python_multiline_assign():
    cs = _py("MULTI = (\n  1 + 2\n)\n", 2)  # hit on continuation line
    assert cs.constants == ("MULTI",)


def test_python_attribute_subscript_lhs_は抽出しない():
    assert _py("self.x = 1\n", 1).vars == ()
    assert _py("d[k] = 1\n", 1).vars == ()


def test_python_property_getter_setter():
    src = ("class C:\n    @property\n    def val(self):\n        return self._v\n"
           "    @val.setter\n    def val(self, v):\n        self._v = v\n")
    assert _py(src, 3).getters == ("val",)   # decorated_definition spans 2-4
    assert _py(src, 6).setters == ("val",)


def test_python_staticmethod_は無視():
    src = "class C:\n    @staticmethod\n    def m():\n        return 1\n"
    cs = _py(src, 3)
    assert cs.getters == () and cs.setters == ()
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_ast_chaser.py -k python -q`
Expected: FAIL（python_chaser 未作成）。

- [ ] **Step 3: python_chaser.py を実装**

```python
"""Python AST chaser（field-directed・spec §6.3/§6.5）。

ASTChaser: extract_tree(language, root, lineno) → ChaseSymbols。parse は呼出側。
束縛導入ノードへ climb し、name:/left: フィールドのみから名を抽出（RHS/型は読まない）。
"""
import re

from grep_analyzer.classifiers.ts_classifier import node_at_line
from grep_analyzer.model import ChaseSymbols

_BINDING = {"assignment", "augmented_assignment", "decorated_definition"}
_CONST_RE = re.compile(r"^[A-Z_][A-Z0-9_]+$")


def _names_from_target(node, consts, vars_):
    t = node.type
    if t == "identifier":
        name = node.text.decode("utf-8", "replace")
        (consts if _CONST_RE.match(name) else vars_).append(name)
    elif t in ("pattern_list", "tuple_pattern", "list_pattern"):
        for ch in node.children:
            if ch.is_named:
                _names_from_target(ch, consts, vars_)
    elif t == "list_splat_pattern":
        for ch in node.children:
            if ch.type == "identifier":
                vars_.append(ch.text.decode("utf-8", "replace"))
    # attribute(self.x) / subscript(d[k]) は束縛でない＝抽出せず（spec §8）


def _from_assignment(node, consts, vars_):
    left = node.child_by_field_name("left")
    if left is not None:
        _names_from_target(left, consts, vars_)
    right = node.child_by_field_name("right")
    while right is not None and right.type == "assignment":  # chained a = b = 1
        l2 = right.child_by_field_name("left")
        if l2 is not None:
            _names_from_target(l2, consts, vars_)
        right = right.child_by_field_name("right")


def _from_decorated(node, getters, setters):
    defn = node.child_by_field_name("definition")
    if defn is None or defn.type != "function_definition":
        return
    name_node = defn.child_by_field_name("name")
    if name_node is None:
        return
    name = name_node.text.decode("utf-8", "replace")
    for ch in node.children:
        if ch.type != "decorator":
            continue
        expr = next((c for c in ch.children if c.is_named), None)
        if expr is None:
            continue
        if expr.type == "identifier" and expr.text.decode("utf-8", "replace") == "property":
            getters.append(name)
            return
        if expr.type == "attribute":
            attr = expr.child_by_field_name("attribute")
            if attr is not None and attr.text.decode("utf-8", "replace") == "setter":
                setters.append(name)
                return


def extract_tree(language, root, lineno):
    node = node_at_line(root, lineno)
    while node is not None and node.type not in _BINDING:
        node = node.parent
    if node is None:
        return ChaseSymbols()
    consts, vars_, getters, setters = [], [], [], []
    if node.type == "decorated_definition":
        _from_decorated(node, getters, setters)
    else:
        _from_assignment(node, consts, vars_)
    return ChaseSymbols(tuple(consts), tuple(vars_), tuple(getters), tuple(setters))
```

- [ ] **Step 4: PASS**

Run: `python -m pytest tests/unit/test_ast_chaser.py -k python -q`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/classifiers/python_chaser.py tests/unit/test_ast_chaser.py
git commit -m "feat(chaser): python_chaser（AST field-directed・@property getter/setter 対応）"
```

---

## Task 9: javascript_chaser（AST field-directed）

**Files:**
- Create: `src/grep_analyzer/classifiers/javascript_chaser.py`
- Test: `tests/unit/test_ast_chaser.py`

- [ ] **Step 1: 失敗テストを追記**

`tests/unit/test_ast_chaser.py` に追記:
```python
def _js(text, lineno):
    from grep_analyzer.classifiers.javascript_chaser import extract_tree
    return extract_tree("javascript", parse_tree("javascript", text), lineno)


def test_js_const_let_var():
    assert _js("const X = 1;\n", 1).constants == ("X",)
    assert _js("let y = 1;\n", 1).vars == ("y",)
    assert _js("var z = 1;\n", 1).vars == ("z",)
    assert _js("a = b;\n", 1).vars == ("a",)


def test_js_destructure():
    assert _js("const {p, q} = o;\n", 1).constants == ("p", "q")
    assert _js("const {a: x} = o;\n", 1).constants == ("x",)   # key a は除外
    assert _js("const {b = 5} = o;\n", 1).constants == ("b",)  # default 値除外
    assert _js("const [m, ...rest] = o;\n", 1).constants == ("m", "rest")


def test_js_field_getter_setter():
    src = ("class C {\n  field = 1;\n  get val() { return 1; }\n"
           "  set val(v) {}\n  method() {}\n}\n")
    assert _js(src, 2).vars == ("field",)
    assert _js(src, 3).getters == ("val",)
    assert _js(src, 4).setters == ("val",)
    assert _js(src, 5).vars == () and _js(src, 5).getters == ()  # 通常メソッドは無視


def test_js_multiline_const():
    assert _js("const MULTI =\n  1 + 2;\n", 2).constants == ("MULTI",)
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_ast_chaser.py -k "js_" -q`
Expected: FAIL（javascript_chaser 未作成）。

- [ ] **Step 3: javascript_chaser.py を実装**

```python
"""JavaScript AST chaser（field-directed・spec §6.5）。

`handle_binding` / `_BINDING` は typescript_chaser から再利用される（DRY）。
"""
from grep_analyzer.classifiers.ts_classifier import node_at_line
from grep_analyzer.model import ChaseSymbols

_BINDING = {"lexical_declaration", "variable_declaration",
            "assignment_expression", "augmented_assignment_expression",
            "field_definition", "method_definition"}


def _names_from_pattern(node, out):
    t = node.type
    if t in ("identifier", "shorthand_property_identifier_pattern"):
        out.append(node.text.decode("utf-8", "replace"))
    elif t == "object_pattern":
        for ch in node.children:
            if ch.type == "shorthand_property_identifier_pattern":
                out.append(ch.text.decode("utf-8", "replace"))
            elif ch.type == "pair_pattern":
                val = ch.child_by_field_name("value")
                if val is not None:
                    _names_from_pattern(val, out)        # key: は読まない
            elif ch.type == "object_assignment_pattern":
                left = ch.child_by_field_name("left")
                if left is not None:
                    _names_from_pattern(left, out)        # default 値 right: は読まない
            elif ch.type == "rest_pattern":
                for c in ch.children:
                    if c.type == "identifier":
                        out.append(c.text.decode("utf-8", "replace"))
    elif t == "array_pattern":
        for ch in node.children:
            if ch.type == "identifier":
                out.append(ch.text.decode("utf-8", "replace"))
            elif ch.type in ("object_pattern", "array_pattern"):
                _names_from_pattern(ch, out)
            elif ch.type == "assignment_pattern":
                left = ch.child_by_field_name("left")
                if left is not None:
                    _names_from_pattern(left, out)
            elif ch.type == "rest_pattern":
                for c in ch.children:
                    if c.type == "identifier":
                        out.append(c.text.decode("utf-8", "replace"))


def _declarators(decl, is_const, consts, vars_):
    target = consts if is_const else vars_
    for ch in decl.children:
        if ch.type != "variable_declarator":
            continue
        name = ch.child_by_field_name("name")
        if name is not None:
            _names_from_pattern(name, target)


def handle_binding(node, consts, vars_, getters, setters):
    t = node.type
    if t == "lexical_declaration":
        is_const = any(not c.is_named and c.text.decode("utf-8", "replace") == "const"
                       for c in node.children)
        _declarators(node, is_const, consts, vars_)
    elif t == "variable_declaration":
        _declarators(node, False, consts, vars_)
    elif t in ("assignment_expression", "augmented_assignment_expression"):
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            vars_.append(left.text.decode("utf-8", "replace"))
    elif t == "field_definition":
        prop = node.child_by_field_name("property")
        if prop is not None and prop.type in ("property_identifier", "private_property_identifier"):
            vars_.append(prop.text.decode("utf-8", "replace"))
    elif t == "method_definition":
        kind = None
        for c in node.children:
            if not c.is_named and c.text.decode("utf-8", "replace") in ("get", "set"):
                kind = c.text.decode("utf-8", "replace")
                break
        name = node.child_by_field_name("name")
        if kind and name is not None and name.type == "property_identifier":
            (getters if kind == "get" else setters).append(name.text.decode("utf-8", "replace"))


def extract_tree(language, root, lineno):
    node = node_at_line(root, lineno)
    while node is not None and node.type not in _BINDING:
        node = node.parent
    if node is None:
        return ChaseSymbols()
    consts, vars_, getters, setters = [], [], [], []
    handle_binding(node, consts, vars_, getters, setters)
    return ChaseSymbols(tuple(consts), tuple(vars_), tuple(getters), tuple(setters))
```

- [ ] **Step 4: PASS**

Run: `python -m pytest tests/unit/test_ast_chaser.py -k "js_" -q`
Expected: 全 PASS。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/classifiers/javascript_chaser.py tests/unit/test_ast_chaser.py
git commit -m "feat(chaser): javascript_chaser（const/let/var・分割代入・get/set・field）"
```

---

## Task 10: typescript_chaser（JS 規則＋enum/readonly・tsx 共用）

**Files:**
- Create: `src/grep_analyzer/classifiers/typescript_chaser.py`
- Test: `tests/unit/test_ast_chaser.py`

- [ ] **Step 1: 失敗テストを追記**

`tests/unit/test_ast_chaser.py` に追記:
```python
def _ts(text, lineno, language="typescript"):
    from grep_analyzer.classifiers.typescript_chaser import extract_tree
    return extract_tree(language, parse_tree(language, text), lineno)


def test_ts_readonly_const_field():
    src = "class C {\n  readonly r = 1;\n  private p = 2;\n}\n"
    assert _ts(src, 2).constants == ("r",)
    assert _ts(src, 3).vars == ("p",)


def test_ts_enum_members_constant():
    assert _ts("enum E { A, B }\n", 1).constants == ("A", "B")
    assert _ts("enum E { A = 1, B = 2 }\n", 1).constants == ("A", "B")


def test_ts_generics_型識別子を抽出しない():
    cs = _ts("const m: Map<string, number> = x;\n", 1)
    assert cs.constants == ("m",)            # Map/string/number/x は出ない


def test_ts_interface_type_は抽出しない():
    assert _ts("interface I { x: number; }\n", 1) == ChaseSymbols()
    assert _ts("type T = number;\n", 1) == ChaseSymbols()


def test_tsx_は同規則():
    assert _ts("const App = () => null;\n", 1, language="tsx").constants == ("App",)
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_ast_chaser.py -k "ts_ or tsx_" -q`
Expected: FAIL（typescript_chaser 未作成）。

- [ ] **Step 3: typescript_chaser.py を実装**

```python
"""TypeScript / TSX AST chaser（JS 規則＋enum/readonly field・spec §6.5）。

JS 規則は javascript_chaser から再利用。tsx は language 引数で grammar 変種を切替
（parse は呼出側＝本モジュールは root のみ受ける）。
"""
from grep_analyzer.classifiers.javascript_chaser import _BINDING as _JS_BINDING
from grep_analyzer.classifiers.javascript_chaser import handle_binding as _handle_js
from grep_analyzer.classifiers.ts_classifier import node_at_line
from grep_analyzer.model import ChaseSymbols

_BINDING = _JS_BINDING | {"public_field_definition", "enum_declaration"}


def _handle_ts(node, consts, vars_, getters, setters):
    t = node.type
    if t == "public_field_definition":
        is_readonly = any(not c.is_named and c.text.decode("utf-8", "replace") == "readonly"
                          for c in node.children)
        name = node.child_by_field_name("name")
        if name is not None and name.type == "property_identifier":
            (consts if is_readonly else vars_).append(name.text.decode("utf-8", "replace"))
    elif t == "enum_declaration":
        body = node.child_by_field_name("body")
        if body is not None:
            for ch in body.children:
                if ch.type == "property_identifier":
                    consts.append(ch.text.decode("utf-8", "replace"))
                elif ch.type == "enum_assignment":
                    nm = ch.child_by_field_name("name")
                    if nm is not None:
                        consts.append(nm.text.decode("utf-8", "replace"))
    else:
        _handle_js(node, consts, vars_, getters, setters)


def extract_tree(language, root, lineno):
    node = node_at_line(root, lineno)
    while node is not None and node.type not in _BINDING:
        node = node.parent
    if node is None:
        return ChaseSymbols()
    consts, vars_, getters, setters = [], [], [], []
    _handle_ts(node, consts, vars_, getters, setters)
    return ChaseSymbols(tuple(consts), tuple(vars_), tuple(getters), tuple(setters))
```

- [ ] **Step 4: PASS**

Run: `python -m pytest tests/unit/test_ast_chaser.py -q`
Expected: 全 PASS（python/js/ts/tsx 全て）。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/classifiers/typescript_chaser.py tests/unit/test_ast_chaser.py
git commit -m "feat(chaser): typescript_chaser（enum/readonly・tsx 共用・型識別子非抽出）"
```

---

## Task 11: _AST_CHASERS レジストリ＋chase.py ラッパ

**Files:**
- Modify: `src/grep_analyzer/classifiers/__init__.py`
- Modify: `src/grep_analyzer/chase.py`
- Test: `tests/unit/test_chase.py`

- [ ] **Step 1: 失敗テストを追記**

`tests/unit/test_chase.py` 末尾に追記:
```python
def test_extract_chase_symbols_tree_python():
    from grep_analyzer.chase import extract_chase_symbols_tree
    cs = extract_chase_symbols_tree("python", "X = 1\n", 1)
    assert cs.constants == ("X",)


def test_extract_chase_symbols_tree_非AST言語は空():
    from grep_analyzer.chase import extract_chase_symbols_tree
    cs = extract_chase_symbols_tree("java", "int x = 1;\n", 1)
    assert cs.constants == () and cs.vars == ()


def test_extract_chase_symbols_from_root_js():
    from grep_analyzer.chase import extract_chase_symbols_from_root
    from grep_analyzer.classifiers.ts_classifier import parse_tree
    cs = extract_chase_symbols_from_root("javascript", parse_tree("javascript", "const A = 1;\n"), 1)
    assert cs.constants == ("A",)
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_chase.py -k "tree or from_root" -q`
Expected: FAIL（関数未定義）。

- [ ] **Step 3: classifiers/__init__.py に _AST_CHASERS を追加**

import 群へ追加し、レジストリを定義:
```python
from grep_analyzer.classifiers import (
    c_chaser,
    groovy_chaser,
    java_chaser,
    javascript_chaser,
    perl_chaser,
    python_chaser,
    shell_chaser,
    sql_chaser,
    typescript_chaser,
)
from grep_analyzer.classifiers.base import ASTChaser, Chaser

# 行ベース chaser（既存）
_CHASERS: dict[str, Chaser] = {
    "java": java_chaser, "c": c_chaser, "proc": c_chaser, "shell": shell_chaser,
    "sql": sql_chaser, "perl": perl_chaser, "groovy": groovy_chaser,
}
# AST ベース chaser（新規・行版 _CHASERS には載せない）
_AST_CHASERS: dict[str, ASTChaser] = {
    "python": python_chaser,
    "javascript": javascript_chaser,
    "typescript": typescript_chaser,
    "tsx": typescript_chaser,
}

__all__ = ["Chaser", "ASTChaser"]
```

- [ ] **Step 4: chase.py にラッパを追加**

import 群へ追加:
```python
from grep_analyzer.classifiers import _AST_CHASERS, _CHASERS
from grep_analyzer.classifiers.ts_classifier import parse_tree
```
ファイル末尾に追加:
```python
def extract_chase_symbols_from_root(language: str, root, lineno: int) -> ChaseSymbols:
    """parse 済 root から AST chaser で抽出（worker 用・file 単位1パース共有）。"""
    chaser = _AST_CHASERS.get(language)
    return ChaseSymbols() if chaser is None else chaser.extract_tree(language, root, lineno)


def extract_chase_symbols_tree(language: str, text: str, lineno: int) -> ChaseSymbols:
    """text を parse して AST chaser で抽出（seed/absorb 用）。非 AST 言語は空。"""
    if language not in _AST_CHASERS:
        return ChaseSymbols()
    return extract_chase_symbols_from_root(language, parse_tree(language, text), lineno)
```

- [ ] **Step 5: PASS＋import 健全性＋回帰なし**

Run: `python -m pytest tests/unit/test_chase.py -q && python -c "import grep_analyzer.pipeline; print('import ok')"`
Expected: 全 PASS ＋ `import ok`（循環 import なし）。

- [ ] **Step 6: Commit**

```bash
git add src/grep_analyzer/classifiers/__init__.py src/grep_analyzer/chase.py tests/unit/test_chase.py
git commit -m "feat(chase): _AST_CHASERS レジストリ＋extract_chase_symbols_tree/from_root"
```

---

## Task 12: fixedpoint 抽出/投入分離（決定的コア・Inv-A 厳守）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（`kinds_of` シグネチャ・`_scan_file` worker）
- Modify: `src/grep_analyzer/fixedpoint/_ingest.py`（`ingest_one` 契約・`absorb_results` 4-tuple）
- Modify: `src/grep_analyzer/fixedpoint/_seed.py`（抽出を呼出側へ）
- Test: `tests/unit/test_fixedpoint.py` / `tests/unit/test_ingest.py`

- [ ] **Step 1: 失敗テスト（AST 多ホップ＋arity）を書く**

`tests/unit/test_fixedpoint.py` 末尾に追記:
```python
def test_kinds_of_はChaseSymbolsを受けconstant優先():
    from grep_analyzer.fixedpoint._scan import kinds_of
    from grep_analyzer.model import ChaseSymbols
    cs = ChaseSymbols(constants=("C",), vars=("v",), getters=("g",), setters=("s",))
    k = kinds_of(cs)
    assert k == {"C": "constant", "v": "var", "g": "getter", "s": "setter"}


def test_found_tupleは4要素（chase_symbols同梱）():
    from grep_analyzer.fixedpoint._scan import _scan_file
    import pathlib
    # python ファイルを 1 つ走査し found が4要素 tuple であることを表明
    src = pathlib.Path(__import__("tempfile").mkdtemp()) / "m.py"
    src.write_text("SEED = 1\nDER = SEED + 1\n", "utf-8")
    relpath, enc, replaced, language, dialect, found = _scan_file(
        (str(src.name), str(src), ["SEED"], {".py": "python"}, []))
    assert language == "python"
    assert all(len(t) == 4 for t in found)
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_fixedpoint.py -k "kinds_of or found_tuple" -q`
Expected: FAIL（`kinds_of` が3引数・found が3要素）。

- [ ] **Step 3: `_scan.py` を更新（kinds_of シグネチャ＋worker AST 抽出）**

`_scan.py` の import を整理（既存 `from grep_analyzer.chase import extract_chase_symbols` は本ファイルでは未使用化するため **`extract_chase_symbols_from_root` へ差し替え**。`extract_chase_symbols` は `_ingest.py` 側でのみ使う）:
```python
from grep_analyzer.chase import extract_chase_symbols_from_root   # ← 旧 extract_chase_symbols を置換
from grep_analyzer.classifiers import _AST_CHASERS
from grep_analyzer.classifiers.ts_classifier import parse_tree
from grep_analyzer.model import ChaseSymbols
```
`kinds_of` を以下へ置換（行→ChaseSymbols 引数・抽出はしない）:
```python
def kinds_of(chase_symbols: ChaseSymbols) -> dict[str, str]:
    """ChaseSymbols の各シンボル→種別。同名は constant 優先（最後に書く）。"""
    out: dict[str, str] = {}
    for kind, names in (("setter", chase_symbols.setters), ("getter", chase_symbols.getters),
                        ("var", chase_symbols.vars), ("constant", chase_symbols.constants)):
        for n in names:
            out[n] = kind
    return out
```
`_scan_file` の found 構築ループを以下へ置換:
```python
    found = []
    if automaton_obj is not None:
        root = None
        if language in _AST_CHASERS:
            try:
                root = parse_tree(language, text)   # parse 失敗は AST 抽出を諦め row 動作（堅牢化）
            except Exception:
                root = None
        for i, line in enumerate(text.split("\n"), start=1):
            symbols = list(automaton.scan_line(automaton_obj, line))
            if not symbols:
                continue
            cs = extract_chase_symbols_from_root(language, root, i) if root is not None else None
            for symbol in symbols:
                found.append((symbol, i, line, cs))
    return relpath, enc, replaced, language, dialect, found
```
（旧 `extract_chase_symbols` の import が未使用なら残置で害なし。`scan_hop` のソートキー `(t[1], t[0])` は4要素でも不変。）

- [ ] **Step 4: `_ingest.py` を更新（ingest_one 契約・absorb 4-tuple）**

`ingest_one` のシグネチャと冒頭を以下へ（抽出2行を削除し、`language` 保持・`chase_symbols`/`kinds` を引数化）:
```python
def ingest_one(state: ChaseState, parent: Occurrence, language: str,
               chase_symbols, kinds: dict[str, str], hop: int, is_seed: bool = False):
    """事前抽出済 (chase_symbols, kinds) を ChaseState に投入する（spec §6.1）。

    抽出は呼出側（seed/absorb/worker）の責務。language は partition→admit の
    keyword 篩（LANG_KEYWORDS.get(language)）に必須＝Inv-A 保持のため保持する。
    """
    diag = state.diagnostics
    opts = state.options
    if hop > opts.max_depth:
        if parent not in state.maxdepth_logged:
            diag.add("prov_max_depth", f"{parent.symbol}@{parent.relpath}:"
                     f"{parent.lineno} (hop {hop} > --max-depth {opts.max_depth})")
            state.maxdepth_logged.add(parent)
        return
    part = partition(chase_symbols, language, state.policy)
```
（`part = partition(...)` 以降の本体＝rejected/chase/terminal ループは現行のまま不変。旧 line 35-36 の `extract_chase_symbols`/`kinds_of` 呼出は削除。）

`absorb_results` の found ループを4-tuple unpack＋呼出側抽出へ:
```python
        for symbol, lineno, line, chase_symbols in found:
            if symbol not in scan_chase and symbol not in scan_term:
                continue
            child = Occurrence(symbol, relpath, lineno)
            for parent in state.introducers.get(symbol, []):
                if parent != child:
                    state.edge_store.add(parent, child)
            if symbol in scan_term:
                if symbol not in state.no_expand_logged:
                    diag.add("getter_setter_no_expand", symbol)
                    state.no_expand_logged.add(symbol)
                continue
            cs = chase_symbols if chase_symbols is not None \
                else extract_chase_symbols(language, dialect, line)
            ingest_one(state, child, language, cs, kinds_of(cs), hop + 1)
```
（`_ingest.py` は既に `extract_chase_symbols`(chase) と `kinds_of`(_scan) を import 済み＝そのまま使用。）

- [ ] **Step 5: `_seed.py` を更新（抽出を呼出側へ）**

import 追加:
```python
from grep_analyzer.chase import extract_chase_symbols, extract_chase_symbols_tree
from grep_analyzer.classifiers import _AST_CHASERS
from grep_analyzer.fixedpoint._scan import file_meta, kinds_of
from grep_analyzer.model import ChaseSymbols
```
seed ループ（`for s in seed_hits:` 内）を以下へ:
```python
        occ = Occurrence(s.keyword, s.file, s.lineno)
        state.graph.add_seed(occ)
        sp = source_root / s.file
        if sp.is_file():
            text, _, _, lang, dialect = file_meta(
                s.file, sp.read_bytes(), opts.lang_map,
                fallback_chain=list(opts.encoding_fallback))
            if lang in _AST_CHASERS:
                cs = extract_chase_symbols_tree(lang, text, s.lineno)
            else:
                _ls = text.split("\n")
                seed_line = _ls[s.lineno - 1] if 0 <= s.lineno - 1 < len(_ls) else ""
                cs = extract_chase_symbols(lang, dialect, seed_line)
        else:
            lang, dialect = s.language, "bourne"
            cs = ChaseSymbols()
        ingest_one(state, occ, lang, cs, kinds_of(cs), hop=1, is_seed=True)
```

- [ ] **Step 6: 新テスト＋既存 fixedpoint/ingest 回帰**

Run: `python -m pytest tests/unit/test_fixedpoint.py tests/unit/test_ingest.py -q`
Expected: 全 PASS。

- [ ] **Step 7: Inv-A＝既存 golden が byte 不変（行言語の挙動保存）**

Run: `python -m pytest tests/golden tests/integration -q`
Expected: 全 PASS（java/c/sql/shell/perl/groovy の golden・結合 byte 不変）。

- [ ] **Step 8: Commit**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py src/grep_analyzer/fixedpoint/_ingest.py src/grep_analyzer/fixedpoint/_seed.py tests/unit/test_fixedpoint.py
git commit -m "refactor(fixedpoint): 抽出/投入分離・kinds_of(cs)・worker AST 抽出・found 4-tuple（Inv-A 保持）"
```

---

## Task 13: snippet（言語別粒度＋build_snippet 分岐）

**Files:**
- Modify: `src/grep_analyzer/snippet/_ts.py`
- Modify: `src/grep_analyzer/snippet/__init__.py:43-50`
- Test: `tests/unit/test_snippet.py`

- [ ] **Step 1: 失敗テストを追記**

`tests/unit/test_snippet.py` に追記:
```python
def test_python_複数行代入スパン():
    from grep_analyzer.snippet import ts_span
    assert ts_span("python", "X = (\n  1 + 2\n)\n", 1) == (0, 2)


def test_python_単純文1行():
    from grep_analyzer.snippet import ts_span
    assert ts_span("python", "a = 1\nb = 2\n", 1) == (0, 0)


def test_js_複数行宣言スパン():
    from grep_analyzer.snippet import ts_span
    assert ts_span("javascript", "const X =\n  1 + 2;\n", 1) == (0, 1)


def test_build_snippet_python():
    from grep_analyzer.snippet import build_snippet
    s = build_snippet("python", "bourne", "X = (\n  1 + 2\n)\n", 1)
    assert "X = (" in s
```

- [ ] **Step 2: 実行して失敗を確認**

Run: `python -m pytest tests/unit/test_snippet.py -k "python_ or js_複数行 or build_snippet_python" -q`
Expected: FAIL（新言語が ts_span/build_snippet 未対応）。

- [ ] **Step 3: `_ts.py` に言語別集合を追加し ts_span を一般化**

既存 `_GRAN_JAVA`/`_GRAN_C`/`_PAREN_ONLY`/`_STMT`/`_BLOCK` の後に追加:
```python
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
```
`ts_span` を以下へ置換（java/c/proc 経路は現行と完全同一・新言語は別経路）:
```python
def ts_span(language: str, file_text: str, lineno: int):
    """選択範囲 [s,e]（0始まり物理行）。取れなければ None（→fallback）。spec §9。"""
    if language in ("java", "c", "proc"):
        lang = "c" if language in ("c", "proc") else "java"
        src = mask_exec_sql(file_text) if language == "proc" else file_text
        gran = _GRAN_JAVA if lang == "java" else _GRAN_C
        stmt, block, paren, parse_lang = _STMT, _BLOCK, _PAREN_ONLY, lang
    elif language in _SETS_BY_LANG:
        gran, stmt, block, paren = _SETS_BY_LANG[language]
        src, parse_lang = file_text, language
    else:
        return None
    try:
        root = parse_tree(parse_lang, src)
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
```

- [ ] **Step 4: `build_snippet` に新言語分岐を追加**

`snippet/__init__.py:43-50` の分岐へ:
```python
    if language in ("java", "c", "python", "javascript", "typescript", "tsx"):
        span = ts_span(language, file_text, lineno)
    elif language == "proc":
        span = proc_exec_span(file_text, lineno)
        if span is None:
            span = ts_span("proc", file_text, lineno)
    elif language in ("sql", "shell", "perl", "groovy"):
        span = heuristic_span(lines, hit, language)
```
（新言語は ts_span 経路＝heuristic は通らない。`build_snippet` は pipeline=direct と `_finalize`=indirect の両方から呼ばれ、両経路で AST スパンになる＝spec §7。）

- [ ] **Step 5: PASS＋java/c 回帰なし**

Run: `python -m pytest tests/unit/test_snippet.py tests/golden -q`
Expected: 全 PASS（java/c/proc snippet byte 不変）。

- [ ] **Step 6: Commit**

```bash
git add src/grep_analyzer/snippet/_ts.py src/grep_analyzer/snippet/__init__.py tests/unit/test_snippet.py
git commit -m "feat(snippet): TS/TSX/JS/Python の AST スパン（ts_span 一般化・build_snippet 分岐）"
```

---

## Task 14: golden ケース（direct＋indirect 多ホップ・再生成）

**Files:**
- Create: `tests/golden/cases/py_chain/{input,src,expected}/*`
- Create: `tests/golden/cases/js_kinds/{input,src,expected}/*`
- Create: `tests/golden/cases/ts_enum_readonly/{input,src,expected}/*`
- Create: `tests/golden/cases/tsx_chain/{input,src,expected}/*`

> 補足: golden は純回帰（自動再生成なし）。各ケースは src/input を作成 → `python -m grep_analyzer` で出力生成 → 出力を expected へコピー → 出力中の絶対 source-root を `{SOURCE_ROOT}` へ置換 → 期待挙動を目視確認 → コミット。再生成手順は各ケースで同一なので Step に明記する。

- [ ] **Step 1: py_chain（多ホップ＝C1 回帰）の src/input 作成**

```bash
mkdir -p tests/golden/cases/py_chain/{input,src,expected}
printf 'SEED = compute()\nDERIVED = SEED + 1\ndef use():\n    return DERIVED\n' \
  > tests/golden/cases/py_chain/src/m.py
printf 'm.py:1:SEED = compute()\n' > tests/golden/cases/py_chain/input/SEED.grep
```
期待挙動: `SEED`(direct 代入) → `DERIVED`(indirect:constant・via SEED・ALL_CAPS) の2ホップ連鎖が出る（C1 の連鎖途絶・kind 化けが無いことを固定）。

- [ ] **Step 2: js_kinds（const/let/get/set）の src/input 作成**

```bash
mkdir -p tests/golden/cases/js_kinds/{input,src,expected}
printf 'const SEED = init();\nconst MIRROR = SEED;\nlet alias = SEED;\nclass C { get cached() { return SEED; } }\n' \
  > tests/golden/cases/js_kinds/src/a.js
printf 'a.js:1:const SEED = init();\n' > tests/golden/cases/js_kinds/input/SEED.grep
```
期待挙動: `SEED`(direct 宣言) → `MIRROR`(indirect:constant)・`alias`(indirect:var)・`cached`(indirect:getter・terminal 非拡張・confidence=low)。getter 名は seed `SEED` と別名にする（同名だと自己参照スキップで terminal が記録されない）。

- [ ] **Step 3: ts_enum_readonly の src/input 作成**

```bash
mkdir -p tests/golden/cases/ts_enum_readonly/{input,src,expected}
printf 'enum Color { RED, GREEN }\nclass C {\n  readonly base = RED;\n}\n' \
  > tests/golden/cases/ts_enum_readonly/src/t.ts
printf 't.ts:1:enum Color { RED, GREEN }\n' > tests/golden/cases/ts_enum_readonly/input/RED.grep
```
期待挙動: `RED`(direct 宣言・enum) → `base`(indirect:constant・readonly field・via RED)。

- [ ] **Step 4: tsx_chain の src/input 作成**

```bash
mkdir -p tests/golden/cases/tsx_chain/{input,src,expected}
printf 'const TITLE = load();\nconst App = () => <div>{TITLE}</div>;\n' > tests/golden/cases/tsx_chain/src/a.tsx
printf 'a.tsx:1:const TITLE = load();\n' > tests/golden/cases/tsx_chain/input/TITLE.grep
```
期待挙動: `TITLE`(direct 宣言・tsx parse) → `App`(indirect:constant・via TITLE。JSX 本体の TITLE 参照箇所から lexical_declaration へ climb して App を抽出)。spec §10「TSX: direct＋1チェーン」を満たす。

- [ ] **Step 5: 4ケースの expected を再生成**

```bash
for c in py_chain js_kinds ts_enum_readonly tsx_chain; do
  d=tests/golden/cases/$c
  rm -rf /tmp/gen_$c && python -m grep_analyzer \
    --input "$d/input" --output /tmp/gen_$c --source-root "$d/src"
  abs=$(python -c "import pathlib;print(pathlib.Path('$d/src').resolve())")
  for tsv in /tmp/gen_$c/*.tsv; do
    sed "s#${abs}/#{SOURCE_ROOT}/#g" "$tsv" > "$d/expected/$(basename "$tsv")"
  done
done
```

- [ ] **Step 6: 期待挙動を目視確認**

各 `tests/golden/cases/*/expected/*.tsv` を開き、Step1-4 に記した ref_kind（direct / indirect:constant / indirect:var / indirect:getter）と chain・via_symbol が意図どおりかを確認する。特に **py_chain で `DERIVED` が `indirect:constant` として SEED 経由で出ている**こと（C1 回帰の本丸）。意図と違えば原因を調査（chaser/fixedpoint の不具合）→修正してから再生成。

- [ ] **Step 7: golden 全件 PASS（新ケース込み）**

Run: `python -m pytest tests/golden -q`
Expected: 全 PASS（新4ケース＋既存）。

- [ ] **Step 8: Commit**

```bash
git add tests/golden/cases/py_chain tests/golden/cases/js_kinds tests/golden/cases/ts_enum_readonly tests/golden/cases/tsx_chain
git commit -m "test(golden): TS/TSX/JS/Python の direct＋indirect 多ホップ回帰ケース"
```

---

## Task 15: 統合・オフライン smoke 更新・最終確認・master 反映

**Files:**
- Modify: `tests/integration/test_v2_langs.py`
- Modify: `tests/unit/test_requirements_lock_offline.py:21-22`
- Modify: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（§2.3/§14/§15/§8.4）

- [ ] **Step 1: 統合テストを追記（pipeline end-to-end・4言語混在）**

`tests/integration/test_v2_langs.py` 末尾に追記:
```python
def test_tree_sitter_langs_pipeline(tmp_path):
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "m.py").write_text("SEED = init()\nDER = SEED + 1\n", "utf-8")
    (src / "a.ts").write_text("enum E { SEED }\nconst x = SEED;\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "SEED.grep").write_text("m.py:1:SEED = init()\na.ts:1:enum E { SEED }\n", "utf-8")
    out = tmp_path / "out"
    assert run(inp, out, src, _default_opts()) == 0
    text = (out / "SEED.tsv").read_text("utf-8-sig")
    assert "python" in text and "typescript" in text
    assert "indirect:constant" in text  # DER (py) または x(ts) の少なくとも一方
```

- [ ] **Step 2: 実行**

Run: `python -m pytest tests/integration/test_v2_langs.py -q`
Expected: 全 PASS。

- [ ] **Step 3: オフライン import smoke に新 grammar を追加**

`tests/unit/test_requirements_lock_offline.py:21-22` の import 行を以下へ:
```python
        [str(py), "-c", "import tree_sitter,tree_sitter_java,tree_sitter_c,"
         "tree_sitter_python,tree_sitter_javascript,tree_sitter_typescript,"
         "ahocorasick,chardet,pytest"], capture_output=True, text=True)
```

- [ ] **Step 4: 全テスト緑（最終回帰確認）**

Run: `python -m pytest -q`
Expected: 全 PASS（Task 0 比で +新規テスト・回帰ゼロ）。skipped 数は Task 0 と同等。

- [ ] **Step 5: master spec に反映**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` を更新（差分設計書 §12 の指示どおり）:
- §2.3 / §14 / §15: track A（TS/TSX/JS/Python）完了を記録。残り track C（JSP/Angular）。
- §4.2 / §15 フェーズ0: track A G1 再ベースライン（0.23.x 採用・正本は差分 spec §2／`phase0-gate-result.md`）。
- §8.4: 差分 spec §8 の既知限界を追加。
- §14: 「既存 java/c chaser の AST 化統一」を後続候補として明記。

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_v2_langs.py tests/unit/test_requirements_lock_offline.py docs/superpowers/specs/2026-05-16-grep-analyzer-design.md
git commit -m "test(integration)+docs: tree-sitter 4言語 end-to-end・offline smoke・master 反映（track A 完了）"
```

---

## 完了条件
- 全テスト緑（Task 0 の基準数＋本計画の新規テスト、回帰ゼロ）。
- Inv-A: 既存 golden（java/c/proc/sql/shell/perl/groovy）byte 不変。
- 新4言語の direct＋indirect 多ホップ golden が緑（特に py_chain の `indirect:constant` 連鎖）。
- requirements.lock↔wheelhouse 整合（lock テスト緑）。
- master spec に track A 完了反映。
- 完了後 finishing-a-development-branch（push）。
