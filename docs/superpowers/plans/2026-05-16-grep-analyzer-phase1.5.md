# grep_analyzer Phase 1.5（決定的コアの方言精密化） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SQL=Oracle 方言・C系シェル(csh/tcsh)・拡張子なしスクリプト(シェバン判別)に対応するよう決定的コア（ディスパッチ／分類器／追跡シンボル抽出規則／golden）を精密化し、direct のみ・完全決定性を保ったまま Phase 2 不動点エンジンの追跡正しさ前提を確立する。

**Architecture:** 既存 Phase 1 パッケージ `grep_analyzer` を後方互換で拡張する。`dispatch.py` にシェバン検出と `.csh/.tcsh`、`detect_shell_dialect` を追加。`regex_classifier.classify_sql` を Oracle 方言規則へ差し替え（既存 golden 等価を維持）、`classify_shell(line, dialect="bourne")` に方言引数を追加（既定 bourne で Phase 1 テスト不変）。`chase.py` を新設し Oracle/bourne/cshell の代入左辺抽出を純関数として unit で固定（Phase 2 が消費。本 Phase ではパイプライン非配線）。`pipeline.py` を方言伝播・`unsupported_shebang` 診断に対応。golden は既存6不変＋新規4ケースを追加。

**Tech Stack:** Python 3.12 / pytest（既存環境）。新規外部依存なし（純標準ライブラリ `re`/`os`。tree-sitter は既存のまま）。設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v7 が正）、テスト規約 `.claude/skills/writing-tests.md`、コーディング規約 `.claude/skills/coding-conventions.md` に従う（docstring/コメントは日本語、テスト名は日本語、古典学派+TDD）。

---

## Task 0: ベースライン緑化ゲート（着手前提・コードなし）

spec §15 フェーズ1.5 は Phase 1 の決定性基盤上に積む。**Phase 1 全テストが緑であること**を着手前に確認し、以降の変更で golden 等が動いたら「意図した追加か／回帰か」を判別できる基準を固定する（writing-tests.md「大量churn＝構造を疑う」）。

- [ ] **Step 1: 全テスト実行でベースラインを確認**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: `43 passed`（unit / integration / golden / smoke すべて PASS、0 failed / 0 error）。

- [ ] **Step 2: spec v7 反映済みを確認**

Run: `grep -n "v7（現行）" docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`
Expected: 1 行ヒット（v7 改訂が spec に存在）。ヒットしなければ本計画を着手しない（spec が正・本計画の入力）。

- [ ] **Step 3: ゲート判定を記録**

`docs/superpowers/plans/phase0-gate-result.md` 末尾に「Phase 1.5 着手ゲート: PASS（43 passed / spec v7 反映済み, UTC 日付）」を追記しコミット。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 1.5 着手ゲート記録（43 passed / spec v7）"
```

注: `pyahocorasick` の wheel 実証は **Phase 2** の着手前提（spec §15 フェーズ2 / `phase0-gate-result.md` 申し送り）。Phase 1.5 は tree-sitter＋chardet＋標準ライブラリのみで完結し、本ゲートをブロックしない。

---

## Task 1: シェバン解析ヘルパ `shebang_dialect`

**Files:**
- Modify: `src/grep_analyzer/dispatch.py`
- Test: `tests/unit/test_dispatch.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_dispatch.py` の末尾に追記:
```python
from grep_analyzer.dispatch import shebang_dialect


def test_bourne系シェバンはbourneを返す():
    assert shebang_dialect("#!/bin/sh\nCODE=1\n") == "bourne"
    assert shebang_dialect("#!/bin/bash -e\n") == "bourne"
    assert shebang_dialect("#!/usr/bin/env ksh\n") == "bourne"


def test_C系シェバンはcshellを返す():
    assert shebang_dialect("#!/bin/csh\n") == "cshell"
    assert shebang_dialect("#!/usr/bin/env tcsh\n") == "cshell"


def test_非シェルシェバンはotherを返す():
    assert shebang_dialect("#!/usr/bin/perl\n") == "other"
    assert shebang_dialect("#!/usr/bin/env python3\n") == "other"


def test_シェバン無しはNoneを返す():
    assert shebang_dialect("CODE=1\n") is None
    assert shebang_dialect("  #!/bin/sh\n") is None  # 1列目以外の #! は無効
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_dispatch.py -q`
Expected: FAIL（`ImportError: cannot import name 'shebang_dialect'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/dispatch.py` の `_EXEC_SQL_RE` 行の直後に追記:
```python
# シェバンは第1物理行の1列目（任意の先頭BOM=U+FEFF 可）に #! が必須（spec §5.1 手順3）。
_SHEBANG_RE = re.compile(r"^\ufeff?#!\s*(\S+)(?:\s+(\S+))?")
_BOURNE_INTERP = {"sh", "bash", "ksh", "dash"}
_CSHELL_INTERP = {"csh", "tcsh"}


