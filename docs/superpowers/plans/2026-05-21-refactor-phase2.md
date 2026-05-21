# Refactor Phase 2: chase 言語別分散化 + TSV 書込経路正本化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** chase.py の言語別分岐を `classifiers/{java,c,shell,sql}_chaser.py` に分散し、`chase.py` を薄い dispatcher に縮約する。同時に TSV 書込経路の二重実装（`tsv.write_tsv` vs `output_writer.finalize`）を R3 事前検証ゲートで判定し、正本化する。

**Architecture:**
- 各 `*_chaser.py` が `Chaser` プロトコル（extract / mask）を実装し、`classifiers/__init__.py` の `_CHASERS: dict[str, Chaser]` に eager import で自己登録する（方式α）。
- `chase.py` は public API `extract_chase_symbols` / `mask_literals` / `extract_var_symbols` を保持しつつ、内部実装を `_CHASERS[language]` に委譲する dispatcher のみに縮約。
- `ChaseSymbols` データクラスは `chase.py` から `model.py` へ移動し、`*_chaser.py` から循環依存なしに参照可能にする。
- TSV 経路は R3 ゲートで実行経路同一性を確認し、結果に応じて (a) dead code 削除、(b) 統合、(c) 並存命名整理、のいずれかを選択。
- 全 Phase で挙動 byte 不変（Inv-A）を維持。

**Tech Stack:** Python 3.12 / pytest / 標準ライブラリ `re` / dataclasses / typing.Protocol

**Related design:** `docs/superpowers/specs/2026-05-21-refactor-design.md` §6 Phase 2 [B][E], §5 R1-R4, §7 V1-V7

---

## Phase 1 引き継ぎ事項

Phase 2 plan の冒頭で記録（V5 ゲートで持ち越された Minor/Suggestion）:

| 項目 | 区分 | 扱い |
|---|---|---|
| `proc_preprocess.py:28` の `_PROC_LIT_RE` 冗長コンパイル（`MASK_PATTERNS["proc"]` を直接使えば省略可） | Minor | **Phase 2 Task 12 で対応** |
| `tests/integration/` / `tests/golden/` の `__init__.py` 不在 | Minor | 必要になった時点で対応（現状は影響なし） |
| `chase.py:43` の mid-file `from dataclasses import dataclass`（PEP8 E402） | Minor | Phase 4 に持ち越し（chase.py 全体を dispatcher 化する Phase 2 Task 11 で自然解消する可能性あり、その時点で再判定） |
| `chase.py` / `snippet.py` module docstring に残る `Phase 1.5` / `Phase 2` / `v9` 等のマーカー | Minor | Phase 4（横断パス）に持ち越し |
| `classifiers/__init__.py` の C3 docstring 不準拠 | Minor | **Phase 2 Task 10 で `_CHASERS` 追加と同時に整理** |

---

## ファイル構造（Phase 2 完了時の最終形）

```
src/grep_analyzer/
├── classifiers/
│   ├── __init__.py        ← _CHASERS registry + 規約 C3 docstring 整理
│   ├── base.py            ← Chaser Protocol を追加（既存 ClassifyResult は維持）
│   ├── java_chaser.py     ← 新規: extract / mask（Java 規則）
│   ├── c_chaser.py        ← 新規: extract / mask（C / Pro*C 規則）
│   ├── shell_chaser.py    ← 新規: extract / mask（bourne / cshell 規則）
│   ├── sql_chaser.py      ← 新規: extract / mask（Oracle 規則）
│   ├── regex_classifier.py  ← 変更なし（既存）
│   └── ts_classifier.py     ← 変更なし（既存）
├── chase.py               ← 薄い dispatcher へ縮約（public API は不変）
├── model.py               ← ChaseSymbols dataclass を追加（chase.py から移動）
├── proc_preprocess.py     ← _PROC_LIT_RE を MASK_PATTERNS["proc"] 直接参照に置換
├── tsv.py                 ← R3 ゲート結果に応じて: write_tsv 削除 or 残置（_sanitize は必ず残す）
├── output_writer.py       ← R3 ゲート結果に応じて: _sanitize の import 元を変更（必要なら）
└── ... (他は変更なし)
```

---

### Task 1: ベースライン確立

**Files:** None（測定のみ）

- [ ] **Step 1: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `252 passed, 5 skipped`（Phase 1 完了時点と一致）。

- [ ] **Step 2: ベースライン commit hash を記録**

Run: `cd /workspaces/grep_helpers2 && git rev-parse HEAD`

Expected: Phase 1 完了 hash `6cf2ca2` の 40 文字版（baseline として後続 Task で参照）。

No code changes, no commits.

---

### Task 2: R3 事前検証ゲート — TSV 書込経路の同一性検証

**Files:** None（調査のみ）

設計 §5 R3 に従い、`pipeline → output_writer.finalize` と `tsv.write_tsv` の実行経路同一性を確認する。

