# java/c/jsp/proc chaser の AST 統一 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** java/c/jsp/proc の chaser を行ベース regex から tree-sitter AST（field-directed・multi-node）へ統一し、classify/chase の解析基盤を一本化する。

**Architecture:** `ts_classifier.py` に複数ノード版コレクタ `bindings_at_line` を新設。`java_chaser.py`/`c_chaser.py` を `extract_tree`（ASTChaser）実装へ置換し、`_CHASERS`→`_AST_CHASERS` へ移動（jsp は java・proc は c を `host_grammar`/`host_source` 経由で流用）。既存 golden は出力 byte 不変（実証済）、AST 改善は新規 golden で固定。dead 化する java/c の regex/mask を除去（**proc の MASK は残置**）。

**Tech Stack:** Python 3.12 / py-tree-sitter 0.23.2 / tree-sitter-java 0.23.5 / tree-sitter-c 0.23.4（既存 wheelhouse・新規 grammar wheel ゼロ）。

**設計書（正本）:** `docs/superpowers/specs/2026-05-23-chaser-ast-unification-design.md`

---

## ファイル構成

- 変更: `src/grep_analyzer/classifiers/ts_classifier.py` — `bindings_at_line`（複数ノード版）追加。
- 置換: `src/grep_analyzer/classifiers/java_chaser.py` — AST `extract_tree`。
- 置換: `src/grep_analyzer/classifiers/c_chaser.py` — AST `extract_tree`（jsp/proc も流用）。
- 変更: `src/grep_analyzer/classifiers/__init__.py` — registry 移動。
- 変更: `src/grep_analyzer/patterns/literal_masking.py` — `MASK_SPECS` から java/c 除去（**proc 残置**）。
- 変更: `src/grep_analyzer/patterns/symbol_extraction.py` — `JAVA_*_RE`/`C_*_RE` 除去。
- 変更: `tests/unit/test_ast_chaser.py` — java/c/jsp/proc の AST テスト追加。
- 変更: `tests/unit/test_chase.py` — 行ベース java/c/jsp/proc テスト除去・mask テスト/非AST テスト修正。
- 変更: `tests/unit/test_ts_classifier.py` — `bindings_at_line` テスト追加。
- 追加: `tests/golden/cases/{java_multiline_chase,proc_exec_sql_chase,c_compound_assign}/`。
- 変更: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` — §96/§390/§389/§208 更新。

---

### Task 1: `bindings_at_line`（複数ノード版コレクタ）

**Files:**
- Modify: `src/grep_analyzer/classifiers/ts_classifier.py`（`binding_at_line` の直後 L123 付近に追加）
- Test: `tests/unit/test_ts_classifier.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_ts_classifier.py` に追加（既存の import に `bindings_at_line` を足す）:

```python
def test_bindings_at_line_行交差全件を決定的順で返す():
    import tree_sitter_java
    from tree_sitter import Language, Parser
    from grep_analyzer.classifiers.ts_classifier import bindings_at_line
    src = "class S { int vv = a.getName(); }\n"
    root = Parser(Language(tree_sitter_java.language())).parse(src.encode()).root_node
    types = {"field_declaration", "method_invocation"}
    got = [n.type for n in bindings_at_line(root, 1, types)]
    # field_declaration（外側・start_byte 小）→ method_invocation（内側）の順
    assert got == ["field_declaration", "method_invocation"]


def test_bindings_at_line_該当なしは空list():
    import tree_sitter_java
    from tree_sitter import Language, Parser
    from grep_analyzer.classifiers.ts_classifier import bindings_at_line
    root = Parser(Language(tree_sitter_java.language())).parse(b"class S {}\n").root_node
    assert bindings_at_line(root, 1, {"method_invocation"}) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_ts_classifier.py -k bindings_at_line -q`
Expected: FAIL（`ImportError: cannot import name 'bindings_at_line'`）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/classifiers/ts_classifier.py` の `binding_at_line` 関数定義の直後に追加:

```python
def bindings_at_line(root, lineno: int, binding_types):
    """対象行に交差し binding_types に属する全ノードを決定的順で返す（list）。

    binding_at_line（最小スパン単一ノード）と異なり、行内に複数の束縛・呼出が
    同居する場合（例 `int count = svc.getName(); obj.setValue(count);`）を
    regex の「行内全マッチ」と等価に拾うため複数件を返す。順序は
    (start_byte, end_byte, type) 昇順で安定（出力 tuple の決定性・spec §3.2）。
    name 行ゲート（method 系のみ name 行でヒット行に絞る）は各 chaser ハンドラの責務。
    """
    target = lineno - 1
    out = []
    cursor = [root]
    while cursor:
        node = cursor.pop()
        if node.start_point[0] <= target <= node.end_point[0]:
            if node.type in binding_types:
                out.append(node)
            cursor.extend(node.children)
    out.sort(key=lambda n: (n.start_byte, n.end_byte, n.type))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_ts_classifier.py -k bindings_at_line -q`
