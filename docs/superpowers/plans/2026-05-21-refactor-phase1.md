# Refactor Phase 1: 規約確定 + regex 集約 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** grep_analyzer の各モジュールに散在する正規表現定数を、用途別サブモジュール `src/grep_analyzer/patterns/{snippet_boundaries,literal_masking,symbol_extraction}.py` に集約する。命名規約・コメント規約・Refactoring Discipline 規約は設計ドキュメント（v5）で確定済。Phase 1 plan は regex 集約の実装のみを扱う。

**Architecture:** `patterns/` サブパッケージを新設し、用途ごとに独立した .py ファイルに正規表現定数を置く（規約 R2 に従い、用途が違えば形が似ていても集約しない）。各サブモジュールは公開名（大文字 + `_RE` 末尾）で定数を export する。`snippet.py` と `chase.py` は移動した定数を `from grep_analyzer.patterns.<module> import <NAME>` で参照する形に置換する。挙動・出力・テスト pass 状況はすべて不変（Inv-A〜E）。

**Tech Stack:** Python 3.12 / pytest / 標準ライブラリ `re` モジュール

**Related design:** `docs/superpowers/specs/2026-05-21-refactor-design.md` §6 Phase 1, §5 R2

---

## ファイル構造（Phase 1 完了時の最終形）

```
src/grep_analyzer/
├── patterns/                       ← 新設
│   ├── __init__.py                ← 空（subpackage マーカー）
│   ├── snippet_boundaries.py      ← _SQL_CLAUSE / _SH_END を SQL_CLAUSE_RE / SH_TERMINATOR_RE として公開
│   ├── literal_masking.py         ← _MASK_SPECS / _MASK_RE を MASK_SPECS / MASK_PATTERNS として公開
│   └── symbol_extraction.py       ← chase.py 内の言語別シンボル抽出 regex を公開名で集約
├── snippet.py                      ← _SQL_CLAUSE / _SH_END 定義を削除、import に置換
└── chase.py                        ← マスク用 + シンボル抽出用 regex 定義を削除、import に置換
```

**移動対象の正規表現一覧**（実コード grep 結果）:

| 現在の位置 | 現在の名前 | 移動先ファイル | 公開名 |
|---|---|---|---|
| snippet.py:75-76 | `_SQL_CLAUSE` | patterns/snippet_boundaries.py | `SQL_CLAUSE_RE` |
| snippet.py:77 | `_SH_END` | patterns/snippet_boundaries.py | `SH_TERMINATOR_RE` |
| chase.py:40-46 | `_MASK_SPECS` | patterns/literal_masking.py | `MASK_SPECS` |
| chase.py:47 | `_MASK_RE` | patterns/literal_masking.py | `MASK_PATTERNS` |
| chase.py:10 | `_ORACLE_ASSIGN_RE` | patterns/symbol_extraction.py | `ORACLE_ASSIGN_RE` |
| chase.py:11 | `_BOURNE_ASSIGN_RE` | patterns/symbol_extraction.py | `BOURNE_ASSIGN_RE` |
| chase.py:12-14 | `_CSHELL_ASSIGN_RE` | patterns/symbol_extraction.py | `CSHELL_ASSIGN_RE` |
| chase.py:49 | `_JAVA_GETSET_RE` | patterns/symbol_extraction.py | `JAVA_GETSET_RE` |
| chase.py:50-52 | `_JAVA_CONST_RE` | patterns/symbol_extraction.py | `JAVA_CONST_RE` |
| chase.py:53 | `_JAVA_VAR_RE` | patterns/symbol_extraction.py | `JAVA_VAR_RE` |
| chase.py:54 | `_C_DEFINE_RE` | patterns/symbol_extraction.py | `C_DEFINE_RE` |
| chase.py:55 | `_C_CONST_RE` | patterns/symbol_extraction.py | `C_CONST_RE` |
| chase.py:56 | `_C_VAR_RE` | patterns/symbol_extraction.py | `C_VAR_RE` |
| chase.py:57 | `_BOURNE_READONLY_RE` | patterns/symbol_extraction.py | `BOURNE_READONLY_RE` |

---

### Task 1: aarch64 wheel availability 事前チェック

**Files:**
- なし（情報収集のみ）