- [ ] **Step 1: pipeline からの実呼び出し経路を確認**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  grep -rn 'output_writer\.finalize\|tsv\.write_tsv\|from grep_analyzer\.tsv\|from grep_analyzer\.output_writer' src/ tests/
```

Expected: 各呼出箇所が列挙される。

- [ ] **Step 2: `tsv.write_tsv` の呼出元を特定**

Run:
```bash
cd /workspaces/grep_helpers2 && grep -rn 'write_tsv\b' src/ tests/
```

Expected:
- 定義: `src/grep_analyzer/tsv.py:21` のみ
- 呼出元: `tests/unit/test_tsv.py` から（おそらく）と、`pipeline.py` から（呼ばれていないなら dead code 候補）

- [ ] **Step 3: 関数本体の同等性を比較**

Read /workspaces/grep_helpers2/src/grep_analyzer/tsv.py:21-42 (`write_tsv`)
Read /workspaces/grep_helpers2/src/grep_analyzer/output_writer.py:88-130 (`finalize`)

両者の差分を以下の観点で記録:
- ソート: 両者とも `sorted(rows, key=sort_key)` → 同一
- サニタイズ: 両者とも `_sanitize` を使用 → 同一
- エンコード: 両者とも `encoding, errors="replace"` → 同一
- 原子書込: 両者とも `tempfile.mkstemp + fsync + os.replace` → 同一
- **差分**: `output_writer.finalize` は manifest 書込・part 分割・孤児クリーンを含む。`tsv.write_tsv` は単一ファイル書込のみ。

- [ ] **Step 4: R3 判定を実施**

Step 2/3 の結果から判定:

| シナリオ | 判定 | 対応 |
|---|---|---|
| `tsv.write_tsv` が src/ からは未呼出、tests/unit/test_tsv.py からのみ | **dead code in production** | `write_tsv` を削除、対応する test を `output_writer.finalize` の方に統合 or 削除（`_sanitize` は必ず残す） |
| `tsv.write_tsv` が pipeline 以外の src/ からも呼ばれている | **active legacy path** | 呼出元を `output_writer.finalize` に切替（または並存命名整理） |
| `tsv.write_tsv` が pipeline 経由で呼ばれている | **co-existing implementations** | 統合 or 並存命名整理（R1 判定） |

判定結果を Step 4 のレポートに **明示的に記録**。判定は以下 3 値のいずれか:
- `dead_code` （`tsv.write_tsv` は src/ からは未呼出、tests からのみ）
- `active_legacy` （src/ の pipeline 以外から呼ばれている）
- `co_existing` （pipeline 経由で両方使われている）

**subagent-driven 実行時の引き渡し**: controller (親 Claude) は Task 2 完了報告から判定値を読み取り、Task 3 dispatch 時の prompt に「Task 2 の判定結果: `<dead_code|active_legacy|co_existing>`」として明示的に含める。Task 3 の subagent はその判定値に応じた手順を実行する。

No code changes, no commits.

---

### Task 3: TSV 経路の正本化（R3 判定結果に応じた実装）

**Files:** Task 2 の R3 判定結果に依存（実装時に最終確定）

Task 2 の判定が「dead code in production」だった場合の手順（最頻ケースと想定）:

- [ ] **Step 1: `tsv.write_tsv` を test から切り離す（必要な場合）**

`tests/unit/test_tsv.py` が `write_tsv` を直接テストしているなら、テストは:
- (a) `output_writer.finalize` の同等動作を検証する形に書き換える、または
- (b) `_sanitize` 等の小単位テストだけ残し、`write_tsv` 経由テストは削除

判定基準: `output_writer.finalize` 経由のテストが `tests/integration/` や `tests/golden/` で既に同等のカバレッジを提供しているなら (b) を選択。

- [ ] **Step 2: `tsv.write_tsv` を削除**

`/workspaces/grep_helpers2/src/grep_analyzer/tsv.py` から `write_tsv` 関数定義を削除。`_sanitize` 関数と `_SANITIZE_MAP` 定数は **必ず残す**（`output_writer.py:16` が import している）。

削除後の tsv.py は約 18 行程度（docstring + `_SANITIZE_MAP` + `_sanitize` のみ）。

不要になった import (`os`, `tempfile`, `Path`, `TSV_COLUMNS`, `Hit`, `sort_key`) を削除。`_sanitize` の動作に必要なのは `import` 文無しのみ（標準ライブラリの `str.translate` のみ使用）。

- [ ] **Step 3: tsv.py の module docstring を更新**

旧 docstring `"""TSV出力（spec §9）。決定的全順序ソート・サニタイズ・原子的書込・BOM規則。"""`
は `write_tsv` の機能を述べているため、削除後は次に変更:

```python
"""TSV フィールドのサニタイズ規約（spec §9 規約①）。

行 / 改ページ分割クラス（\\t \\r \\n \\v \\f U+0085 U+2028 U+2029）を
半角空白 1 個に置換する `_sanitize` のみを提供する。書込本体は output_writer.py。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [E]
"""
```

- [ ] **Step 4: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: 全件 pass（test の調整があれば集計が変わる可能性あり、それは想定内）。golden 22 件 pass は必須。

Run: `cd /workspaces/grep_helpers2 && pytest tests/golden -q 2>&1 | tail -3`

Expected: 22 passed。

- [ ] **Step 5: commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/tsv.py tests/unit/test_tsv.py && \
  git commit -m "refactor(tsv): write_tsv は dead code として削除、_sanitize のみ残置（R3 判定）"
```

Task 2 の判定が「dead code in production」**ではなかった**場合:

実装方針を Task 2 のレポートで決め直し、本 Task の Step 1-5 を再設計する（plan の自動更新は subagent-driven の手順内で実施）。判定が「active legacy path」なら呼出元書換タスクを Step 1.5 として挟む、「co-existing」なら R1 判定で統合 or 並存を決める。

---

### Task 4: Chaser Protocol 追加 + ChaseSymbols を model.py へ移動 (atomic)

**Files:**
- Modify: `src/grep_analyzer/classifiers/base.py`（既存 `ClassifyResult` 型は維持、`Chaser` Protocol を追記）
- Modify: `src/grep_analyzer/model.py`（`ChaseSymbols` dataclass を追加）
- Modify: `src/grep_analyzer/chase.py`（`ChaseSymbols` 定義を削除、`model` から import）
- Modify: `src/grep_analyzer/stoplist.py`（mid-file `from grep_analyzer.chase import ChaseSymbols` を `from grep_analyzer.model import ChaseSymbols` に変更し、ファイル先頭の import セクションへ集約）
- Modify: `tests/unit/test_chase.py`（`from grep_analyzer.chase import ChaseSymbols` を `from grep_analyzer.model import ChaseSymbols` に変更）
- Modify: `tests/unit/test_stoplist.py`（同上）