Expected: PASS（2 passed）

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/classifiers/ts_classifier.py tests/unit/test_ts_classifier.py
git commit -m "feat(chaser): bindings_at_line 複数ノード版コレクタ（行交差全件・決定的順・spec §3.2）"
```

---

### Task 2: Java AST chaser（`extract_tree` を追加・行ベースと共存）

**Files:**
- Modify: `src/grep_analyzer/classifiers/java_chaser.py`（既存 `extract`/`mask` は**残したまま** `extract_tree` を追加。registry 移動は Task 5）
- Test: `tests/unit/test_ast_chaser.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_ast_chaser.py` 末尾に追加:

```python
def _java(text, lineno):
    from grep_analyzer.classifiers.java_chaser import extract_tree
    return extract_tree("java", parse_tree("java", text), lineno)


def test_java_static_final_const_と_var():
    assert _java("class C { static final String K = init(); }\n", 1).constants == ("K",)
    assert _java("class C { int n = 1; }\n", 1).vars == ("n",)
    # 配列・ジェネリクスも const
    assert _java("class C { static final int[] A = x; }\n", 1).constants == ("A",)
    assert _java(
        "class C { private static final Map<String,Integer> M = init(); }\n", 1
    ).constants == ("M",)
    # final のみ（static 無し）は var
    cs = _java("class C { void f(){ final int X = 1; } }\n", 1)
    assert cs.constants == () and cs.vars == ("X",)


def test_java_文字列内の代入様字句は非抽出():
    cs = _java('class C { void f(){ String s = "url=/x"; int n = 1; } }\n', 1)
    assert cs.vars == ("s", "n") and "url" not in cs.vars


def test_java_getter_setter_var_同行multinode():
    cs = _java("class C { void f(){ int count = svc.getName(); obj.setValue(count); } }\n", 1)
    assert cs.vars == ("count",)
    assert cs.getters == ("getName",) and cs.setters == ("setValue",)


def test_java_getter_setter_本体行は過抽出しない():
    src = ("class C {\n"
           "  public String getName() {\n"     # L2 シグネチャ（name 行）
           "    return this.name;\n"           # L3 本体
           "  }\n"
           "}\n")
    assert _java(src, 2).getters == ("getName",)   # name 行は採用
    assert _java(src, 3).getters == ()             # 本体行は過抽出しない


def test_java_field_access_左辺は非抽出():
    cs = _java("class C { void f(){ this.y = 6; total += 1; } }\n", 1)
    assert "y" not in cs.vars            # field_access 左辺は非抽出
    assert cs.vars == ("total",)         # 複合代入は捕捉


def test_java_try_with_resources():
    src = "class C { void f() throws Exception { try (java.io.Reader r = open()) { } } }\n"
    assert _java(src, 1).vars == ("r",)


def test_java_jsp_経由():
    from grep_analyzer.chase import extract_chase_symbols_tree
    assert "x" in extract_chase_symbols_tree("jsp", "<% int x = TRACKED; %>\n", 1).vars
    assert extract_chase_symbols_tree("jsp", "${ TRACKED.code }\n", 1).vars == ()
```

注: `parse_tree` は本ファイル冒頭で既に import 済（`from grep_analyzer.classifiers.ts_classifier import parse_tree`）。`test_java_jsp_経由` は registry 非依存（`extract_chase_symbols_tree` は parse_tree("jsp")→host_grammar=java で動く）が、`_AST_CHASERS["jsp"]` 未登録だと空を返すため**Task 5 完了後に green**になる。Task 2 では `test_java_jsp_経由` を `@pytest.mark.skip(reason="Task5 で registry 登録後 green")` で一旦 skip し、Task 5 で skip を外す。**この skip のため test_ast_chaser.py 冒頭に `import pytest` を追加**（Task 5 で skip 解除後に未使用化するので Task 5 Step 4 で除去）。他の `_java(...)` 直接テストは Task 2 で green。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_ast_chaser.py -k java -q`
Expected: FAIL（`ImportError: cannot import name 'extract_tree' from ... java_chaser` ／ java_chaser に extract_tree 未定義）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/classifiers/java_chaser.py` の**末尾に追加**（既存 `mask`/`extract` はそのまま）。冒頭に `import re` と新 import を追加:

```python
import re