def shebang_dialect(content_sample: str) -> str | None:
    """第1物理行のシェバンからシェル方言を判定する（spec §5.1）。

    戻り値: "bourne" / "cshell" / "other"（シェバンだが非シェル）/ None（シェバン無し）。
    `#!/usr/bin/env X` は X を interpreter とみなす。判定は第1行のみに依存し決定的。
    """
    first_line = content_sample.split("\n", 1)[0]
    m = _SHEBANG_RE.match(first_line)
    if m is None:
        return None
    interp = m.group(1).rsplit("/", 1)[-1]
    if interp == "env" and m.group(2):
        interp = m.group(2).rsplit("/", 1)[-1]
    if interp in _BOURNE_INTERP:
        return "bourne"
    if interp in _CSHELL_INTERP:
        return "cshell"
    return "other"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_dispatch.py -q`
Expected: PASS（既存 dispatch テスト＋新規4本）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat(dispatch): シェバン方言判定ヘルパ shebang_dialect"
```

---

## Task 2: `detect_language` 拡張（`.csh/.tcsh`＋拡張子なしシェバン判別）

**Files:**
- Modify: `src/grep_analyzer/dispatch.py`
- Test: `tests/unit/test_dispatch.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_dispatch.py` の末尾に追記:
```python
def test_csh拡張子はshellと判定する():
    assert detect_language("a/run.csh", "", {}) == "shell"
    assert detect_language("a/run.tcsh", "", {}) == "shell"


def test_拡張子なしでもシェル系シェバンならshellと判定する():
    assert detect_language("bin/deploy", "#!/bin/csh\nset X = 1\n", {}) == "shell"
    assert detect_language("bin/backup", "#!/bin/sh\nX=1\n", {}) == "shell"


def test_拡張子なし非シェルシェバンはshellにしない():
    # perl は §14 将来言語。Shell に分類せず既存フォールバック（EXEC SQL 無→c）。
    assert detect_language("bin/tool", "#!/usr/bin/perl\nmy $x=1;\n", {}) == "c"


def test_拡張子なしEXEC_SQLはProCにフォールバックする():
    assert detect_language("x/embedded", "void f(){ EXEC SQL SELECT 1; }", {}) == "proc"
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_dispatch.py -q`
Expected: FAIL（`.csh` が `_EXT_MAP` 未登録で `"c"` 判定、拡張子なしシェバン未対応）

- [ ] **Step 3: 実装**

`src/grep_analyzer/dispatch.py` の `_EXT_MAP` を次に置換（`.csh`/`.tcsh` 追加）:
```python
_EXT_MAP = {
    ".java": "java",
    ".sql": "sql",
    ".sh": "shell", ".ksh": "shell", ".bash": "shell",
    ".csh": "shell", ".tcsh": "shell",
    ".pc": "proc",
    ".c": "c", ".h": "c",
}
```

同ファイルの `detect_language` を次に全置換（spec §5.1 の優先順位順）:
```python
def detect_language(path: str, content_sample: str, lang_map: dict[str, str]) -> str:
    """spec §5.1 の決定的優先順位で言語を返す。

    1) --lang-map 上書き 2) 拡張子マップ 3) 拡張子未知/無ならシェバン検出
    4) EXEC SQL ヒューリスティック 5) C にフォールバック。
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in lang_map:
        return lang_map[ext]
    lang = _EXT_MAP.get(ext)
    if lang == "shell":
        return "shell"
    if lang in ("c", "proc") or ext == ".h":
        if _EXEC_SQL_RE.search(content_sample):
            return "proc"
        return lang or "c"
    if lang is not None:  # java / sql
        return lang
    # 拡張子が未知または無い: シェバン検出（手順3）→ EXEC SQL（手順4）→ c（手順5）
    if shebang_dialect(content_sample) in ("bourne", "cshell"):
        return "shell"
    if _EXEC_SQL_RE.search(content_sample):
        return "proc"
    return "c"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_dispatch.py -q`
Expected: PASS（既存 dispatch テスト不変＋Task1/Task2 追加分すべて緑）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat(dispatch): .csh/.tcsh とシェバンによる拡張子なし判別（spec §5.1）"
```

---

## Task 3: `detect_shell_dialect`（言語=shell 時の方言確定・シェバン優先）

**Files:**
- Modify: `src/grep_analyzer/dispatch.py`
- Test: `tests/unit/test_dispatch.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_dispatch.py` の末尾に追記:
```python
from grep_analyzer.dispatch import detect_shell_dialect


