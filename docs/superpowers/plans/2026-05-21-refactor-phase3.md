# Refactor Phase 3: snippet.py 分割 + fixedpoint.py 分割（ChaseState 化）Implementation Plan v2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** snippet.py（246 行）と fixedpoint.py（350 行）を責務別サブパッケージへ分割する。fixedpoint は新規 `ChaseState` データクラスへ局所変数群を集約し、`run_fixedpoint` を薄いオーケストレータに縮約する。挙動は byte 不変（Inv-A〜E 全保持）。

**Architecture:**
- `snippet.py` → `snippet/` サブパッケージ。公開 API `build_snippet`、テスト由来公開 API `clamp_lines` / `heuristic_span` / `ts_span` / `proc_exec_span` は `snippet/__init__.py` で再 export。private 部分は `_clamp` / `_heuristic` / `_ts` / `_sanitize_line` の 4 サブモジュールへ。
- `fixedpoint.py` → `fixedpoint/` サブパッケージ。`run_fixedpoint` と `EngineOptions` は `fixedpoint/__init__.py` で公開（`EngineOptions` の実体は `_options.py` に切り出し）。内部実装は `_state` / `_seed` / `_scan` / `_ingest` / `_budget_control` / `_finalize` の 6 サブモジュールへ。
- `ChaseState` は **main process でのみ保持**、`_scan_file` worker への送信は禁止（pickle/Inv-E 維持）。worker には従来通り `(rel, abspath, sym_list, lang_map, fallback)` のプリミティブのみ渡す。V3 ゲートで `inspect.signature` ベースの機械検証を行う。
- **共有 helper の許容**: `_scan.py` の `_file_meta` / `_kinds_of` は ChaseState を引数に取らない純関数 helper として `_seed` / `_ingest` / `_finalize` から共有 import する。これは「ChaseState は worker に渡さない」「`_state` 経由でやり取りする」原則と矛盾しない（クラス参照を含まない関数の共有は層分離違反ではない）。
- R4 (Rule of Three) 判定: Task A2 Step 0 で **試作的に 1 経路統合版** を実装し、(a) 単一経路時のコード量が現状の `nchunks <= 1` 経路を上回らないか、(b) `automaton_split` diag の発火条件が `nchunks > 1` のみに局所化できるか、を判定する。本 plan の初期仮説は「2 関数並存」だが、Step 0 の試作結果で覆る場合は plan を更新する。
- V6 性能リグレッション抑止: `tests/perf/test_perf.py` の `@pytest.mark.perf` を `pytest -m perf` で明示走らせ、Phase 3 [A] 着手前後で 3 回計測し中央値を比較する。

**Tech Stack:** Python 3.12 / pytest / dataclasses / multiprocessing / typing.Protocol

**Related design:** `docs/superpowers/specs/2026-05-21-refactor-design.md` §6 Phase 3 [C][A], §7 V1-V7, §3 N5

---

## Phase 2 引き継ぎ事項

Phase 2 V5 ゲートで持ち越された Minor を以下のように扱う:

| # | 項目 | 扱い |
|---|---|---|
| 1 | `tests/unit/test_chase.py:46-47` mid-file import（PEP8 E402） | **Phase 3 Task 0b で解消** |
| 2 | `tests/unit/test_stoplist.py:39-40` mid-file import | **Phase 3 Task 0b で解消** |
| 3 | `src/grep_analyzer/chase.py:20-21` の `extract_var_symbols` docstring 「fixedpoint の `_ingest` が...」 | **Phase 3 Task B1 で書換** |
| 4 | `_CHASERS` の private 接頭辞と `__all__` 公開の不整合 | **Phase 3 Task B1 で `__all__` から除外** |
| 5 | `patterns/literal_masking.py` の java/c/proc 完全重複 | Phase 4 持ち越し（Pro*C 個別化のタイミングと連動） |
| 6 | `chase.py` / `snippet.py` module docstring の `Phase 1.5` / `Phase 2` / `v9` 等のマーカー | Phase 4 持ち越し（横断 C5 適用パス） |
| 7 | `classifiers/__init__.py` eager import 失敗リスク（optional deps 不在環境） | Phase 4 持ち越し（運用判断: 現状 deps は requirements_lock 化されており失敗しない） |

---

## ファイル構造（Phase 3 完了時の最終形）

```
src/grep_analyzer/
├── snippet/
│   ├── __init__.py          ← build_snippet（公開）+ 既存 test 由来公開 API の再 export
│   ├── _clamp.py            ← clamp_lines / _render / 定数（LINE_MAX, CHAR_MAX, SEP, ELL）
│   ├── _heuristic.py        ← heuristic_span / _balanced
│   ├── _ts.py               ← ts_span / proc_exec_span / _paren_span / _has_error / _GRAN_* / _STMT / _BLOCK / _PAREN_ONLY
│   └── _sanitize_line.py    ← _physical_lines（旧 _phys）/ _escape_sep
├── fixedpoint/
│   ├── __init__.py          ← run_fixedpoint（薄い orchestrator）+ EngineOptions 再 export
│   ├── _options.py          ← EngineOptions dataclass
│   ├── _state.py            ← ChaseState dataclass + _REF_KIND 定数
│   ├── _seed.py             ← initialize_state（seed_hits → ChaseState 構築・hop0→hop1）
│   ├── _scan.py             ← _scan_file（worker）/ _file_meta / _kinds_of / scan_hop_single / scan_hop_chunked
│   ├── _ingest.py           ← ingest_one（旧クロージャ）/ absorb_results（scan 結果反映）
│   ├── _budget_control.py   ← apply_global_cap / maybe_spill / compute_nchunks
│   └── _finalize.py         ← build_indirect_hits
├── chase.py                 ← extract_var_symbols の docstring を「indirect:var 抽出の用途」中心へ書換
└── classifiers/__init__.py  ← _CHASERS の private/公開を整合（__all__ から除外）
tests/unit/
├── test_chase.py            ← L46-47 mid-file import を先頭へ集約
└── test_stoplist.py         ← L39-40 mid-file import を先頭へ集約
```

> **公開 API の不変性**: `from grep_analyzer.snippet import build_snippet` / `from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint` を含む現行の全 import 文は無変更で動き続けること。

> **Phase 3 範囲の rename**（構造変更に伴うもののみ・最小化）:
> - `_phys` → `_physical_lines`（snippet/_sanitize_line.py）
> - `_err` → `_has_error`（snippet/_ts.py）
> - `intro` → `introducers`、`sym_kind` → `symbol_kind`、`sym_hop` → `symbol_hop`、`estore` → `edge_store`、`enc_of` → `encoding_of`（fixedpoint/_state.py の ChaseState フィールド）
> - `term_active` / `term_done` → `terminal_active` / `terminal_done`（fixedpoint/_state.py）
> - `prog` → `progress`（fixedpoint/__init__.py のローカル変数）
> - `_ingest` → `ingest_one`（fixedpoint/_ingest.py の関数名 / N3 動詞統一）
> - `_apply_global_cap` → `apply_global_cap`（fixedpoint/_budget_control.py / 同上）
>
> その他のローカル変数 rename（`au` / `sym` / `cs` / `dia` / `agg` / `meta` 等）は **Phase 4** で実施する。

---

### Task 0a: ベースライン確立 + 性能 baseline 計測

**Files:** Create `docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md`

- [ ] **Step 1: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`（Phase 2 完了時点と一致）。なお現状 254 件 collected、うち 5 件は `@pytest.mark.perf` で既定 skip。

- [ ] **Step 2: ベースライン commit hash を取得**

Run: `cd /workspaces/grep_helpers2 && git rev-parse HEAD`

40 文字の commit hash を控える（Phase 3 全体の baseline）。

- [ ] **Step 3: V6 perf baseline 計測（`tests/perf/test_perf.py` の最大ケース）**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  ls tests/perf/ && \
  grep -n "@pytest.mark.perf\|n_files\|def test_" tests/perf/test_perf.py | head -20
```

`tests/perf/test_perf.py` の最大 n_files ケース（例: `test_scale[800]`）を 3 回実行:

```bash
cd /workspaces/grep_helpers2 && for i in 1 2 3; do
  pytest tests/perf/test_perf.py -m perf -q -s 2>&1 | grep -E "PERF|dt=" | tail -5
  echo "---"
done
```

各実行で出力される `PERF n=... dt=<秒>` の中で **最大 n** の `dt` を 3 回分記録。中央値を baseline_median とする。

- [ ] **Step 4: perf 記録ファイル作成**

Create: `docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md`

```markdown
# Phase 3 V6 性能計測

## Baseline (Phase 2 完了時点: <commit hash>)

- 計測コマンド: `pytest tests/perf/test_perf.py -m perf -q -s | grep PERF`
- 対象ケース: 最大 n_files（test_perf.py で固定された最大値）
- 3 回実行の dt (秒): [t1, t2, t3]
- 中央値: <baseline_median>

## R4 試作判定 (Task A2 Step 0 で記録)

| 項目 | 判定 |
|---|---|
| 統合版コード量 | <行数> |
| 並存版コード量 | <行数> |
| diag 発火局所性 | OK/NG |
| 採用: 統合 or 並存 | <結論> |

## Phase 3 [A] 完了後

（Task A6 後に記録）

### `force_chunks=0`（single 経路）
- 3 回実行: [t1, t2, t3]
- 中央値: <new_median_single>

### `force_chunks=3`（chunked 経路, R4 並存採用時のみ）
- 3 回実行: [t1, t2, t3]
- 中央値: <new_median_chunked>

## 判定

baseline_median + 10% 又は +5 秒以内であれば許容。
- single: baseline_median <baseline> → new <new_single>（差 <diff>%）→ OK/NG
- chunked: 同上
```

- [ ] **Step 5: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md && \
  git commit -m "docs(plan): Phase 3 V6 性能 baseline 計測結果"
```

---

### Task 0b: tests の mid-file import 集約（Phase 2 引き継ぎ #1 + #2）

**Files:**
- Modify: `tests/unit/test_chase.py`（L3 を multi-line 形式に置換 + L46-47 削除）
- Modify: `tests/unit/test_stoplist.py`（L39-40 を先頭へ移動）

- [ ] **Step 1: 現状確認**

```bash
cd /workspaces/grep_helpers2 && \
  grep -n "^from\|^import\|ChaseSymbols" tests/unit/test_chase.py | head -20 && \
  echo "---" && \
  grep -n "^from\|^import" tests/unit/test_stoplist.py | head -20