- [ ] **Step 1: 各依存パッケージの aarch64 wheel 存在を確認**

Run:
```bash
for pkg in pyahocorasick tree-sitter tree-sitter-java tree-sitter-c chardet; do
  echo "=== $pkg ==="
  pip index versions "$pkg" 2>&1 | head -3
done
```

Expected: 各パッケージのバージョン一覧が表示される。`pip index versions` が `ERROR: No matching distribution` を返さないことを確認。

- [ ] **Step 2: 現状の lock ファイル整合性を確認**

Run: `head -20 /workspaces/grep_helpers2/requirements.lock`

Expected: `pyahocorasick==2.3.1`, `tree-sitter==0.21.3` 等の固定バージョンが lock されていることを確認（memory `dgx-spark-aarch64-wheel-policy.md` の解決済方針）。

- [ ] **Step 3: 結果記録（次タスクの前提として）**

Step 1/2 の結果に問題がなければ何もしない。問題があればここで停止し、設計レビューに戻る。

---

### Task 2: ベースライン確立 — 全テスト pass と TSV 出力 byte ハッシュ記録

**Files:**
- なし（測定のみ）

- [ ] **Step 1: 全 unit / integration / golden / smoke テストを pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -20`

Expected: `passed` で終わる集計行が表示される。1 件でも fail / error があれば停止し、設計に戻る。

- [ ] **Step 2: ベースライン commit hash を記録**

Run: `git rev-parse HEAD`

Expected: 40 文字の commit hash が表示される。Phase 1 完了時にこの hash と golden 出力の byte 完全一致を確認する。

(ハッシュ値は Phase 1 完了時の Task 11 で再度参照する。本 plan の最後で `BASELINE_HASH` として参照する)

---

### Task 3: `patterns/` サブパッケージの骨格作成

**Files:**
- Create: `src/grep_analyzer/patterns/__init__.py`

- [ ] **Step 1: サブパッケージディレクトリを作成し空の __init__.py を置く**

Run:
```bash
mkdir -p /workspaces/grep_helpers2/src/grep_analyzer/patterns
```

Then create `/workspaces/grep_helpers2/src/grep_analyzer/patterns/__init__.py` with content:

```python
"""正規表現定数の用途別集約。

用途が違えば形が似ていても別ファイルに置く（規約 R2）。サブモジュール:
- snippet_boundaries: スニペット切り出しの境界判定用
- literal_masking: 言語別リテラル/コメントのマスク用
- symbol_extraction: 言語別シンボル抽出用

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §5 R2, §6 Phase 1
"""
```

- [ ] **Step 2: パッケージとして認識されるか smoke 確認**

Run: `cd /workspaces/grep_helpers2 && python -c "from grep_analyzer import patterns; print(patterns.__doc__[:30])"`

Expected: `正規表現定数の用途別集約。` で始まる文字列が表示される。

- [ ] **Step 3: 既存テスト全件 pass 確認（新規ファイル追加で壊れないこと）**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `passed` の集計行（fail / error なし）。

- [ ] **Step 4: commit**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/patterns/__init__.py && \
  git commit -m "feat(patterns): patterns/ サブパッケージの骨格を新設（規約 R2 準拠）"
```

---

### Task 4: `patterns/snippet_boundaries.py` 作成

**Files:**
- Create: `src/grep_analyzer/patterns/snippet_boundaries.py`

- [ ] **Step 1: snippet_boundaries.py を作成**

Create `/workspaces/grep_helpers2/src/grep_analyzer/patterns/snippet_boundaries.py` with content:

```python
"""スニペット切り出しの境界判定用 regex。

`heuristic_span` が sql / shell のスパン停止条件として参照する。
判定対象はマスク後の行末・句境界・shell 終端構文。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 1
"""

import re

SQL_CLAUSE_RE = re.compile(
    r"\b(WHERE|SET|VALUES|SELECT|FROM|GROUP\s+BY|ORDER\s+BY|HAVING)\b", re.I)

SH_TERMINATOR_RE = re.compile(r"(?:^|\s)(fi|done|esac|breaksw)\b|;")
```