def test_csh拡張子はcshell方言():
    assert detect_shell_dialect("a/run.csh", "set X = 1\n") == "cshell"
    assert detect_shell_dialect("a/run.tcsh", "") == "cshell"


def test_sh系拡張子はbourne方言():
    assert detect_shell_dialect("a/run.sh", "X=1\n") == "bourne"
    assert detect_shell_dialect("a/run.ksh", "") == "bourne"


def test_シェバンは拡張子より優先される():
    # 既知シェル拡張子でもシェバンが方言を上書きする（spec §5.1「言語判定と独立」）
    assert detect_shell_dialect("a/run.sh", "#!/bin/csh\nset X = 1\n") == "cshell"
    assert detect_shell_dialect("a/run.csh", "#!/bin/sh\nX=1\n") == "bourne"


def test_拡張子なしシェバンなしはbourne既定():
    assert detect_shell_dialect("bin/deploy", "X=1\n") == "bourne"
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_dispatch.py -q`
Expected: FAIL（`ImportError: cannot import name 'detect_shell_dialect'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/dispatch.py` の末尾に追記:
```python
def detect_shell_dialect(path: str, content_sample: str) -> str:
    """言語が Shell のとき方言（"bourne"/"cshell"）を決定的に返す（spec §5.1）。

    ① シェル系シェバンがあればそれを優先 ② 無ければ拡張子 ③ どちらも無ければ bourne。
    本関数は言語判定とは独立に呼ばれ、既知シェル拡張子でも第1物理行のシェバンを必ず見る。
    """
    sd = shebang_dialect(content_sample)
    if sd in ("bourne", "cshell"):
        return sd
    ext = os.path.splitext(path)[1].lower()
    if ext in (".csh", ".tcsh"):
        return "cshell"
    return "bourne"
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_dispatch.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/dispatch.py tests/unit/test_dispatch.py
git commit -m "feat(dispatch): detect_shell_dialect（シェバン優先・spec §5.1）"
```

---

## Task 4: SQL 分類器を Oracle 方言に精密化

**Files:**
- Modify: `src/grep_analyzer/classifiers/regex_classifier.py`
- Test: `tests/unit/test_regex_classifier.py`

spec §7: `:=`＝代入、`||`連結／`DECODE(...)`／`CASE WHEN`＝分岐、`WHERE …` 比較演算子＝比較、`INSERT/UPDATE`＝代入。既存 golden（`sql_direct`: `SELECT * FROM t WHERE col = 'X';`→比較）と既存 unit を**等価維持**する規則順とする。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_regex_classifier.py` の末尾に追記:
```python
def test_OracleのPLSQL代入は代入と判定する():
    assert classify_sql("v_code := 'X';") == ("代入", "medium")


def test_OracleのDECODEは分岐と判定する():
    assert classify_sql("SELECT DECODE(st,1,'OK','NG') FROM dual") == ("分岐", "medium")


def test_OracleのCASE_WHENは分岐と判定する():
    assert classify_sql("SELECT CASE WHEN st=1 THEN 'A' END FROM dual") == ("分岐", "medium")


def test_既存のWHERE比較とINSERT代入はOracle規則でも不変():
    assert classify_sql("WHERE col = 'X'") == ("比較", "medium")
    assert classify_sql("INSERT INTO t VALUES ('X')") == ("代入", "medium")
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_regex_classifier.py -q`
Expected: FAIL（`:=`/`DECODE` 未対応で `その他`/誤判定）

- [ ] **Step 3: 実装**

`src/grep_analyzer/classifiers/regex_classifier.py` の `_SQL_RULES` を次に置換:
```python
# spec §7（Oracle 方言）。_apply は先頭一致優先。:= を最優先にし、
# 既存 golden 等価のため WHERE比較→分岐(DECODE/CASE/||)→INSERT/UPDATE代入 の順。
_SQL_RULES = [
    (re.compile(r":="), "代入"),
    (re.compile(r"\bWHERE\b.*?[=<>]", re.IGNORECASE), "比較"),
    (re.compile(r"\bCASE\s+WHEN\b|\bDECODE\s*\(|\|\|", re.IGNORECASE), "分岐"),
    (re.compile(r"\b(?:INSERT|UPDATE)\b", re.IGNORECASE), "代入"),
]
```
`classify_sql` の docstring を更新（本体ロジック不変）:
```python
def classify_sql(line: str) -> ClassifyResult:
    """SQL行（Oracle方言）を分類する（spec §7・confidence=medium）。"""
    return _apply(_SQL_RULES, line)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_regex_classifier.py -q`
