# Refactor Phase 4: 命名・コメントの全モジュール横断適用 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Phase 1〜3 で構造確定したコード全体に対し、N1〜N4 命名規約と C1〜C5 コメント規約を横断適用する。さらに Phase 3 から持ち越した技術債務（`_estimate_items` 動的参照清潔化、`_REF_KIND` 所在移動、private 接頭辞整理など）を解消する。挙動は byte 不変（Inv-A〜E 全保持）。

**Architecture:**
- N1〜N4: 略語 → フルスペル、述語/動詞 統一、ドメイン語彙固定、ループ慣用識別子除外
- C1〜C5: 識別子で伝わるコメント削除、spec 参照を `Related:` に集約、フェーズ/版マーカー除去
- Phase 3 引き継ぎの技術債務を Task 群で個別解消
- 設計 §7 V7 の適用順序: N1〜N4 inventory → rename → C1〜C5 適用 → R1 再検査

**Tech Stack:** Python 3.12 / pytest / ripgrep / grep ベースの inventory

**Related design:** `docs/superpowers/specs/2026-05-21-refactor-design.md` §3 N1-N5, §4 C1-C6, §6 Phase 4, §7 V1-V7

---

## Phase 3 引き継ぎ事項

Phase 3 V5 で持ち越した全項目を本 plan で消化する:

| # | 出自 | 項目 | 対象 Task |
|---|---|---|---|
| 1 | 設計 §3 N5 | au / sym / syms / dia / cs / agg / meta 等ローカル変数の横断 rename | Task N-1〜N-4 |
| 2 | Phase 2 #5 | `patterns/literal_masking.py` の java/c/proc 完全重複（Pro*C 個別化判定） | Task R-1 |
| 3 | Phase 2 #6 | `Phase 1.5` / `Phase 2a` / `v9` 等のマーカー除去（C5） | Task C-1 |
| 4 | Phase 2 #7 | `classifiers/__init__.py` eager import 失敗時の運用判断 | Task R-2 |
| 5 | Phase 3 | `_state.py` の `_REF_KIND` 命名 + 所在（`_state` → `_finalize`） | Task A-1 |
| 6 | Phase 3 | `_state.py` を `state.py`（public）にする選択肢 | Task A-1 で判断 |
| 7 | Phase 3 | `snippet/__init__.py` の `build_snippet` docstring を C3 形式へ | Task C-2 |
| 8 | Phase 3 | `test_encoding_wiring.py` コメントの `enc_of` → `encoding_of` 表記 | Task N-3 |
| 9 | Phase 3 V5 Major | `_budget_control._estimate_items` 動的参照清潔化 | Task A-2 |
| 10 | Phase 3 V5 | `_options.py:15` の `（Phase 2a/2b 範囲）` マーカー削除 | Task C-1 |
| 11 | Phase 3 V5 | `_seed.py` / `_finalize.py` の `_file_meta` private prefix 共有 | Task A-3 |
| 12 | Phase 3 V5 | `_ingest.py` の `hop` 引数 docstring 統一 | Task C-2 |
| 13 | Phase 3 V5 | `apply_global_cap` の discard コメント | Task C-2 |
| 14 | Phase 3 V5 | `snippet/__init__.py` の `__all__` 位置 | Task C-2 |
| 15 | Phase 3 V5 | `snippet/_ts.py` の `_GRAN_*` 出典コメント | Task C-2 |

---

## ファイル構造（Phase 4 完了時）

Phase 3 完了時点と同じ構造を維持する（新規ファイルなし、削除なし、移動は `_state.py` の `_REF_KIND` → `_finalize.py` のみ）。

```
src/grep_analyzer/
├── snippet/                ← Phase 3 完了時のまま、内部 rename + C5 適用
├── fixedpoint/             ← Phase 3 完了時のまま、内部 rename + C5 適用
│   ├── _state.py           ← _REF_KIND を削除（→ _finalize.py へ）
│   ├── _finalize.py        ← _REF_KIND を持つ
│   └── _budget_control.py  ← _estimate_items 動的参照を直接 import に戻す
├── classifiers/            ← Phase 3 完了時のまま、内部 rename + C5 適用
├── patterns/               ← Phase 3 完了時のまま、内部 rename + C5 適用
├── chase.py                ← rename + C5
├── automaton.py            ← au local 変数 rename
└── ...（他全モジュール）
tests/
├── perf/test_perf.py       ← monkeypatch ターゲット変更（Task A-2 連動）
├── integration/test_encoding_wiring.py ← コメント追従
└── ...（他全モジュール）
```

---

## ファイル単位の rename 対象（N1〜N4 inventory）

設計 §3 N1〜N4 / 既存 fixedpoint 完了時の grep ベース調査結果:

### 略語ローカル変数（N1 違反、ホワイトリスト外）

| 旧 | 新 | 主な出現箇所（概数）|
|---|---|---|
| `au` | `automaton`（local 変数として）| `automaton.py:13`, `_scan.py:40-42` |
| `sym` / `syms` | `symbol` / `symbols` | `_scan.py:45,53`, `_ingest.py:38-52,72-83`, `automaton.py:15` |
| `cs` | `chase_symbols` | `stoplist.py:91`, `_scan.py:51-54`, `_ingest.py:35` |
| `dia` | `dialect` | `_seed.py:48-56`, `_finalize.py:37-41` |
| `agg` | `hits_by_relpath` | `_scan.py:78-93` |
| `meta` | `file_meta_by_relpath` | `_scan.py:79-92`, `_finalize.py:23-41` |
| `dn` / `up` | `down_idx` / `up_idx` | `snippet/_clamp.py:36-58` |
| `ra` / `rb` | `above_count` / `below_count` | `snippet/_clamp.py:43-54` |
| `lp` / `rps` | `lparen` / `rparens` | `snippet/_ts.py:37-39` |
| `d` (paren_depth) | `paren_depth` | `snippet/_heuristic.py:21-29` |
| `t` (type) | `node_type` | `snippet/_heuristic.py:23-32`, `snippet/_ts.py:78-92` |
| `m` (mask) | `masked_lines` | `snippet/_heuristic.py:42` |
| `n` (node) | `node` | `snippet/_ts.py:75` |
| `s, e` (span) | 場合により `start`, `end` | `snippet/_heuristic.py`, `snippet/_ts.py` ほか |

**N5 除外**: 内包表記内の `x for x in xs`、`for i in range(...)`、`_` 単独、定義から最終参照まで 3 行以内のローカル変数。

### N4 ドメイン語彙固定

すでに概ね統一済（`relpath`, `lineno`, `keyword`, `symbol`, `occurrence`, `provenance`, `chain`, `hop`, `seed`）。grep ベースで違反がないことを確認するのみ。

---

## C5 違反 inventory（マーカー除去）

`grep -rn "Phase ?[0-9]\([a-z]\|\.[0-9]\)\?\|spec v[0-9]\|Inv-[0-9]\| v9\b\| v10\b" src/grep_analyzer/` で検出される対象:

| ファイル | 行 | 表記 | 処理 |
|---|---|---|---|
| `proc_preprocess.py` | L40 | `spec §7 v9 Crit-1` | `v9` 削除 → `spec §7 Crit-1` |
| `pipeline.py` | L1 | `spec §15 フェーズ2 Phase 2a` | `Phase 2a` 削除 → `spec §15` |
| `automaton.py` | L26 | `spec v10 で実証` | `v10` 削除 |
| `budget.py` | L8 | `Phase 3 perf の領分` | `Phase 3` 削除 |
| `model.py` | L29 | `Phase 1 では ref_kind は常に "direct"` | `Phase 1 では` 削除（実装と乖離・現在は indirect も存在） |
| `model.py` | L56 | `spec §9 v9 全順序キー` | `v9` 削除 |
| `output_writer.py` | L1, L4, L27, L42 | `spec v4 §X` / `Inv-5` | `v4` / `Inv-5` 削除 |
| `resume.py` | L1 | `spec v4 §4 WS1` | `v4` / `WS1` 削除 |
| `classifiers/ts_classifier.py` | L16 | `Phase 1 は決定的基盤が目的` | `Phase 1 は` 削除 |
| `fixedpoint/_options.py` | L15 | `（Phase 2a/2b 範囲）` | 削除 |
| 他、各モジュール docstring の `Related:` 行 | - | refactor-design 参照 | **Phase 4 では維持**（リファクタ完了後の clean-up で再判断） |