from grep_analyzer.classifiers.ts_classifier import bindings_at_line

_AST_BINDING = {"local_variable_declaration", "field_declaration", "resource",
                "assignment_expression", "method_invocation", "method_declaration"}
_GETSET_RE = re.compile(r"^(get|set)[A-Z]\w*$")


def _modifier_tokens(node) -> set[str]:
    for ch in node.children:
        if ch.type == "modifiers":
            return {c.text.decode("utf-8", "replace") for c in ch.children if not c.is_named}
    return set()


def _handle_java(node, lineno, consts, vars_, getters, setters):
    t = node.type
    if t in ("local_variable_declaration", "field_declaration"):
        mods = _modifier_tokens(node)
        target = consts if ("static" in mods and "final" in mods) else vars_
        for ch in node.children:
            if ch.type == "variable_declarator":
                nm = ch.child_by_field_name("name")
                if nm is not None and nm.type == "identifier":
                    target.append(nm.text.decode("utf-8", "replace"))
    elif t == "resource":
        nm = node.child_by_field_name("name")
        if nm is not None and nm.type == "identifier":
            vars_.append(nm.text.decode("utf-8", "replace"))
    elif t == "assignment_expression":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            vars_.append(left.text.decode("utf-8", "replace"))
    elif t in ("method_invocation", "method_declaration"):
        nm = node.child_by_field_name("name")
        if nm is not None and nm.start_point[0] == lineno - 1:    # name 行ゲート（spec §3.2）
            name = nm.text.decode("utf-8", "replace")
            if _GETSET_RE.match(name):
                (getters if name[0] == "g" else setters).append(name)


def extract_tree(language, root, lineno):
    """parse 済 root から java 束縛を field-directed・multi-node 抽出（spec §3.3）。"""
    consts, vars_, getters, setters = [], [], [], []
    for node in bindings_at_line(root, lineno, _AST_BINDING):
        _handle_java(node, lineno, consts, vars_, getters, setters)
    const_set = set(consts)
    vars_ = [v for v in vars_ if v not in const_set]
    return ChaseSymbols(tuple(consts), tuple(vars_), tuple(getters), tuple(setters))
```

（`ChaseSymbols` は既存 import 済。）

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_ast_chaser.py -k java -q`
Expected: PASS（`test_java_jsp_経由` は skip、他 java テスト green）

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/classifiers/java_chaser.py tests/unit/test_ast_chaser.py
git commit -m "feat(chaser): java AST extract_tree（multi-node・name行ゲート・resource/複合代入対応・spec §3.3）行ベースと共存"
```

---

### Task 3: C / Pro*C AST chaser（`extract_tree` を追加・行ベースと共存）

**Files:**
- Modify: `src/grep_analyzer/classifiers/c_chaser.py`（既存 `extract`/`mask` は残したまま `extract_tree` 追加）
- Test: `tests/unit/test_ast_chaser.py`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_ast_chaser.py` 末尾に追加:

```python
def _c(text, lineno, language="c"):
    from grep_analyzer.classifiers.c_chaser import extract_tree
    return extract_tree(language, parse_tree(language, text), lineno)


def test_c_define_と_const_と_var():
    assert _c("#define MAX_LEN 10\n", 1).constants == ("MAX_LEN",)
    assert _c("const int FOO = 1;\n", 1).constants == ("FOO",)
    assert _c("int n = 3;\n", 1).vars == ("n",)


def test_c_関数様マクロ_const():
    assert _c("#define SQ(x) ((x)*(x))\n", 1).constants == ("SQ",)


def test_c_ポインタ_複数宣言子_noinit():
    assert _c('char *p = "X";\n', 1).vars == ("p",)
    assert _c("int a = 1, b = 2;\n", 1).vars == ("a", "b")
    assert _c("int x;\n", 1).vars == ("x",)            # no-init も捕捉


def test_c_struct_member_field_declaration():
    src = "struct S { const int K; int *q; int a, b; };\n"
    cs = _c(src, 1)
    assert "K" in cs.constants
    assert cs.vars == ("q", "a", "b")


def test_c_関数宣言名_関数ポインタは非抽出():
    assert _c("int foo(void);\n", 1) .vars == ()
    assert _c("int (*fp)(void) = cb;\n", 1).vars == ()


def test_c_複合代入捕捉():
    assert _c("void f(){ total += x; arr[i] += 1; }\n", 1).vars == ("total",)


def test_c_getter_setterは無し():
    cs = _c("int n = 3;\n", 1)
    assert cs.getters == () and cs.setters == ()


def test_proc_exec_sql内は非抽出_区間外は抽出():
    from grep_analyzer.chase import extract_chase_symbols_tree
    # 単一行 EXEC SQL → mask_exec_sql で空白化
    cs = extract_chase_symbols_tree("proc", "EXEC SQL SELECT c INTO :host FROM t;\n", 1)
    assert cs.vars == () and cs.constants == () and "host" not in cs.vars
    # 区間外の C 宣言は抽出
    src = ("int f(){\n"
           " EXEC SQL UPDATE t SET col = v WHERE id = :h;\n"
           " int after = 1;\n"
           "}\n")
    assert extract_chase_symbols_tree("proc", src, 2).vars == ()       # EXEC SQL 行
    assert extract_chase_symbols_tree("proc", src, 3).vars == ("after",)  # 区間外
```