- [ ] **Step 2: import 可能性 smoke 確認**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.patterns.snippet_boundaries import SQL_CLAUSE_RE, SH_TERMINATOR_RE
assert SQL_CLAUSE_RE.search('WHERE x=1') is not None
assert SH_TERMINATOR_RE.search('done') is not None
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: 既存テスト pass 確認（snippet.py はまだ未変更だが、新規モジュール追加で何も壊れないこと）**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `passed`（fail / error なし）。

- [ ] **Step 4: commit**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/patterns/snippet_boundaries.py && \
  git commit -m "feat(patterns): snippet_boundaries.py — SQL 句 / shell 終端 regex を集約"
```

---

### Task 5: `snippet.py` を `patterns.snippet_boundaries` 経由に置換

**Files:**
- Modify: `src/grep_analyzer/snippet.py` (L75-77 削除、import 追加)

- [ ] **Step 1: snippet.py の import に snippet_boundaries を追加**

`/workspaces/grep_helpers2/src/grep_analyzer/snippet.py` の現状 L10-13 周辺:

```python
from grep_analyzer.chase import mask_literals
from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree
from grep_analyzer.proc_preprocess import exec_spans, mask_exec_sql
from grep_analyzer.tsv import _sanitize
```

これを次に変更:

```python
from grep_analyzer.chase import mask_literals
from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree
from grep_analyzer.patterns.snippet_boundaries import SH_TERMINATOR_RE, SQL_CLAUSE_RE
from grep_analyzer.proc_preprocess import exec_spans, mask_exec_sql
from grep_analyzer.tsv import _sanitize
```

- [ ] **Step 2: snippet.py L75-77 の `_SQL_CLAUSE` と `_SH_END` 定義を削除**

削除対象（snippet.py 現状の L75-77）:

```python
_SQL_CLAUSE = re.compile(
    r"\b(WHERE|SET|VALUES|SELECT|FROM|GROUP\s+BY|ORDER\s+BY|HAVING)\b", re.I)
_SH_END = re.compile(r"(?:^|\s)(fi|done|esac|breaksw)\b|;")
```

これらを完全削除。前後の空行は維持（1 行）。

- [ ] **Step 3: snippet.py 内の `_SQL_CLAUSE` 参照を `SQL_CLAUSE_RE` に、`_SH_END` を `SH_TERMINATOR_RE` に置換**

該当箇所（snippet.py:107-108 周辺）:

```python
        if language == "sql":
            return x.rstrip().endswith(";") or bool(_SQL_CLAUSE.search(x))
        return bool(_SH_END.search(x))
```

変更後:

```python
        if language == "sql":
            return x.rstrip().endswith(";") or bool(SQL_CLAUSE_RE.search(x))
        return bool(SH_TERMINATOR_RE.search(x))
```

- [ ] **Step 4: snippet.py が `re` を直接使う他の箇所が無ければ `import re` を削除しないこと**

Run: `cd /workspaces/grep_helpers2 && grep -n '\bre\.' src/grep_analyzer/snippet.py`

Expected: `re.` を含む行が出れば `import re` は残す。出なければそのままでも害は無いので残す（YAGNI: 関係ない削除はしない）。

- [ ] **Step 5: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `passed`（fail / error なし）。1 件でも fail があれば Step 1-3 を見直す。

- [ ] **Step 6: import 経路の確認（cyclic / 逆依存が無いこと）**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
import grep_analyzer.snippet
print('snippet OK')
import grep_analyzer.patterns.snippet_boundaries
print('snippet_boundaries OK')
"
```

Expected: `snippet OK` / `snippet_boundaries OK` が表示される。

- [ ] **Step 7: commit**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/snippet.py && \
  git commit -m "refactor(snippet): regex 定数を patterns.snippet_boundaries から import に置換"
```

---

### Task 6: `patterns/literal_masking.py` 作成

**Files:**
- Create: `src/grep_analyzer/patterns/literal_masking.py`

- [ ] **Step 1: literal_masking.py を作成**

Create `/workspaces/grep_helpers2/src/grep_analyzer/patterns/literal_masking.py` with content:

```python
"""言語別リテラル / コメントのマスク用 regex。

`mask_literals` が偽陽性抑止のため、リテラル文字列・コメントを同字数空白に
置換するときの言語別パターン集。マッチ全体を空白に潰すため、後段の正規表現
抽出は行番号・桁を保ったまま行える。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 1
"""