注: subagent-driven の各タスク = 1 commit 原則に従い、Task 4 と旧 Task 5 を 1 タスクに統合。intermediate broken state を残さない（C-1 / M-2 反映）。

- [ ] **Step 1: model.py に ChaseSymbols を追加**

Edit `/workspaces/grep_helpers2/src/grep_analyzer/model.py`:

現状の `from dataclasses import dataclass` の直下、`Hit` 定義の前に追加:

```python
@dataclass(frozen=True)
class ChaseSymbols:
    """1 行から抽出した追跡候補。

    `constants` / `vars` は不動点で多ホップ追跡される。
    `getters` / `setters` は横展開せず、全反復で terminal として報告する。
    """

    constants: tuple[str, ...] = ()
    vars: tuple[str, ...] = ()
    getters: tuple[str, ...] = ()
    setters: tuple[str, ...] = ()
```

- [ ] **Step 2: classifiers/base.py に Chaser Protocol を追加**

Edit `/workspaces/grep_helpers2/src/grep_analyzer/classifiers/base.py`:

現状（全 4 行）:
```python
"""分類器の共通型。Phase 1 は direct 行の分類のみ（spec §15 フェーズ1）。"""

# 分類結果 = (共通上位カテゴリ, confidence)。category_sub は v1 空固定（spec §9）。
ClassifyResult = tuple[str, str]
```

変更後（属性形式の Protocol を採用 — mypy/pyright で module オブジェクトに対しても structural にマッチする形）:
```python
"""分類器の共通型と Chaser プロトコル。

ClassifyResult: direct 行の分類結果型。
Chaser: 言語別 Chaser サブモジュールが実装する抽出 IF。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from typing import Callable, Protocol

from grep_analyzer.model import ChaseSymbols

ClassifyResult = tuple[str, str]


class Chaser(Protocol):
    """言語別 Chaser モジュールの抽出 IF。

    各 `*_chaser.py` がモジュールレベルで `extract` / `mask` を関数として
    公開し、`_CHASERS[language] = module` で登録する。属性形式の Protocol
    を採用することで、module オブジェクトを `Chaser` 型として扱える
    （mypy/pyright の structural 互換性）。
    """

    extract: Callable[[str, str], ChaseSymbols]
    """(dialect, line) → ChaseSymbols。line は生行（マスクは extract 内で実施）。"""

    mask: Callable[[str], str]
    """line → masked_line。同字数空白へ置換する。"""
```

- [ ] **Step 3: chase.py から ChaseSymbols 定義を削除し、import を追加**

Edit `/workspaces/grep_helpers2/src/grep_analyzer/chase.py`:

L43 の `from dataclasses import dataclass` と L56-66 の `@dataclass(frozen=True) class ChaseSymbols: ...` を削除。

ファイル冒頭の import 部分（既存 `from grep_analyzer.patterns.*` の後）に追加:

```python
from grep_analyzer.model import ChaseSymbols
```

- [ ] **Step 4: stoplist.py の mid-file import を先頭集約 + model から import**

Edit `/workspaces/grep_helpers2/src/grep_analyzer/stoplist.py`:

L76 の mid-file `from grep_analyzer.chase import ChaseSymbols` を削除。
ファイル先頭の import セクション（`from dataclasses import dataclass` の近辺）に追加:

```python
from grep_analyzer.model import ChaseSymbols
```

L76 を削除することで PEP8 E402 違反も解消（Phase 1 引き継ぎ事項の 1 つを併せて消化）。

- [ ] **Step 5: tests/unit/test_chase.py の import を model 経由に変更**

Edit `/workspaces/grep_helpers2/tests/unit/test_chase.py`:

現状（L46 周辺の結合 import）:
```python
from grep_analyzer.chase import ChaseSymbols, extract_chase_symbols, mask_literals
```

これを 2 つの import 行に分離:
```python
from grep_analyzer.chase import extract_chase_symbols, mask_literals
from grep_analyzer.model import ChaseSymbols
```

`extract_chase_symbols` と `mask_literals` は chase の public API として維持されるため、chase 経由 import を保持。`ChaseSymbols` のみ model 経由へ。

- [ ] **Step 6: tests/unit/test_stoplist.py の import を model 経由に変更**

Edit `/workspaces/grep_helpers2/tests/unit/test_stoplist.py`:

`from grep_analyzer.chase import ChaseSymbols` を:
```python
from grep_analyzer.model import ChaseSymbols
```
に変更。

- [ ] **Step 7: 旧 import が残っていないことを確認**

Run:
```bash
cd /workspaces/grep_helpers2 && grep -rn 'from grep_analyzer\.chase import ChaseSymbols\|from grep_analyzer\.chase import.*ChaseSymbols' src/ tests/
```

Expected: 空出力（chase 経由の ChaseSymbols import が src/ tests/ から完全消滅）。

- [ ] **Step 8: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: 252 passed, 5 skipped。

Run: `cd /workspaces/grep_helpers2 && pytest tests/unit/test_chase.py tests/unit/test_model.py tests/unit/test_stoplist.py -v 2>&1 | tail -25`

Expected: 全件 PASSED。

- [ ] **Step 9: atomic commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/classifiers/base.py src/grep_analyzer/model.py src/grep_analyzer/chase.py src/grep_analyzer/stoplist.py tests/unit/test_chase.py tests/unit/test_stoplist.py && \
  git commit -m "refactor(model): ChaseSymbols を model.py へ移動 + Chaser Protocol 追加（stoplist/tests も合わせて更新）"