注: `test_proc_*` は `extract_chase_symbols_tree("proc", …)`（parse_tree→host_grammar=c・host_source=mask_exec_sql）で動くが `_AST_CHASERS["proc"]` 未登録だと空。**Task 5 完了後 green**になるため Task 3 では `@pytest.mark.skip(reason="Task5 で registry 登録後 green")` を付け、Task 5 で外す。`_c(...)` 直接テストは Task 3 で green。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_ast_chaser.py -k "c_ or proc" -q`
Expected: FAIL（`ImportError: cannot import name 'extract_tree' from ... c_chaser`）

- [ ] **Step 3: Write minimal implementation**

`src/grep_analyzer/classifiers/c_chaser.py` の末尾に追加（既存 `mask`/`extract` はそのまま）。冒頭に新 import 追加:

```python
from grep_analyzer.classifiers.ts_classifier import bindings_at_line

_AST_BINDING = {"declaration", "field_declaration", "preproc_def",
                "preproc_function_def", "assignment_expression"}


def _declarator_name(node):
    """init/pointer/array declarator を再帰的に剥がし末尾 identifier/field_identifier を返す。"""
    t = node.type
    if t in ("identifier", "field_identifier"):
        return node.text.decode("utf-8", "replace")
    if t in ("init_declarator", "pointer_declarator", "array_declarator"):
        d = node.child_by_field_name("declarator")
        return _declarator_name(d) if d is not None else None
    return None     # function_declarator（関数名・関数ポインタ）等は非抽出


def _decl_names(node, out):
    for ch in node.children:
        if ch.type in ("init_declarator", "pointer_declarator", "array_declarator",
                       "identifier", "field_identifier"):
            nm = _declarator_name(ch)
            if nm is not None:
                out.append(nm)


def _is_const(node) -> bool:
    return any(ch.type == "type_qualifier" and "const" in ch.text.decode("utf-8", "replace").split()
               for ch in node.children)


def _handle_c(node, consts, vars_):
    t = node.type
    if t in ("preproc_def", "preproc_function_def"):
        nm = node.child_by_field_name("name")
        if nm is not None:
            consts.append(nm.text.decode("utf-8", "replace"))
    elif t in ("declaration", "field_declaration"):
        _decl_names(node, consts if _is_const(node) else vars_)
    elif t == "assignment_expression":
        left = node.child_by_field_name("left")
        if left is not None and left.type == "identifier":
            vars_.append(left.text.decode("utf-8", "replace"))


def extract_tree(language, root, lineno):
    """parse 済 root から C/Pro*C 束縛を field-directed・multi-node 抽出（spec §3.4）。"""
    consts, vars_ = [], []
    for node in bindings_at_line(root, lineno, _AST_BINDING):
        _handle_c(node, consts, vars_)
    const_set = set(consts)
    vars_ = [v for v in vars_ if v not in const_set]
    return ChaseSymbols(tuple(consts), tuple(vars_), (), ())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /workspaces/grep_helpers2 && python -m pytest tests/unit/test_ast_chaser.py -k "c_ or proc" -q`
Expected: PASS（proc テストは skip、`_c` テスト green）

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/classifiers/c_chaser.py tests/unit/test_ast_chaser.py
git commit -m "feat(chaser): c/proc AST extract_tree（preproc_function_def/field_declaration/declarator剥がし/複合代入・spec §3.4）行ベースと共存"
```

---

### Task 4: Inv 差分スナップショット（再生成ガード・実装前ベースライン）

**Files:**
- 一時ファイル（commit しない）: `/tmp/inv_baseline.txt`

目的: spec §4.4 の再生成ガード。registry 移動（Task 5）の**前**に現行（行ベース）の golden 出力をスナップショットし、AST 化後の差分を「改善/退行」で判定する基準にする。

- [ ] **Step 1: 現行 golden を全て green で確認しスナップショット**