import re

MASK_SPECS: dict[str, list[str]] = {
    "java": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "c": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "proc": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "sql": [r"'(?:''|[^'])*'", r"--[^\n]*", r"/\*.*?\*/"],
    "shell": [r'"(?:\\.|[^"\\])*"', r"'[^']*'", r"#[^\n]*"],
}

MASK_PATTERNS: dict[str, re.Pattern[str]] = {
    lang: re.compile("|".join(p), re.DOTALL) for lang, p in MASK_SPECS.items()
}
```

- [ ] **Step 2: import smoke 確認**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.patterns.literal_masking import MASK_SPECS, MASK_PATTERNS
assert set(MASK_SPECS.keys()) == set(MASK_PATTERNS.keys())
assert MASK_PATTERNS['java'].search('\"hello\"') is not None
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: 既存テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `passed`。

- [ ] **Step 4: commit**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/patterns/literal_masking.py && \
  git commit -m "feat(patterns): literal_masking.py — 言語別リテラル/コメント regex を集約"
```

---

### Task 7: `chase.py` を `patterns.literal_masking` 経由に置換

**Files:**
- Modify: `src/grep_analyzer/chase.py` (L40-47 削除、import 追加、L66 参照置換)

- [ ] **Step 1: chase.py の import に literal_masking を追加**

`/workspaces/grep_helpers2/src/grep_analyzer/chase.py` の L7 直下に追記:

現状 L1-7:

```python
"""追跡シンボル抽出規則（spec §8.1）。Phase 2 不動点エンジンが消費する純関数。

Phase 1.5 では direct パイプラインには配線せず、抽出規則の正しさを unit で固定する
（spec §15 フェーズ1.5: Oracle/csh 代入抽出を Phase 2 前に確定し golden 誤固定を防ぐ）。
"""

import re
```

を次に変更（import を追加）:

```python
"""追跡シンボル抽出規則（spec §8.1）。Phase 2 不動点エンジンが消費する純関数。

Phase 1.5 では direct パイプラインには配線せず、抽出規則の正しさを unit で固定する
（spec §15 フェーズ1.5: Oracle/csh 代入抽出を Phase 2 前に確定し golden 誤固定を防ぐ）。
"""

import re

from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
```

- [ ] **Step 2: chase.py L40-47 の `_MASK_SPECS` と `_MASK_RE` 定義を削除**

削除対象（現状 L40-47）:

```python
_MASK_SPECS = {
    "java": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "c": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "proc": [r'"(?:\\.|[^"\\])*"', r"'(?:\\.|[^'\\])*'", r"//[^\n]*", r"/\*.*?\*/"],
    "sql": [r"'(?:''|[^'])*'", r"--[^\n]*", r"/\*.*?\*/"],
    "shell": [r'"(?:\\.|[^"\\])*"', r"'[^']*'", r"#[^\n]*"],
}
_MASK_RE = {lang: re.compile("|".join(p), re.DOTALL) for lang, p in _MASK_SPECS.items()}
```

これらを完全削除。前後の空行は維持（1 行）。

- [ ] **Step 3: `_MASK_RE` 参照を `MASK_PATTERNS` に置換**

chase.py:66 の `mask_literals` 内:

```python
def mask_literals(language: str, line: str) -> str:
    """..."""
    re_ = _MASK_RE.get(language)
    return line if re_ is None else re_.sub(lambda m: " " * len(m.group(0)), line)
```

を次に変更:

```python
def mask_literals(language: str, line: str) -> str:
    """..."""
    pattern = MASK_PATTERNS.get(language)
    return line if pattern is None else pattern.sub(lambda m: " " * len(m.group(0)), line)
```

- [ ] **Step 4: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `passed`。1 件でも fail があれば Step 1-3 を見直す（特に `MASK_PATTERNS` の dict 型に matching API があるか）。

- [ ] **Step 5: commit**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/chase.py && \
  git commit -m "refactor(chase): mask 用 regex を patterns.literal_masking から import に置換"