```

---

### Task 6: java_chaser.py 作成

**Files:**
- Create: `src/grep_analyzer/classifiers/java_chaser.py`

- [ ] **Step 1: java_chaser.py を作成**

Use Write tool to create `/workspaces/grep_helpers2/src/grep_analyzer/classifiers/java_chaser.py`:

```python
"""Java 用 Chaser — 言語別シンボル抽出とリテラルマスク。

`Chaser` プロトコル準拠のモジュールレベル関数を公開する。
chase.py の dispatcher が `_CHASERS["java"]` 経由で呼び出す。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    JAVA_CONST_RE,
    JAVA_GETSET_RE,
    JAVA_VAR_RE,
)


def mask(line: str) -> str:
    """Java のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["java"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に Java の規則で分類抽出する（dialect は無視）。

    static final 修飾子付き宣言を constant、それ以外の代入を var、
    getter/setter を terminal として収集する。
    """
    masked = mask(line)
    consts = tuple(
        g.group(2) for g in JAVA_CONST_RE.finditer(masked)
        if "static" in g.group(1).split() and "final" in g.group(1).split()
    )
    getters = tuple(
        x.group(1) for x in JAVA_GETSET_RE.finditer(masked) if x.group(1)[0] == "g"
    )
    setters = tuple(
        x.group(1) for x in JAVA_GETSET_RE.finditer(masked) if x.group(1)[0] == "s"
    )
    const_set = set(consts)
    vars_ = tuple(
        v for v in (x.group(1) for x in JAVA_VAR_RE.finditer(masked))
        if v not in const_set
    )
    return ChaseSymbols(consts, vars_, getters, setters)
```

- [ ] **Step 2: import smoke 確認 + Inv-A 回帰テスト（マスク経由の挙動互換性）**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.classifiers import java_chaser
from grep_analyzer.model import ChaseSymbols

# 基本動作
result = java_chaser.extract('', 'public static final int FOO = 1;')
assert 'FOO' in result.constants, f'expected FOO in constants, got {result}'

# マスク動作
masked = java_chaser.mask('// comment')
assert masked.strip() == '', f'expected blank after mask, got {masked!r}'

# Inv-A 回帰: マスク後の代入抽出が現行 chase.extract_chase_symbols と一致
# コメント内の代入はマスクで消えるべき
r2 = java_chaser.extract('', 'public static final int FOO = 1; // x = 2')
assert 'FOO' in r2.constants, f'FOO must be in constants: {r2}'
assert 'x' not in r2.vars, f'x in comment must not be extracted: {r2}'

# 文字列内の代入もマスクで消える
r3 = java_chaser.extract('', 'String s = \"y = 1\"; int z = 1;')
assert 'z' in r3.vars, f'z must be in vars: {r3}'
assert 'y' not in r3.vars, f'y in string literal must not be extracted: {r3}'

print('OK')
"
```

Expected: `OK`。

これは Inv-A 直接保証（マスク前/後で代入抽出結果が変わらないこと）。Phase 1 で patterns/* に regex を移した後の挙動と完全同等を確認。

- [ ] **Step 3: 既存テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -3`

Expected: 252 passed, 5 skipped (baseline 維持 — まだ chase.py 側で java_chaser は呼ばれていない)。

- [ ] **Step 4: commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/classifiers/java_chaser.py && \
  git commit -m "feat(classifiers): java_chaser.py — Java の Chaser モジュールを新設"
```

---

### Task 7: c_chaser.py 作成（C + Pro*C）

**Files:**
- Create: `src/grep_analyzer/classifiers/c_chaser.py`

- [ ] **Step 1: c_chaser.py を作成**

Use Write tool to create `/workspaces/grep_helpers2/src/grep_analyzer/classifiers/c_chaser.py`:

```python
"""C / Pro*C 用 Chaser — 言語別シンボル抽出とリテラルマスク。

C と Pro*C は同じ抽出規則を共有する（Pro*C は C のスーパーセット）。
chase.py の dispatcher が `_CHASERS["c"]` / `_CHASERS["proc"]` 経由で呼び出す。
Pro*C のホスト変数 `:var` は追跡投入しない（spec §8.1 手順1 外部・ホスト境界）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    C_CONST_RE,
    C_DEFINE_RE,
    C_VAR_RE,
)