Run:
```bash
cd /workspaces/grep_helpers2
python -m pytest tests/golden -q 2>&1 | tail -5
# 現行 java/c/proc/jsp 関連 golden の expected を基準として記録
for c in java_direct c_direct proc_direct indirect_constant getter_no_expand jsp_chain parsefail_fallback; do
  echo "=== $c ==="; cat tests/golden/cases/$c/expected/*; echo;
done > /tmp/inv_baseline.txt
wc -l /tmp/inv_baseline.txt
```
Expected: golden 全 green。`/tmp/inv_baseline.txt` に7ケースの expected が記録される。

- [ ] **Step 2: Commit（スナップショットは commit 不要・このタスクは確認のみ）**

このタスクはコード変更なし。次タスクの判定基準を作るだけ。commit はスキップ（`git status` がクリーンであることを確認）。

---

### Task 5: registry 移動（AST 経路の有効化・Inv チェックポイント）

**Files:**
- Modify: `src/grep_analyzer/classifiers/__init__.py`
- Modify: `src/grep_analyzer/classifiers/java_chaser.py`（dead 化した `extract`/`mask` と旧 import を除去）
- Modify: `src/grep_analyzer/classifiers/c_chaser.py`（同上）
- Modify: `tests/unit/test_chase.py`（行ベース java/c/jsp/proc テスト除去・mask/非AST テスト修正）
- Modify: `tests/unit/test_ast_chaser.py`（Task 2/3 で skip した jsp/proc テストの skip を外す）

- [ ] **Step 1: registry を移動**

`src/grep_analyzer/classifiers/__init__.py` を編集。`_CHASERS` から java/c/proc/jsp を除去、`_AST_CHASERS` に追加:

```python
_CHASERS: dict[str, Chaser] = {
    "shell": shell_chaser, "sql": sql_chaser, "perl": perl_chaser, "groovy": groovy_chaser,
}
_AST_CHASERS: dict[str, ASTChaser] = {
    "python": python_chaser,
    "javascript": javascript_chaser,
    "typescript": typescript_chaser,
    "tsx": typescript_chaser,
    "angular": typescript_chaser,
    "angular_inline": typescript_chaser,
    "java": java_chaser,
    "c": c_chaser,
    "proc": c_chaser,
    "jsp": java_chaser,
}
```

（`from grep_analyzer.classifiers import ( c_chaser, java_chaser, … )` の import 群は据え置き。）

- [ ] **Step 2: dead 化した行ベース API を chaser から除去**

`java_chaser.py` から `mask`・`extract` 関数と `from grep_analyzer.patterns.literal_masking import MASK_PATTERNS` / `from grep_analyzer.patterns.symbol_extraction import (JAVA_CONST_RE, JAVA_GETSET_RE, JAVA_VAR_RE)` を削除（`extract_tree` 系のみ残す）。`c_chaser.py` から同様に `mask`・`extract` と `MASK_PATTERNS`/`C_*_RE` import を削除。モジュール docstring を AST 版へ更新。

- [ ] **Step 3: test_chase.py の移行（6 関数を削除＋3 関数を編集）**

`tests/unit/test_chase.py` から次の**6 関数を削除**（AST 版は test_ast_chaser.py に Task2/3 で追加済）:
- `test_文字列内の代入様字句は追跡シンボルにしない`
- `test_Java定数はstaticかつfinalのみでgenericと配列を許容する`
- `test_Javaのgetterとsetterとvarをマスクのうえ分類抽出する`
- `test_C定義とconst定数を抽出しProCホスト変数は追跡投入しない`
- `test_jsp_行ベースchaserが代入左辺を抽出`
- `test_jsp_ELは束縛なし`

`test_ref_kind言語表の禁止セルは空を返す` から **proc の2行**（`pc = extract_chase_symbols("proc", ...)` と関連 assert）を削除し sql/shell 部分のみ残す。

`test_文字列とコメントをマスクし行長を保つ` を perl ベースへ縮小（java/c 断削除）:
```python
def test_文字列とコメントをマスクし行長を保つ():
    # mask_literals は sql/shell/perl/groovy のみ対象（java/c は AST 化で非対象）
    assert mask_literals("perl", 'my $s = "x=1"; # c') == "my $s =      ;    "
    assert len(mask_literals("groovy", 'a=1; /* z=9 */ b=2')) == len('a=1; /* z=9 */ b=2')
```

`test_extract_chase_symbols_tree_非AST言語は空` の言語を groovy へ差し替え:
```python
def test_extract_chase_symbols_tree_非AST言語は空():
    from grep_analyzer.chase import extract_chase_symbols_tree
    cs = extract_chase_symbols_tree("groovy", "int x = 1;\n", 1)
    assert cs.constants == () and cs.vars == ()
```