```

---

### Task 8: `patterns/symbol_extraction.py` 作成

**Files:**
- Create: `src/grep_analyzer/patterns/symbol_extraction.py`

- [ ] **Step 1: symbol_extraction.py を作成**

Create `/workspaces/grep_helpers2/src/grep_analyzer/patterns/symbol_extraction.py` with content:

```python
"""言語別シンボル抽出 regex。

`extract_chase_symbols` と `extract_var_symbols` が、マスク後の行から
代入左辺・const 定義・getter/setter 等を切り出すために使う。

- SQL (Oracle): PL/SQL `var := 式` の左辺。バインド `:v`／置換 `&v` は非抽出
- Shell (bourne): 行頭 `var=` の左辺
- Shell (cshell): `set v =` / `setenv V` / `@ v =` の左辺
- Java: getter/setter, static final 定数, 一般変数代入
- C / Pro*C: `#define`, `const ... var =`, 一般変数代入

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 1
"""

import re

ORACLE_ASSIGN_RE = re.compile(r"(?<![:&])\b([A-Za-z_]\w*)\s*:=")

BOURNE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)=")

CSHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:set\s+([A-Za-z_]\w*)\s*=|setenv\s+([A-Za-z_]\w*)\b|@\s+([A-Za-z_]\w*)\s*=)"
)

JAVA_GETSET_RE = re.compile(r"\b((?:get|set)[A-Z]\w*)\s*\(")

JAVA_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+[\w.$]+(?:\s*<[^=;{}]*?>)?(?:\s*\[\s*\])*\s+([A-Za-z_]\w*)\s*=")

JAVA_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")

C_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")

C_CONST_RE = re.compile(r"\bconst\b[\w\s*]*?\b([A-Za-z_]\w*)\s*=")

C_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")

BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")
```

- [ ] **Step 2: import smoke 確認**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.patterns.symbol_extraction import (
    ORACLE_ASSIGN_RE, BOURNE_ASSIGN_RE, CSHELL_ASSIGN_RE,
    JAVA_GETSET_RE, JAVA_CONST_RE, JAVA_VAR_RE,
    C_DEFINE_RE, C_CONST_RE, C_VAR_RE, BOURNE_READONLY_RE,
)
assert ORACLE_ASSIGN_RE.search('v := 1') is not None
assert BOURNE_ASSIGN_RE.match('FOO=bar') is not None
assert JAVA_GETSET_RE.search('getName()') is not None
assert C_DEFINE_RE.match('#define X 1') is not None
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: 既存テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `passed`。

- [ ] **Step 4: commit**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/patterns/symbol_extraction.py && \
  git commit -m "feat(patterns): symbol_extraction.py — 言語別シンボル抽出 regex を集約"
```

---

### Task 9: `chase.py` を `patterns.symbol_extraction` 経由に置換

**Files:**
- Modify: `src/grep_analyzer/chase.py` (L9-14 削除、L49-57 削除、import 追加、参照置換)

- [ ] **Step 1: chase.py の import に symbol_extraction の名前群を追加**

Task 7 で既に追加済の `from grep_analyzer.patterns.literal_masking import MASK_PATTERNS` の直下に追記:

```python
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    BOURNE_ASSIGN_RE,
    BOURNE_READONLY_RE,
    C_CONST_RE,
    C_DEFINE_RE,
    C_VAR_RE,
    CSHELL_ASSIGN_RE,
    JAVA_CONST_RE,
    JAVA_GETSET_RE,
    JAVA_VAR_RE,
    ORACLE_ASSIGN_RE,
)
```

- [ ] **Step 2: chase.py L9-14 の Oracle / Bourne / Cshell 代入 regex 定義を削除**

削除対象（現状 L9-14、コメント付き）:

```python
# 代入左辺の識別子。Oracle は直前が : / & のもの（バインド/置換変数）を除外（spec §8.4）。
_ORACLE_ASSIGN_RE = re.compile(r"(?<![:&])\b([A-Za-z_]\w*)\s*:=")
_BOURNE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)=")
_CSHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:set\s+([A-Za-z_]\w*)\s*=|setenv\s+([A-Za-z_]\w*)\b|@\s+([A-Za-z_]\w*)\s*=)"
)
```