---

## Task 一覧（実施順）

設計 §7 V7 適用順序: (1) N1〜N4 inventory → (2) rename 適用 → (3) C1〜C5 → (4) R1 再検査。

### Task 0: ベースライン

- [ ] **Step 1: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

- [ ] **Step 2: baseline hash 記録**

Run: `git rev-parse HEAD` で `8fac007` 相当の hash を記録。

No commits.

---

## Part [A]: 技術債務解消（Phase 3 引き継ぎ）

### Task A-1: `_REF_KIND` を `_state.py` → `_finalize.py` へ移送 + 命名見直し

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_state.py`（`_REF_KIND` 削除）
- Modify: `src/grep_analyzer/fixedpoint/_finalize.py`（`_REF_KIND` 追加 + import 修正）

判定: `_REF_KIND` は indirect Hit 構築でのみ使用 → `_finalize.py` 内部定数として移送。命名は `_REF_KIND` のまま維持（Phase 4 で命名整理する第 2 提案は `INDIRECT_REF_KIND_BY_KIND` だが、長すぎ可読性低下 → 維持）。

- [ ] **Step 1: `_state.py` から削除**

`old_string`:
```python
_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}
```
`new_string`: 空文字列（削除）

- [ ] **Step 2: `_finalize.py` に追加 + import 修正**

`old_string`:
```python
from grep_analyzer.fixedpoint._state import ChaseState, _REF_KIND
```
`new_string`:
```python
from grep_analyzer.fixedpoint._state import ChaseState

_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}
```

`_REF_KIND` は module top に置く（既存の import group 直後）。

- [ ] **Step 3: 検証**

Run: `pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

- [ ] **Step 4: `_state.py` を `state.py` にするかの判断**

`_state.py` は引き続き `ChaseState` のみを持つ。public 化（`state.py`）の妥当性は:
- `ChaseState` は型 hint として `_ingest`/`_budget_control`/`_seed`/`_finalize` から import される
- 外部（pipeline.py, cli.py）からは触らない
- → private 接頭辞 (`_state.py`) のまま維持。判断: 不変

- [ ] **Step 5: Commit**

```
git add src/grep_analyzer/fixedpoint/_state.py src/grep_analyzer/fixedpoint/_finalize.py
git commit -m "refactor(fixedpoint): _REF_KIND を _state.py から _finalize.py へ移送（Phase 3 引き継ぎ #5）"
```

---

### Task A-2: `_estimate_items` 動的参照清潔化（Phase 3 V5 Major #1）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_budget_control.py`（`_estimate_items` ラッパ削除、直接 import に戻す）
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`（`estimate_items` import + `__all__` から削除）
- Modify: `tests/perf/test_perf.py`（monkeypatch ターゲットを `grep_analyzer.budget.estimate_items` に変更）

判定: `_budget_control.py` を `from grep_analyzer import budget as _budget` の形に変えれば、`monkeypatch.setattr("grep_analyzer.budget.estimate_items", _spy)` で `_budget.estimate_items(...)` 経由の attribute lookup が spy に置き換わる。これは Python のモジュール属性 lookup の挙動として確実に動作する。

- [ ] **Step 1: `_budget_control.py` の動的参照を整理**

`old_string`:
```python
def _estimate_items(*, n_symbols, n_edges, n_intro):
    """`grep_analyzer.fixedpoint.estimate_items` を動的参照する間接呼出。
    （以下 docstring 全体）
    """
    from grep_analyzer import fixedpoint as _fp
    return _fp.estimate_items(n_symbols=n_symbols, n_edges=n_edges, n_intro=n_intro)
```
`new_string`: 空文字列（削除）

そして `_estimate_items(...)` 呼出 4 箇所を `_budget.estimate_items(...)` に置換。

`old_string`:
```python
from grep_analyzer.fixedpoint._state import ChaseState
```
`new_string`:
```python
from grep_analyzer import budget as _budget
from grep_analyzer.fixedpoint._state import ChaseState
```

`_estimate_items(n_symbols=keep_count, n_edges=0, n_intro=keep_count)` 等の 4 箇所を `_budget.estimate_items(n_symbols=..., n_edges=..., n_intro=...)` に `replace_all=True` で一括置換。

- [ ] **Step 2: `__init__.py` から `estimate_items` import 削除**

`old_string`:
```python
from grep_analyzer.budget import MemoryBudget, estimate_items  # estimate_items: perf test の monkeypatch 接点（tests/perf/test_perf.py:49）
```
`new_string`:（**削除しない**。`MemoryBudget` は `_seed.py` 内で使用されるが `__init__.py` から削除可。実機で `grep -n "MemoryBudget" src/grep_analyzer/fixedpoint/__init__.py` を実行して参照 0 を確認）

→ 修正: `MemoryBudget` の使用が `__init__.py` 内になければ、import 行全体を削除。

`old_string`:
```python
from grep_analyzer.budget import MemoryBudget, estimate_items  # estimate_items: perf test の monkeypatch 接点（tests/perf/test_perf.py:49）
```
`new_string`: 空文字列

`__all__` から `estimate_items` を削除:

`old_string`:
```python
__all__ = ["EngineOptions", "run_fixedpoint", "estimate_items"]
```
`new_string`:
```python
__all__ = ["EngineOptions", "run_fixedpoint"]
```

- [ ] **Step 3: `tests/perf/test_perf.py` の monkeypatch ターゲット変更**

`old_string`:
```python
    monkeypatch.setattr("grep_analyzer.fixedpoint.estimate_items", _spy)
```
`new_string`:
```python
    monkeypatch.setattr("grep_analyzer.budget.estimate_items", _spy)
```

`docstring` も追従修正:

`old_string`:
```python
    # fixedpoint は `from grep_analyzer.budget import estimate_items`（関数
```
`new_string`:
```python
    # _budget_control は `from grep_analyzer import budget as _budget`（モジュール