- [ ] **Step 4: test_ast_chaser.py の skip 解除＋未使用 import 除去**

Task 2 の `test_java_jsp_経由`、Task 3 の `test_proc_exec_sql内は非抽出_区間外は抽出` の `@pytest.mark.skip` を削除。skip が無くなり `import pytest` が未使用になるため**冒頭の `import pytest` を除去**（lint 衛生・F401 回避）。

- [ ] **Step 5: 全テスト実行＋Inv チェックポイント**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q 2>&1 | tail -15`
Expected: 全 green。**特に golden（tests/golden）が全 pass**＝既存 java/c/proc/jsp golden の出力 byte 不変。

万一 golden に差分が出た場合（`pytest tests/golden -q` で fail）:
1. 差分を `/tmp/inv_baseline.txt` と比較。
2. 差分が spec §4.4 のチェックリスト（`this.y`/EXEC SQL 内代入/複合代入/ポインタ var/no-init/多行束縛）の**改善**に該当 → `python -m grep_analyzer ...`（既存 golden 生成手順）で expected 再生成し、差分票を残してレビューへ。
3. 該当しない（取りこぼし・誤分類）→ **退行**。chaser を修正して再実行。

- [ ] **Step 6: Commit**

```bash
git add src/grep_analyzer/classifiers/__init__.py src/grep_analyzer/classifiers/java_chaser.py \
        src/grep_analyzer/classifiers/c_chaser.py tests/unit/test_chase.py tests/unit/test_ast_chaser.py
git commit -m "feat(chaser): java/c/jsp/proc を _AST_CHASERS へ移動・行ベースAPI除去・テスト移行（Inv: 既存golden byte不変）"
```

---

### Task 6: dead code 除去（java/c の regex/mask・**proc は残置**）

**Files:**
- Modify: `src/grep_analyzer/patterns/literal_masking.py`
- Modify: `src/grep_analyzer/patterns/symbol_extraction.py`

- [ ] **Step 1: 残存参照ゼロを確認**

Run:
```bash
cd /workspaces/grep_helpers2
rg -n "JAVA_CONST_RE|JAVA_VAR_RE|JAVA_GETSET_RE|C_DEFINE_RE|C_CONST_RE|C_VAR_RE" src tests
rg -n 'MASK_PATTERNS\["java"\]|MASK_PATTERNS\["c"\]|MASK_SPECS\["java"\]|MASK_SPECS\["c"\]' src tests
rg -n 'MASK_PATTERNS\["proc"\]|MASK_SPECS\["proc"\]' src tests   # proc は残す（参照あるはず）
```
Expected: JAVA_*/C_* と `["java"]`/`["c"]` 添字は src/grep_analyzer 内で参照ゼロ（Task5 で chaser から除去済）。`["proc"]` は `proc_preprocess.py:30` が参照（**残置必須**）。

- [ ] **Step 2: literal_masking.py から java/c を除去（proc 残置）**

`src/grep_analyzer/patterns/literal_masking.py` の `MASK_SPECS` から `"java"` と `"c"` の行のみ削除。`"proc"` 行は**残す**。docstring に「java/c は AST 化で非対象・proc は proc_preprocess が依存」と注記。

- [ ] **Step 3: symbol_extraction.py から JAVA_*/C_* を除去**

`src/grep_analyzer/patterns/symbol_extraction.py` から `JAVA_GETSET_RE`/`JAVA_CONST_RE`/`JAVA_VAR_RE`/`C_DEFINE_RE`/`C_CONST_RE`/`C_VAR_RE` の定義を削除。module docstring の Java/C 行を削除。SQL/Shell/Perl/Groovy の定義は残す。

- [ ] **Step 4: 全テスト実行**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q 2>&1 | tail -5`
Expected: 全 green（proc_preprocess・proc 系 golden 含め無傷）。

- [ ] **Step 5: Commit**

```bash
git add src/grep_analyzer/patterns/literal_masking.py src/grep_analyzer/patterns/symbol_extraction.py
git commit -m "refactor(chaser): dead化した java/c の regex/mask を除去（MASK_SPECS proc は proc_preprocess 依存のため残置）"
```

---

### Task 7: 新規 golden（AST 能力の固定）

**Files:**
- Create: `tests/golden/cases/java_multiline_chase/{src,input,expected}/`
- Create: `tests/golden/cases/proc_exec_sql_chase/{src,input,expected}/`
- Create: `tests/golden/cases/c_compound_assign/{src,input,expected}/`