注: L9 のコメント「Oracle は直前が : / & のもの（バインド/置換変数）を除外（spec §8.4）」は、移動先 `patterns/symbol_extraction.py` の module docstring に既に記述済（"SQL (Oracle)" 行）。なので chase.py 側からは削除して OK。

- [ ] **Step 3: chase.py L49-57 の Java / C / Bourne readonly regex 定義を削除**

削除対象（現状 L49-57）:

```python
_JAVA_GETSET_RE = re.compile(r"\b((?:get|set)[A-Z]\w*)\s*\(")
_JAVA_CONST_RE = re.compile(
    r"\b((?:public|protected|private|static|final)(?:\s+(?:public|protected|private|static|final))*)"
    r"\s+[\w.$]+(?:\s*<[^=;{}]*?>)?(?:\s*\[\s*\])*\s+([A-Za-z_]\w*)\s*=")
_JAVA_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
_C_DEFINE_RE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
_C_CONST_RE = re.compile(r"\bconst\b[\w\s*]*?\b([A-Za-z_]\w*)\s*=")
_C_VAR_RE = re.compile(r"(?<![=!<>+\-*/%&|^])\b([A-Za-z_]\w*)\s*=(?!=)")
_BOURNE_READONLY_RE = re.compile(r"^\s*readonly\s+([A-Za-z_]\w*)=")
```

これらを完全削除。

- [ ] **Step 4: chase.py の参照箇所を新名前に一括置換**

置換対応:

| 旧名 | 新名 |
|---|---|
| `_ORACLE_ASSIGN_RE` | `ORACLE_ASSIGN_RE` |
| `_BOURNE_ASSIGN_RE` | `BOURNE_ASSIGN_RE` |
| `_CSHELL_ASSIGN_RE` | `CSHELL_ASSIGN_RE` |
| `_JAVA_GETSET_RE` | `JAVA_GETSET_RE` |
| `_JAVA_CONST_RE` | `JAVA_CONST_RE` |
| `_JAVA_VAR_RE` | `JAVA_VAR_RE` |
| `_C_DEFINE_RE` | `C_DEFINE_RE` |
| `_C_CONST_RE` | `C_CONST_RE` |
| `_C_VAR_RE` | `C_VAR_RE` |
| `_BOURNE_READONLY_RE` | `BOURNE_READONLY_RE` |

Run（確認）: `cd /workspaces/grep_helpers2 && grep -n '_\(ORACLE\|BOURNE\|CSHELL\|JAVA\|C_DEFINE\|C_CONST\|C_VAR\)' src/grep_analyzer/chase.py`

Expected: 旧名（先頭アンダースコア付き）が **検出されない** こと（空出力）。

- [ ] **Step 5: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `passed`（fail / error なし）。特に `tests/unit/test_chase.py` が pass することを確認:

Run: `cd /workspaces/grep_helpers2 && pytest tests/unit/test_chase.py -v 2>&1 | tail -20`

Expected: 全件 PASSED。

- [ ] **Step 6: commit**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/chase.py && \
  git commit -m "refactor(chase): シンボル抽出 regex を patterns.symbol_extraction から import に置換"
```

---

### Task 10: V3 — import グラフ層分離検証

**Files:**
- なし（検証のみ）

- [ ] **Step 1: cyclic import 実機検証**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
import grep_analyzer
import grep_analyzer.cli
import grep_analyzer.fixedpoint
import grep_analyzer.snippet
import grep_analyzer.chase
import grep_analyzer.patterns
import grep_analyzer.patterns.snippet_boundaries
import grep_analyzer.patterns.literal_masking
import grep_analyzer.patterns.symbol_extraction
print('all imports OK')
"
```

Expected: `all imports OK`。`ImportError` や `CircularImportError` が出ないこと。

- [ ] **Step 2: pytest collection が import エラーなく完了することを確認**

Run: `cd /workspaces/grep_helpers2 && pytest --collect-only -q 2>&1 | tail -5`

Expected: テストケース総数のみ表示され、`ERROR` / `ImportError` が出ないこと。

- [ ] **Step 3: 禁止逆依存の機械チェック — patterns/ から他モジュールへの import が無いこと**

Run: `cd /workspaces/grep_helpers2 && grep -rEn 'from grep_analyzer' src/grep_analyzer/patterns/`