Expected: PASS（新規4本＋既存 SQL/Shell テストすべて緑）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classifiers/regex_classifier.py tests/unit/test_regex_classifier.py
git commit -m "feat(classifier): SQL を Oracle 方言規則に精密化（spec §7）"
```

---

## Task 5: Shell 分類器を方言対応（`classify_shell(line, dialect)`）

**Files:**
- Modify: `src/grep_analyzer/classifiers/regex_classifier.py`
- Test: `tests/unit/test_regex_classifier.py`

`dialect` 既定 `"bourne"` で既存 Phase 1 テスト・パイプラインを不変に保つ。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_regex_classifier.py` の末尾に追記:
```python
def test_cshellのset代入は代入と判定する():
    assert classify_shell("set CODE = \"X\"", "cshell") == ("代入", "medium")
    assert classify_shell("setenv PATH /usr/bin", "cshell") == ("代入", "medium")
    assert classify_shell("@ i = 1", "cshell") == ("代入", "medium")


def test_cshellのif括弧比較は比較と判定する():
    assert classify_shell('if ( "$x" == "X" ) then', "cshell") == ("比較", "medium")


def test_cshellのswitchは分岐と判定する():
    assert classify_shell("switch ( $x )", "cshell") == ("分岐", "medium")


def test_dialect既定bourneは従来挙動と同一():
    assert classify_shell('CODE="X"') == ("代入", "medium")
    assert classify_shell('[ "$x" = "X" ]') == ("比較", "medium")
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_regex_classifier.py -q`
Expected: FAIL（`classify_shell()` が 2 引数を受け取らない / cshell 規則未実装）

- [ ] **Step 3: 実装**

`src/grep_analyzer/classifiers/regex_classifier.py` の `_SHELL_RULES` 定義（`(re.compile(r"^\s*\w+="), "代入") ...` の 3 行）を次に置換:
```python
_SHELL_RULES_BOURNE = [
    (re.compile(r"^\s*\w+="), "代入"),
    (re.compile(r"\[\s+.+?(?:=|==|-eq)\s+.+?\]"), "比較"),
    (re.compile(r"^\s*case\s+"), "分岐"),
]
# spec §7 C系シェル。代入: set V=/setenv V/@ V=、比較: if(/while(、分岐: switch(/case ...:/breaksw
_SHELL_RULES_CSHELL = [
    (re.compile(r"^\s*(?:set\s+\w+\s*=|setenv\s+\w+|@\s+\w+\s*=)"), "代入"),
    (re.compile(r"^\s*(?:if|while)\s*\("), "比較"),
    (re.compile(r"^\s*switch\s*\(|^\s*case\s+.+:|^\s*breaksw\b"), "分岐"),
]
```
同ファイルの `classify_shell` を次に全置換:
```python
def classify_shell(line: str, dialect: str = "bourne") -> ClassifyResult:
    """Shell行を分類する（spec §7・confidence=medium）。

    dialect="cshell" のとき csh/tcsh 規則、それ以外（既定）は bourne 規則。
    """
    rules = _SHELL_RULES_CSHELL if dialect == "cshell" else _SHELL_RULES_BOURNE
    return _apply(rules, line)
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_regex_classifier.py tests/unit/test_pipeline.py -q`
Expected: PASS（既定 bourne によりパイプライン経路も不変）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/classifiers/regex_classifier.py tests/unit/test_regex_classifier.py
git commit -m "feat(classifier): Shell を bourne/cshell 二方言対応（spec §7）"
```

---

## Task 6: 追跡シンボル抽出 `chase.py`（Oracle/bourne/cshell 代入左辺）

**Files:**
- Create: `src/grep_analyzer/chase.py`
- Test: `tests/unit/test_chase.py`

spec §15 フェーズ1.5 / §8.1: Phase 2 不動点エンジンが消費する抽出規則を**純関数として unit で固定**する（本 Phase ではパイプライン非配線。Phase 2 前に正しさを確定し追跡 golden の誤固定を防ぐ）。バインド `:v`／置換 `&v` は外部境界＝非抽出（spec §8.1/§8.4）。

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_chase.py`:
```python
"""追跡シンボル抽出規則の仕様（spec §8.1・Phase 2 が消費）。"""

from grep_analyzer.chase import extract_var_symbols


def test_Oracleの代入左辺を抽出する():
    assert extract_var_symbols("sql", "", "v_code := 'X';") == ["v_code"]


def test_Oracleのバインド変数と置換変数は抽出しない():
    assert extract_var_symbols("sql", "", ":bind := 1") == []
    assert extract_var_symbols("sql", "", "WHERE c = &subst") == []


def test_bourneの変数代入左辺を抽出する():
    assert extract_var_symbols("shell", "bourne", 'CODE="X"') == ["CODE"]
    assert extract_var_symbols("shell", "bourne", 'echo "$CODE"') == []


def test_cshellのset_setenv_atの左辺を抽出する():
    assert extract_var_symbols("shell", "cshell", 'set CODE = "X"') == ["CODE"]
    assert extract_var_symbols("shell", "cshell", "setenv PATH /usr/bin") == ["PATH"]
    assert extract_var_symbols("shell", "cshell", "@ i = 1") == ["i"]


def test_対象外言語と該当なしは空リスト():
    assert extract_var_symbols("java", "", 'String K = "X";') == []
    assert extract_var_symbols("sql", "", "SELECT 1 FROM dual") == []
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'grep_analyzer.chase'`）