既存 golden の構成（src ディレクトリ・input/*.grep・expected/* は utf-8-sig BOM・`{SOURCE_ROOT}` 正規化）に従う。expected はツールで生成し内容をレビューする。

- [ ] **Step 1: java_multiline_chase の src/input を作成**

`tests/golden/cases/java_multiline_chase/src/A.java`:
```java
class A { static final String TRACKED = "T"; }
```
`tests/golden/cases/java_multiline_chase/src/B.java`:
```java
class B {
  void m() {
    String alias =
        TRACKED;
    use(alias);
  }
}
```
`tests/golden/cases/java_multiline_chase/input/TRACKED.grep`（keyword TRACKED の直接ヒット2件）:
```
A.java:1:class A { static final String TRACKED = "T"; }
B.java:4:        TRACKED;
```

- [ ] **Step 2: proc_exec_sql_chase の src/input を作成**

`tests/golden/cases/proc_exec_sql_chase/src/p.pc`:
```c
int f(){
  EXEC SQL UPDATE t
    SET col = TRACKED
    WHERE id = :h;
  int after = TRACKED;
}
int g(){ int col = 99; }
```
`tests/golden/cases/proc_exec_sql_chase/input/TRACKED.grep`:
```
p.pc:3:    SET col = TRACKED
p.pc:5:  int after = TRACKED;
```

- [ ] **Step 3: c_compound_assign の src/input を作成**

`tests/golden/cases/c_compound_assign/src/m.c`:
```c
int total = SEED;
void f(){ total += 1; }
```
`tests/golden/cases/c_compound_assign/input/SEED.grep`:
```
m.c:1:int total = SEED;
```

- [ ] **Step 4: expected を生成（`tests/golden/test_golden.py` と同一の正規化で生成）**

expected は `pipeline.run`→manifest encoding 読戻し→`sr+"/"` を `{SOURCE_ROOT}/` へ各行先頭1回置換→utf-8-sig 書出し、で生成する（`tests/golden/test_golden.py` の照合ロジックと一致させる）。**重要（worktree レビュー I-1）**: editable install の `.pth` が古い src を指す事故を防ぐため、冒頭で当該作業ツリーの `src` を `sys.path` 先頭に挿入し、`bindings_at_line` の存在で AST 化済 src を使っていることを assert する。

Run:
```bash
cd /workspaces/grep_helpers2
python -c '
import sys; sys.path.insert(0, "src")
from grep_analyzer.classifiers import ts_classifier
assert hasattr(ts_classifier, "bindings_at_line"), "AST 化済 src を使うこと（古い editable src で生成しない）"
import json, tempfile
from pathlib import Path
from grep_analyzer.pipeline import _default_opts, run
for case in ["java_multiline_chase", "proc_exec_sql_chase", "c_compound_assign"]:
    base = Path("tests/golden/cases") / case
    out = Path(tempfile.mkdtemp())
    assert run(input_dir=base/"input", output_dir=out, source_root=base/"src", opts=_default_opts()) == 0
    sr = str((base/"src").resolve())
    (base/"expected").mkdir(exist_ok=True)
    for tsv in sorted(out.glob("*.tsv")):
        enc = "utf-8-sig"
        m = out / (tsv.stem + ".manifest.json")
        if m.is_file(): enc = json.loads(m.read_text("utf-8")).get("encoding", "utf-8-sig")
        txt = tsv.read_text(enc)
        txt = "".join((ln.replace(sr+"/", "{SOURCE_ROOT}/", 1) if (sr+"/") in ln else ln)
                      for ln in txt.splitlines(keepends=True))
        (base/"expected"/tsv.name).write_text(txt, encoding="utf-8-sig")
        print("wrote", base/"expected"/tsv.name)
'
```

- [ ] **Step 5: expected の内容をレビューし主張を確認**

確認項目:
- `java_multiline_chase`: `alias` が **継続行ヒット由来で**現れる（`... -> alias@B.java:5` の chain 行が存在）。これは AST が外側 `local_variable_declaration` を捕捉した証拠（行ベースなら alias は出ない）。
- `proc_exec_sql_chase`: EXEC SQL 内 `col`/`id` が chase されず（`col@p.pc:7` の `int col = 99` への indirect 行が**存在しない**）。区間外 `after` は現れる。TRACKED 直接2行は出る。
- `c_compound_assign`: `total` が `+=` 行（m.c:2）から chase され `total@m.c:2` の indirect 行が現れる（複合代入捕捉）。

- [ ] **Step 6: Commit**

```bash
git add tests/golden/cases/java_multiline_chase tests/golden/cases/proc_exec_sql_chase tests/golden/cases/c_compound_assign
git commit -m "test(golden): AST 能力固定 — java多行宣言追跡/proc EXEC SQL偽抽出排除/C複合代入捕捉（spec §4.3）"
```

---

### Task 8: master spec 更新（完了反映）

**Files:**
- Modify: `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`

- [ ] **Step 1: テスト件数を確定**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q 2>&1 | tail -3`
Expected: 件数を控える（worktree 実走での実測は **395 passed, 5 skipped**＝旧 381 から +14。本番でも同数の見込み。差があれば実測値を使う）。

- [ ] **Step 2: テストベースライン更新（`381 passed, 5 skipped` を実測値へ）**

master spec 内の全suite ベースライン記述（文字列 `381 passed, 5 skipped`・§96 参照の本文／§389 完了反映の本文に現れる）を `rg -n "381 passed, 5 skipped" docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` で特定し、Step1 の確定件数（395 想定）へ更新。世代注記（track A 331・track C 366・§389 381・本変更 395）を1行追記。注: §96 周辺の依存系 `244 passed`（pyahocorasick 互換）は別物＝触らない。

- [ ] **Step 3: §390 を完了化し proc を明記**

§390（L390 付近）の「既存 java/c/jsp chaser の AST 化統一（後続候補）」を「**（完了・2026-05-23）**」へ。対象に **proc** を明記、差分設計書 `docs/superpowers/specs/2026-05-23-chaser-ast-unification-design.md` と実装計画 `docs/superpowers/plans/2026-05-23-chaser-ast-unification.md` を参照。完了基準（multi-node `bindings_at_line`・name 行ゲート・既存 golden byte 不変・新規 golden 3件）を要約。

- [ ] **Step 4: §389 末尾と §208(6) 更新**

§389（L389 付近）末尾「残る後続候補は §390（chaser AST 化統一）のみ」を「§390 完了により v2 後続候補は完遂」へ更新。
§208（L208 付近）track C 既知限界(6)「多行 scriptlet（java_chaser 単行制約・行跨ぎ束縛非追跡）」を「**§390 の AST 化で多行 scriptlet の行跨ぎ束縛を追跡可能になり解消**」へ更新。

- [ ] **Step 5: 全テスト最終確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q 2>&1 | tail -3`
Expected: 全 green・Step1 と同件数。

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/specs/2026-05-16-grep-analyzer-design.md
git commit -m "docs(spec): 候補2 完了反映 — §390完了化(proc明記)・§389後続候補完遂・§208(6)多行scriptlet解消・§96ベースライン更新"
```

---

## Self-Review チェック（plan 作成者）

- **Spec coverage:** §3.1 registry→T5 / §3.2 bindings_at_line→T1 / §3.3 java→T2 / §3.4 c→T3 / §3.5 proc・jsp→T2(jsp)/T3(proc) / §4.1 Inv→T4,T5 / §4.3 新規 golden→T7 / §4.4 ガード→T4,T5 / §5.1 テスト移行→T2,T3,T5 / §5.2 dead code(proc 残置)→T6 / §6 既知限界→実装に内包 / §7 完了基準→T5,T7,T8。全カバー。
- **Placeholder scan:** golden 生成コマンドのみ「既存手順に合わせる」と委譲（生成出力のため不可避・確認手順は具体化）。他に TBD なし。
- **Type consistency:** `extract_tree(language, root, lineno)`・`bindings_at_line(root, lineno, binding_types)`・`ChaseSymbols(consts, vars_, getters, setters)` を全タスクで一貫使用。`_AST_BINDING`/`_GETSET_RE`/`_handle_java`/`_handle_c`/`_declarator_name`/`_decl_names`/`_is_const`/`_modifier_tokens` の名称統一。

## 既知の実装上の注意

- Task 2/3 は行ベース API を残したまま AST を追加し共存させる（Task 5 の registry 移動まで line-based 経路を壊さない）。jsp/proc テストは Task 5 まで skip。
- name 行ゲート（`nm.start_point[0] == lineno-1`）は **method_invocation/method_declaration のみ**。宣言/代入/resource は非ゲート（多行追跡維持）。これを取り違えると getter_no_expand（要 getter 検出）か java_multiline_chase（要多行宣言）のいずれかが壊れる。
- `MASK_SPECS["proc"]` は **絶対に消さない**（proc_preprocess.py:30 が添字アクセス・import 時 KeyError 全壊）。
- 既存 python/js/ts chaser は `binding_at_line`（単数）を使い続ける。`bindings_at_line`（複数）は java/c 専用追加。既存3言語へ影響なし。