```

具体的な docstring 全体（L42-48）の修正は subagent が現状を `Read` で取得して文脈に合わせて修正する。

- [ ] **Step 4: 検証**

Run:
```bash
pytest -q 2>&1 | tail -5
pytest tests/perf/test_perf.py -m perf -q -s 2>&1 | tail -10
```

Expected: `249 passed, 5 skipped` + perf test 全 pass（CALIB の spy が動作）。

CALIB 出力で `bytes_per_item=...` が記録されることを確認。

- [ ] **Step 5: Commit**

```
git add src/grep_analyzer/fixedpoint/_budget_control.py src/grep_analyzer/fixedpoint/__init__.py tests/perf/test_perf.py
git commit -m "refactor(fixedpoint,perf): _estimate_items 動的参照を直接 import に戻す + monkeypatch 接点を grep_analyzer.budget へ（Phase 3 V5 Major #1）"
```

---

### Task A-3: `_file_meta` / `_kinds_of` の private 接頭辞整理（Phase 3 V5 Minor）

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（`_file_meta` → `file_meta`、`_kinds_of` → `kinds_of`）
- Modify: `src/grep_analyzer/fixedpoint/_seed.py`（import 修正）
- Modify: `src/grep_analyzer/fixedpoint/_ingest.py`（import 修正）
- Modify: `src/grep_analyzer/fixedpoint/_finalize.py`（import 修正）

判定: `_file_meta` / `_kinds_of` は `_seed` / `_ingest` / `_finalize` から **共有 import** されており「module 内 private」の意味が破れている。public 接頭辞無しに昇格。`_scan_file` は worker 関数として `multiprocessing.Pool` に pickle されるため private 接頭辞のまま維持（外部から呼ばれないが pickle 由来）。

- [ ] **Step 1: `_scan.py` の関数定義 rename**

`replace_all=True` で `def _file_meta(` → `def file_meta(` 、 `def _kinds_of(` → `def kinds_of(`

- [ ] **Step 2: `_scan.py` 内部呼出 rename**

`_file_meta(...)` 呼出箇所を `file_meta(...)` に置換、`_kinds_of(...)` 呼出箇所を `kinds_of(...)` に置換。

- [ ] **Step 3: import 修正（3 ファイル）**

`_seed.py`:
`old_string`:
```python
from grep_analyzer.fixedpoint._scan import _file_meta
```
`new_string`:
```python
from grep_analyzer.fixedpoint._scan import file_meta
```
そして関数本体内の `_file_meta(...)` 呼出を `file_meta(...)` に置換。

`_ingest.py`:
`old_string`:
```python
from grep_analyzer.fixedpoint._scan import _kinds_of
```
`new_string`:
```python
from grep_analyzer.fixedpoint._scan import kinds_of
```
そして関数本体内の `_kinds_of(...)` 呼出を `kinds_of(...)` に置換。

`_finalize.py`:
`old_string`:
```python
from grep_analyzer.fixedpoint._scan import _file_meta
```
`new_string`:
```python
from grep_analyzer.fixedpoint._scan import file_meta
```
そして関数本体内の `_file_meta(...)` 呼出を `file_meta(...)` に置換。

- [ ] **Step 4: 検証**

Run: `pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

- [ ] **Step 5: Commit**

```
git add src/grep_analyzer/fixedpoint/
git commit -m "refactor(fixedpoint): _file_meta/_kinds_of を public 名（file_meta/kinds_of）に昇格（Phase 3 V5 Minor）"
```

---

## Part [N]: N1〜N4 ローカル変数 rename

### Task N-1: automaton.py の `au` rename + `sym` rename

**Files:**
- Modify: `src/grep_analyzer/automaton.py`
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`（`au` ローカル変数）

- [ ] **Step 1: `automaton.py` の rename**

`au = ahocorasick.Automaton()` を `automaton_obj = ahocorasick.Automaton()` に。`return au` を `return automaton_obj` に。

ループ変数 `for s in syms` の `s` は N5 除外（ループ慣用）→ 維持。

`syms` → `symbols`、`sym` → `symbol`（grep で範囲確認後 rename）。

- [ ] **Step 2: `_scan.py` の `au` rename**

`au = automaton.build(sym_list)` を `automaton_obj = automaton.build(sym_list)` に。`if au is not None` を `if automaton_obj is not None` に。`automaton.scan_line(au, line)` を `automaton.scan_line(automaton_obj, line)` に。

`for sym in automaton.scan_line(...)` の `sym` は N5 除外（ループ慣用、2 行で終わる短い使用）→ 維持。

ただし `found.append((sym, i, line))` の使用が 1 行下にあるため有効範囲は 2 行。N5 除外で維持。

- [ ] **Step 3: 検証 + Commit**

Run: `pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

Commit: `refactor(automaton): au → automaton_obj rename（N1 フルスペル）`

---

### Task N-2: fixedpoint 配下の cs / dia / agg / meta rename

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py`
- Modify: `src/grep_analyzer/fixedpoint/_ingest.py`
- Modify: `src/grep_analyzer/fixedpoint/_seed.py`
- Modify: `src/grep_analyzer/fixedpoint/_finalize.py`
- Modify: `src/grep_analyzer/stoplist.py`（`partition(cs: ChaseSymbols, ...)`）

- [ ] **Step 1: `cs` → `chase_symbols` rename**

各ファイルで `cs = extract_chase_symbols(...)` を `chase_symbols = extract_chase_symbols(...)` に。`cs.constants` / `cs.vars` / `cs.getters` / `cs.setters` を `chase_symbols.constants` / etc に。

stoplist.py の `def partition(cs: ChaseSymbols, ...)` を `def partition(chase_symbols: ChaseSymbols, ...)` に。本体内の `cs.` 参照を全て `chase_symbols.` に。

- [ ] **Step 2: `dia` → `dialect` rename**

`_seed.py` / `_finalize.py` の `lang, dia = ...` / `meta_of[c.relpath] = (text, lang, dia)` / `ingest_one(state, occ, lang, dia, ...)` を全て `dialect` に統一。

- [ ] **Step 3: `agg` / `meta` rename**

`_scan.py` の `agg: dict[str, list] = {}` を `hits_by_relpath: dict[str, list] = {}` に。`meta: dict[str, tuple] = {}` を `file_meta_by_relpath: dict[str, tuple] = {}` に。本体内の参照も全て統一。

`_finalize.py` の `meta_of: dict[str, tuple[str, str, str]] = {}` を `file_meta_of: dict[str, tuple[str, str, str]] = {}` に（または `file_meta_by_relpath` で統一）。

- [ ] **Step 4: 検証 + Commit**

Run: `pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

Commit: `refactor(fixedpoint): cs/dia/agg/meta をフルスペル名へ rename（N1）`

---

### Task N-3: snippet 配下のローカル変数 rename + test_encoding_wiring.py コメント追従

**Files:**
- Modify: `src/grep_analyzer/snippet/_clamp.py`（dn / up / ra / rb）
- Modify: `src/grep_analyzer/snippet/_heuristic.py`（m / d / t / s, e）
- Modify: `src/grep_analyzer/snippet/_ts.py`（lp / rps / n / t / cur 等）
- Modify: `tests/integration/test_encoding_wiring.py`（コメント中の `enc_of` → `encoding_of`）

- [ ] **Step 1: `_clamp.py` の rename**

`dn` → `down_idx`、`up` → `up_idx`、`ra` → `above_count`、`rb` → `below_count` を `replace_all=True` で慎重に置換。短い識別子のため周辺コンテキスト一致で false-positive リスクあり、subagent は注意深く `grep -n "\bdn\b\|\bup\b\|\bra\b\|\brb\b" src/grep_analyzer/snippet/_clamp.py` で確認後実施。

`s, e = 0, len(lines) - 1` の `s` / `e` は span を表す慣用識別子。**N5 除外**（span_start / span_end への rename は意味の冗長化）→ 維持。

- [ ] **Step 2: `_heuristic.py` の rename**

`m = [mask_literals(...) for ln in lines]` を `masked_lines = [...]` に。
`def stop(i): x = m[i]` の `x` は N5 除外（局所変数）→ 維持。
`_balanced(t: str)` の `t` パラメータは `text` に、本体内 `d = 0` の `d` は `paren_depth` に rename。`for c in t` の `c` はループ慣用 → 維持。

- [ ] **Step 3: `_ts.py` の rename**

`lp = next(...)` を `lparen = next(...)`、`rps = [c for c in ...]` を `rparens = [...]` に。
`def _has_error(node)`、`def ts_span(language, file_text, lineno)` の引数名はそのまま。
`n = node_at_line(...)` を `node = node_at_line(...)` に。
`while cur is not None: t = cur.type` の `t` を `node_type` に。
`for ch in node.children` の `ch` はループ慣用 → 維持。

- [ ] **Step 4: `test_encoding_wiring.py` コメント追従**

コメント中の `enc_of` を `encoding_of` に書換。

- [ ] **Step 5: 検証 + Commit**

Run: `pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

Commit: `refactor(snippet,tests): snippet 配下ローカル変数 rename + test_encoding_wiring.py コメント追従（N1）`

---

### Task N-4: 横断検証（V4 機械チェック）

**Files:** None（検証のみ）

- [ ] **Step 1: N1 違反検出**

```bash
cd /workspaces/grep_helpers2 && \
  grep -rEn '\b(au|sym|syms|dia|prog|agg|meta|intro|estore|enc_of)\b' src/grep_analyzer/ | \
    grep -v "__pycache__\|automaton\|symbol\|symbols\|dialect\|progress\|hits_by\|file_meta\|introducers\|edge_store\|encoding_of"
```

Expected: ヒット 0（rename 漏れなし）。

ただし、`sym` のループ慣用識別子は N5 除外で `for sym in ...` の形で残るため、上記 grep は `sym` で false-positive する。subagent は手動で確認:
- `for sym in ...` / `for symbol in ...` の使い分けは Phase 4 では混在許容（N5 除外との境界）
- `automaton.py:15` の `for s in syms` → `for symbol in symbols` に既に rename 済か確認

最終的に **ループ慣用識別子以外の N1 違反がゼロ** であることを確認。

- [ ] **Step 2: N4 違反検出**

```bash
grep -rEn '\b(rel_path|relative_path|line_no|linenum)\b' src/grep_analyzer/
```

Expected: ヒット 0。

---

## Part [C]: C1〜C5 コメント整理

### Task C-1: C5 違反マーカー除去（横断）

**Files:** 各モジュール（C5 違反 inventory 参照）

- [ ] **Step 1: 自動 grep でマーカー検出**

```bash
cd /workspaces/grep_helpers2 && \
  grep -rEn 'Phase ?[0-9]([a-z]|\.[0-9])?|spec v[0-9]|Inv-[0-9]| v9\b| v10\b|WS[0-9]' src/grep_analyzer/ | \
    grep -v "__pycache__\|Related:.*refactor-design"
```

Expected: 個別検出箇所が列挙される（C5 違反 inventory と一致）。

- [ ] **Step 2: 各箇所を編集**

| ファイル | 修正 |
|---|---|
| `proc_preprocess.py:40` | `spec §7 v9 Crit-1` → `spec §7 Crit-1` |
| `pipeline.py:1` | `spec §15 フェーズ2 Phase 2a` → `spec §15` |
| `automaton.py:26` | `2.1.0→2.3.1 版更新で出力 byte 不変＝spec v10 で実証` → `2.1.0→2.3.1 版更新で出力 byte 不変＝実機検証済` |
| `budget.py:8` | `Phase 3 perf の領分。本定数は degrade 発火の決定的トリガとしてのみ機能。` → `perf の領分。本定数は degrade 発火の決定的トリガとしてのみ機能。` |
| `model.py:29` | `TSV1行に対応する分類結果。Phase 1 では ref_kind は常に "direct"。` → `TSV1行に対応する分類結果（direct / indirect:* を含む）。` |
| `model.py:56` | `spec §9 v9 全順序キー。` → `spec §9 全順序キー。` |
| `output_writer.py:1` | `spec v4 §2/§3` → `spec §2/§3` |
| `output_writer.py:4` | `Inv-5=テストが共有` → `テストが共有` |
| `output_writer.py:27,42` | `spec v4 §3` → `spec §3` |
| `resume.py:1` | `spec v4 §4 WS1・完了判定1〜5` → `spec §4・完了判定1〜5` |
| `classifiers/ts_classifier.py:16` | `Phase 1 は決定的基盤が目的（分類精度は handcrafted の領分・spec §11）` → `決定的基盤が目的（分類精度は handcrafted の領分・spec §11）` |
| `fixedpoint/_options.py:15` | `spec §8/§10.4 のエンジン挙動パラメータ（Phase 2a/2b 範囲）。` → `spec §8/§10.4 のエンジン挙動パラメータ。` |

- [ ] **Step 3: 検証 + Commit**

Run:
```bash
grep -rEn 'Phase ?[0-9]([a-z]|\.[0-9])?|spec v[0-9]|Inv-[0-9]| v9\b| v10\b|WS[0-9]' src/grep_analyzer/ | grep -v "__pycache__\|Related:.*refactor-design"
```

Expected: ヒット 0（C5 違反ゼロ。Related: 行のみは Phase 4 範囲外）。

Run: `pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

Commit: `docs: フェーズマーカー・版マーカー除去（C5 横断適用）`

---

### Task C-2: C1〜C3 コメント整理（横断）

**Files:** 各モジュール

- [ ] **Step 1: 識別子で伝わる WHAT コメントの削除（C1）**

各モジュールを順に確認し、識別子で伝わる WHAT コメントを削除する。具体的には:
- `# 言語別 chaser の registry` のような繰り返し説明
- `# spec §X 参照」のみのコメント（C2: 末尾 `Related:` に集約）

判断は subagent が WHY/WHAT で個別判断。**機械化が困難なため、目視レビュー + 軽微修正**。

- [ ] **Step 2: `_ingest.py` の hop 引数 docstring 統一（Phase 3 V5 Minor）**

`ingest_one` docstring に hop 意味を明記:

`old_string`:
```python
def ingest_one(state: ChaseState, parent: Occurrence, language: str,
               dialect: str, line: str, hop: int, is_seed: bool = False):
    """1 行を ChaseState に取り込む。spec §8.1 手順 1〜4。"""
```
`new_string`:
```python
def ingest_one(state: ChaseState, parent: Occurrence, language: str,
               dialect: str, line: str, hop: int, is_seed: bool = False):
    """1 行を ChaseState に取り込む（spec §8.1 手順 1〜4）。

    `hop` は **このシンボルが投入される hop 番号**（seed の最初の ingest は
    hop=1、scan 結果から再 ingest される子は hop+1）。`hop > opts.max_depth`
    で prov_max_depth diag を立てて return（停止性の安全弁）。
    """
```

`absorb_results` docstring の hop も統一:

`old_string`:
```python
def absorb_results(state: ChaseState, pass_results, scan_chase: set[str],
                   scan_term: set[str], hop: int):
    """scan_hop の結果を ChaseState に反映する（edge 追加・diag・子の再 ingest）。

    `hop` は呼出時点で完了済みの hop 番号。子の ingest_one には `hop + 1` を渡す。
    """
```
`new_string`:
```python
def absorb_results(state: ChaseState, pass_results, scan_chase: set[str],
                   scan_term: set[str], hop: int):
    """scan_hop の結果を ChaseState に反映する（edge 追加・diag・子の再 ingest）。

    `hop` は **直前に scan 完了した hop 番号**。子の `ingest_one` には `hop + 1`
    を渡して「次 hop で投入される」semantics を維持する。
    """
```

- [ ] **Step 3: `_budget_control.py` の `apply_global_cap` に discard コメント追加（Phase 3 V5 Suggestion）**

`old_string`:
```python
    for s in live[keep_count:]:
        if s not in state.capped:
            diag.add("symbol_rejected", f"capped\t{s}")
            state.capped.add(s)
        state.chase_active.discard(s)
        state.terminal_active.discard(s)
```
`new_string`:
```python
    for s in live[keep_count:]:
        if s not in state.capped:
            diag.add("symbol_rejected", f"capped\t{s}")
            state.capped.add(s)
        # 既 capped であっても discard は冪等。直前の hop で active になっていた
        # 可能性があるため両 set から確実に除外する。
        state.chase_active.discard(s)
        state.terminal_active.discard(s)
```

- [ ] **Step 4: `snippet/__init__.py` の `__all__` 位置調整（Phase 3 V5 Suggestion）**

現状: `__all__ = [...]` がモジュール末尾。
変更: import 群末尾（`from grep_analyzer.tsv import _sanitize` の直後）に移動。

- [ ] **Step 5: `snippet/_ts.py` の `_GRAN_*` 等定数集合に出典コメント追加（Phase 3 V5 Suggestion）**

`old_string`:
```python
_GRAN_JAVA = {"if_statement", "while_statement", "for_statement",
              "switch_expression", "switch_statement",
              ...}
```
`new_string`:
```python
# tree-sitter 0.21 系のノード型集合（spec §9 表「ts_span 粒度」と対応）。
# tree-sitter ライブラリ版更新時はこれらの集合を再点検する。
_GRAN_JAVA = {"if_statement", "while_statement", "for_statement",
              "switch_expression", "switch_statement",
              ...}
```

- [ ] **Step 6: `snippet/__init__.py` の `build_snippet` docstring を C3 形式へ（Phase 3 引き継ぎ）**

`build_snippet` docstring の `(spec §X)` 形式を末尾 `Related: spec §X` 形式に集約。

- [ ] **Step 7: 検証 + Commit**

Run: `pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

Commit: `docs: C1〜C3 コメント整理（hop docstring 統一・discard コメント・snippet __all__ 位置 ほか）`

---

## Part [R]: R1〜R4 再検査

### Task R-1: patterns/literal_masking.py の java/c/proc 重複検査

**Files:** `src/grep_analyzer/patterns/literal_masking.py`

- [ ] **Step 1: 現状確認**

```bash
cat src/grep_analyzer/patterns/literal_masking.py
```

`MASK_SPECS` 内で java/c/proc が同一の regex 集合になっているか確認。同一なら設計 §5 R1 の判定:
- (1) 同一知識か? java/c/proc は同じ literal/comment 文法を共有する? → **Yes**（C 系言語と Pro*C は基本的に同じリテラル文法。Pro*C は EXEC SQL を別途処理）
- (2) 同じ用語で説明できるか? → "C 系リテラルマスク" として説明可
- (3) Rule of Three: 3 箇所 → R1 集約条件を満たす

判定: 同一なら共通名（例: `_C_FAMILY_MASK_SPECS`）に集約し、`MASK_SPECS = {"java": _C_FAMILY, "c": _C_FAMILY, "proc": _C_FAMILY, ...}` で参照。

ただし Phase 4 範囲では **判定のみで実装は次フェーズ**（Pro*C 個別化が将来必要になる可能性がある）。判定結果を引き継ぎ事項として記録。

- [ ] **Step 2: 引き継ぎ記録**

`docs/superpowers/specs/2026-05-21-refactor-design.md` の §8 完了条件部分に判定結果を追記、または別途 ADR 形式で記録。本 Phase 4 では実装変更なし。

- [ ] **Step 3: Commit（記録のみ）**

No code changes. `pytest -q` で 249 passed 確認後、次 Task へ。

---

### Task R-2: classifiers/__init__.py eager import 失敗判断（Phase 2 #7）

**Files:** `src/grep_analyzer/classifiers/__init__.py`

- [ ] **Step 1: 現状確認**

```bash
cat src/grep_analyzer/classifiers/__init__.py
```

eager import（`from grep_analyzer.classifiers import (c_chaser, java_chaser, shell_chaser, sql_chaser)`）の失敗リスクを評価:
- 各 chaser は `from grep_analyzer.patterns.X import Y` の standard import のみ
- optional deps（chardet, tree-sitter）に依存する `ts_classifier` は import されていない
- 失敗リスクなし

判定: 現状維持（lazy import 化不要）。Phase 4 では実装変更なし。

---

### Task R-3: V7 R1 再検査（rename 後の同責務疑い構造検出）

**Files:** None（検証のみ）

設計 §7 V7 (b) の同責務疑い構造検出:

```bash
grep -rEn 'def (build|compute|extract|sanitize)_' src/grep_analyzer/
```

Expected: 既存関数群が列挙される。同名・同責務でないことを目視確認。

```bash
grep -rEn 'hits_by_relpath|file_meta_by_relpath|introducers|edge_store' src/grep_analyzer/
```

Expected: 各識別子が **責務上の出現箇所のみ**（誤集約による多重定義なし）。

判定結果を `docs/superpowers/plans/2026-05-21-refactor-phase4.md` 末尾に記録。

---

## V3 / V4 / V5 / V6 ゲート（Phase 4 完了時）

### V3 Import グラフ層分離

設計 §7 V3 / Phase 3 V3 と同じ検査:

```bash
grep -rn "from grep_analyzer" \
  src/grep_analyzer/snippet/ \
  src/grep_analyzer/fixedpoint/ \
  src/grep_analyzer/classifiers/ \
  src/grep_analyzer/patterns/ 2>&1 | head -80
```

Phase 4 で構造変更なしのため、Phase 3 V3 結果と同一であることを確認。

### V4 命名規約機械チェック

```bash
grep -rEn '\b(au|sym|syms|dia|prog|agg|meta)\b' src/grep_analyzer/ | \
  grep -v "__pycache__\|symbol\|symbols\|dialect\|progress\|meta_of\|automaton"
```

Expected: ヒット 0（ループ慣用識別子の `sym` 等を除く）。

```bash
grep -rEn 'Phase ?[0-9]([a-z]|\.[0-9])?|spec v[0-9]|Inv-[0-9]| v9\b| v10\b|WS[0-9]' src/grep_analyzer/ | \
  grep -v "__pycache__\|Related:.*refactor-design"
```

Expected: ヒット 0。

### V5 Phase 4 ゲート

実装完了後、批判的 AI レビュー（観点 A + 観点 B）を最低 2 巡実行し Critical/Major ゼロまで収束。

### V6 性能リグレッション抑止

Phase 4 は構造変更ではなく rename とコメント整理が中心のため、原理的に性能影響なし。`pytest tests/perf/test_perf.py -m perf -q -s 2>&1 | grep "PERF n=800"` を 3 回実行して baseline と比較。

---

## Phase 4 完了基準

- [ ] Inv-A: golden 22 件 byte 同値
- [ ] Inv-B: pytest 249 passed, 5 skipped 維持
- [ ] Inv-C: 公開 API シグネチャ・戻り値・diagnostics キー文字列が無変更
- [ ] Inv-D: V3 で層分離違反ゼロ
- [ ] Inv-E: pyahocorasick 版差吸収・決定性保持
- [ ] V4: N1〜N4 違反ゼロ（grep 機械チェック）+ C5 違反ゼロ
- [ ] V5: AI レビュー Critical/Major ゼロに収束
- [ ] V6: 性能リグレッション 10% / +5 秒以内

---

---

## v2 修正補遺（1 巡目 AI レビュー反映）

本 plan v1 に対して以下の修正を **subagent 実行時に併用** すること。本補遺の内容は plan 本体の指示に優先する。

### 補-A1（観点 A Major #2）: Phase 3 引き継ぎ表の整合化

L23-40 の引き継ぎ表で以下を訂正:
- #11: 「`_seed.py` / `_finalize.py` の `_file_meta` private prefix 共有」→ 「`_file_meta` / `_kinds_of` を public 名へ昇格（`_helpers.py` 分離は将来検討）」
- #12: 「`_ingest.py` の `hop` 引数 docstring 統一」→ 「`_ingest.py` の `ingest_one` / `absorb_results` 両関数の `hop` 引数 docstring 統一」
- #4: Task R-2 の判定結果（実装変更なし・現状維持）は Phase 4 完了報告に明記する

### 補-A2（観点 A Major #3）: `Related:` 行の C5 例外の明文化

L114 の判断根拠を以下に明記:

> **例外根拠**: `Related: docs/.../refactor-design.md §6 Phase X [Y]` 行はリファクタリング進行中の設計-実装トレーサビリティとして機能する。Phase 4 完了直前または Phase 5 (clean-up) で一括削除予定。本 Phase 4 では設計 §4 C5 の **明示的例外** とし、V4 機械チェックの grep で `grep -v "Related:.*refactor-design"` で除外する。Phase 4 完了基準 V4「C5 違反ゼロ」は `Related:` 行を除いた範囲で判定する。

### 補-A3（観点 A Major #4）: `_REF_KIND` 維持判断の N1 根拠

Task A-1 L146 の維持判断を以下に書き換え:

> `_REF_KIND` の `REF` は設計 §3 N1 ホワイトリスト外の略語だが、(i) モジュール private 定数、(ii) 単一モジュール `_finalize.py` 内のみで使用、(iii) `REFERENCE_KIND_BY_KIND` 等の代替名は冗長化のため可読性低下 — の 3 点で N1 例外として維持する。引き継ぎ #5 で挙がった `INDIRECT_REF_KIND_BY_KIND` は採用しない。本判断は設計 §3 N1 の **明示的例外**として Phase 4 完了レビューで再判定対象とする。

### 補-A4（観点 A Major #5）: `_scan_file` private 維持判断の正確な根拠

Task A-3 L311 の判断根拠を以下に修正:

> `_scan_file` は worker 関数として `_scan.py` 内のトップレベル純関数。`multiprocessing.Pool` の pickle 経由呼出は `__module__.__qualname__` 文字列ベースのため private 接頭辞自体は pickle に無関係。維持判断の真の根拠は (i) `_scan_file` は `_scan.py` 内 `scan_hop` 関数からのみ呼ばれ外部公開 API でない、(ii) tests/ から直接呼ばれていない、(iii) 同モジュール内の他関数 `_file_meta` / `_kinds_of` と異なり共有 import されていない — の 3 点。

### 補-A5（観点 A Major #6）: Task N-2 で `lang` を rename 対象から除外

Task N-2 Step 2 L420-422 の指示を以下に修正:

> `_seed.py` / `_finalize.py` の `dia` を `dialect` に rename。**`lang` は N1 ホワイトリストに含まれるため変更しない**。具体的に対象は:
> - `_seed.py:48` の `text, _, _, lang, dia = file_meta(...)` の `dia`
> - `_seed.py:54` の `lang, dia = s.language, "bourne"` の `dia`
> - `_seed.py:56` の `ingest_one(..., lang, dia, ...)` の `dia`
> - `_finalize.py:37` の `text, ..., lang, dia = file_meta(...)` の `dia`
> - `_finalize.py:41` の `meta_of[...] = (text, lang, dia)` の `dia`

### 補-A6（観点 A Major #7）: Task N-3 の `_heuristic.py` `t` rename 詳細化

Task N-3 Step 2 を以下に置換:

> `m = [mask_literals(...) for ln in lines]` を `masked_lines = [...]` に。
> `_balanced(t: str)` 関数全体（_heuristic.py:17-25 の 9 行）を `old_string` に取り、内部の `t` を `text` に、`d = 0` を `paren_depth = 0` に、`d` の他参照を `paren_depth` に置換した完全コード（subagent が `Read` で実機 byte 取得後構成）を `new_string` にする 1 つの atomic Edit。
> `for c in t` の `c` はループ慣用識別子で **維持**。

### 補-A7（観点 A Major + B Major #2）: Task N-3 の `_ts.py` `t` / `n` rename 全箇所網羅

Task N-3 Step 3 を以下に置換:

> `lp = next(...)` → `lparen = next(...)`、`rps = [c for c in ...]` → `rparens = [...]` 置換は `_paren_span` 関数内（_ts.py:30-39）。実機 grep で `_ts.py` 内 `lp` / `rps` の参照箇所を確認後、関数全体を `old_string` に取り完全置換。
>
> `n = node_at_line(...)` → `node = node_at_line(...)` 置換は `ts_span` 関数内（_ts.py:62-87）。**ただし `node` 名は `_paren_span(node)` パラメータ名と衝突するため、関数スコープが異なる`ts_span` 内に限定**。`if n is None: return None` の `n` も追従。
>
> `t = cur.type` の `t` を `node_type` に rename: 実機 `grep -nE '\bt\b' src/grep_analyzer/snippet/_ts.py` で `ts_span` 関数内（L71-87）の `t = cur.type`, `if t in _STMT`, `if t in gran`, `if t in _PAREN_ONLY`, `if t in _BLOCK` の **5 箇所**を確認。関数全体を `old_string` に取り、`t` → `node_type` 一括置換した版を `new_string` にする atomic Edit。

### 補-B1（観点 B Critical #1〜#5）: Task A-2 の全面再設計

Task A-2 を以下の手順に置き換える（Critical 5 件を全て解消）:

**前提状況の確認**:
```bash
cd /workspaces/grep_helpers2 && \
  grep -n "estimate_items\|_estimate_items\|_fp\." src/grep_analyzer/fixedpoint/_budget_control.py && \
  grep -n "estimate_items\|MemoryBudget" src/grep_analyzer/fixedpoint/__init__.py && \
  grep -n "estimate_items\|monkeypatch" tests/perf/test_perf.py
```

実機の現状把握後、以下を atomic な順序で実施（Step 単独で中間状態は壊れても良いが、commit 前に Step 1〜4 全完了させる）:

**Step 1: `_budget_control.py` の動的参照ラッパ削除**

(a) `Read` で `_budget_control.py` の L1-90 を取得し、`_estimate_items(*, n_symbols, n_edges, n_intro):` 関数定義全体（docstring + 関数内 import + return 文の **9 行**）の byte 列を確認。

(b) Edit 1 - 関数定義削除（実機 byte 列をそのまま `old_string` に）:
```python
# old_string（実機 byte をそのまま）:
def _estimate_items(*, n_symbols, n_edges, n_intro):
    """`grep_analyzer.fixedpoint.estimate_items` を動的参照する間接呼出。

    perf test (tests/perf/test_perf.py) が `monkeypatch.setattr(
    "grep_analyzer.fixedpoint.estimate_items", _spy)` で spy 差し替えを行うため、
    `_budget_control.py` 側でも `__init__.py` 名前空間経由で参照する必要がある。
    関数内 import で循環を回避する。
    """
    from grep_analyzer import fixedpoint as _fp
    return _fp.estimate_items(n_symbols=n_symbols, n_edges=n_edges, n_intro=n_intro)


# new_string: 空文字列（完全削除）
```

(c) Edit 2 - import 追加:
```python
# old_string:
from grep_analyzer.fixedpoint._state import ChaseState

# new_string:
from grep_analyzer import budget as _budget
from grep_analyzer.fixedpoint._state import ChaseState
```

(d) Edit 3 - 呼出 4 箇所を一括置換（関数定義は (b) で消えているため `_estimate_items(` は呼出のみ残る、replace_all=True 安全）:
```python
# old_string: _estimate_items(
# new_string: _budget.estimate_items(
# replace_all=True
```

**Step 2: `__init__.py` から `estimate_items` import / `__all__` を整理**

`Read` で実機 `__init__.py:17` を確認。**実機の正確な byte 列**:
```python
from grep_analyzer.budget import estimate_items  # perf test の monkeypatch 接点（tests/perf/test_perf.py:49）
```

(a) Edit 4 - import 削除:
```python
# old_string（実機 byte をそのまま）:
from grep_analyzer.budget import estimate_items  # perf test の monkeypatch 接点（tests/perf/test_perf.py:49）

# new_string: 空文字列
```

(b) Edit 5 - `__all__` から `estimate_items` 削除:
```python
# old_string:
__all__ = ["EngineOptions", "run_fixedpoint", "estimate_items"]

# new_string:
__all__ = ["EngineOptions", "run_fixedpoint"]
```

**Step 3: `tests/perf/test_perf.py` の monkeypatch ターゲット変更**

`Read` で L40-49 を取得し、`real = _b.estimate_items` 行と `monkeypatch.setattr(...)` 行の順序を確認。`real = ...` は setattr より **前** にあること（spy が元関数を捕獲するため）。

(a) Edit 6 - monkeypatch ターゲット変更:
```python
# old_string:
    monkeypatch.setattr("grep_analyzer.fixedpoint.estimate_items", _spy)

# new_string:
    monkeypatch.setattr("grep_analyzer.budget.estimate_items", _spy)
```

(b) Edit 7 - docstring の経路説明を追従（実機を Read で取得して該当 docstring 部分を `_budget_control` 経由に書き換え）。具体的に:
```python
# old_string（実機 byte をそのまま、概ね L42-48 の 7 行）:
    # fixedpoint は `from grep_analyzer.budget import estimate_items`（関数

# new_string:
    # _budget_control は `from grep_analyzer import budget as _budget`（モジュール
```
（実機 docstring の文脈を Read で確認後、構成）

**Step 4: 検証**

```bash
python -c "from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint; print('OK')"
pytest -q 2>&1 | tail -5
pytest tests/perf/test_perf.py -m perf -q -s 2>&1 | tail -10
pytest tests/unit/test_budget.py -q
```

Expected:
- `OK`
- `249 passed, 5 skipped`
- perf test 全 pass（CALIB の spy が動作し `bytes_per_item=...` が出力される）
- test_budget 全 pass

**重要**: Step 4 の検証は Step 1〜3 全完了後にのみ実行。中間 commit ではテストが壊れる。

**Step 5: V6 perf 計測**

baseline (`8fac007` 相当) と比較し、Phase 3 で +16.6% だった perf 退行が改善（または同等）か確認:

```bash
for i in 1 2 3; do
  pytest tests/perf/test_perf.py::test_scale -m perf -q -s 2>&1 | grep "PERF n=800"
done
```

Phase 3 baseline_median 0.358 秒（Task A6 計測値）。Task A-2 後の中央値が ±5% 以内なら改善 OK。退行（+5%超）なら要因解析。

**Step 6: Commit**

```bash
git add src/grep_analyzer/fixedpoint/_budget_control.py src/grep_analyzer/fixedpoint/__init__.py tests/perf/test_perf.py
git commit -m "refactor(fixedpoint,perf): _estimate_items 動的参照ラッパ削除 + monkeypatch 接点を grep_analyzer.budget へ（Phase 3 V5 Major #1 解消）"
```

### 補-B2（観点 B Critical #6）: Task A-3 の atomic 化

Task A-3 Step 1 と Step 2 を統合し、`_scan.py` の rename を atomic な 1 Edit に:

`Read` で `_scan.py` 全体を取得し、以下の **2 つの atomic replace_all** を実施:

```bash
# Edit 1: _scan.py 内 _file_meta → file_meta
old_string: "_file_meta"
new_string: "file_meta"
replace_all: True
# （定義 1 箇所 + 呼出 1 箇所 = 計 2 箇所が同時に変更される）

# Edit 2: _scan.py 内 _kinds_of → kinds_of
old_string: "_kinds_of"
new_string: "kinds_of"
replace_all: True
```

各 import 元（_seed.py / _ingest.py / _finalize.py）でも同様の `replace_all=True` で原子的に rename。

ただし `_kinds_of` は `_kinds_of` で識別子全体一致のため安全（部分文字列誤マッチなし）。`_file_meta` も同様。

**Step 4 検証**:
```bash
grep -rn "_file_meta\|_kinds_of" src/grep_analyzer/
```
Expected: 0 件（rename 完了）。

### 補-B3（観点 B Major #1）: Edit 失敗時のリカバリ手順を明示

plan 冒頭「For agentic workers」の項に以下を明記:

> Edit が `String not found` で失敗した場合、(a) `Read` で実機ファイルから対象範囲を取得、(b) コメント・空白・行末改行を含めた完全 byte 列を `old_string` に貼り直す、(c) `replace_all=False` を試す、の手順でリカバリ。plan の `old_string` は **指示の意図** であり、最終 byte 一致は実機が正本。

### 補-B4（観点 B Major #5）: Task C-1 inventory 補完（budget.py:9-11）

Task C-1 Step 2 表に以下を追加:

| ファイル | 修正 |
|---|---|
| `budget.py:9-11` | `Phase4 spec §15 で snippet 多行化（build_snippet）により 1 レコード最大 / バイトが増→過小評価是正のため再較正（130084→74044）。詳細 phase3-perf-report.md。` → `spec §15 で snippet 多行化（build_snippet）により 1 レコード最大バイトが増→過小評価是正のため再較正（130084→74044）` |

### 補-B5（観点 B Major #6）: tests/ 側 C5 違反の検査範囲

V4 検証 grep に `tests/` を含める:

```bash
grep -rEn 'Phase ?[0-9]([a-z]|\.[0-9])?|spec v[0-9]|Inv-[0-9]| v9\b| v10\b|WS[0-9]' src/grep_analyzer/ tests/ | \
  grep -v "__pycache__\|Related:.*refactor-design\|setup-test-fixture"
```

Expected: tests/ 側のヒットも 0 件（test_encoding_wiring.py の `test_fixedpoint.py:212` 等の旧パス参照を含む場合は Task C-1 で同時修正）。

### 補-B6（観点 B Major #7）: Task C-2 Step 4 `__all__` 移動の具体的 Edit

`Read` で `snippet/__init__.py` を取得。以下 2 つの Edit:

(a) Edit 1 - 末尾 `__all__` 削除:
```python
# old_string（実機 L50-56 の 7 行）:
__all__ = [
    "build_snippet",
    "clamp_lines",
    "heuristic_span",
    "ts_span",
    "proc_exec_span",
]

# new_string: 空文字列
```

(b) Edit 2 - import 群末尾に `__all__` 挿入:
```python
# old_string:
from grep_analyzer.tsv import _sanitize

# new_string:
from grep_analyzer.tsv import _sanitize

__all__ = [
    "build_snippet",
    "clamp_lines",
    "heuristic_span",
    "ts_span",
    "proc_exec_span",
]
```

### 補-B7（観点 B Major #8）: Task C-2 Step 5 `_GRAN_*` コメント追加の具体的 Edit

`Read` で `snippet/_ts.py:L13-27` の完全 byte 列を取得後、以下の Edit:

```python
# old_string:
_GRAN_JAVA = {"if_statement", "while_statement", "for_statement",
              "switch_expression", "switch_statement",
              "try_statement", "try_with_resources_statement",
              "local_variable_declaration", "field_declaration",
              "return_statement", "expression_statement", "do_statement"}

# new_string:
# tree-sitter 0.21 系のノード型集合（spec §9 表「ts_span 粒度」と対応）。
# tree-sitter ライブラリ版更新時はこれらの集合を再点検する。
_GRAN_JAVA = {"if_statement", "while_statement", "for_statement",
              "switch_expression", "switch_statement",
              "try_statement", "try_with_resources_statement",
              "local_variable_declaration", "field_declaration",
              "return_statement", "expression_statement", "do_statement"}
```

### 補-B8（観点 B Major #9）: Task C-2 Step 6 `build_snippet` docstring 書換具体例

`Read` で `snippet/__init__.py:L16-47` の `build_snippet` を取得後、以下の Edit（実機を確認した上で構成。subagent が判断）:

C3 形式適用方針:
- 関数本文中の `(spec §X)` 参照は維持（具体的な手順を明確化するため）
- docstring 末尾に `\n    Related: spec §7, §9` を追加
- 重複説明は削除

### 補-B9（観点 B Major #10）: Task A-1 Step 2 `_REF_KIND` PEP8 配置

Task A-1 Step 2 の new_string で `_REF_KIND` の挿入位置を「全 import 群終了直後、関数定義の直前」に明示:

```python
# old_string:
from grep_analyzer.fixedpoint._state import ChaseState, _REF_KIND

# new_string:
from grep_analyzer.fixedpoint._state import ChaseState
```

その後、別 Edit で `_finalize.py` の **`from grep_analyzer.snippet import build_snippet` の直後（最後の import 行直後）に空行 + `_REF_KIND` 定義を挿入**:

```python
# old_string:
from grep_analyzer.snippet import build_snippet


def build_indirect_hits(state: ChaseState) -> list[Hit]:

# new_string:
from grep_analyzer.snippet import build_snippet

_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}


def build_indirect_hits(state: ChaseState) -> list[Hit]:
```

### 補-B10（観点 B Major #11）: Task A-2 の V6 perf 改善期待値

Task A-2 完了後に V6 計測（Step 5）。期待値:
- Phase 3 baseline_median 0.358 秒（Task A6）と同等以下
- 改善幅は理論上 +5%〜+15% の解消（関数内 import 排除分）
- 退行が +5% 超なら直接束縛案（`from grep_analyzer.budget import estimate_items as _estimate_items`）への切替を検討

### 補-B11（観点 B Minor #1）: `s, e` rename の規約適用

Task N-3 Step 1 で `_clamp.py` の `s, e = 0, len(lines) - 1` を **`span_start, span_end` に rename**（N5 計数規約に従い 26 行スコープで除外条件を満たさないため）。

### 補-B12（観点 B Minor #3）: `meta_of` rename 確定

Task N-2 Step 3 で `_finalize.py:28` の `meta_of` を **`file_meta_by_relpath` に統一**（`_scan.py` の同名と整合）。

### 補-B13（観点 B Major #13）: Task 0 ベースライン件数の動的化

Task 0 Step 1 の expected を `249 passed, 5 skipped`（具体値）から「現状の `pytest -q | tail -5` 出力と一致すること（subagent が実機計測値を記録）」に緩和。実機の pass / skip 件数は Phase 4 開始時の HEAD で再測定。

---

## v3 修正補遺（2 巡目 AI レビュー反映）

本 plan v3 では 2 巡目で検出された新規 Critical 1 / Major 3 / Minor 群を解消する。本補遺は v2 補遺・本体に優先する。

### 補-C1（観点 A Critical / 観点 B Major #2）: automaton.py rename の実機整合

**実機の現状**: `automaton.py` は既に `def build(symbols: list[str])`（引数は `symbols`）。ローカルは `syms = [s for s in symbols if s]`（L10）、`for s in syms`（L14）、`au.add_word(s, s)`（L15）、`au = ahocorasick.Automaton()`（L13）。`scan_line` は `for end, sym in au.iter(line)`（L32）。

Task N-1 / inventory L76 / L498 を以下に訂正:
- `syms`（L10 の内包表記中間変数、build 全体スコープだが `symbols` 引数と衝突するため **rename しない・N5 除外で維持**）
- `for s in syms` の `s`（ループ慣用）→ 維持
- `au` → `automaton_obj` に rename（`au = ahocorasick.Automaton()`（L13）、`au.add_word`（L15）、`au.make_automaton`（L16）、`return au`（L17））
- `scan_line(au, line)` の引数 `au` → `automaton_obj` に rename（L20 シグネチャ、L28 `if au is None`、L32 `au.iter(line)`）
- `scan_line` の `for end, sym in au.iter(line)` の `sym`（L32-37 の 4 行スコープ、ループ慣用）→ **N5 除外で維持**
- inventory 表 L76 の「`automaton.py:15` の `sym`」記述は **実機に存在しないため削除**

`_scan.py` の `au`（L40 `au = automaton.build(sym_list)`、L42 `if au is not None`、L44 `automaton.scan_line(au, line)`）→ `automaton_obj` に rename。`for sym in automaton.scan_line(...)` の `sym` は N5 除外で維持。

実施法: automaton.py / _scan.py 各々を `Read` で取得し、`au` を含む行を文脈一致で `automaton_obj` に置換（`au.` / `(au,` / `au is` / `return au` / `= au` 等の境界に注意。`automaton`（モジュール名）/`automaton.build`/`automaton.scan_line` は誤マッチ対象外なので、`\bau\b` 相当の境界で慎重に）。

### 補-C2（観点 A Major / 観点 B Major #1）: tests/ 側 C5 は Phase 4 範囲外

補-B5 を **撤回**し、以下に置き換える:

> tests/ 配下の C5 マーカー（`spec v4 §4 WS*`、`spec v9/v10`、`Inv-N`、テスト関数名内の `Phase2a` 等、24+ 箇所）は **Phase 4 範囲外**。理由:
> - テストは git log トレーサビリティ優先
> - テスト関数名の rename は Inv-B（テスト pass 数・同定）リスク
> - `# 再ベースライン理由A` 等のコメントは golden 再生成の決定性根拠（設計 §4 C2 削除禁止「決定性根拠」に該当）
>
> Task C-1 / V4 検証の C5 違反「ゼロ」判定は **src/grep_analyzer/ 配下のみ**を対象とする。tests/ の C5 整理は将来の clean-up フェーズに委ねる。
>
> 例外: `tests/integration/test_encoding_wiring.py` のコメント `enc_of` → `encoding_of` 表記追従のみ Task N-3 Step 4 で実施（これは C5 ではなく N4 表記追従）。

V4 検証 grep（補-B5）の対象を `src/grep_analyzer/` のみに戻す:
```bash
grep -rEn 'Phase ?[0-9]([a-z]|\.[0-9])?|spec v[0-9]|Inv-[0-9]| v9\b| v10\b|WS[0-9]' src/grep_analyzer/ | \
  grep -v "__pycache__\|Related:.*refactor-design"
```
Expected: 0 件。

### 補-C3（観点 A Major / 観点 B 解消）: ingest docstring は実機で既に hop 説明済

**実機確認**: `_ingest.py` の `ingest_one`（L23-）と `absorb_results`（L66-）の docstring は Phase 3 で既に hop 説明を含む。

Task C-2 Step 2（hop docstring 統一）は以下に変更:
- subagent は `Read` で `_ingest.py` の両 docstring を確認
- 既に hop 説明が十分なら **no-op（skip）**
- 表現を統一する余地があれば軽微修正（ただし byte 不変。テストに影響なし）
- 本体 Task C-2 Step 2 の old_string（`"""1 行を ChaseState に取り込む。spec §8.1 手順 1〜4。"""` の 1 行版）は **実機に存在しないため無効**。skip 判断を優先

### 補-C4（観点 A Major / 観点 B Major #3）: `s, e` rename の atomic 化 + __init__.py:43 の扱い

補-B11 を以下に拡張:

**`_clamp.py` の `s, e`**（L31 定義、L40-57 で多数参照、26 行スコープ → N5 除外条件を満たさず rename 対象）:
- `clamp_lines` 関数全体（実機 `_clamp.py` の該当関数）を `Read` で取得
- `s, e = 0, len(lines) - 1` → `span_start, span_end = 0, len(lines) - 1`
- 関数内の `s` / `e` の全参照を `span_start` / `span_end` に反映した完全版を **1 つの atomic Edit** で置換
- **注意**: `progressed` / `lines` / `else` / `break` 等 `s` / `e` を部分文字列に含む語に誤マッチしないよう、必ず関数全体を old_string にして手動で `s`/`e` のみ置換した new_string を構成（単独 `replace_all="s"` は厳禁）
- `_render(rows, top_k, bot_k)` は別関数で `s`/`e` を持たないため対象外

**`snippet/__init__.py:43` の `s, e = span`**（build_snippet 内、L43-46 の 4 行スコープ）:
- 4 行スコープであり N5 除外条件（3 行以内）を僅かに超えるが、**span を unpack して即座に clamp に渡す局所的慣用** であり、`span_start`/`span_end` への rename は冗長化で可読性低下
- **判定: N5 準用で維持**（_clamp.py の 26 行スコープとは性質が異なる）
- この非対称は「スコープ長と用途」で正当化される（_clamp は関数全体に渡る状態変数、__init__ は span unpack の即時消費）

### 補-C5（観点 A Minor / 観点 B Minor）: 本体 Task A-2 の廃止明示

> **★ 本体 Task A-2 は補-B1（v2 補遺）で全面置換済。本体 Task A-2 の Step 記述（特に `from grep_analyzer.budget import MemoryBudget, estimate_items` を含む old_string）は実機と byte 不一致のため参照しない。Task A-2 の実装は補-B1 の Step 1〜6 のみに従う。**

### 補-C6（観点 B Minor）: output_writer.py:4 の Inv-5 除去の完全行指定

Task C-1 Step 2 表の `output_writer.py:4` 修正を以下の完全行 byte で明示:

`old_string`:
```
正規形は _canonical_data_blob に一元化（書込側=完了判定=Inv-5=テストが共有）。
```
`new_string`:
```
正規形は _canonical_data_blob に一元化（書込側=完了判定=テストが共有）。
```

### 補-C7（観点 B Minor）: baseline ハッシュの動的化

Task 0 Step 2 / 補-B1 Step 5 / 補-B10 の baseline ハッシュ「8fac007」固定記述を撤回。Phase 4 開始時の `git rev-parse HEAD` で取得した実 HEAD を baseline とする（subagent が記録）。perf 比較も同 HEAD を基準にする。

### 補-C8（観点 B Minor）: 補遺 old_string は実機 Read 前提（再掲）

補-B3 を再掲・強調: 全補遺の `old_string` は **意図の提示**。subagent は各 Edit 前に必ず `Read` で実機 byte を取得し、コメント・改行・バッククォート・行末空白を含めて完全一致させる。budget.py:9-11（補-B4）/ _estimate_items docstring（補-B1 Step1）の改行・バッククォートは特に注意。

---

Phase 4 で対処しないが将来検討する項目:
- `Related:` 行（`docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase X [Y]`）の整理 — リファクタリング完了後の clean-up で全削除 or 整理
- `_state.py` を `state.py`（public）に rename する判断（現時点では維持判断、Phase 4 範囲外）
- `_scan.py` の `_scan_file` の private 接頭辞（worker pickle 制約のため pickle 安全名として維持）