- [ ] **Step 3: 実装**

`src/grep_analyzer/chase.py`:
```python
"""追跡シンボル抽出規則（spec §8.1）。Phase 2 不動点エンジンが消費する純関数。

Phase 1.5 では direct パイプラインには配線せず、抽出規則の正しさを unit で固定する
（spec §15 フェーズ1.5: Oracle/csh 代入抽出を Phase 2 前に確定し golden 誤固定を防ぐ）。
"""

import re

# 代入左辺の識別子。Oracle は直前が : / & のもの（バインド/置換変数）を除外（spec §8.4）。
_ORACLE_ASSIGN_RE = re.compile(r"(?<![:&])\b([A-Za-z_]\w*)\s*:=")
_BOURNE_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)=")
_CSHELL_ASSIGN_RE = re.compile(
    r"^\s*(?:set\s+([A-Za-z_]\w*)\s*=|setenv\s+([A-Za-z_]\w*)\b|@\s+([A-Za-z_]\w*)\s*=)"
)


def extract_var_symbols(language: str, dialect: str, line: str) -> list[str]:
    """1行から indirect:var 追跡シンボル（代入の左辺識別子）を決定的に抽出する。

    - SQL(Oracle): PL/SQL `var := 式` の左辺。バインド `:v`／置換 `&v` は非抽出。
    - Shell(bourne): 行頭 `var=` の左辺。
    - Shell(cshell): `set v =`／`setenv V`／`@ v =` の左辺。
    対象外言語・該当なしは空リスト。
    """
    if language == "sql":
        return [m.group(1) for m in _ORACLE_ASSIGN_RE.finditer(line)]
    if language == "shell" and dialect == "cshell":
        out: list[str] = []
        for m in _CSHELL_ASSIGN_RE.finditer(line):
            out.append(next(g for g in m.groups() if g))
        return out
    if language == "shell":
        m = _BOURNE_ASSIGN_RE.match(line)
        return [m.group(1)] if m else []
    return []
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/unit/test_chase.py -q`
Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/chase.py tests/unit/test_chase.py
git commit -m "feat(chase): Oracle/bourne/cshell 代入抽出規則（spec §8.1・Phase2 入力）"
```

---

## Task 7: パイプライン配線（方言伝播・SQL=Oracle・`unsupported_shebang` 診断）

**Files:**
- Modify: `src/grep_analyzer/pipeline.py`
- Test: `tests/integration/test_pipeline_dialect.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_pipeline_dialect.py`:
```python
"""方言伝播と非シェルシェバン診断の境界契約（spec §5.1/§7/§8.4）。"""

from pathlib import Path

from grep_analyzer.pipeline import run