Expected: **空出力**（patterns/* は何にも依存しないという葉ノード要件）。`import re` のみは OK（標準ライブラリは対象外）。

- [ ] **Step 4: chase.py / snippet.py が patterns 経由で import している箇所のみ存在することを確認**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  grep -n 'from grep_analyzer.patterns' src/grep_analyzer/chase.py && \
  echo '---' && \
  grep -n 'from grep_analyzer.patterns' src/grep_analyzer/snippet.py
```

Expected:
- chase.py に 2 行（`literal_masking` と `symbol_extraction`）
- snippet.py に 1 行（`snippet_boundaries`）

---

### Task 11: V1 — Inv-A byte 不変確認（Phase 1 完了判定）

**Files:**
- なし（検証のみ）

- [ ] **Step 1: 全 unit / integration / golden / smoke / perf テスト pass を確認**

Run: `cd /workspaces/grep_helpers2 && pytest 2>&1 | tail -10`

Expected: `passed` の集計行のみで、`failed` / `error` がゼロ。具体的に `test_chase.py` / `test_snippet.py` / `tests/golden/` 配下が全件 PASSED であること。

- [ ] **Step 2: Phase 1 ベースライン（Task 2 で記録）からの diff が文字列・コメント変更のみであることを確認**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  git diff $(git log --format=%H -n 1 --skip 7) HEAD -- src/grep_analyzer/ \
  | grep -E '^[+-][^+-]' | head -50
```

Expected: 削除と追加が `patterns/` への移動による相互に対応していること（実質的な機能変更が無いこと）。

- [ ] **Step 3: golden 出力が baseline と byte 完全一致することを確認**

Run: `cd /workspaces/grep_helpers2 && pytest tests/golden -q 2>&1 | tail -5`

Expected: `passed`（fail / error なし）。spec §11 v9 golden 比較機構が pass = Inv-A 満足。

---

### Task 12: V5 — Phase 1 完了 AI レビューゲート

**Files:**
- なし（レビューのみ。指摘反映があれば対応）

- [ ] **Step 1: 批判的 AI レビューを並列 2 件で起動**

Phase 1 完了状態の `src/grep_analyzer/` および新規 `patterns/` を対象に、独立 2 視点で批判的レビューを行う。レビュー観点:

- **観点 A**: 設計（v5）の §6 Phase 1 と §5 R2 規約に照らした実装の整合性
- **観点 B**: 命名規約 N1-N4 / コメント規約 C1-C5 に照らした実装の整合性（公開名の `_RE` 接尾辞、用途別サブモジュールの単一責務、module docstring の C3 形式準拠）

各レビューは Critical / Major / Minor / Suggestion に分類して報告させる。

- [ ] **Step 2: 指摘の反映**

- **Critical / Major**: 即座に反映 → Step 1 から再実施（2 巡目）
- **Minor / Suggestion**: 次 Phase の plan 冒頭に「前 Phase 引き継ぎ事項」として記録（V5 通過には影響しない）

- [ ] **Step 3: V5 通過条件の確認**

Critical / Major の指摘数がゼロになっていることを確認。最低 2 巡を満たしていれば次 Phase に進む可。

- [ ] **Step 4: Phase 1 完了の最終 commit（必要に応じて）**

レビュー反映が無ければ追加 commit 不要。反映があれば:

```bash
cd /workspaces/grep_helpers2 && \
  git add -A && \
  git commit -m "fix(refactor-phase1): AI レビュー指摘を反映（<指摘内容を要約>）"
```

---

## Phase 1 完了サマリ

すべての Task が完了した時点で:

- ✅ `src/grep_analyzer/patterns/` サブパッケージが新設され、3 つの用途別サブモジュールに正規表現定数が集約されている
- ✅ `snippet.py` と `chase.py` から既存の regex 定数定義が削除され、import 経由参照に置換されている
- ✅ 全テスト（unit / integration / golden / smoke）が pass
- ✅ V3 import グラフが葉→ルート一方向、cyclic import なし
- ✅ V1 Inv-A: 出力 byte が baseline と完全一致
- ✅ V5 AI レビューが Critical / Major ゼロに収束

→ Phase 2（chase 言語別分散化 + TSV 書込経路の正本化）の plan 作成へ進む。