def mask(line: str) -> str:
    """C / Pro*C のリテラル / コメントを同字数空白に置換する。

    呼び出し元の dispatcher が `language` で `_CHASERS["c"]` と `_CHASERS["proc"]`
    を切り替えるが、現行 spec では両者の MASK パターンは完全同一。
    """
    pattern = MASK_PATTERNS["c"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に C / Pro*C の規則で分類抽出する（dialect は無視）。

    `#define` と `const ... var =` を constant、それ以外の代入を var として収集。
    """
    masked = mask(line)
    consts = tuple(x.group(1) for x in C_DEFINE_RE.finditer(masked)) + tuple(
        x.group(1) for x in C_CONST_RE.finditer(masked)
    )
    const_set = set(consts)
    vars_ = tuple(
        v for v in (x.group(1) for x in C_VAR_RE.finditer(masked))
        if v not in const_set and v != "const"
    )
    return ChaseSymbols(consts, vars_, (), ())
```

- [ ] **Step 2: import smoke 確認**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.classifiers import c_chaser
r = c_chaser.extract('', '#define MAX 10')
assert 'MAX' in r.constants, f'expected MAX, got {r}'
r2 = c_chaser.extract('', 'int x = 5;')
assert 'x' in r2.vars, f'expected x in vars, got {r2}'
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: 既存テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -3`

Expected: 252 passed, 5 skipped.

- [ ] **Step 4: commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/classifiers/c_chaser.py && \
  git commit -m "feat(classifiers): c_chaser.py — C / Pro*C の Chaser モジュールを新設"
```

---

### Task 8: shell_chaser.py 作成（bourne + cshell）

**Files:**
- Create: `src/grep_analyzer/classifiers/shell_chaser.py`

- [ ] **Step 1: shell_chaser.py を作成**

Use Write tool to create `/workspaces/grep_helpers2/src/grep_analyzer/classifiers/shell_chaser.py`:

```python
"""Shell 用 Chaser — bourne / cshell 両方言を処理する。

dialect 引数で bourne / cshell を分岐する。
- bourne: 行頭 `var=` の左辺、`readonly var=` で constant 化
- cshell: `set v =` / `setenv V` / `@ v =` の左辺

chase.py の dispatcher が `_CHASERS["shell"]` 経由で呼び出す。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import (
    BOURNE_ASSIGN_RE,
    BOURNE_READONLY_RE,
    CSHELL_ASSIGN_RE,
)


def mask(line: str) -> str:
    """Shell のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["shell"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def _extract_var_symbols(dialect: str, line: str) -> list[str]:
    """マスク前の生行から代入左辺を抽出する（dispatcher 向け公開ヘルパ）。

    dialect=cshell: `set v =` / `setenv V` / `@ v =` の左辺
    dialect=その他: 行頭 `var=` の左辺
    """
    if dialect == "cshell":
        out: list[str] = []
        for m in CSHELL_ASSIGN_RE.finditer(line):
            out.append(next(g for g in m.groups() if g))
        return out
    m = BOURNE_ASSIGN_RE.match(line)
    return [m.group(1)] if m else []


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に shell の規則で分類抽出する。

    bourne: `readonly v=` を constant、それ以外の代入を var
    cshell: 代入をすべて var として収集
    """
    masked = mask(line)
    if dialect != "cshell":
        rm = BOURNE_READONLY_RE.match(masked)
        if rm is not None:
            return ChaseSymbols((rm.group(1),), (), (), ())
    return ChaseSymbols((), tuple(_extract_var_symbols(dialect, masked)), (), ())
```

- [ ] **Step 2: import smoke 確認**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.classifiers import shell_chaser
r = shell_chaser.extract('bourne', 'FOO=bar')
assert 'FOO' in r.vars, f'expected FOO in vars, got {r}'
r2 = shell_chaser.extract('bourne', 'readonly C=1')
assert 'C' in r2.constants, f'expected C in constants, got {r2}'
r3 = shell_chaser.extract('cshell', 'set v = 1')
assert 'v' in r3.vars, f'expected v in vars (cshell), got {r3}'
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: 既存テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -3`

Expected: 252 passed, 5 skipped.

- [ ] **Step 4: commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/classifiers/shell_chaser.py && \
  git commit -m "feat(classifiers): shell_chaser.py — Shell（bourne/cshell）の Chaser モジュールを新設"
```

---

### Task 9: sql_chaser.py 作成（Oracle）

**Files:**
- Create: `src/grep_analyzer/classifiers/sql_chaser.py`

- [ ] **Step 1: sql_chaser.py を作成**

Use Write tool to create `/workspaces/grep_helpers2/src/grep_analyzer/classifiers/sql_chaser.py`:

```python
"""SQL (Oracle PL/SQL) 用 Chaser — 言語別シンボル抽出とリテラルマスク。

PL/SQL の `var := 式` の左辺を var として抽出する。
バインド変数 `:v` / 置換変数 `&v` は ORACLE_ASSIGN_RE の lookbehind で除外。
constant / getter / setter は SQL では発生しないため常に空タプル。

chase.py の dispatcher が `_CHASERS["sql"]` 経由で呼び出す。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from grep_analyzer.model import ChaseSymbols
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
from grep_analyzer.patterns.symbol_extraction import ORACLE_ASSIGN_RE


def mask(line: str) -> str:
    """SQL のリテラル / コメントを同字数空白に置換する。"""
    pattern = MASK_PATTERNS["sql"]
    return pattern.sub(lambda m: " " * len(m.group(0)), line)


def _extract_var_symbols(dialect: str, line: str) -> list[str]:
    """マスク前の生行から PL/SQL `:=` の左辺を抽出する。"""
    return [m.group(1) for m in ORACLE_ASSIGN_RE.finditer(line)]


def extract(dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に SQL の規則で分類抽出する（dialect は無視）。"""
    masked = mask(line)
    return ChaseSymbols((), tuple(_extract_var_symbols(dialect, masked)), (), ())
```

- [ ] **Step 2: import smoke 確認**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.classifiers import sql_chaser
r = sql_chaser.extract('', 'v := 1;')
assert 'v' in r.vars, f'expected v in vars, got {r}'
r2 = sql_chaser.extract('', 'SELECT :host FROM dual;')  # bind var must NOT be extracted
assert 'host' not in r2.vars, f'host bind var should NOT be extracted, got {r2}'
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: 既存テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -3`

Expected: 252 passed, 5 skipped.

- [ ] **Step 4: commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/classifiers/sql_chaser.py && \
  git commit -m "feat(classifiers): sql_chaser.py — SQL (Oracle PL/SQL) の Chaser モジュールを新設"
```

---

### Task 10: classifiers/__init__.py に _CHASERS registry を追加

**Files:**
- Modify: `src/grep_analyzer/classifiers/__init__.py`

- [ ] **Step 1: __init__.py を書き換え**

Use Write tool to replace `/workspaces/grep_helpers2/src/grep_analyzer/classifiers/__init__.py` content:

```python
"""言語別 Chaser / Classifier モジュール群と Chaser registry。

`_CHASERS` は方式α（eager import）で各 *_chaser.py を import 時に登録する。
chase.py の dispatcher が `_CHASERS[language]` で対応モジュールを取得する。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from grep_analyzer.classifiers import (
    c_chaser,
    java_chaser,
    shell_chaser,
    sql_chaser,
)
from grep_analyzer.classifiers.base import Chaser

_CHASERS: dict[str, Chaser] = {
    "java": java_chaser,
    "c": c_chaser,
    "proc": c_chaser,
    "shell": shell_chaser,
    "sql": sql_chaser,
}

__all__ = ["_CHASERS", "Chaser"]
```

注: `_CHASERS["proc"] = c_chaser` は、Pro*C が C と同じ Chaser を共有するため。

- [ ] **Step 2: import smoke 確認**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.classifiers import _CHASERS, Chaser
assert set(_CHASERS.keys()) == {'java', 'c', 'proc', 'shell', 'sql'}, _CHASERS.keys()
assert _CHASERS['proc'] is _CHASERS['c'], 'proc must share c_chaser'
r = _CHASERS['java'].extract('', 'public static final int X = 1;')
assert 'X' in r.constants
print('OK')
"
```

Expected: `OK`

- [ ] **Step 3: cyclic import 実機検証**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
import grep_analyzer
import grep_analyzer.cli
import grep_analyzer.fixedpoint
import grep_analyzer.snippet
import grep_analyzer.chase
import grep_analyzer.classifiers
print('all imports OK')
"
```

Expected: `all imports OK`

- [ ] **Step 4: 既存テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -3`

Expected: 252 passed, 5 skipped.

- [ ] **Step 5: commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/classifiers/__init__.py && \
  git commit -m "feat(classifiers): _CHASERS registry を __init__ に追加（方式α: eager import）"
```

---

### Task 11: chase.py を dispatcher 化

**Files:**
- Modify: `src/grep_analyzer/chase.py`（dispatcher のみに縮約）

これが Phase 2 [B] の中核タスク。chase.py の現状 96 行が約 40-50 行（dispatcher のみ）に縮約される。

**事前検証**: 実装前に `MASK_PATTERNS` と `_CHASERS` の言語キー集合が一致することを assert する（M-3 反映）。これにより `mask_literals` の旧挙動（`MASK_PATTERNS.get(language)` → `None` 時に原行返却）と新 dispatcher 経由（`_CHASERS.get(language)` → `None` 時に原行返却）の挙動同等性が構造的に保証される。

```bash
cd /workspaces/grep_helpers2 && python -c "
from grep_analyzer.classifiers import _CHASERS
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS
assert set(MASK_PATTERNS.keys()) == set(_CHASERS.keys()), \
    f'key mismatch: MASK_PATTERNS={set(MASK_PATTERNS.keys())} vs _CHASERS={set(_CHASERS.keys())}'
print('key set match OK:', sorted(_CHASERS.keys()))
"
```

Expected: `key set match OK: ['c', 'java', 'proc', 'shell', 'sql']`。キー不一致なら BLOCKED 報告（Task 6-9 / Task 10 のいずれかでキー追加漏れ）。

**masked vs raw 引数の論点**（M2 反映）: 旧 `extract_chase_symbols` は内部で `mask_literals` してから `extract_var_symbols(language, dialect, masked)` を呼んでいた（chase.py:95）。新 dispatcher の `extract_chase_symbols` は `chaser.extract(dialect, line)` に **生行** を渡し、各 Chaser の `extract` が内部で `mask` を呼ぶ実装になる（Task 6-9 で確認済）。そのため、生行を渡しても Chaser 内で一度マスクされ、結果は旧実装と完全同等。`_extract_var_symbols` も同様に各 Chaser 内で `masked` を受けて動作する（shell_chaser:_extract_var_symbols / sql_chaser:_extract_var_symbols）。

**`_extract_var_symbols` が leaky private API である件**: chase.py dispatcher が `_extract_var_symbols` を shell_chaser / sql_chaser から import するのは、`extract_var_symbols` (fixedpoint が直接呼ぶ言語非依存 IF) と `Chaser.extract` (Chaser Protocol) が **別経路** だから。java / c は `extract_var_symbols` が空リストを返す既存挙動を維持するため、Chaser に第 3 メソッドを追加しなくて済むよう dispatcher の if 分岐で表現する。Phase 4 横断 rename で再整理する候補（regex `_extract_var_symbols` を `extract_var_assignments` 等に rename しつつ、Chaser に第 3 メソッドとして追加する選択肢あり）。

- [ ] **Step 1: chase.py を dispatcher 化**

Replace `/workspaces/grep_helpers2/src/grep_analyzer/chase.py` entirely with:

```python
"""追跡シンボル抽出 dispatcher。

各言語の規則は `classifiers/{java,c,shell,sql}_chaser.py` に分散され、
`_CHASERS[language]` で取得する。本ファイルは public API
（extract_var_symbols / mask_literals / extract_chase_symbols）を保持しつつ
内部実装を Chaser に委譲する薄い dispatcher のみ。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 2 [B]
"""

from grep_analyzer.classifiers import _CHASERS
from grep_analyzer.classifiers.shell_chaser import _extract_var_symbols as _shell_extract
from grep_analyzer.classifiers.sql_chaser import _extract_var_symbols as _sql_extract
from grep_analyzer.model import ChaseSymbols


def extract_var_symbols(language: str, dialect: str, line: str) -> list[str]:
    """1 行から indirect:var 追跡シンボル（代入の左辺識別子）を抽出する。

    fixedpoint の `_ingest` が言語非依存の var シンボル列を必要とするため、
    Chaser を経由せず直接対応する `*_chaser._extract_var_symbols` を呼ぶ。
    対象外言語・該当なしは空リスト。
    """
    if language == "sql":
        return _sql_extract(dialect, line)
    if language == "shell":
        return _shell_extract(dialect, line)
    return []


def mask_literals(language: str, line: str) -> str:
    """文字列リテラル・コメントを同字数空白に置換する。

    言語が登録されていない場合は原行をそのまま返す（既存 behavior 保持）。
    """
    chaser = _CHASERS.get(language)
    return line if chaser is None else chaser.mask(line)


def extract_chase_symbols(language: str, dialect: str, line: str) -> ChaseSymbols:
    """1 行をマスク後に言語別 Chaser で分類抽出する（決定的・出現順）。

    対象外言語は空の ChaseSymbols を返す。
    """
    chaser = _CHASERS.get(language)
    if chaser is None:
        return ChaseSymbols()
    return chaser.extract(dialect, line)
```

注意点:
- `_extract_var_symbols` は shell_chaser と sql_chaser が公開する内部ヘルパ（Task 8/9 で `_` プレフィックス付きで定義済）。`chase.py` は両者を `_shell_extract` / `_sql_extract` として import し、`extract_var_symbols` 内で言語別に dispatch する。
- 旧 `extract_var_symbols` で java / c は空リストを返していたため、それと一致する挙動。
- `mask_literals` と `extract_chase_symbols` は `_CHASERS` 経由で完全に dispatcher 化。
- public API（3 関数）のシグネチャと挙動は完全に保持される。

- [ ] **Step 2: 旧 import / 旧定義が残っていないことを確認**

Run: `cd /workspaces/grep_helpers2 && grep -n 'patterns\|dataclasses' src/grep_analyzer/chase.py`

Expected: 空出力（chase.py からは patterns/* への直接 import が消え、dataclasses の mid-file import も消える）。

- [ ] **Step 3: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: 252 passed, 5 skipped。特に `tests/unit/test_chase.py` が全件 PASSED。

Run: `cd /workspaces/grep_helpers2 && pytest tests/unit/test_chase.py -v 2>&1 | tail -25`

Expected: 全 15 件 PASSED。

- [ ] **Step 4: golden test pass（Inv-A）**

Run: `cd /workspaces/grep_helpers2 && pytest tests/golden -q 2>&1 | tail -3`

Expected: 22 passed。

- [ ] **Step 5: commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/chase.py && \
  git commit -m "refactor(chase): 言語別ロジックを classifiers/*_chaser に委譲し dispatcher に縮約"
```

---

### Task 12: proc_preprocess.py の _PROC_LIT_RE 改善（Phase 1 引き継ぎ）

**Files:**
- Modify: `src/grep_analyzer/proc_preprocess.py`

Phase 1 V5 ゲートで Suggestion として記録された改善。`MASK_PATTERNS["proc"]` を直接使えば `_PROC_LIT_RE` の冗長コンパイルが不要になる。

- [ ] **Step 1: 現状確認**

Read /workspaces/grep_helpers2/src/grep_analyzer/proc_preprocess.py and find the `_PROC_LIT_RE` definition (around L28) and its usages.

期待される現状:
```python
from grep_analyzer.patterns.literal_masking import MASK_SPECS
# ...
_PROC_LIT_RE = re.compile("|".join(MASK_SPECS["proc"]), re.DOTALL)
```

- [ ] **Step 2: import と定義を整理**

`MASK_SPECS` import を `MASK_PATTERNS` import に変更（既にコンパイル済みの dict を使う）:

旧:
```python
from grep_analyzer.patterns.literal_masking import MASK_SPECS
# ...
_PROC_LIT_RE = re.compile("|".join(MASK_SPECS["proc"]), re.DOTALL)
```

新:
```python
from grep_analyzer.patterns.literal_masking import MASK_PATTERNS

_PROC_LIT_RE = MASK_PATTERNS["proc"]
```

注: もし他の場所で `MASK_SPECS` を直接使っているなら（grep で確認）、その箇所は維持して `MASK_SPECS` も import する。

Run: `cd /workspaces/grep_helpers2 && grep -n 'MASK_SPECS' src/grep_analyzer/proc_preprocess.py`

Expected: `_PROC_LIT_RE = ...` 行（修正対象）のみ。他に MASK_SPECS 使用が無ければ MASK_SPECS import を削除可。

- [ ] **Step 3: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -3`

Expected: 252 passed, 5 skipped。

特に `tests/unit/test_proc_preprocess.py` が全件 PASSED。

- [ ] **Step 4: commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/proc_preprocess.py && \
  git commit -m "refactor(proc_preprocess): _PROC_LIT_RE を MASK_PATTERNS['proc'] 直接参照に置換（冗長コンパイル除去）"
```

---

### Task 13: V3 import グラフ層分離検証

**Files:** None（検証のみ）

- [ ] **Step 1: cyclic import 実機検証**

Run:
```bash
cd /workspaces/grep_helpers2 && python -c "
import grep_analyzer
import grep_analyzer.cli
import grep_analyzer.fixedpoint
import grep_analyzer.snippet
import grep_analyzer.chase
import grep_analyzer.classifiers
import grep_analyzer.classifiers.java_chaser
import grep_analyzer.classifiers.c_chaser
import grep_analyzer.classifiers.shell_chaser
import grep_analyzer.classifiers.sql_chaser
print('all imports OK')
"
```

Expected: `all imports OK`。

- [ ] **Step 2: pytest collection 確認**

Run: `cd /workspaces/grep_helpers2 && pytest --collect-only -q 2>&1 | tail -5`

Expected: 257 tests collected (Phase 1 末尾と一致)、ERROR / ImportError なし。

- [ ] **Step 3: 各 *_chaser.py が patterns/* と model のみに依存していることを確認**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  grep -rn 'from grep_analyzer' src/grep_analyzer/classifiers/*_chaser.py
```

Expected: 各 `*_chaser.py` が次のみを import:
- `from grep_analyzer.model import ChaseSymbols`
- `from grep_analyzer.patterns.literal_masking import MASK_PATTERNS`
- `from grep_analyzer.patterns.symbol_extraction import ...`

→ `fixedpoint`, `ingest`, `spill`, `pipeline` 等への逆依存が無いこと。

- [ ] **Step 4: 設計 §7 V3 の禁止逆依存を機械チェック**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  echo "=== classifiers/* → fixedpoint, pipeline, ingest, spill (PROHIBITED) ===" && \
  grep -rn 'from grep_analyzer\.\(fixedpoint\|pipeline\|ingest\|spill\)' src/grep_analyzer/classifiers/ && \
  echo "=== patterns/* → 上位 (PROHIBITED) ===" && \
  grep -rn 'from grep_analyzer\.\(chase\|classifiers\|snippet\|fixedpoint\|pipeline\)' src/grep_analyzer/patterns/ && \
  echo "=== model → 下位以外 (PROHIBITED) ===" && \
  grep -n 'from grep_analyzer' src/grep_analyzer/model.py
```

Expected: 全 3 セクションで「`=== ... ===`」行のみ表示され、実際の grep 結果は空（禁止逆依存なし）。

No code changes, no commits.

---

### Task 14: V1 Inv-A byte 不変確認

**Files:** None（検証のみ）

- [ ] **Step 1: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest 2>&1 | tail -10`

Expected: passed の集計行で fail / error がゼロ。tests/golden / tests/integration / tests/unit / tests/test_smoke.py の各分類が pass。

- [ ] **Step 2: golden test pass (Inv-A 直接保証)**

Run: `cd /workspaces/grep_helpers2 && pytest tests/golden -v 2>&1 | tail -25`

Expected: tests/golden 配下の 22 ケース全件 PASSED。

- [ ] **Step 3: Phase 2 ベースラインからの commit リスト**

Run: `cd /workspaces/grep_helpers2 && git log --oneline 6cf2ca2..HEAD`

Expected: Phase 2 の commit 一覧。Task 3 / Task 4 / Task 6 / Task 7 / Task 8 / Task 9 / Task 10 / Task 11 / Task 12 の 9 commit。Task 5 はラベル統合により独立 commit を持たない（Task 4 に atomic に含まれる）。Task 4-5 を 1 commit にまとめる atomic 設計のため、計数は 9 件で正しい。

- [ ] **Step 4: ファイル構造確認**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  ls src/grep_analyzer/classifiers/ && \
  echo "---" && \
  wc -l src/grep_analyzer/chase.py
```

Expected:
- `classifiers/` 配下に 7 ファイル: `__init__.py`, `base.py`, `c_chaser.py`, `java_chaser.py`, `regex_classifier.py`, `shell_chaser.py`, `sql_chaser.py`, `ts_classifier.py`（合計 8 ファイル — `__init__.py` 込み）
- `chase.py` が約 40-50 行（dispatcher のみに縮約）

No code changes, no commits.

---

### Task 15: V5 完了 AI レビューゲート

**Files:** None（レビューのみ。指摘反映があれば対応）

- [ ] **Step 1: 批判的 AI レビューを並列 2 件で起動**

Phase 2 完了状態の `src/grep_analyzer/` を対象に、独立 2 視点で批判的レビュー。

**観点 A — 設計 §6 Phase 2 [B][E] と §5 R1-R4 規約 への準拠**:
- chase.py の dispatcher 化が完全か（言語別ロジックが残っていないか）
- 各 *_chaser.py の境界が明確か（責務混在無し）
- _CHASERS registry の方式α実装が正しく機能しているか
- R3 ゲートの判定が妥当だったか（TSV 経路）
- Inv-A〜E 維持

**観点 B — 命名規約 N1-N4 / コメント規約 C1-C5 / Refactoring Discipline R1-R4 への準拠**:
- 新規ファイルの命名（`*_chaser.py` の suffix 一貫性）
- module docstring の C3 形式準拠
- Phase 1 引き継ぎ事項（特に Task 12）が反映されているか
- 新規導入された dead code / 未使用 import がないか
- R1 DRY 誤適用（似た形の Chaser が形式的に統合されていないか）

各レビューは Critical / Major / Minor / Suggestion に分類して報告させる。

- [ ] **Step 2: 指摘の反映**

- **Critical / Major**: 即座に反映 → Step 1 から再実施（2 巡目）
- **Minor / Suggestion**: 次 Phase（Phase 3 plan）の冒頭に「前 Phase 引き継ぎ事項」として記録

- [ ] **Step 3: V5 通過条件の確認**

Critical / Major の指摘数がゼロになっていることを確認。最低 2 巡を満たしていれば Phase 2 完了。

- [ ] **Step 4: Phase 2 完了の最終 commit（必要に応じて）**

レビュー反映が無ければ追加 commit 不要。反映があれば commit を追加。

---

## Phase 2 完了サマリ

すべての Task が完了した時点で:

- ✅ `chase.py` が約 40-50 行の薄い dispatcher に縮約
- ✅ `classifiers/` 配下に 4 つの `*_chaser.py` が新設され、言語別ロジックが分離
- ✅ `classifiers/__init__.py` に `_CHASERS` registry が追加
- ✅ `classifiers/base.py` に `Chaser` Protocol が定義
- ✅ `ChaseSymbols` が `model.py` に移動（共有用ドメインモデル）
- ✅ `proc_preprocess.py` の `_PROC_LIT_RE` 冗長コンパイル除去（Phase 1 引き継ぎ事項解消）
- ✅ R3 ゲートで TSV 経路を正本化（`tsv.write_tsv` の dead code 削除 or 統合判定）
- ✅ 全テスト pass、golden byte 完全一致（Inv-A〜E 全件維持）
- ✅ V3 import グラフが葉→ルート一方向、新規逆依存なし
- ✅ V5 AI レビューが Critical / Major ゼロに収束

→ Phase 3（snippet 責務分割 + fixedpoint ChaseState 化）の plan 作成へ進む。