def test_csh拡張子は方言cshellで分類されshell言語で出力される(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "r.csh").write_text('set CODE = "X"\n', "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "CODE.grep").write_text('r.csh:1:set CODE = "X"\n', "utf-8")
    out = tmp_path / "out"
    assert run(input_dir=inp, output_dir=out, source_root=src) == 0
    tsv = (out / "CODE.tsv").read_text("utf-8-sig").splitlines()
    row = dict(zip(tsv[0].split("\t"), tsv[1].split("\t")))
    assert row["language"] == "shell"
    assert row["category"] == "代入"
    assert row["confidence"] == "medium"


def test_非シェルシェバンはunsupported_shebangを診断に出す(tmp_path: Path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "tool").write_text("#!/usr/bin/perl\nmy $x='X';\n", "utf-8")
    inp = tmp_path / "input"
    inp.mkdir()
    (inp / "X.grep").write_text("tool:2:my $x='X';\n", "utf-8")
    out = tmp_path / "out"
    assert run(input_dir=inp, output_dir=out, source_root=src) == 0
    assert "unsupported_shebang" in (out / "diagnostics.txt").read_text("utf-8")
```

- [ ] **Step 2: 失敗を確認**

Run: `python -m pytest tests/integration/test_pipeline_dialect.py -q`
Expected: FAIL（方言未伝播で cshell が `その他`、`unsupported_shebang` 未記録）

- [ ] **Step 3: 実装**

`src/grep_analyzer/pipeline.py` を次に全置換:
```python
"""direct-only パイプライン（spec §15 フェーズ1/1.5）。多ホップ追跡は Phase 2。"""

from pathlib import Path

from grep_analyzer.classifiers.regex_classifier import classify_shell, classify_sql
from grep_analyzer.classifiers.ts_classifier import classify_ts
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.dispatch import (
    detect_language,
    detect_shell_dialect,
    shebang_dialect,
)
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.ingest import parse_grep_line
from grep_analyzer.model import Hit
from grep_analyzer.tsv import write_tsv


def _classify(language: str, dialect: str, file_text: str, lineno: int, content: str):
    if language in ("java", "c", "proc"):
        return classify_ts(language, file_text, lineno)
    if language == "sql":
        return classify_sql(content)
    if language == "shell":
        return classify_shell(content, dialect)
    # 未知言語は bourne shell 規則にフォールバック（Phase 2 で言語追加時は
    # dispatch と本関数の両方を更新すること）
    return classify_shell(content, "bourne")


def run(input_dir: Path, output_dir: Path, source_root: Path) -> int:
    """input/*.grep を処理し、キーワード毎TSV＋diagnostics.txt を出力する。"""
    diag = Diagnostics()
    output_dir.mkdir(parents=True, exist_ok=True)

    for grep_file in sorted(Path(input_dir).glob("*.grep")):
        keyword = grep_file.stem
        raw_bytes = grep_file.read_bytes()
        text, _, _ = decode_bytes(raw_bytes, DEFAULT_FALLBACK)
        hits: list[Hit] = []

        for raw_line in text.splitlines():
            parsed = parse_grep_line(raw_line)
            if parsed is None:
                diag.add("bad_grep_line", f"{grep_file.name}: {raw_line!r}")
                continue
            rel, lineno, content = parsed
            target = Path(source_root) / rel
            if not target.is_file():
                diag.add("missing_source", str(rel))
                continue
            file_text, enc, replaced = decode_bytes(target.read_bytes(), DEFAULT_FALLBACK)
            if replaced:
                diag.add("decode_replaced", str(rel))
            sample = file_text[:4096]
            language = detect_language(rel, sample, {})
            dialect = detect_shell_dialect(rel, sample) if language == "shell" else "bourne"
            # 非シェルのシェバンで Shell 判定されなかった場合は §8.4 として明示
            if language != "shell" and shebang_dialect(sample) == "other":
                diag.add("unsupported_shebang", str(rel))
            category, confidence = _classify(language, dialect, file_text, lineno, content)
            hits.append(Hit(
                keyword=keyword, language=language, file=rel, lineno=lineno,
                ref_kind="direct", category=category, category_sub="",
                usage_summary=f"{category} ({language})", via_symbol="",
                chain=f"{keyword}@{rel}:{lineno}", snippet=content,
                encoding=enc + (" 要確認" if replaced else ""), confidence=confidence,
            ))

        write_tsv(output_dir / f"{keyword}.tsv", hits, "utf-8-sig")

    (output_dir / "diagnostics.txt").write_text(diag.render(), encoding="utf-8")
    return 0
```

- [ ] **Step 4: テストが通ることを確認**

Run: `python -m pytest tests/integration/test_pipeline_dialect.py tests/unit/test_pipeline.py -q`
Expected: PASS（新規 integration ＋ 既存 pipeline unit すべて緑）

- [ ] **Step 5: コミット**

```bash
git add src/grep_analyzer/pipeline.py tests/integration/test_pipeline_dialect.py
git commit -m "feat(pipeline): 方言伝播・SQL=Oracle・unsupported_shebang 診断（spec §5.1/§8.4）"
```

---

## Task 8: golden 追加（Oracle/csh/拡張子なし）＋既存6不変確認

**Files:**
- Create: `tests/golden/cases/oracle_direct/{src/o.sql,input/X.grep,expected/X.tsv}`
- Create: `tests/golden/cases/csh_direct/{src/run.csh,input/CODE.grep,expected/CODE.tsv}`
- Create: `tests/golden/cases/csh_noext_shebang/{src/deploy,input/CODE.grep,expected/CODE.tsv}`
- Create: `tests/golden/cases/sh_noext_shebang/{src/backup,input/CODE.grep,expected/CODE.tsv}`

> spec §11 必須回帰のうち「Oracle 方言（`:=`・`DECODE`）」「C系シェル（`set var =`・拡張子なし＋`#!/bin/csh`）」「拡張子なし bourne（`#!/bin/sh`）」を Phase 1.5（direct のみ）で満たす。`tests/golden/conftest.py` は `cases/*/` を自動 parametrize し `expected/*.tsv` のみ照合する（diagnostics は照合外＝`unsupported_shebang` は Task 7 の integration で担保）。`category_sub` 空固定。

- [ ] **Step 1: 失敗を確認（ケース未作成）**

Run: `python -m pytest tests/golden/test_golden.py -q`
Expected: 既存6ケースは PASS（このタスクで壊さない）。新規ケースはまだ無いため parametrize 対象外＝この時点では「追加すべきケースが存在しない」状態。Step 3 で作成後に Step 4 で検証する。

- [ ] **Step 2: ソースと grep 入力を作成**

`tests/golden/cases/oracle_direct/src/o.sql`:
```sql
v_code VARCHAR2(10);
v_code := 'X';
SELECT DECODE(st,1,'OK','NG') FROM dual;
```
`tests/golden/cases/oracle_direct/input/X.grep`:
```
o.sql:2:v_code := 'X';
o.sql:3:SELECT DECODE(st,1,'OK','NG') FROM dual;
```

`tests/golden/cases/csh_direct/src/run.csh`:
```csh
set CODE = "X"
if ( "$CODE" == "X" ) then
  echo hit
endif
```
`tests/golden/cases/csh_direct/input/CODE.grep`:
```
run.csh:1:set CODE = "X"
run.csh:2:if ( "$CODE" == "X" ) then
```

`tests/golden/cases/csh_noext_shebang/src/deploy`（拡張子なし・C系シェバン）:
```
#!/bin/csh
set CODE = "X"
```
`tests/golden/cases/csh_noext_shebang/input/CODE.grep`:
```
deploy:2:set CODE = "X"
```

`tests/golden/cases/sh_noext_shebang/src/backup`（拡張子なし・bourne シェバン）:
```
#!/bin/sh
CODE="X"
```
`tests/golden/cases/sh_noext_shebang/input/CODE.grep`:
```
backup:2:CODE="X"
```

- [ ] **Step 3: 期待 TSV を実行生成し目視レビューして配置**

writing-tests.md「必ず `git diff` で目視レビューしてから regen を commit」に従う。生成:
```bash
cd /workspaces/grep_helpers2
for c in oracle_direct csh_direct csh_noext_shebang sh_noext_shebang; do
  python -m grep_analyzer --input "tests/golden/cases/$c/input" \
    --output "/tmp/g15/$c" --source-root "tests/golden/cases/$c/src"
done
```
生成された `/tmp/g15/<case>/*.tsv` が下記内容（タブ区切り・末尾改行・**UTF-8 BOM 付き**）と一致することを目視確認し、一致したら各 `expected/` に配置（`cp /tmp/g15/<case>/<name>.tsv tests/golden/cases/<case>/expected/<name>.tsv`。`diagnostics.txt` は expected に含めない）。

`tests/golden/cases/oracle_direct/expected/X.tsv`（列順の内容）:
```
keyword	language	file	lineno	ref_kind	category	category_sub	usage_summary	via_symbol	chain	snippet	encoding	confidence
X	sql	o.sql	2	direct	代入		代入 (sql)		X@o.sql:2	v_code := 'X';	utf-8	medium
X	sql	o.sql	3	direct	分岐		分岐 (sql)		X@o.sql:3	SELECT DECODE(st,1,'OK','NG') FROM dual;	utf-8	medium
```

`tests/golden/cases/csh_direct/expected/CODE.tsv`:
```
keyword	language	file	lineno	ref_kind	category	category_sub	usage_summary	via_symbol	chain	snippet	encoding	confidence
CODE	shell	run.csh	1	direct	代入		代入 (shell)		CODE@run.csh:1	set CODE = "X"	utf-8	medium
CODE	shell	run.csh	2	direct	比較		比較 (shell)		CODE@run.csh:2	if ( "$CODE" == "X" ) then	utf-8	medium
```

`tests/golden/cases/csh_noext_shebang/expected/CODE.tsv`:
```
keyword	language	file	lineno	ref_kind	category	category_sub	usage_summary	via_symbol	chain	snippet	encoding	confidence
CODE	shell	deploy	2	direct	代入		代入 (shell)		CODE@deploy:2	set CODE = "X"	utf-8	medium
```

`tests/golden/cases/sh_noext_shebang/expected/CODE.tsv`:
```
keyword	language	file	lineno	ref_kind	category	category_sub	usage_summary	via_symbol	chain	snippet	encoding	confidence
CODE	shell	backup	2	direct	代入		代入 (shell)		CODE@backup:2	CODE="X"	utf-8	medium
```
生成物が上表と異なる場合は実装バグ。Task 1〜7 の該当箇所を修正してから確定する（反射的に expected を書き換えない＝writing-tests.md「alarm を殺さない」）。

- [ ] **Step 4: 既存6 golden が不変であることを確認**

Run: `python -m pytest tests/golden/test_golden.py -q && git status --porcelain tests/golden/cases/java_direct tests/golden/cases/c_direct tests/golden/cases/proc_direct tests/golden/cases/sql_direct tests/golden/cases/shell_direct tests/golden/cases/encoding_utf8`
Expected: golden 全 PASS（既存6＋新規4）。`git status --porcelain` の出力が**空**（既存6ケースの `expected/*.tsv` に変更なし＝Oracle/方言化が direct 既存挙動を壊していない）。空でなければ回帰。

- [ ] **Step 5: コミット**

```bash
git add tests/golden/cases/oracle_direct tests/golden/cases/csh_direct tests/golden/cases/csh_noext_shebang tests/golden/cases/sh_noext_shebang
git commit -m "chore(golden): Oracle/csh/拡張子なし direct 代表ケース追加（spec §11）"
```

---

## Task 9: Phase 1.5 全テスト緑化と完了確認

**Files:**
- Modify: `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テスト実行**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: 全 PASS（Phase 1 の 43 ＋ Phase 1.5 追加分。0 failed / 0 error）。失敗があれば該当 Task に戻る（完了主張しない）。

- [ ] **Step 2: spec §15 フェーズ1.5 充足をチェックリスト照合**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` §15 フェーズ1.5 の各要件と実装の対応を確認:
- §5.1 シェバン検出（拡張子なし判別）＋`.csh`/`.tcsh` → Task 1〜3（`dispatch.py` / `test_dispatch.py`）
- §7 SQL=Oracle 方言精密化 → Task 4（`regex_classifier._SQL_RULES`）
- §7 Shell の bourne/cshell 二方言 → Task 5（`regex_classifier.classify_shell`）
- §8.1 用 Oracle/csh 追跡シンボル抽出規則 → Task 6（`chase.py`）
- パイプライン方言伝播・§8.4 `unsupported_shebang` → Task 7（`pipeline.py`）
- 対応 golden の決定的拡張・既存6不変 → Task 8（`tests/golden/cases/*`）
- direct のみ・完全決定性維持 → Task 8 Step 4（既存 golden 不変）＋ Step 1 全緑

- [ ] **Step 3: 完了記録を追記しコミット**

`docs/superpowers/plans/phase0-gate-result.md` 末尾に「## Phase 1.5 完了記録」（完了日 UTC、コミット範囲、全テスト結果、上記 §15 フェーズ1.5 対応表、Phase 2 着手前提として `pyahocorasick` G1 相当が未了である旨の再掲）を追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 1.5 完了（決定的コアの方言精密化・direct-only）"
```

---

## Phase 1.5 の境界（Phase 2 以降は別計画）

- **本計画に含まない**: §8.1 不動点反復ループ・§8.3 シンボル採否ポリシー・§8.2 来歴集約/性能/degrade・`pyahocorasick`・chain 複数経路・多ホップ golden。これらは Phase 2（不動点エンジン）で、spec §8/§15 を入力に別の writing-plans で計画する。**Phase 2 着手前提**: `pyahocorasick` の §4.2 G1 相当 wheel 実証（spec §15 フェーズ2 / `phase0-gate-result.md` 申し送り）。
- `chase.py` は Phase 1.5 では純関数として unit 固定のみ（パイプライン非配線）。Phase 2 の不動点エンジンがこれを消費する。
- Phase 1.5 の成果物は「Oracle・C系シェル・拡張子なしスクリプトを正しく direct 分類し、完全決定的 TSV＋golden を出す動くツール」であり、それ単体でテスト可能・出荷可能。