```

`ChaseSymbols` が `tests/unit/test_chase.py` 本文で使用されているか確認。本文（コード）で `ChaseSymbols(` のインスタンス化が無ければ import 不要。

- [ ] **Step 2: test_chase.py の Edit**

`old_string`:
```python
from grep_analyzer.chase import extract_var_symbols
```
`new_string`:
```python
from grep_analyzer.chase import (
    extract_chase_symbols,
    extract_var_symbols,
    mask_literals,
)
```

ただし Step 1 の確認で `ChaseSymbols` が本文で **使用されている** 場合のみ、追加で:

`old_string`:
```python
from grep_analyzer.chase import (
    extract_chase_symbols,
    extract_var_symbols,
    mask_literals,
)
```
`new_string`:
```python
from grep_analyzer.chase import (
    extract_chase_symbols,
    extract_var_symbols,
    mask_literals,
)
from grep_analyzer.model import ChaseSymbols
```

その後 L46-47 の mid-file import を削除:

`old_string`:
```python
from grep_analyzer.chase import extract_chase_symbols, mask_literals
from grep_analyzer.model import ChaseSymbols
```
`new_string`:（空文字列で削除）

- [ ] **Step 3: test_stoplist.py の Edit**

ファイル先頭（既存の `from grep_analyzer.stoplist import SymbolPolicy, admit, load_stoplist` がある行）を以下に置換:

`old_string`:
```python
from grep_analyzer.stoplist import SymbolPolicy, admit, load_stoplist
```
`new_string`:
```python
from grep_analyzer.model import ChaseSymbols
from grep_analyzer.stoplist import SymbolPolicy, admit, load_stoplist, partition
```

その後、L39-40 の mid-file import（具体的には `from grep_analyzer.model import ChaseSymbols` と `from grep_analyzer.stoplist import partition`）を削除。

- [ ] **Step 4: テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest tests/unit/test_chase.py tests/unit/test_stoplist.py -q`

Expected: 全件 pass（テスト内容不変）。

- [ ] **Step 5: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add tests/unit/test_chase.py tests/unit/test_stoplist.py && \
  git commit -m "style(tests): mid-file import を先頭へ集約（Phase 2 引き継ぎ Minor #1 #2 / PEP8 E402）"
```

---

## Part [C]: snippet.py 責務分割（Task C1）

snippet.py を `snippet/` サブパッケージに**単一の atomic commit で**分解する。`snippet.py` ファイルと `snippet/` パッケージは Python の名前解決で衝突するため、中間 commit を打たない。

### Task C1: snippet/ サブパッケージへの一括移行（atomic 1 commit）

**Files:**
- Create: `src/grep_analyzer/snippet/__init__.py`
- Create: `src/grep_analyzer/snippet/_clamp.py`
- Create: `src/grep_analyzer/snippet/_heuristic.py`
- Create: `src/grep_analyzer/snippet/_ts.py`
- Create: `src/grep_analyzer/snippet/_sanitize_line.py`
- Delete: `src/grep_analyzer/snippet.py`

- [ ] **Step 1: ディレクトリ作成**

Run: `cd /workspaces/grep_helpers2 && mkdir -p src/grep_analyzer/snippet`

- [ ] **Step 2: `_clamp.py` を作成（既存 snippet.py L1-72 から抽出）**

Create `src/grep_analyzer/snippet/_clamp.py`:

```python
"""snippet 縮約（spec §9「上限と切り詰め」）。

ヒット行を中心に上下対称に拡張し、行数 LINE_MAX / 文字数 CHAR_MAX で
頭打ちにする。文字数は連結後 body の Python `len()`（コードポイント数）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

SEP = " \\n "
ELL = "…"
LINE_MAX = 12
CHAR_MAX = 800


def _render(rows: list[str], top_k: int, bot_k: int) -> str:
    body = SEP.join(rows)
    if top_k:
        body = f"{ELL}(+{top_k}上行省略)" + body
    if bot_k:
        body = body + f"{ELL}(+{bot_k}下行省略)"
    return body


def clamp_lines(lines: list[str], hit: int, line_max: int = LINE_MAX,
                char_max: int = CHAR_MAX) -> str:
    """選択範囲 lines をヒット中心に縮約。

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
```

- [ ] **Step 3: `_heuristic.py` を作成（既存 snippet.py L74-118 から抽出）**

Create `src/grep_analyzer/snippet/_heuristic.py`:

```python
"""sql/shell ヒューリスティック span（spec §9 表「決定的境界」）。

mask_literals を行ごとに適用し、句境界・文末・shell 終端で停止する。
heredoc は mask 非対応＝§8.4 既知境界。LINE_MAX で必ず有限停止。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

from grep_analyzer.chase import mask_literals
from grep_analyzer.patterns.snippet_boundaries import (
    SH_TERMINATOR_RE,
    SQL_CLAUSE_RE,
)
from grep_analyzer.snippet._clamp import LINE_MAX


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
            return x.rstrip().endswith(";") or bool(SQL_CLAUSE_RE.search(x))
        return bool(SH_TERMINATOR_RE.search(x))

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
```

- [ ] **Step 4: `_ts.py` を作成（既存 snippet.py L130-205 から抽出。`_err` → `_has_error` rename）**

Create `src/grep_analyzer/snippet/_ts.py`:

```python
"""tree-sitter による java/c span（spec §9 段1→段2）+ Pro*C EXEC span。

node_at_line で最小内包葉を取り、.parent 上昇で粒度表へ昇格する。
block 等到達は直近 statement。proc は mask_exec_sql 後を解析（行番号保存）。
ERROR/MISSING は**確定した選択ノードの部分木のみ**で判定。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

from grep_analyzer.classifiers.ts_classifier import node_at_line, parse_tree
from grep_analyzer.proc_preprocess import exec_spans, mask_exec_sql

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
    """( 〜対応 ) の物理行スパン（spec §9 表）。AST 子で取得（文字列内括弧に頑健）。"""
    for ch in node.children:
        if ch.type == "parenthesized_expression":
            return (ch.start_point[0], ch.end_point[0])
    lp = next((c for c in node.children if c.type == "("), None)
    rps = [c for c in node.children if c.type == ")"]
    if lp is not None and rps:
        return (lp.start_point[0], rps[-1].end_point[0])
    return (node.start_point[0], node.end_point[0])


def _has_error(node) -> bool:
    """ERROR/MISSING 判定。`has_error` は子孫包含の真偽（py-tree-sitter 0.21）。

    判定は**選択ノードの部分木のみ**（祖先遡上しない＝ファイル内の無関係な
    エラーで健全行を捨てない・部分木継続）。
    """
    return node.is_missing or node.type == "ERROR" or node.has_error


def ts_span(language: str, file_text: str, lineno: int):
    """java/c 選択範囲 [s,e]（0始まり物理行）。取れなければ None（→fallback）。

    段1（node_at_line=最小内包葉・列非依存）→段2（.parent 上昇で粒度表へ
    昇格／block 等到達は直近 statement／無ければ None）。proc は生 EXEC が
    C パースを壊すため mask_exec_sql 後を解析（行番号保存）。
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
            if _has_error(cur):
                return None
            if t in _PAREN_ONLY:
                return _paren_span(cur)
            return (cur.start_point[0], cur.end_point[0])
        if t in _BLOCK:
            if last_stmt is None or _has_error(last_stmt):
                return None
            return (last_stmt.start_point[0], last_stmt.end_point[0])
        cur = cur.parent
    if last_stmt is None or _has_error(last_stmt):
        return None
    return (last_stmt.start_point[0], last_stmt.end_point[0])


def proc_exec_span(file_text: str, lineno: int):
    """Pro*C EXEC SQL 区間にヒットがあれば、生 EXEC 行のスパン [s,e] を返す。

    区間外は None。proc 言語で `ts_span("proc", ...)` の前段に呼ばれ、
    EXEC 区間の整列を優先する。

    Related: spec §7 (Pro*C 取扱), §9 (snippet)
    """
    hit = lineno - 1
    for s, e in exec_spans(file_text):
        if s <= hit <= e:
            return (s, e)
    return None
```

- [ ] **Step 5: `_sanitize_line.py` を作成（既存 snippet.py L20-25, L208-211 から抽出。`_phys` → `_physical_lines` rename）**

Create `src/grep_analyzer/snippet/_sanitize_line.py`:

```python
"""snippet 行サニタイズ（spec §9 規約①②）と物理行分解。

物理行分解は末尾改行由来の人工空要素を 1 個だけ除去する。
区切り衝突エスケープは行中の ' \\n ' と同一 4 文字並びの \\ を二重化する。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

from grep_analyzer.snippet._clamp import SEP


def _physical_lines(file_text: str) -> list[str]:
    """物理行配列。末尾改行由来の人工空要素を 1 個だけ除去（spec §9 物理行定義）。"""
    lines = file_text.split("\n")
    if file_text.endswith("\n") and lines and lines[-1] == "":
        lines = lines[:-1]
    return lines


def _escape_sep(line: str) -> str:
    """行中の区切り列 ' \\n '(U+0020 005C 006E 0020) と同一 4 文字並びの
    \\(U+005C) を \\\\ へ二重化（区切りと本文の曖昧化防止）。"""
    return line.replace(SEP, " \\\\n ")
```

- [ ] **Step 6: `snippet/__init__.py` を作成（既存 snippet.py L214-end の build_snippet を保持）**

Create `src/grep_analyzer/snippet/__init__.py`:

```python
"""snippet 切り出し（spec §9）パッケージ。

公開エントリは build_snippet。clamp_lines / heuristic_span / ts_span /
proc_exec_span は仕様検証用の test 由来公開 API として再 export する。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [C]
"""

from grep_analyzer.snippet._clamp import clamp_lines
from grep_analyzer.snippet._heuristic import heuristic_span
from grep_analyzer.snippet._sanitize_line import _escape_sep, _physical_lines
from grep_analyzer.snippet._ts import proc_exec_span, ts_span
from grep_analyzer.tsv import _sanitize


def build_snippet(language: str, dialect: str, file_text: str,
                  lineno: int) -> str:
    """spec §9 snippet 切り出しのエントリ。確定済み 1 セル文字列を返す。

    java/c: ts_span→無ければ ヒット 1 行（spec §9 フォールバック: java/c に
      sql/shell ヒューリスティックは適用しない）。
    proc: EXEC 区間=proc_exec_span／区間外=ts_span("proc",..)（内部で
      mask_exec_sql 後 C 解析）→ いずれも None なら ヒット 1 行（spec §7/§9）。
    sql/shell: heuristic_span（AST 非使用）。
    `dialect` は将来 cshell 境界用の予約引数（v1 未使用・呼出互換のため受領）。
    連結前に各行へ _sanitize→_escape_sep を適用し clamp_lines。
    """
    lines = _physical_lines(file_text)
    hit = lineno - 1
    if hit < 0 or hit >= len(lines):
        return ""
    span = None
    if language in ("java", "c"):
        span = ts_span(language, file_text, lineno)
    elif language == "proc":
        span = proc_exec_span(file_text, lineno)
        if span is None:
            span = ts_span("proc", file_text, lineno)
    elif language in ("sql", "shell"):
        span = heuristic_span(lines, hit, language)
    if span is None:
        span = (hit, hit)
    s, e = span
    s = max(0, min(s, hit))
    e = min(len(lines) - 1, max(e, hit))
    body = [_escape_sep(_sanitize(x)) for x in lines[s:e + 1]]
    return clamp_lines(body, hit - s)


__all__ = [
    "build_snippet",
    "clamp_lines",
    "heuristic_span",
    "ts_span",
    "proc_exec_span",
]
```

- [ ] **Step 7: 旧 `snippet.py` を削除**

Run: `cd /workspaces/grep_helpers2 && rm src/grep_analyzer/snippet.py`

- [ ] **Step 8: import 健全性確認**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "from grep_analyzer.snippet import build_snippet, clamp_lines, heuristic_span, ts_span, proc_exec_span; print('OK')"
```

Expected: `OK`

- [ ] **Step 9: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`（変動なし）。golden test も byte 一致。

- [ ] **Step 10: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/snippet/ && \
  git rm src/grep_analyzer/snippet.py 2>/dev/null || true && \
  git commit -m "refactor(snippet): snippet.py を snippet/ サブパッケージへ分割（_clamp/_heuristic/_ts/_sanitize_line）"
```

---

## Part [A]: fixedpoint.py 分割（Task A1a〜A6）

fixedpoint.py を `fixedpoint/` サブパッケージへ分解する。`ChaseState` を新規データクラスとして導入し、局所変数群と `_ingest` / `_apply_global_cap` クロージャを抽出する。

**設計方針**:
- Task A1a で **内容を一切変えずに** `fixedpoint.py` を `fixedpoint/__init__.py` へ移動（git mv）
- Task A1b で `_state.py` / `_options.py` を追加し、`__init__.py` 内の局所変数を Edit ベースで `state.xxx` に逐次置換
- Task A2〜A5 で各責務を別モジュールに抽出
- 各 Task は **1 commit / pytest 全件 pass** を維持

### Task A1a: fixedpoint.py の git mv（内容不変）

**Files:**
- Move: `src/grep_analyzer/fixedpoint.py` → `src/grep_analyzer/fixedpoint/__init__.py`

- [ ] **Step 1: ディレクトリ作成 + ファイル移動**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  mkdir -p src/grep_analyzer/fixedpoint && \
  git mv src/grep_analyzer/fixedpoint.py src/grep_analyzer/fixedpoint/__init__.py
```

- [ ] **Step 2: import 健全性 + 全テスト**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint; print('OK')" && \
  pytest -q 2>&1 | tail -5
```

Expected: `OK` + `249 passed, 5 skipped`。

- [ ] **Step 3: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git commit -m "refactor(fixedpoint): fixedpoint.py を fixedpoint/__init__.py へ git mv（内容不変・サブパッケージ化準備）"
```

---

### Task A1b: _state.py + _options.py 導入 + ChaseState 経由化（Edit 個別置換）

**Files:**
- Create: `src/grep_analyzer/fixedpoint/_state.py`
- Create: `src/grep_analyzer/fixedpoint/_options.py`
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`（14 局所変数 → `state.xxx` へ個別 Edit）

- [ ] **Step 1: `_options.py` を作成（既存 `__init__.py` の `EngineOptions` を抽出）**

Create `src/grep_analyzer/fixedpoint/_options.py`:

```python
"""EngineOptions: エンジン挙動パラメータ（spec §8/§10.4）。

`run_fixedpoint` 経由でエンジン内部で参照される。`fixedpoint/__init__.py`
から `from grep_analyzer.fixedpoint import EngineOptions` で再 export される。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EngineOptions:
    """spec §8/§10.4 のエンジン挙動パラメータ。"""

    max_depth: int
    min_specificity: int
    stoplist_path: Path | None
    lang_map: dict[str, str]
    include: list[str]
    exclude: list[str]
    jobs: int
    follow_symlinks: bool
    max_file_bytes: int
    max_symbols: int
    max_paths: int
    memory_limit_mb: int | None = None
    use_ripgrep: bool = False
    max_passes: int = 8
    progress: str = "off"
    spill_dir: Path | None = None
    force_chunks: int = 0
    resume: bool = False
    output_encoding: str = "utf-8-sig"
    encoding_fallback: tuple[str, ...] = ("cp932", "euc-jp", "latin-1")
    max_rows_per_part: int = 1_048_575
    diagnostics_detail_limit: int = 1000
```

- [ ] **Step 2: `_state.py` を作成**

Create `src/grep_analyzer/fixedpoint/_state.py`:

```python
"""ChaseState: run_fixedpoint の局所状態を集約するデータクラス。

main process でのみ保持・更新する（multiprocessing worker には渡さない）。
worker には _scan_file へ (rel, abspath, sym_list, lang_map, fallback) の
プリミティブのみ渡す（pickle 制約 + Inv-E 決定性維持）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from dataclasses import dataclass, field
from pathlib import Path

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy

_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}


@dataclass
class ChaseState:
    """不動点反復の全状態。main process 専有。

    `introducers`: シンボル -> 実抽出元 Occurrence 群（spec §8.2「発見元」）
    `symbol_kind`: シンボル -> kind（constant/var/getter/setter、最終 setter は
      逆順ループで最後に書き込む constant が最強）
    `symbol_hop`: シンボル -> 投入された hop 番号（決定性キー）
    `chase_active`/`chase_done`: chase 対象（constant/var）の active/done 集合
    `terminal_active`/`terminal_done`: terminal 対象（getter/setter）の集合
    `capped`: --memory-limit 等で切り捨てたシンボル
    `rel_to_abs`: walk 結果（rel → abspath）。worker への送信用 abspath を保持
    `encoding_of`: rel → (encoding, replaced)。scan 結果から逐次更新
    `*_logged`: 同一事象の重複 diagnostics 抑止用
    """

    source_root: Path
    options: EngineOptions
    diagnostics: Diagnostics
    policy: SymbolPolicy
    budget: MemoryBudget
    graph: ProvenanceGraph
    edge_store: EdgeStore
    keyword: str
    introducers: dict[str, list[Occurrence]] = field(default_factory=dict)
    symbol_kind: dict[str, str] = field(default_factory=dict)
    symbol_hop: dict[str, int] = field(default_factory=dict)
    chase_active: set[str] = field(default_factory=set)
    chase_done: set[str] = field(default_factory=set)
    terminal_active: set[str] = field(default_factory=set)
    terminal_done: set[str] = field(default_factory=set)
    capped: set[str] = field(default_factory=set)
    rel_to_abs: dict[str, Path] = field(default_factory=dict)
    encoding_of: dict[str, tuple[str, bool]] = field(default_factory=dict)
    spill_logged: bool = False
    no_expand_logged: set[str] = field(default_factory=set)
    replaced_logged: set[str] = field(default_factory=set)
    maxdepth_logged: set[Occurrence] = field(default_factory=set)
```

- [ ] **Step 3: `__init__.py` の `EngineOptions` 定義を削除し import に置換**

Edit `src/grep_analyzer/fixedpoint/__init__.py`:

`old_string`:
```python
@dataclass(frozen=True)
class EngineOptions:
    """spec §8/§10.4 のエンジン挙動パラメータ（Phase 2a/2b 範囲）。"""

    max_depth: int
    min_specificity: int
    stoplist_path: Path | None
    lang_map: dict[str, str]
    include: list[str]
    exclude: list[str]
    jobs: int
    follow_symlinks: bool
    max_file_bytes: int
    max_symbols: int
    max_paths: int
    memory_limit_mb: int | None = None
    use_ripgrep: bool = False
    max_passes: int = 8
    progress: str = "off"
    spill_dir: Path | None = None
    force_chunks: int = 0
    resume: bool = False
    output_encoding: str = "utf-8-sig"
    encoding_fallback: tuple[str, ...] = ("cp932", "euc-jp", "latin-1")
    max_rows_per_part: int = 1_048_575
    diagnostics_detail_limit: int = 1000
```
`new_string`:
```python
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._state import ChaseState, _REF_KIND
```

そして以下も削除（重複定義防止）:

`old_string`:
```python
from dataclasses import dataclass
from pathlib import Path
```
`new_string`:
```python
from pathlib import Path
```

`old_string`:
```python
_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}
```
`new_string`:（空文字列で削除）

- [ ] **Step 4: `run_fixedpoint` 内の局所変数を ChaseState 経由に置換**

`__init__.py` の `run_fixedpoint` 内冒頭、`keyword = ...` の直後に ChaseState 構築を挿入する。

`old_string`:
```python
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    intro: dict[str, list[Occurrence]] = {}   # symbol -> 実抽出元 Occurrence 群
    sym_kind: dict[str, str] = {}
    sym_hop: dict[str, int] = {}
    estore = EdgeStore(opts.spill_dir, budget)
    spill_logged = False
    chase_active: set[str] = set()
    chase_done: set[str] = set()
    term_active: set[str] = set()
    term_done: set[str] = set()
    capped: set[str] = set()
    no_expand_logged: set[str] = set()
    replaced_logged: set[str] = set()
    maxdepth_logged: set[Occurrence] = set()
```
`new_string`:
```python
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    state = ChaseState(
        source_root=source_root,
        options=opts,
        diagnostics=diag,
        policy=policy,
        budget=budget,
        graph=graph,
        edge_store=EdgeStore(opts.spill_dir, budget),
        keyword=keyword,
    )
```

- [ ] **Step 5: 関数本体内の局所変数参照を `state.xxx` に置換（replace_all で個別）**

`__init__.py` 内で、`run_fixedpoint` 関数スコープ全体に対して以下を **個別の Edit + replace_all=False** で実施。各 Edit は周辺コンテキストを含めて一意化する必要があるため、subagent は Edit が失敗した場合 **より広いコンテキスト** を `old_string` に含めて再試行する。

主な置換対象（subagent は `__init__.py` 内で grep して全箇所を発見し、文脈に応じて置換）:

| 旧 | 新 |
|---|---|
| `intro[sym]` / `intro.setdefault(sym, [])` / `intro.get(sym, [])` / `len(intro.values())` / `sum(len(v) for v in intro.values())` | `state.introducers...`（同様に） |
| `sym_kind.setdefault` / `sym_kind.get` | `state.symbol_kind.setdefault` / `state.symbol_kind.get` |
| `sym_hop.setdefault` / `sym_hop.get` | `state.symbol_hop.setdefault` / `state.symbol_hop.get` |
| `estore.add` / `estore.maybe_spill_now` / `estore.spilled` / `estore.in_memory_len()` / `estore.sorted_unique()` / `estore.close()` | `state.edge_store....`（同様に） |
| `spill_logged` | `state.spill_logged` |
| `chase_active` (除く `state.chase_active = set()`) | `state.chase_active` |
| `chase_done` | `state.chase_done` |
| `term_active` | `state.terminal_active` |
| `term_done` | `state.terminal_done` |
| `capped` | `state.capped` |
| `no_expand_logged` | `state.no_expand_logged` |
| `replaced_logged` | `state.replaced_logged` |
| `maxdepth_logged` | `state.maxdepth_logged` |
| `enc_of` | `state.encoding_of` |
| `rel_to_abs` (定義 `rel_to_abs = {...}` 行も) | `state.rel_to_abs`（定義行は `state.rel_to_abs = {rel: abspath for rel, abspath in files}`） |

各置換は subagent が以下のいずれかの方法で実施:
- (a) 該当行をユニーク文脈で個別 `Edit`
- (b) **同一行内で完結する単純置換**（例: `intro[sym]` → `state.introducers[sym]`）は `replace_all=True` で一括

**重要**: 内側のクロージャ `_ingest` / `_apply_global_cap` も同様に書き換える（クロージャ内で `state.xxx` を参照する）。クロージャは `state` を外側スコープから捕獲する。

- [ ] **Step 6: `_ingest` クロージャの引数を整理（is_seed パラメータ位置不変・本体のみ state 経由化）**

`_ingest` 関数の引数 `(parent, language, dialect, line, hop, is_seed=False)` は維持。本体内の `intro` / `chase_active` / `term_active` / `sym_kind` / `sym_hop` / `capped` / `maxdepth_logged` 参照を全て `state.xxx` に置換。

- [ ] **Step 7: 型 hint の import 整理**

`__init__.py` の不要 import を削除:

`old_string`:
```python
from grep_analyzer.budget import MemoryBudget, estimate_items
```
`new_string`:
```python
from grep_analyzer.budget import estimate_items
```
（`MemoryBudget` は `_state.py` 内のみで参照）

`old_string`:
```python
from grep_analyzer.spill import EdgeStore
```
`new_string`:（空文字列で削除。EdgeStore は `state.edge_store` 経由で参照されるため）

ただし `EdgeStore(opts.spill_dir, budget)` の呼出が `state = ChaseState(...)` 内の `edge_store=` に残るため、import は残す必要あり。再確認:

→ `EdgeStore(opts.spill_dir, budget)` が `state = ChaseState(..., edge_store=EdgeStore(opts.spill_dir, budget), ...)` の中で呼ばれる。よって `from grep_analyzer.spill import EdgeStore` は維持する。

- [ ] **Step 8: import 健全性 + 全テスト**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint; from grep_analyzer.fixedpoint._state import ChaseState; print('OK')" && \
  pytest -q 2>&1 | tail -5
```

Expected: `OK` + `249 passed, 5 skipped`。

- [ ] **Step 9: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git commit -m "refactor(fixedpoint): _state.py + _options.py 導入、run_fixedpoint を ChaseState 経由に置換（A1b）"
```

---

### Task A2: R4 試作判定 + _scan.py 抽出

**Files:**
- Create: `src/grep_analyzer/fixedpoint/_scan.py`
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`（`_file_meta`/`_scan_file`/`_kinds_of` 削除 + import 置換）

- [ ] **Step 0: R4 事前試作判定**

設計 §5 R4 に従い、`scan_hop_single` と `scan_hop_chunked` を **統合する案**（単一関数 `scan_hop(scan_syms, scan_files, opts, nchunks)`）と **並存する案** のコード量・診断局所性を比較する。

試作（並存案）:
```python
def scan_hop_single(scan_syms, scan_files, opts):
    args = [(rel, str(abspath), scan_syms, opts.lang_map, list(opts.encoding_fallback))
            for rel, abspath in scan_files]
    results = ([_scan_file(a) for a in args] if opts.jobs <= 1 else
               _pool_map(opts.jobs, args))
    return sorted(results, key=lambda r: r[0])

def scan_hop_chunked(scan_syms, scan_files, opts, nchunks):
    size = -(-len(scan_syms) // nchunks)
    chunks = [scan_syms[i:i + size] for i in range(0, len(scan_syms), size)] or [[]]
    agg, meta = {}, {}
    for chunk in chunks:
        args = [(rel, str(abspath), chunk, opts.lang_map, list(opts.encoding_fallback))
                for rel, abspath in scan_files]
        res = ([_scan_file(a) for a in args] if opts.jobs <= 1 else
               _pool_map(opts.jobs, args))
        for rel, enc, replaced, language, dialect, found in res:
            meta.setdefault(rel, (enc, replaced, language, dialect))
            agg.setdefault(rel, []).extend(found)
    return ([(rel, *meta[rel], sorted(agg[rel], key=lambda t: (t[1], t[0])))
             for rel in sorted(agg)], len(chunks))
```

試作（統合案）:
```python
def scan_hop(scan_syms, scan_files, opts, nchunks):
    if nchunks <= 1:
        chunks = [scan_syms]
    else:
        size = -(-len(scan_syms) // nchunks)
        chunks = [scan_syms[i:i + size] for i in range(0, len(scan_syms), size)] or [[]]
    agg, meta = {}, {}
    for chunk in chunks:
        args = [(rel, str(abspath), chunk, opts.lang_map, list(opts.encoding_fallback))
                for rel, abspath in scan_files]
        res = ([_scan_file(a) for a in args] if opts.jobs <= 1 else
               _pool_map(opts.jobs, args))
        for rel, enc, replaced, language, dialect, found in res:
            meta.setdefault(rel, (enc, replaced, language, dialect))
            agg.setdefault(rel, []).extend(found)
    return ([(rel, *meta[rel], sorted(agg[rel], key=lambda t: (t[1], t[0])))
             for rel in sorted(agg)], len(chunks))
```

判定基準:
1. **コード量**: 統合案は ~16 行、並存案 single+chunked 合計 ~22 行 → 統合案がやや短い
2. **diag 局所性**: 統合案では呼出側で `if nchunks > 1: diag.add("automaton_split", ...)` を書く必要があるが、並存案でも呼出側で書く必要があり同等
3. **挙動同値性**: 統合案で `nchunks=1` ⇒ `chunks=[scan_syms]` の単発実行で、結果は既存と byte 一致（`agg` で集約せず単一 chunk なら sorted 結果に差なし）

**判定結論（仮）**: 統合案を採用する（コード量 -6 行・diag 発火条件は呼出側で明示）。

**ただし**: subagent は試作版を**実機で書き上げて pytest 全件 pass を確認した後**に判定確定する。pass しない場合は本 plan の仮判定を覆し、並存案で進める。

- [ ] **Step 1: 判定確定後、`_scan.py` を作成（統合案採用時）**

Create `src/grep_analyzer/fixedpoint/_scan.py`:

```python
"""scan worker と scan-hop オーケストレーション。

`_scan_file` は multiprocessing.Pool 用のトップレベル純関数（pickle 制約）。
ChaseState は worker に渡さず、main process で構築した args タプルのみ渡す。
`scan_hop` は ChaseState から取り出した必要プリミティブだけを引数に取り、
worker からの戻り値を呼出側で ChaseState へ反映する。

`_file_meta` / `_kinds_of` は ChaseState を引数に取らない純関数 helper として
`_seed` / `_ingest` / `_finalize` から共有 import される（pickle 制約と矛盾なし）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

import multiprocessing
from pathlib import Path

from grep_analyzer import automaton
from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.dispatch import detect_language, detect_shell_dialect


def _file_meta(rel: str, raw: bytes, lang_map: dict[str, str], fallback_chain=None):
    """1 度だけデコードし (text, encoding, replaced, language, dialect) を返す。"""
    chain = list(fallback_chain) if fallback_chain else DEFAULT_FALLBACK
    text, enc, replaced = decode_bytes(raw, chain)
    language = detect_language(rel, text[:4096], lang_map)
    dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
    return text, enc, replaced, language, dialect


def _scan_file(args):
    """1 ファイルをワーカ内で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む。automaton 走査は raw 行。
    """
    rel, abspath, sym_list, lang_map, fallback = args
    raw = Path(abspath).read_bytes()
    text, enc, replaced, language, dialect = _file_meta(rel, raw, lang_map, fallback_chain=fallback)
    au = automaton.build(sym_list)
    found = []
    if au is not None:
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(au, line):
                found.append((sym, i, line))
    return rel, enc, replaced, language, dialect, found


def _kinds_of(language: str, dialect: str, line: str) -> dict[str, str]:
    """1 行の各シンボル→種別。同名は逆順ループで最後に書き込む constant が優先。"""
    cs = extract_chase_symbols(language, dialect, line)
    out: dict[str, str] = {}
    for kind, names in (("setter", cs.setters), ("getter", cs.getters),
                        ("var", cs.vars), ("constant", cs.constants)):
        for n in names:
            out[n] = kind
    return out


def scan_hop(scan_syms, scan_files, opts, nchunks):
    """1 hop の走査を chunks に分けて実行し、rel 単位の集約済み結果を返す。

    `nchunks=1` の場合は単一 chunk として全 sym を 1 度に走査する（既存
    fixedpoint.py L260-272 の単発経路と byte 同値）。`nchunks>1` の場合は
    chunk 別に Pool.map し、rel 単位で found を集約してから (lineno, sym) で
    再ソート（既存 L273-289 と byte 同値）。

    戻り値: (pass_results, n_actual_chunks)
      - pass_results: [(rel, enc, replaced, language, dialect, found)] の list
      - n_actual_chunks: 呼出側 diag.add("automaton_split", ...) 用
    """
    if nchunks <= 1:
        chunks = [scan_syms]
    else:
        size = -(-len(scan_syms) // nchunks)
        chunks = [scan_syms[i:i + size]
                  for i in range(0, len(scan_syms), size)] or [[]]
    agg: dict[str, list] = {}
    meta: dict[str, tuple] = {}
    for chunk in chunks:
        args = [(rel, str(abspath), chunk, opts.lang_map, list(opts.encoding_fallback))
                for rel, abspath in scan_files]
        if opts.jobs > 1:
            with multiprocessing.Pool(opts.jobs) as pool:
                res = pool.map(_scan_file, args)
        else:
            res = [_scan_file(a) for a in args]
        for rel, enc, replaced, language, dialect, found in res:
            meta.setdefault(rel, (enc, replaced, language, dialect))
            agg.setdefault(rel, []).extend(found)
    pass_results = [(rel, *meta[rel],
                     sorted(agg[rel], key=lambda t: (t[1], t[0])))
                    for rel in sorted(agg)]
    return pass_results, len(chunks)
```

- [ ] **Step 2: R4 判定の `phase3-perf.md` への記録**

`docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md` の R4 試作判定セクションを更新:

```markdown
## R4 試作判定

| 項目 | 並存案 | 統合案 |
|---|---|---|
| コード量 | ~22 行 | ~16 行 |
| diag 発火局所性 | 呼出側 | 呼出側（同等） |
| pytest 全件 pass | OK | OK |
| 結論 | × | **採用** |

統合に進む（差分が "chunks の構築方法" だけに収束、R4 規約 §5 を満たす）。
```

- [ ] **Step 3: `__init__.py` から `_file_meta`/`_scan_file`/`_kinds_of` を削除 + import 置換**

`__init__.py` の各関数定義を削除し、import を `_scan` 経由に統一:

`old_string`:
```python
def _file_meta(rel: str, raw: bytes, lang_map: dict[str, str], fallback_chain=None):
    """1 度だけデコードし (text, enc, replaced, language, dialect) を返す。"""
    chain = list(fallback_chain) if fallback_chain else DEFAULT_FALLBACK
    text, enc, replaced = decode_bytes(raw, chain)
    language = detect_language(rel, text[:4096], lang_map)
    dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
    return text, enc, replaced, language, dialect


def _scan_file(args):
    """1 ファイルをワーカ内で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む（spec §8.2）。
    automaton 走査は raw 行。出力は Phase 2a と byte 不変。
    """
    rel, abspath, sym_list, lang_map, fallback = args
    raw = Path(abspath).read_bytes()
    text, enc, replaced, language, dialect = _file_meta(rel, raw, lang_map, fallback_chain=fallback)
    au = automaton.build(sym_list)
    found = []
    if au is not None:
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(au, line):
                found.append((sym, i, line))
    return rel, enc, replaced, language, dialect, found


def _kinds_of(language: str, dialect: str, line: str) -> dict[str, str]:
    """1 行の各シンボル→種別。同名は constant>var>getter>setter の決定的優先。"""
    cs = extract_chase_symbols(language, dialect, line)
    out: dict[str, str] = {}
    for kind, names in (("setter", cs.setters), ("getter", cs.getters),
                        ("var", cs.vars), ("constant", cs.constants)):
        for n in names:
            out[n] = kind
    return out
```
`new_string`:
```python
from grep_analyzer.fixedpoint._scan import (
    _file_meta,
    _kinds_of,
    _scan_file,
    scan_hop,
)
```

- [ ] **Step 4: メインループの nchunks 分岐を `scan_hop` 呼出 1 本に置換**

`__init__.py` の `run_fixedpoint` 内、`if nchunks <= 1:` から `pass_results = [...]` までのブロックを以下に置換:

`old_string`:
```python
            if nchunks <= 1:
                args = [(rel, str(abspath), scan_syms, opts.lang_map, list(opts.encoding_fallback))
                        for rel, abspath in scan_files]
                if opts.jobs > 1:
                    with multiprocessing.Pool(opts.jobs) as pool:
                        results = pool.map(_scan_file, args)
                else:
                    results = [_scan_file(a) for a in args]
                pass_results = sorted(results, key=lambda r: r[0])
            else:
                size = -(-len(scan_syms) // nchunks)
                chunks = [scan_syms[i:i + size]
                          for i in range(0, len(scan_syms), size)] or [[]]
                diag.add("automaton_split", f"hop={hop} chunks={len(chunks)}")
                agg: dict[str, list] = {}
                meta: dict[str, tuple] = {}
                for chunk in chunks:
                    args = [(rel, str(abspath), chunk, opts.lang_map, list(opts.encoding_fallback))
                            for rel, abspath in scan_files]
                    if opts.jobs > 1:
                        with multiprocessing.Pool(opts.jobs) as pool:
                            res = pool.map(_scan_file, args)
                    else:
                        res = [_scan_file(a) for a in args]
                    for rel, enc, replaced, language, dialect, found in res:
                        meta.setdefault(rel, (enc, replaced, language, dialect))
                        agg.setdefault(rel, []).extend(found)
                pass_results = [(rel, *meta[rel],
                                 sorted(agg[rel], key=lambda t: (t[1], t[0])))
                                for rel in sorted(agg)]
```
`new_string`:
```python
            pass_results, n_actual_chunks = scan_hop(scan_syms, scan_files, opts, nchunks)
            if nchunks > 1:
                diag.add("automaton_split", f"hop={hop} chunks={n_actual_chunks}")
```

- [ ] **Step 5: 未使用 import を削除**

`__init__.py` から以下を削除:

`old_string`:
```python
import multiprocessing
```
`new_string`:（空文字列で削除）

`old_string`:
```python
from grep_analyzer import automaton, walk
```
`new_string`:
```python
from grep_analyzer import walk
```

`old_string`:
```python
from grep_analyzer.chase import extract_chase_symbols
```
`new_string`:（空文字列で削除）

`old_string`:
```python
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
```
`new_string`:（空文字列で削除）

`old_string`:
```python
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
```
`new_string`:（空文字列で削除）

注: ただし `__init__.py` 内で `_ingest` クロージャが直接 `extract_chase_symbols` / `partition` を呼ぶ場合は import を残す。各削除前に `grep -n "<symbol>" src/grep_analyzer/fixedpoint/__init__.py` で参照を確認。

- [ ] **Step 6: 検証**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "
import inspect
from grep_analyzer.fixedpoint._scan import _scan_file, scan_hop
sig_scan = list(inspect.signature(_scan_file).parameters)
assert sig_scan == ['args'], sig_scan
sig_hop = list(inspect.signature(scan_hop).parameters)
assert 'state' not in sig_hop, sig_hop
assert 'ChaseState' not in str(inspect.signature(scan_hop)), inspect.signature(scan_hop)
print('worker isolation OK')
" && \
  pytest -q 2>&1 | tail -5
```

Expected: `worker isolation OK` + `249 passed, 5 skipped`。

- [ ] **Step 7: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md && \
  git commit -m "refactor(fixedpoint): _scan.py 抽出 + R4 統合判定で scan_hop に一本化"
```

---

### Task A3: _ingest.py 抽出（旧クロージャ）

**Files:**
- Create: `src/grep_analyzer/fixedpoint/_ingest.py`
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`（`_ingest` クロージャ削除 + 子の再 ingest 抽出）

- [ ] **Step 1: `_ingest.py` を作成**

Create `src/grep_analyzer/fixedpoint/_ingest.py`:

```python
"""1 行から ChaseState への追跡シンボル投入（spec §8.1 手順）。

extract_chase_symbols で得た候補を stoplist.partition で chase / terminal /
rejected に分け、`introducers`（発見元）に親 Occurrence を記録する。
非 seed の自己定義行が自分自身を再抽出しても発見元にしない（spec §8.2）。

`absorb_results`: scan 結果を ChaseState に反映する（edge_store 追加、
encoding 記録、子の再 ingest）。`hop` は **現在処理中の hop（呼出時点で
完了済み hop の番号）**。内部で hop+1 して次 hop の ingest に渡す。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.fixedpoint._scan import _kinds_of
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.provenance import Occurrence
from grep_analyzer.stoplist import partition


def ingest_one(state: ChaseState, parent: Occurrence, language: str,
               dialect: str, line: str, hop: int, is_seed: bool = False):
    """1 行を ChaseState に取り込む。spec §8.1 手順 1〜4。"""
    diag = state.diagnostics
    opts = state.options
    if hop > opts.max_depth:
        if parent not in state.maxdepth_logged:
            diag.add("prov_max_depth", f"{parent.symbol}@{parent.relpath}:"
                     f"{parent.lineno} (hop {hop} > --max-depth {opts.max_depth})")
            state.maxdepth_logged.add(parent)
        return
    cs = extract_chase_symbols(language, dialect, line)
    kinds = _kinds_of(language, dialect, line)
    part = partition(cs, language, state.policy)
    for sym, reason in sorted(part.rejected):
        diag.add("symbol_rejected", f"{reason}\t{sym}")
    for sym in part.chase:
        if sym in state.capped:
            continue
        if not is_seed and sym == parent.symbol:
            continue
        state.symbol_kind.setdefault(sym, kinds.get(sym, "var"))
        state.symbol_hop.setdefault(sym, hop)
        lst = state.introducers.setdefault(sym, [])
        if parent not in lst:
            lst.append(parent)
        if sym not in state.chase_done:
            state.chase_active.add(sym)
    for sym in part.terminal:
        if sym in state.capped:
            continue
        if not is_seed and sym == parent.symbol:
            continue
        state.symbol_kind.setdefault(sym, kinds.get(sym, "getter"))
        state.symbol_hop.setdefault(sym, hop)
        lst = state.introducers.setdefault(sym, [])
        if parent not in lst:
            lst.append(parent)
        if sym not in state.terminal_done:
            state.terminal_active.add(sym)


def absorb_results(state: ChaseState, pass_results, scan_chase: set[str],
                   scan_term: set[str], hop: int):
    """scan_hop の結果を ChaseState に反映する（edge 追加・diag・子の再 ingest）。

    `hop` は呼出時点で完了済みの hop 番号。子の ingest_one には `hop + 1` を渡す。
    """
    diag = state.diagnostics
    for rel, enc, replaced, language, dialect, found in pass_results:
        state.encoding_of.setdefault(rel, (enc, replaced))
        if replaced and rel not in state.replaced_logged:
            diag.add("decode_replaced", rel)
            state.replaced_logged.add(rel)
        for sym, i, line in found:
            if sym not in scan_chase and sym not in scan_term:
                continue
            child = Occurrence(sym, rel, i)
            for parent in state.introducers.get(sym, []):
                if parent != child:
                    state.edge_store.add(parent, child)
            if sym in scan_term:
                if sym not in state.no_expand_logged:
                    diag.add("getter_setter_no_expand", sym)
                    state.no_expand_logged.add(sym)
                continue
            ingest_one(state, child, language, dialect, line, hop + 1)
```

- [ ] **Step 2: `__init__.py` の `_ingest` クロージャを削除し、`ingest_one` を呼ぶ**

Edit `src/grep_analyzer/fixedpoint/__init__.py`:

`old_string`:
```python
    def _ingest(parent: Occurrence, language: str, dialect: str, line: str,
                hop: int, is_seed: bool = False):
```
〜（クロージャ本体最後の行まで）の全ブロックを削除。

そして:

`old_string`:
```python
        _ingest(occ, lang, dia, seed_line, hop=1, is_seed=True)
```
`new_string`:
```python
        ingest_one(state, occ, lang, dia, seed_line, hop=1, is_seed=True)
```

メインループ末尾の `for rel, enc, replaced, ... in pass_results: ...` ブロック全体を `absorb_results(state, pass_results, scan_chase, scan_term, hop)` に置換:

`old_string`:
```python
            for rel, enc, replaced, language, dialect, found in pass_results:
                state.encoding_of.setdefault(rel, (enc, replaced))
                if replaced and rel not in state.replaced_logged:
                    diag.add("decode_replaced", rel)
                    state.replaced_logged.add(rel)
                for sym, i, line in found:
                    if sym not in scan_chase and sym not in scan_term:
                        continue
                    child = Occurrence(sym, rel, i)
                    for parent in state.introducers.get(sym, []):
                        if parent != child:
                            state.edge_store.add(parent, child)
                    if sym in scan_term:
                        if sym not in state.no_expand_logged:
                            diag.add("getter_setter_no_expand", sym)
                            state.no_expand_logged.add(sym)
                        continue
                    _ingest(child, language, dialect, line, hop + 1)
```
`new_string`:
```python
            absorb_results(state, pass_results, scan_chase, scan_term, hop)
```

そして import 追加:

`old_string`:
```python
from grep_analyzer.fixedpoint._scan import (
    _file_meta,
    _kinds_of,
    _scan_file,
    scan_hop,
)
```
`new_string`:
```python
from grep_analyzer.fixedpoint._ingest import absorb_results, ingest_one
from grep_analyzer.fixedpoint._scan import (
    _file_meta,
    _kinds_of,
    _scan_file,
    scan_hop,
)
```

- [ ] **Step 3: 検証**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

- [ ] **Step 4: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git commit -m "refactor(fixedpoint): _ingest クロージャを _ingest.py の ingest_one/absorb_results に抽出"
```

---

### Task A4: _budget_control.py 抽出

**Files:**
- Create: `src/grep_analyzer/fixedpoint/_budget_control.py`
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`

`_apply_global_cap` をトップレベル関数化し、spill 判定 / nchunks 計算も同モジュールに集約。

- [ ] **Step 1: `_budget_control.py` を作成**

Create `src/grep_analyzer/fixedpoint/_budget_control.py`:

```python
"""グローバル cap / spill / nchunks 計算（spec §8.2 L164 優先 1 / §8.3）。

- apply_global_cap: --memory-limit / --max-symbols でシンボル集合を切り詰める。
  単調縮小・決定的（キー: (symbol_hop, len(s), s)）。
- maybe_spill: in-memory edge 数と introducers 数で予算超過判定し、超過時に
  edge_store.maybe_spill_now() を呼ぶ。1 度だけ diag を立てる。
- compute_nchunks: 1 hop の chunk 数を予算と force_chunks から決める。

注: compute_nchunks は **scan_active/term_active を空にした直後**に呼ばれる
前提（既存 fixedpoint.py L246-258 と同じタイミング・n_live 計算同値）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from grep_analyzer.budget import estimate_items
from grep_analyzer.fixedpoint._state import ChaseState


def apply_global_cap(state: ChaseState):
    """シンボル集合を memory_limit / max_symbols で決定的に切り詰める。"""
    diag = state.diagnostics
    opts = state.options
    live = sorted(state.chase_active | state.chase_done
                  | state.terminal_active | state.terminal_done,
                  key=lambda s: (state.symbol_hop.get(s, 0), len(s), s))
    keep_count = opts.max_symbols
    if not state.budget.unlimited:
        while keep_count > 0 and state.budget.exceeded(estimate_items(
                n_symbols=keep_count, n_edges=0, n_intro=keep_count)):
            keep_count -= 1
    if len(live) <= keep_count:
        return
    for s in live[keep_count:]:
        if s not in state.capped:
            diag.add("symbol_rejected", f"capped\t{s}")
            state.capped.add(s)
        state.chase_active.discard(s)
        state.terminal_active.discard(s)


def maybe_spill(state: ChaseState, hop: int):
    """予算超過時に edge_store を spill する（1 度だけ diag 記録）。"""
    if state.budget.unlimited or state.edge_store.spilled:
        return
    n_intro = sum(len(v) for v in state.introducers.values())
    n_live = len(state.chase_active | state.chase_done
                 | state.terminal_active | state.terminal_done)
    if state.budget.exceeded(estimate_items(
            n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
            n_intro=n_intro)):
        state.edge_store.maybe_spill_now()
        if not state.spill_logged:
            state.diagnostics.add("graph_spilled", f"hop={hop}")
            state.spill_logged = True


def compute_nchunks(state: ChaseState, scan_syms: list[str]) -> int:
    """1 hop の chunk 数を決める。`force_chunks` 指定優先、超過予算時のみ自動増やす。"""
    opts = state.options
    nchunks = 1
    if opts.force_chunks and opts.force_chunks > 1:
        return min(opts.force_chunks, opts.max_passes, max(1, len(scan_syms)))
    if state.budget.unlimited:
        return 1
    n_intro = sum(len(v) for v in state.introducers.values())
    n_live = len(state.chase_active | state.chase_done
                 | state.terminal_active | state.terminal_done)
    if not state.budget.exceeded(estimate_items(
            n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
            n_intro=n_intro)):
        return 1
    while nchunks < opts.max_passes and nchunks < len(scan_syms) and \
            state.budget.exceeded(estimate_items(
                n_symbols=-(-len(scan_syms) // (nchunks + 1)),
                n_edges=state.edge_store.in_memory_len(), n_intro=n_intro)):
        nchunks += 1
    return nchunks
```

- [ ] **Step 2: `__init__.py` の `_apply_global_cap` を削除 + メインループ簡略化**

`old_string`:
```python
    def _apply_global_cap():
        live = sorted(state.chase_active | state.chase_done | state.terminal_active | state.terminal_done,
                      key=lambda s: (state.symbol_hop.get(s, 0), len(s), s))
        keep_count = opts.max_symbols
        if not state.budget.unlimited:
            while keep_count > 0 and state.budget.exceeded(estimate_items(
                    n_symbols=keep_count, n_edges=0, n_intro=keep_count)):
                keep_count -= 1
        if len(live) <= keep_count:
            return
        for s in live[keep_count:]:
            if s not in state.capped:
                diag.add("symbol_rejected", f"capped\t{s}")
                state.capped.add(s)
            state.chase_active.discard(s)
            state.terminal_active.discard(s)
```
`new_string`:（空文字列で削除）

メインループ内冒頭の spill 判定ブロックを `maybe_spill(state, hop)` 1 行に置換:

`old_string`:
```python
            _apply_global_cap()
            if not state.budget.unlimited and not state.edge_store.spilled:
                n_intro = sum(len(v) for v in state.introducers.values())
                n_live = len(state.chase_active | state.chase_done
                             | state.terminal_active | state.terminal_done)
                if state.budget.exceeded(estimate_items(
                        n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
                        n_intro=n_intro)):
                    state.edge_store.maybe_spill_now()
                    if not state.spill_logged:
                        diag.add("graph_spilled", f"hop={hop}")
                        state.spill_logged = True
```
`new_string`:
```python
            apply_global_cap(state)
            maybe_spill(state, hop)
```

nchunks 計算ブロックを `compute_nchunks(state, scan_syms)` に置換:

`old_string`:
```python
            n_intro = sum(len(v) for v in state.introducers.values())
            n_live = len(state.chase_active | state.chase_done
                         | state.terminal_active | state.terminal_done)
            nchunks = 1
            if opts.force_chunks and opts.force_chunks > 1:
                nchunks = min(opts.force_chunks, opts.max_passes,
                              max(1, len(scan_syms)))
            elif not state.budget.unlimited and state.budget.exceeded(estimate_items(
                    n_symbols=n_live, n_edges=state.edge_store.in_memory_len(),
                    n_intro=n_intro)):
                while nchunks < opts.max_passes and nchunks < len(scan_syms) and \
                        state.budget.exceeded(estimate_items(
                            n_symbols=-(-len(scan_syms) // (nchunks + 1)),
                            n_edges=state.edge_store.in_memory_len(), n_intro=n_intro)):
                    nchunks += 1
```
`new_string`:
```python
            nchunks = compute_nchunks(state, scan_syms)
```

import 追加:

`old_string`:
```python
from grep_analyzer.fixedpoint._ingest import absorb_results, ingest_one
```
`new_string`:
```python
from grep_analyzer.fixedpoint._budget_control import (
    apply_global_cap,
    compute_nchunks,
    maybe_spill,
)
from grep_analyzer.fixedpoint._ingest import absorb_results, ingest_one
```

未使用 import 削除:

> **重要（A-C1 致命修正）**: `from grep_analyzer.budget import estimate_items` は **絶対に削除しない**。
>
> 理由: `tests/perf/test_perf.py:49` が `monkeypatch.setattr("grep_analyzer.fixedpoint.estimate_items", _spy)` で `grep_analyzer.fixedpoint` 名前空間の `estimate_items` 属性を差し替えて Inv-1 較正テストを行う。test docstring L47-48「fixedpoint は `from grep_analyzer.budget import estimate_items`（関数オブジェクト束縛）ゆえ fixedpoint 名前空間側を差し替える」と明記。
>
> 削除すると `pytest tests/perf/test_perf.py -m perf` 全件 fail → V6 baseline 計測自体が不可能になる。
>
> `__init__.py` の関数本体内で `estimate_items` が呼ばれなくなっても、**perf test の monkeypatch 接点として import 文を維持** する。インラインコメントで明示:
>
> ```python
> from grep_analyzer.budget import estimate_items  # perf test の monkeypatch 接点（tests/perf/test_perf.py:49）
> ```

- [ ] **Step 3: 検証**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

- [ ] **Step 4: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git commit -m "refactor(fixedpoint): _apply_global_cap / spill / nchunks 計算を _budget_control.py へ抽出"
```

---

### Task A5: _seed.py + _finalize.py 抽出 + __init__.py を orchestrator に縮約

**Files:**
- Create: `src/grep_analyzer/fixedpoint/_seed.py`
- Create: `src/grep_analyzer/fixedpoint/_finalize.py`
- Rewrite: `src/grep_analyzer/fixedpoint/__init__.py`（最終形 Write）

- [ ] **Step 1: `_seed.py` を作成**

Create `src/grep_analyzer/fixedpoint/_seed.py`:

```python
"""seed_hits から ChaseState を初期化する（hop0→hop1）。

seed ファイルを実読してその行から spec §5.1 決定的に language/dialect を確定し、
hop=1 で initial ingest を行う。is_seed=True なので「自分が自分を再抽出」も
許容する（seed は keyword 原点）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from pathlib import Path

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint._ingest import ingest_one
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._scan import _file_meta
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.model import Hit
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy, load_stoplist


def initialize_state(seed_hits: list[Hit], source_root: Path,
                     opts: EngineOptions, diag: Diagnostics) -> ChaseState:
    """seed_hits を ChaseState に取り込み、hop=1 までの初期 ingest を完了させる。"""
    policy = SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path))
    budget = MemoryBudget(opts.memory_limit_mb)
    graph = ProvenanceGraph()
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    state = ChaseState(
        source_root=source_root,
        options=opts,
        diagnostics=diag,
        policy=policy,
        budget=budget,
        graph=graph,
        edge_store=EdgeStore(opts.spill_dir, budget),
        keyword=keyword,
    )

    for s in seed_hits:
        occ = Occurrence(s.keyword, s.file, s.lineno)
        state.graph.add_seed(occ)
        sp = source_root / s.file
        if sp.is_file():
            text, _, _, lang, dia = _file_meta(
                s.file, sp.read_bytes(), opts.lang_map,
                fallback_chain=list(opts.encoding_fallback))
            _ls = text.split("\n")
            seed_line = _ls[s.lineno - 1] if 0 <= s.lineno - 1 < len(_ls) else ""
        else:
            lang, dia = s.language, "bourne"
            seed_line = ""
        ingest_one(state, occ, lang, dia, seed_line, hop=1, is_seed=True)
    return state
```

- [ ] **Step 2: `_finalize.py` を作成**

Create `src/grep_analyzer/fixedpoint/_finalize.py`:

```python
"""scan ループ終了後の indirect Hit 列構築（spec §8.2 / §9）。

edge_store の (parent, child) を graph に追加し、終端 Occurrence ごとに
chain_to を列挙して indirect Hit を生成する。seed と同じ (relpath, lineno) は
除外する（seed は direct 側で既に出力されている）。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from grep_analyzer.classify import classify_hit
from grep_analyzer.fixedpoint._scan import _file_meta
from grep_analyzer.fixedpoint._state import ChaseState, _REF_KIND
from grep_analyzer.model import Hit
from grep_analyzer.provenance import Occurrence
from grep_analyzer.snippet import build_snippet


def build_indirect_hits(state: ChaseState) -> list[Hit]:
    """edge_store を走査し indirect Hit 列を決定的に構築する。"""
    opts = state.options
    diag = state.diagnostics
    for p, c in state.edge_store.sorted_unique():
        state.graph.add_edge(p, c)

    indirect: list[Hit] = []
    seen: set[Occurrence] = set()
    line_cache: dict[str, list[str]] = {}
    meta_of: dict[str, tuple[str, str, str]] = {}
    for _, c in state.edge_store.sorted_unique():
        if c in seen or c.symbol not in (state.chase_done | state.terminal_done):
            continue
        if state.graph.is_seed_location(c.relpath, c.lineno):
            continue
        seen.add(c)
        if c.relpath not in line_cache:
            raw = state.rel_to_abs[c.relpath].read_bytes() if c.relpath in state.rel_to_abs else b""
            text, enc, replaced, lang, dia = _file_meta(
                c.relpath, raw, opts.lang_map,
                fallback_chain=list(opts.encoding_fallback))
            line_cache[c.relpath] = text.split("\n")
            meta_of[c.relpath] = (text, lang, dia)
            state.encoding_of.setdefault(c.relpath, (enc, replaced))
        text, language, dialect = meta_of[c.relpath]
        lines = line_cache[c.relpath]
        line = lines[c.lineno - 1] if 0 <= c.lineno - 1 < len(lines) else ""
        kind = state.symbol_kind.get(c.symbol, "var")
        cat, conf = classify_hit(language, dialect, text, c.lineno, line)
        if kind in ("getter", "setter"):
            conf = "low"
        enc, replaced = state.encoding_of.get(c.relpath, ("utf-8", False))
        for chain in state.graph.chains_to(c, max_depth=opts.max_depth,
                                           max_paths=opts.max_paths, diag=diag):
            indirect.append(Hit(
                keyword=state.keyword, language=language, file=c.relpath,
                lineno=c.lineno, ref_kind=_REF_KIND[kind], category=cat,
                category_sub="", usage_summary=f"{cat} ({language})",
                via_symbol=c.symbol, chain=chain,
                snippet=build_snippet(language, dialect, text, c.lineno),
                encoding=enc + (" 要確認" if replaced else ""),
                confidence=conf))
    return indirect
```

- [ ] **Step 3: `__init__.py` を最終 orchestrator 形へ Write 置換**

Write `src/grep_analyzer/fixedpoint/__init__.py`:

```python
"""不動点・ターゲットスキャン・エンジン（spec §8.1/§8.2/§8.3）。

direct ヒットを seed に constant/var を多ホップ追跡し indirect ヒットと chain
を出す。getter/setter は §8.3 で横展開しないが全反復走査・全件 low 報告(§8.4)。
出力は走査順・並列完了順に非依存で決定的(spec §9)。

公開 API:
  - EngineOptions: エンジン挙動パラメータ dataclass
  - run_fixedpoint: seed → indirect Hit 列

停止性(spec §8.1 手順5): 追跡シンボルは原ソース字句のみ。母集合有限・採用集合
単調増加(chase_done から削らない＝cap は capped で scan 除外のみ)。よって高々
|母集合| ステップで飽和。--max-depth/max_symbols/max_paths は安全弁。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

from grep_analyzer import ripgrep as _rg
from grep_analyzer import walk
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.fixedpoint._budget_control import (
    apply_global_cap,
    compute_nchunks,
    maybe_spill,
)
from grep_analyzer.fixedpoint._finalize import build_indirect_hits
from grep_analyzer.fixedpoint._ingest import absorb_results
from grep_analyzer.fixedpoint._options import EngineOptions
from grep_analyzer.fixedpoint._scan import scan_hop
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.model import Hit
from grep_analyzer.progress import Progress

__all__ = ["EngineOptions", "run_fixedpoint"]


def run_fixedpoint(
    seed_hits: list[Hit], source_root, opts: EngineOptions, diag: Diagnostics,
    *, files=None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    files 指定時は内部 walk を省き事前収集 (rel, abspath) 列を使う（同値）。
    """
    from pathlib import Path
    source_root = Path(source_root)
    state = initialize_state(seed_hits, source_root, opts, diag)

    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    state.rel_to_abs = {rel: abspath for rel, abspath in files}
    progress = Progress(opts.progress)
    progress.start(len(files))

    try:
        hop = 1
        while state.chase_active or state.terminal_active:
            apply_global_cap(state)
            maybe_spill(state, hop)
            scan_chase = {s for s in state.chase_active if s not in state.capped}
            scan_term = {s for s in state.terminal_active if s not in state.capped}
            scan_syms = sorted(scan_chase | scan_term)
            state.chase_done |= state.chase_active
            state.chase_active = set()
            state.terminal_done |= state.terminal_active
            state.terminal_active = set()
            if not scan_syms or hop > opts.max_depth:
                break
            scan_files = files
            if opts.use_ripgrep:
                keep_rels = _rg.prefilter(source_root, state.rel_to_abs, scan_syms)
                if keep_rels is not None:
                    scan_files = [(r, a) for r, a in files if r in keep_rels]
            nchunks = compute_nchunks(state, scan_syms)
            pass_results, n_actual_chunks = scan_hop(scan_syms, scan_files, opts, nchunks)
            if nchunks > 1:
                diag.add("automaton_split", f"hop={hop} chunks={n_actual_chunks}")
            absorb_results(state, pass_results, scan_chase, scan_term, hop)
            progress.hop(hop, len(scan_syms), len(scan_files))
            hop += 1

        indirect = build_indirect_hits(state)
        progress.done()
        return indirect
    finally:
        state.edge_store.close()
```

- [ ] **Step 4: import 健全性 + 全テスト**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint; print('OK')" && \
  pytest -q 2>&1 | tail -5
```

Expected: `OK` + `249 passed, 5 skipped`。

- [ ] **Step 5: jobs > 1 経路の sanity check**

Run: `cd /workspaces/grep_helpers2 && pytest tests/unit/test_fixedpoint.py -k jobs -q 2>&1 | tail -3`

Expected: jobs 関連テストが pass。

- [ ] **Step 6: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git commit -m "refactor(fixedpoint): _seed.py / _finalize.py 抽出 + __init__.py を orchestrator に縮約"
```

---

### Task A6: V6 性能リグレッション計測

**Files:**
- Modify: `docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md`

- [ ] **Step 1: Phase 3 [A] 完了後の計測（force_chunks=0 経路）**

Run:
```bash
cd /workspaces/grep_helpers2 && for i in 1 2 3; do
  pytest tests/perf/test_perf.py -m perf -q -s 2>&1 | grep -E "PERF|dt=" | tail -5
  echo "---"
done
```

R4 統合採用なら force_chunks=3 経路は **scan_hop 内の同一コードパス** を nchunks 引数違いで通るため、原理的に統合経路 1 本での計測で十分（ただし `tests/perf/` が force_chunks 設定を切り替えている場合は両方計測）。

- [ ] **Step 2: 判定 + 記録**

`docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md` の「Phase 3 [A] 完了後」セクションを更新。

baseline_median + 10% / +5 秒以内なら OK。超過時は **user に判断を仰ぐ**（subagent は OK 判定しない）。

```bash
cd /workspaces/grep_helpers2 && \
  git add docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md && \
  git commit -m "perf(phase3): V6 性能リグレッション計測結果"
```

---

## Part [B]: Phase 2 引き継ぎ #3 + #4 の解消

### Task B1: chase.py docstring + _CHASERS の `__all__` 整合

**Files:**
- Modify: `src/grep_analyzer/chase.py:20-22`
- Modify: `src/grep_analyzer/classifiers/__init__.py`

- [ ] **Step 1: chase.py の docstring 書換**

`old_string`:
```python
def extract_var_symbols(language: str, dialect: str, line: str) -> list[str]:
    """1 行から indirect:var 追跡シンボル（代入の左辺識別子）を抽出する。

    fixedpoint の `_ingest` が言語非依存の var シンボル列を必要とするため、
    Chaser を経由せず直接対応する `*_chaser._extract_var_symbols` を呼ぶ。
    対象外言語・該当なしは空リスト。
    """
```
`new_string`:
```python
def extract_var_symbols(language: str, dialect: str, line: str) -> list[str]:
    """1 行から indirect:var 追跡シンボル（代入の左辺識別子）を抽出する。

    indirect:var 追跡で左辺識別子のみを必要とする呼出元から使われるため、
    Chaser を経由せず直接対応する `*_chaser._extract_var_symbols` を呼ぶ。
    対象外言語・該当なしは空リスト。
    """
```

- [ ] **Step 2: `classifiers/__init__.py` の `__all__` から `_CHASERS` を除外**

`old_string`:
```python
__all__ = ["_CHASERS", "Chaser"]
```
`new_string`:
```python
__all__ = ["Chaser"]
```

**根拠**: `_CHASERS` の lookup は `chase.py` の `from grep_analyzer.classifiers import _CHASERS` でのみ行われ、外部呼出側からは `chase.extract_chase_symbols(...)` / `chase.mask_literals(...)` 経由のみ参照される。`__all__` は `from module import *` の対象集合を定義するため、`_CHASERS` を `__all__` から外すと `*` import で晒れず private 接頭辞と整合する。直接 `from grep_analyzer.classifiers import _CHASERS` で参照する `chase.py` は `__all__` の影響を受けないため引き続き動作する。

- [ ] **Step 3: テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

- [ ] **Step 4: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/chase.py src/grep_analyzer/classifiers/__init__.py && \
  git commit -m "docs(chase,classifiers): chase docstring 書換 + _CHASERS を private に整合（Phase 2 引き継ぎ #3 #4）"
```

---

## V3 / V5 ゲート（Phase 3 完了時）

### V3 Import グラフ層分離検証

- [ ] **Step 1: 依存関係抽出**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  grep -rn "from grep_analyzer" \
    src/grep_analyzer/snippet/ \
    src/grep_analyzer/fixedpoint/ \
    src/grep_analyzer/classifiers/ \
    src/grep_analyzer/patterns/ \
    src/grep_analyzer/progress.py 2>&1 | head -80
```

Expected（許容）:
- `patterns/*` は `grep_analyzer.*` を import しない（葉）
- `classifiers/*` は `patterns/*` と `model` のみ
- `snippet/*` は `chase`, `classifiers.ts_classifier`, `patterns.snippet_boundaries`, `proc_preprocess`, `tsv` のみ
- `fixedpoint/*` は `snippet`, `chase`, `classify`, `dispatch`, `encoding`, `model`, `walk`, `ripgrep`, `stoplist`, `spill`, `provenance`, `diagnostics`, `budget`, `automaton`, `progress` のみ
- `progress.py` は `grep_analyzer.*` を import しない（葉）

逆方向確認:
```bash
cd /workspaces/grep_helpers2 && \
  grep -rn "from grep_analyzer.fixedpoint._" src/grep_analyzer/{pipeline,cli,output_writer}.py 2>&1
```

Expected: ヒット 0（上位レイヤが `fixedpoint/_*` private に直接触れていない）。

- [ ] **Step 2: cyclic import 実機検証 + ChaseState worker 非送信検証**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "
import inspect
import grep_analyzer
import grep_analyzer.cli
import grep_analyzer.fixedpoint
import grep_analyzer.snippet
from grep_analyzer.fixedpoint._scan import _scan_file, scan_hop
sig_scan = list(inspect.signature(_scan_file).parameters)
assert sig_scan == ['args'], sig_scan
sig_hop = list(inspect.signature(scan_hop).parameters)
assert 'state' not in sig_hop and 'ChaseState' not in str(inspect.signature(scan_hop)), sig_hop
print('imports OK + worker isolation OK')
" && \
  grep -n "ChaseState" src/grep_analyzer/fixedpoint/_scan.py
```

Expected: `imports OK + worker isolation OK` + `_scan.py` 内に `ChaseState` 文字列ヒット 0（ChaseState を worker モジュールが import していない）。

- [ ] **Step 3: pytest collection 確認**

Run: `cd /workspaces/grep_helpers2 && pytest --collect-only -q 2>&1 | grep -E "error|ERROR" || echo "OK"`

Expected: `OK`（collection エラーゼロ）。

### V5 Phase 3 ゲート

実装完了後、批判的 AI レビュー（観点 A: 設計遵守＋仕様準拠／観点 B: 実装品質＋境界条件）を最低 2 巡実行し Critical/Major ゼロまで収束。

---

## V1〜V5 Phase 3 完了基準

- [ ] Inv-A: golden 22 全件 byte 一致
- [ ] Inv-B: pytest 全件 pass（249 passed, 5 skipped 維持）
- [ ] Inv-C: 公開 API（EngineOptions / run_fixedpoint / build_snippet / clamp_lines / heuristic_span / ts_span / proc_exec_span）シグネチャ・戻り値不変
- [ ] Inv-D: V3 で層分離違反ゼロ + ChaseState worker 非送信検証 pass
- [ ] Inv-E: pyahocorasick 版差吸収・決定性保持
- [ ] V6: 性能リグレッション 10% / +5s 以内（超過時 user 判断）
- [ ] V5: AI レビュー Critical/Major ゼロに収束

---

---

## v3 修正補遺（2 巡目 AI レビュー反映）

本 plan v2 に対して以下の修正を **subagent 実行時に併用** すること。本補遺の内容は plan 本体の指示に優先する。

### 補-1（A-C1 / 致命）: `estimate_items` import を維持

Task A4 Step 5 の指示通り、`from grep_analyzer.budget import estimate_items` は `fixedpoint/__init__.py` に **削除しないで保持** する（perf test の monkeypatch 接点として必須）。

### 補-2（B-C3 / A-M1）: Task A1b Step 3 の Edit 順序を厳密化

旧 Step 3 は `EngineOptions` class を `from ... import ...` に置換する `Edit` を最初に実施する指示だが、これは PEP8 E402（module-level import が冒頭でない）違反になる。以下の順序に書き換える:

**Step 3 改訂（v3）**:

1. **Edit 1**: ファイル冒頭の import 群末尾（`from grep_analyzer.stoplist import ...` の直後）に以下 2 行を追加:
   ```python
   from grep_analyzer.fixedpoint._options import EngineOptions
   from grep_analyzer.fixedpoint._state import ChaseState, _REF_KIND
   ```
   - `old_string`: `from grep_analyzer.stoplist import SymbolPolicy, load_stoplist, partition`
   - `new_string`: `from grep_analyzer.stoplist import SymbolPolicy, load_stoplist, partition\nfrom grep_analyzer.fixedpoint._options import EngineOptions\nfrom grep_analyzer.fixedpoint._state import ChaseState, _REF_KIND`

2. **Edit 2**: `@dataclass(frozen=True) class EngineOptions: ...` ブロック（既存 L33-58）を完全削除。

3. **Edit 3**: 元の `_REF_KIND = {...}` 定義行（既存 L61-62）を完全削除。

4. **Edit 4**: `from dataclasses import dataclass` を削除（`EngineOptions` 移動後は `__init__.py` 内で `dataclass` を使わなくなるため）。

これにより中間状態でも import が冒頭に集約され、PEP8 E402 違反なし。

### 補-3（A-M2）: Task 0b に L110 関数内 import の削除を追加

Task 0b Step 2 完了後、追加で以下を実施:

**Step 2b**: `tests/unit/test_chase.py:110` の関数内 import を削除。
- `old_string`:
  ```python
  def test_var抽出は既存extract_var_symbolsと一致する():
      from grep_analyzer.chase import extract_var_symbols
      line = 'CODE="X"'
  ```
- `new_string`:
  ```python
  def test_var抽出は既存extract_var_symbolsと一致する():
      line = 'CODE="X"'
  ```

理由: L3 で既に `extract_var_symbols` が import 済み。関数内重複 import は Phase 2 引き継ぎ #1 の趣旨と整合させるべき。

### 補-4（A-M3）: Task A1b Step 4 で policy/budget/graph の local 定義も同時削除

Step 4 の old_string を以下に拡張（`policy = ...` 行から `maxdepth_logged: ...` 行までを含める）:

```
    policy = SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path))
    budget = MemoryBudget(opts.memory_limit_mb)
    graph = ProvenanceGraph()
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    intro: dict[str, list[Occurrence]] = {}   # symbol -> 実抽出元 Occurrence 群
    sym_kind: dict[str, str] = {}
    sym_hop: dict[str, int] = {}
    estore = EdgeStore(opts.spill_dir, budget)
    spill_logged = False
    chase_active: set[str] = set()
    chase_done: set[str] = set()
    term_active: set[str] = set()
    term_done: set[str] = set()
    capped: set[str] = set()
    no_expand_logged: set[str] = set()
    replaced_logged: set[str] = set()
    maxdepth_logged: set[Occurrence] = set()
```

`new_string`:
```python
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""

    state = ChaseState(
        source_root=source_root,
        options=opts,
        diagnostics=diag,
        policy=SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path)),
        budget=MemoryBudget(opts.memory_limit_mb),
        graph=ProvenanceGraph(),
        edge_store=EdgeStore(opts.spill_dir, budget),
        keyword=keyword,
    )
```

注: `EdgeStore(opts.spill_dir, budget)` の `budget` 引数は **同じ式 `MemoryBudget(opts.memory_limit_mb)` を 2 度書くと dataclass 内の参照が同一オブジェクトでなくなり挙動差リスク**。よって以下を採用:

```python
    keyword = sorted({s.keyword for s in seed_hits})[0] if seed_hits else ""
    budget = MemoryBudget(opts.memory_limit_mb)
    state = ChaseState(
        source_root=source_root,
        options=opts,
        diagnostics=diag,
        policy=SymbolPolicy(opts.min_specificity, load_stoplist(opts.stoplist_path)),
        budget=budget,
        graph=ProvenanceGraph(),
        edge_store=EdgeStore(opts.spill_dir, budget),
        keyword=keyword,
    )
```

`budget` local 変数は ChaseState 構築後は使わない（後続コードでは `state.budget` 経由）。Step 5 の rename 表で local `budget` は対象外（直後に未使用化されるため）。

### 補-5（A-M3 / B-M1）: Task A1b Step 5 の rename 表を更新 + 網羅性検証

Step 5 表に以下を追加:

| `policy` (関数内 / `partition(cs, language, policy)` 等) | `state.policy` |
| `budget.unlimited` / `budget.exceeded` | `state.budget.unlimited` / `state.budget.exceeded`（補-4 で削除した local `budget` は使わない） |
| `graph.add_seed` / `graph.add_edge` / `graph.is_seed_location` / `graph.chains_to` | `state.graph.xxx`（一括 replace_all） |

**事前 grep カウント（Step 5 冒頭で実行）**:
```bash
cd /workspaces/grep_helpers2 && for name in intro sym_kind sym_hop estore enc_of \
    chase_active chase_done term_active term_done capped spill_logged \
    no_expand_logged replaced_logged maxdepth_logged rel_to_abs \
    policy budget graph; do
  count=$(grep -cE "\b${name}\b" src/grep_analyzer/fixedpoint/__init__.py)
  echo "${name}: ${count}"
done
```

**事後検証（Step 5 完了直後）**:
```bash
grep -nE "\b(intro|sym_kind|sym_hop|estore|enc_of|chase_active|chase_done|term_active|term_done|capped|spill_logged|no_expand_logged|replaced_logged|maxdepth_logged|rel_to_abs)\b" src/grep_analyzer/fixedpoint/__init__.py | grep -v "state\." || echo "OK: no bare references"
```

ヒット 0 件（または `OK: no bare references`）であることを確認。

### 補-6（B-M2）: Task A1b Step 4-8 を 1 commit に統合（中間 pytest 禁止）

Step 4 完了直後の `__init__.py` は「`state` 構築済みだが関数本体内の旧変数参照が残る」中間状態のため、Step 4 完了時点では pytest を **走らせない**。Step 4 → Step 5 → Step 6 → Step 7 を順次完了させ、Step 8 で初めて pytest を実行する。subagent への明示:

> **重要**: Task A1b の Step 4〜7 は中間状態を許容する一連の Edit である。途中で pytest を走らせると確実に失敗する。Step 8（検証）に到達するまで pytest を試行しないこと。Step 5 完了後の grep 検証のみが中間チェック。

### 補-7（B-M3 / B-M7）: Task A2 Step 0 の試作コード配置と `_pool_map` 撤廃

Step 0 の試作版コード snippet 内の `_pool_map(opts.jobs, args)` は **擬似コードとして撤廃**。正規版（Step 1 の `_scan.py` 採用版）と同じく `multiprocessing.Pool(opts.jobs)` 直接呼出で書く。

試作配置:
- 試作（並存案・統合案）コードは `/tmp/phase3_r4_proto/scan_split.py` と `/tmp/phase3_r4_proto/scan_unified.py` に書く（`src/grep_analyzer/` には**書かない**）
- 試作実行の検証は subagent が自由判断で行う（plan 必須化なし。試作の主目的はコード量・diag 局所性の比較のみ）
- Step 1 の `_scan.py` 作成時に試作版は流用しない（責務 docstring・import が異なる）
- Phase 3 完了時に `/tmp/phase3_r4_proto/` は **手動削除推奨**（subagent タスクには含めない）

### 補-8（A-C2）: Task A2 Step 0 に byte 同値の論証追記

「挙動同値性」判定の根拠を以下に明記:

> automaton.scan_line() の戻り値は内部 `set` を `sorted()` で正規化した list であり同一行内 sym は昇順。`_scan_file` の二重ループは外側が `enumerate(text.split("\n"), start=1)` で line 昇順、内側が sorted sym 列挙のため、戻り値 found は (line 昇順, 同一 line 内 sym 昇順) 順となる。これは統合案の `sorted(agg[rel], key=lambda t: (t[1], t[0]))` と完全一致するため、`nchunks=1` ⇔ 単一 chunk 統合案の出力は (rel ソート, found 内ソート) ともに恒等に保たれる。
>
> さらに `diag.add("automaton_split", f"hop={hop} chunks={n_actual_chunks}")` の発火条件 `nchunks > 1` も既存と一致（既存は `else` ブロックで発火＝nchunks>1 経路のみ）。`n_actual_chunks = len(chunks)` だが、`compute_nchunks` が `>= 2` を返した場合は `len(chunks) >= 1`、`len(scan_syms) >= 1` のもとで `chunks` の `or [[]]` フォールバックは発動しないため `len(chunks) == nchunks` が成立し、既存 `f"chunks={len(chunks)}"` と数値一致。
>
> golden 22 件 + integration 全件 + perf monkeypatch test の 3 軸が pass する場合のみ Step 0 判定確定。

### 補-9（A-M4）: V3 worker isolation 検証強化

V3 Step 2 の `inspect.signature` 検証だけでは関数の型 annotation が無い場合 false-positive で常に pass する（実害なし）。これに加えてソース文字列 grep を追加:

```bash
cd /workspaces/grep_helpers2 && \
  grep -n "ChaseState\|_state" src/grep_analyzer/fixedpoint/_scan.py
```

Expected: ヒット 0（`_scan.py` 内で `ChaseState` 型名・`_state` モジュール参照が無いこと）。

### 補-10（B-M5 / B-M6）: Task A5 Step 3 を Edit ベース化

Step 3 の Write 全置換を以下の Edit 列に置換:

1. ChaseState 構築 + seed_hits ループ全体（補-4 で書いた `state = ChaseState(..., keyword=keyword)` + 後続 `for s in seed_hits: ...` 全ブロック）を `state = initialize_state(seed_hits, source_root, opts, diag)` 1 行に Edit
2. `for p, c in state.edge_store.sorted_unique(): graph.add_edge(p, c)` 以降の indirect Hit 構築ブロック全体 を `indirect = build_indirect_hits(state)` 1 行に Edit
3. import 整理:
   - 不要 import 削除: `multiprocessing` / `dataclass` / `automaton`（既に削除済の可能性）/ `Occurrence` / `ProvenanceGraph` / `EdgeStore`（_seed.py 内で使用） / `SymbolPolicy`, `load_stoplist`, `partition` / `MemoryBudget` / `DEFAULT_FALLBACK`, `decode_bytes` / `detect_language`, `detect_shell_dialect` / `extract_chase_symbols` / `classify_hit` / `build_snippet` / `Hit`（型 hint で使用なら残す）
   - 追加 import: `from grep_analyzer.fixedpoint._seed import initialize_state` / `from grep_analyzer.fixedpoint._finalize import build_indirect_hits`
4. `from pathlib import Path` を module 冒頭 import 群に置く（関数内 import 廃止）

`Hit` import は `run_fixedpoint` の型 hint `seed_hits: list[Hit]` / 戻り値 `list[Hit]` で使用されるため残す。`estimate_items` は補-1 で維持必須。

### 補-11（B-C1 / B-C2 / B-M8）: Edit old_string の byte 一致リスク対策

Task A1b / A2 / A3 / A4 の各 Edit 実行前に、subagent は実ファイルから対象範囲を `Read` で取得し、plan の old_string と byte 比較する。不一致時は実ファイル内容を優先（コメント・空白を含めて完全コピー）。subagent への明示:

> Edit が `old_string not found` で失敗した場合、`Read` でファイル該当範囲を取得し、コメント・行末空白・空行も含めて完全コピーした文字列を old_string に使う。plan に書かれた old_string は **指示の意図** であり、最終的な byte 一致は実ファイルが正本。

### 補-12（B-M9）: `_REF_KIND` の所在判定

Task A1b 時点では `_REF_KIND` を `_state.py` に置く（plan 通り）。Phase 4 で `_finalize.py` へ移動する。これは plan L2165 の引き継ぎ事項として既に記録されており、Phase 3 範囲では `_state.py` のままで問題ない（_finalize.py が `from grep_analyzer.fixedpoint._state import _REF_KIND` を行うため）。

### 補-13（B-M10）: Task A3 Step 2 の `_ingest` クロージャ削除の old_string

A1b 完了後の `_ingest` クロージャ全文（state.xxx 化された 40 行）を subagent は Read で取得し、old_string に貼る。plan に明示的に「`def _ingest(parent: Occurrence, ...): ... state.terminal_active.add(sym)` までの全 40 行を `Read` で取得して old_string に使う」と注記する。

### 補-14（A-M2 派生）: Phase 3 → 4 引き継ぎへの Minor 移送

以下の Minor は Phase 3 内では対処せず、Phase 4 plan の引き継ぎ枠に移送:
- _options.py の docstring `（Phase 2a/2b 範囲）` 削除（C5 予備適用 vs 厳格化判断）
- Task A4/A5 で生じる潜在的な未使用 import の lint 警告
- ingest_one docstring の hop 引数 semantics 強化

---

## Phase 3 → Phase 4 引き継ぎ事項（予定枠）

Phase 3 で発生・残置する Minor は Phase 4 plan 冒頭に記録する:

- N1〜N4 違反（au / sym / cs / dia / agg / meta 等のローカル変数）の全モジュール横断 rename
- Phase 2 引き継ぎ #5 `patterns/literal_masking.py` の java/c/proc 重複（Pro*C 個別化判定）
- Phase 2 引き継ぎ #6 `chase.py` / `snippet/*` / `fixedpoint/*` module docstring の `Phase 1.5` / `v9` 等マーカー除去（C5 違反）
- Phase 2 引き継ぎ #7 `classifiers/__init__.py` eager import 失敗時の挙動
- Phase 3 で抽出した `_state.py` の `_REF_KIND` 命名（`INDIRECT_REF_KIND_BY_KIND` 等の意図的命名）+ 所在（`_state` → `_finalize` 内が責務上適切）
- `_state.py` を `state.py`（public）にする選択肢の検討
- `snippet/__init__.py` の `build_snippet` docstring を C3 形式（spec 参照を末尾 Related: に集約）へ
- `test_encoding_wiring.py` 内コメントの `enc_of` → `encoding_of` 表記追従
- **`_budget_control._estimate_items` 動的属性参照の清潔化** (V5 観点 B Major #1): Phase 3 で `_estimate_items(*, n_symbols, n_edges, n_intro)` ラッパが `from grep_analyzer import fixedpoint as _fp; _fp.estimate_items(...)` を関数内 import で呼ぶ実装になっている（perf test の `monkeypatch.setattr("grep_analyzer.fixedpoint.estimate_items", _spy)` 接点維持のため）。Phase 4 で `tests/perf/test_perf.py:49` を `monkeypatch.setattr("grep_analyzer.budget.estimate_items", _spy)` に変更し、`_budget_control.py` も `from grep_analyzer.budget import estimate_items` 直接呼出に戻す（hot path のオーバヘッド削減 + 可読性向上）
- `_options.py:15` の `（Phase 2a/2b 範囲）` マーカー削除（C5 違反、補-14 で既登録）
- `_seed.py` / `_finalize.py` の `from grep_analyzer.fixedpoint._scan import _file_meta` の private prefix 共有（`_file_meta` / `_kinds_of` を public 名に rename + `_helpers.py` への分離を検討）
- `_ingest.py` の `absorb_results` / `ingest_one` の `hop` 引数 docstring 統一（V5 観点 B Minor #4）
- `apply_global_cap` の `discard` 行に「既 capped でも discard する理由」コメント付与（V5 観点 B Suggestion）
- `snippet/__init__.py` の `__all__` を冒頭の import 群末尾へ移動（V5 観点 A Suggestion）
- `snippet/_ts.py` の `_GRAN_*` 等定数集合に tree-sitter 0.21 由来の出典コメント追加（V5 観点 A Suggestion #2）
