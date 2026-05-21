# Refactor Phase 3: snippet.py 分割 + fixedpoint.py 分割（ChaseState 化）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** snippet.py（246 行）と fixedpoint.py（350 行）を責務別サブパッケージへ分割する。fixedpoint は新規 `ChaseState` データクラスへ局所変数群を集約し、`run_fixedpoint` を薄いオーケストレータに縮約する。挙動は byte 不変（Inv-A〜E 全保持）。

**Architecture:**
- `snippet.py` → `snippet/` サブパッケージ。公開 API `build_snippet`、テスト由来公開 API `clamp_lines` / `heuristic_span` / `ts_span` / `proc_exec_span` は `snippet/__init__.py` で再 export。private 部分は `_clamp` / `_heuristic` / `_ts` / `_sanitize_line` の 4 サブモジュールへ。
- `fixedpoint.py` → `fixedpoint/` サブパッケージ。`run_fixedpoint` と `EngineOptions` は `fixedpoint/__init__.py` で公開。内部実装は `_state` / `_seed` / `_scan` / `_ingest` / `_budget_control` / `_finalize` の 6 サブモジュールへ。
- `ChaseState` は **main process でのみ保持**、`_scan_file` worker への送信は禁止（pickle/Inv-E 維持）。worker には従来通り `(rel, abspath, sym_list, lang_map, fallback)` のプリミティブのみ渡す。
- R4 (Rule of Three) 判定: `nchunks <= 1` 経路と `nchunks > 1` 経路は内部実装が有意に異なる（結果の aggregation 有無）ため、本 plan では **`_scan_hop_single` / `_scan_hop_chunked` の 2 関数を並存** させる。
- V6 性能リグレッション抑止: Phase 3 [A] 着手前後で `tests/perf/` の同一データセットを 3 回計測し中央値で比較する。

**Tech Stack:** Python 3.12 / pytest / dataclasses / multiprocessing / typing.Protocol

**Related design:** `docs/superpowers/specs/2026-05-21-refactor-design.md` §6 Phase 3 [C][A], §7 V1-V7, §3 N5（Phase 3 内の rename は最小限）

---

## Phase 2 引き継ぎ事項

Phase 2 V5 ゲートで持ち越された Minor を以下のように扱う:

| # | 項目 | 扱い |
|---|---|---|
| 1 | `tests/unit/test_chase.py:46-47` mid-file import（PEP8 E402） | **Phase 3 Task 0b で解消** |
| 2 | `tests/unit/test_stoplist.py:39-40` mid-file import | **Phase 3 Task 0b で解消** |
| 3 | `src/grep_analyzer/chase.py:20-21` の `extract_var_symbols` docstring 「fixedpoint の `_ingest` が...」 | **Phase 3 Task 8 で fixedpoint 分割と同時に書換** |
| 4 | `_CHASERS` の private 接頭辞と `__all__` 公開の不整合 | **Phase 3 Task A 末尾で解消（`_CHASERS` → `CHASERS` 又は `__all__` から除外）** |
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
│   ├── _ts.py               ← ts_span / proc_exec_span / _paren_span / _has_error / _GRAN_*
│   └── _sanitize_line.py    ← _physical_lines（旧 _phys）/ _escape_sep
├── fixedpoint/
│   ├── __init__.py          ← EngineOptions（dataclass）+ run_fixedpoint（薄い orchestrator）
│   ├── _state.py            ← ChaseState dataclass + _REF_KIND 定数
│   ├── _seed.py             ← initialize_state（seed_hits → ChaseState 構築・hop0→hop1）
│   ├── _scan.py             ← _scan_file（worker）/ _file_meta / _kinds_of / scan_hop_single / scan_hop_chunked
│   ├── _ingest.py           ← ingest_one（旧クロージャ）/ absorb_results（scan 結果反映）
│   ├── _budget_control.py   ← apply_global_cap / maybe_spill
│   └── _finalize.py         ← build_indirect_hits
├── chase.py                 ← extract_var_symbols の docstring を「indirect:var 抽出の用途」中心へ書換
└── classifiers/__init__.py  ← _CHASERS の private/公開を整合（rename or __all__ 整理）
tests/unit/
├── test_chase.py            ← L46-47 mid-file import を先頭へ集約
└── test_stoplist.py         ← L39-40 mid-file import を先頭へ集約
```

> **公開 API の不変性**: `from grep_analyzer.snippet import build_snippet` / `from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint` を含む現行の全 import 文は無変更で動き続けること。再 export は `snippet/__init__.py` / `fixedpoint/__init__.py` で担保する。

> **rename について**: Phase 3 では構造変更に伴って **必要最小限の rename** のみ実施する（例: `_phys` → `_physical_lines`、`_err` → `_has_error`、`intro` → `introducers`、`estore` → `edge_store` 等）。これは ChaseState フィールド名と整合させるためであり、ファイル内ローカル変数の包括 rename は Phase 4 で実施する。

---

### Task 0a: ベースライン確立 + 性能 baseline 計測

**Files:** None（測定のみ）

- [ ] **Step 1: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`（Phase 2 完了時点と一致）。

- [ ] **Step 2: ベースライン commit hash を記録**

Run: `cd /workspaces/grep_helpers2 && git rev-parse HEAD`

Expected: Phase 2 完了 hash `8d5213b` の 40 文字版（baseline として後続 V6 計測で参照）。

- [ ] **Step 3: V6 perf baseline 計測**

`tests/perf/` 配下のスクリプトで最大ケースを 3 回実行し中央値を `docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md` に記録する。perf ディレクトリの構成を確認:

Run: `cd /workspaces/grep_helpers2 && ls tests/perf/ && find tests/perf -name '*.py' | head -5`

Expected: 既存の perf スクリプト一覧。スクリプトが存在しない場合は **暫定的に integration test の最大ケース** を使う（`tests/integration/test_pipeline_phase3.py` 等）。具体的なベンチコマンド:

```bash
cd /workspaces/grep_helpers2 && for i in 1 2 3; do
  /usr/bin/time -f '%e' pytest tests/integration/test_pipeline_phase3.py -q 2>&1 | tail -3
done
```

3 回実行の壁時計時間（秒）を記録。中央値を baseline_median とする。

- [ ] **Step 4: baseline 記録ファイル作成**

Create: `docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md`

```markdown
# Phase 3 V6 性能計測

## Baseline (Phase 2 完了時点: <commit hash>)

- 計測コマンド: `pytest tests/integration/test_pipeline_phase3.py -q`
- 3 回実行の壁時計時間（秒）: [t1, t2, t3]
- 中央値: <baseline_median>

## Phase 3 [A] 完了後

（Task A6 後に記録）

## 判定

baseline_median + 10% 又は +5 秒以内であれば許容。
```

No code changes.

---

### Task 0b: tests の mid-file import 集約（Phase 2 引き継ぎ #1 + #2）

**Files:**
- Modify: `tests/unit/test_chase.py:46-47`（`from grep_analyzer.chase import extract_chase_symbols, mask_literals` と `from grep_analyzer.model import ChaseSymbols` を先頭へ移動）
- Modify: `tests/unit/test_stoplist.py:39-40`（`from grep_analyzer.model import ChaseSymbols` と `from grep_analyzer.stoplist import partition` を先頭へ移動）

- [ ] **Step 1: test_chase.py の import を先頭集約**

```python
# 既存先頭の `from grep_analyzer.chase import extract_var_symbols` の直後に追加。
# 元の L46-47 行は削除。
from grep_analyzer.chase import (
    extract_chase_symbols,
    extract_var_symbols,
    mask_literals,
)
from grep_analyzer.model import ChaseSymbols
```

（`ChaseSymbols` は test_chase 内で使用されているか確認: `grep -n "ChaseSymbols" tests/unit/test_chase.py`。使用されていなければ import しない＝既存挙動踏襲）

- [ ] **Step 2: test_stoplist.py の import を先頭集約**

ファイル先頭の既存 import の直後に `from grep_analyzer.model import ChaseSymbols` と `from grep_analyzer.stoplist import partition` を追加し、L39-40 を削除。

- [ ] **Step 3: テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest tests/unit/test_chase.py tests/unit/test_stoplist.py -q`

Expected: 該当テストが全て pass（テスト内容不変）。

- [ ] **Step 4: Commit**

```bash
cd /workspaces/grep_helpers2 && git add tests/unit/test_chase.py tests/unit/test_stoplist.py && \
  git commit -m "style(tests): mid-file import を先頭へ集約（Phase 2 引き継ぎ Minor #1 #2 / PEP8 E402）"
```

---

## Part [C]: snippet.py 責務分割（Task C1〜C5）

snippet.py を `snippet/` サブパッケージに分解する。`build_snippet` は __init__.py に置き、private 部品は責務別サブモジュールに移す。

**Phase 3 範囲の rename**（構造移動に伴うもののみ）:
- `_phys` → `_physical_lines`（snippet/_sanitize_line.py）
- `_err` → `_has_error`（snippet/_ts.py）
- N3「真偽返却は `is_*`/`has_*`」適用

**並列実行禁止**: Phase 3 のタスクは互いに依存するため逐次実行のみ。

### Task C1: snippet/ サブパッケージ骨格 + _clamp.py 作成

**Files:**
- Create: `src/grep_analyzer/snippet/__init__.py`（暫定: 既存 snippet.py から全シンボル再 export のみ）
- Create: `src/grep_analyzer/snippet/_clamp.py`
- Modify: `src/grep_analyzer/snippet.py`（旧 _phys/_render/clamp_lines を削除し、新 module から import）

**重要**: パッケージ化途中でファイル名衝突が起きないよう、以下の順で実施する:
1. まず `snippet/` ディレクトリを作成し、`_clamp.py` を新規追加
2. 既存 `snippet.py` から該当関数を削除し、`_clamp` 経由で import に置換
3. テスト pass を確認

`snippet/__init__.py` は **作成しない**（まだ snippet.py が module として存在するため。`snippet/` をサブパッケージ化するのは Task C5 で最後にまとめて行う）。

> 注: Python のモジュール解決ルールでは `snippet.py` と `snippet/` ディレクトリは同じ namespace を競合する。安全のため Task C1〜C4 は `snippet.py` を保持しつつ、新サブモジュールは `_snippet_clamp.py` のような **トップレベル一時名** で配置するか、又は **Task C5 で一括移行** する必要がある。本 plan では後者（一括移行）を採用する。

**修正**: Task C1〜C4 を統合し、**Task C1〜C4 は順序のみ守って原子的に Task C-MERGE として 1 commit にまとめる**。途中 commit を打たない（中間状態が import 不能になるため）。

→ **Task C1（再定義）: 単一の atomic commit で snippet/ サブパッケージへ全移行**

**Files:**
- Create: `src/grep_analyzer/snippet/__init__.py`
- Create: `src/grep_analyzer/snippet/_clamp.py`
- Create: `src/grep_analyzer/snippet/_heuristic.py`
- Create: `src/grep_analyzer/snippet/_ts.py`
- Create: `src/grep_analyzer/snippet/_sanitize_line.py`
- Delete: `src/grep_analyzer/snippet.py`

- [ ] **Step 1: `src/grep_analyzer/snippet/` ディレクトリ作成（git mv は不要）**

Run: `cd /workspaces/grep_helpers2 && mkdir -p src/grep_analyzer/snippet`

- [ ] **Step 2: `_clamp.py` を作成**

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

- [ ] **Step 3: `_heuristic.py` を作成**

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

- [ ] **Step 4: `_ts.py` を作成**

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

    spec §9 v9: 判定は**選択ノードの部分木のみ**（祖先遡上しない＝ファイル内の
    無関係なエラーで健全行を捨てない・§10.3 部分木継続）。
    """
    return node.is_missing or node.type == "ERROR" or node.has_error


def ts_span(language: str, file_text: str, lineno: int):
    """java/c 選択範囲 [s,e]（0始まり物理行）。取れなければ None（→fallback）。

    spec §9 段1（node_at_line=最小内包葉・列非依存）→段2（.parent 上昇で
    粒度表へ昇格／block 等到達は直近 statement／無ければ None）。proc は
    生 EXEC が C パースを壊すため mask_exec_sql 後を解析（行番号保存）。
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
    """hit が EXEC 区間に含まれれば原ソース行スパン [s,e]、なければ None。"""
    hit = lineno - 1
    for s, e in exec_spans(file_text):
        if s <= hit <= e:
            return (s, e)
    return None
```

- [ ] **Step 5: `_sanitize_line.py` を作成**

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

- [ ] **Step 6: `snippet/__init__.py` を作成（public 集約）**

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

## Part [A]: fixedpoint.py 分割（Task A1〜A6）

fixedpoint.py を `fixedpoint/` サブパッケージへ分解する。`ChaseState` を新規データクラスとして導入し、`run_fixedpoint` 内の局所変数群と `_ingest` / `_apply_global_cap` クロージャを抽出する。

**rename（Phase 3 範囲）**: ChaseState 化に伴う構造一貫性のための rename のみ:
- `intro` → `introducers`（spec §8.2 用語）
- `sym_kind` → `symbol_kind`
- `sym_hop` → `symbol_hop`
- `estore` → `edge_store`
- `enc_of` → `encoding_of`
- `chase_done`/`chase_active`/`term_done`/`term_active` → `chase_done`/`chase_active`/`terminal_done`/`terminal_active`
- ローカル変数 `au` `sym` `cs` `dia` `prog` `agg` `meta` の rename は **Phase 4** で行う

### Task A1: fixedpoint/ サブパッケージ骨格 + ChaseState 導入（中間状態）

**Files:**
- Create: `src/grep_analyzer/fixedpoint/__init__.py`（暫定: 旧 fixedpoint.py の全内容＋ChaseState 利用）
- Create: `src/grep_analyzer/fixedpoint/_state.py`
- Delete: `src/grep_analyzer/fixedpoint.py`

snippet と同じく、`fixedpoint.py` と `fixedpoint/` ディレクトリは namespace 衝突するため、**1 task で atomic に subpackage 化する**。Task A1 は subpackage 骨格を作り、`_state.py` に ChaseState を定義、`__init__.py` で run_fixedpoint がそれを使う形に変換する。**この段階では `_seed`/`_scan`/`_ingest`/`_budget_control`/`_finalize` への分割は行わない**（A2 以降）。

- [ ] **Step 1: ディレクトリ作成**

Run: `cd /workspaces/grep_helpers2 && mkdir -p src/grep_analyzer/fixedpoint`

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
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy


_REF_KIND = {"constant": "indirect:constant", "var": "indirect:var",
             "getter": "indirect:getter", "setter": "indirect:setter"}


@dataclass
class ChaseState:
    """不動点反復の全状態。main process 専有。

    `introducers`: シンボル -> 実抽出元 Occurrence 群（spec §8.2「発見元」）
    `symbol_kind`: シンボル -> kind（constant/var/getter/setter、同名は decisive 優先）
    `symbol_hop`: シンボル -> 投入された hop 番号（決定性キー）
    `chase_active`/`chase_done`: chase 対象（constant/var）の active/done 集合
    `terminal_active`/`terminal_done`: terminal 対象（getter/setter）の集合
    `capped`: --memory-limit 等で切り捨てたシンボル
    `rel_to_abs`: walk 結果（rel → abspath）。worker への送信用 abspath を保持
    `encoding_of`: rel → (encoding, replaced)。scan 結果から逐次更新
    `*_logged`: 同一事象の重複 diagnostics 抑止用
    """

    source_root: Path
    options: "EngineOptions"  # forward ref（__init__.py で定義）
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

- [ ] **Step 3: `fixedpoint/__init__.py` を作成（旧 fixedpoint.py を ChaseState 化）**

Create `src/grep_analyzer/fixedpoint/__init__.py` （旧 fixedpoint.py の内容を ChaseState 利用形に書き換えたもの）:

```python
"""不動点・ターゲットスキャン・エンジン（spec §8.1/§8.2/§8.3）。

direct ヒットを seed に constant/var を多ホップ追跡し indirect ヒットと chain
を出す。getter/setter は §8.3 で横展開しないが全反復走査・全件 low 報告(§8.4)。
出力は走査順・並列完了順に非依存で決定的(spec §9)。

停止性(spec §8.1 手順5): 追跡シンボルは原ソース字句のみ。母集合有限・採用
集合単調増加(chase_done から削らない＝cap は capped で scan 除外のみ)。よって
高々 |母集合| ステップで飽和。--max-depth/max_symbols/max_paths は安全弁。

Related: docs/superpowers/specs/2026-05-21-refactor-design.md §6 Phase 3 [A]
"""

import multiprocessing
from dataclasses import dataclass
from pathlib import Path

from grep_analyzer import automaton, walk
from grep_analyzer.budget import MemoryBudget, estimate_items
from grep_analyzer.chase import extract_chase_symbols
from grep_analyzer.classify import classify_hit
from grep_analyzer.diagnostics import Diagnostics
from grep_analyzer.dispatch import detect_language, detect_shell_dialect
from grep_analyzer.encoding import DEFAULT_FALLBACK, decode_bytes
from grep_analyzer.fixedpoint._state import ChaseState, _REF_KIND
from grep_analyzer.model import Hit
from grep_analyzer.progress import Progress
from grep_analyzer import ripgrep as _rg
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.snippet import build_snippet
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy, load_stoplist, partition


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


def _file_meta(rel: str, raw: bytes, lang_map: dict[str, str], fallback_chain=None):
    """1 度だけデコードし (text, enc, replaced, language, dialect) を返す。"""
    chain = list(fallback_chain) if fallback_chain else DEFAULT_FALLBACK
    text, enc, replaced = decode_bytes(raw, chain)
    language = detect_language(rel, text[:4096], lang_map)
    dialect = detect_shell_dialect(rel, text[:4096]) if language == "shell" else "bourne"
    return text, enc, replaced, language, dialect


def _scan_file(args):
    """1 ファイルをワーカ内で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む。
    automaton 走査は raw 行。
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


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics,
    *, files=None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    files 指定時は内部 walk を省き事前収集 (rel, abspath) 列を使う（同値）。
    """
    source_root = Path(source_root)
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

    def _ingest(parent: Occurrence, language: str, dialect: str, line: str,
                hop: int, is_seed: bool = False):
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
        _ingest(occ, lang, dia, seed_line, hop=1, is_seed=True)

    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    state.rel_to_abs = {rel: abspath for rel, abspath in files}
    prog = Progress(opts.progress)
    prog.start(len(files))

    def _apply_global_cap():
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

    try:
        hop = 1
        while state.chase_active or state.terminal_active:
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
            prog.hop(hop, len(scan_syms), len(scan_files))
            hop += 1

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
                text, enc, replaced, lang, dia = _file_meta(c.relpath, raw, opts.lang_map, fallback_chain=list(opts.encoding_fallback))
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
                    keyword=keyword, language=language, file=c.relpath,
                    lineno=c.lineno, ref_kind=_REF_KIND[kind], category=cat,
                    category_sub="", usage_summary=f"{cat} ({language})",
                    via_symbol=c.symbol, chain=chain,
                    snippet=build_snippet(language, dialect, text, c.lineno),
                    encoding=enc + (" 要確認" if replaced else ""),
                    confidence=conf))
        prog.done()
        return indirect
    finally:
        state.edge_store.close()
```

- [ ] **Step 4: 旧 `fixedpoint.py` を削除**

Run: `cd /workspaces/grep_helpers2 && rm src/grep_analyzer/fixedpoint.py`

- [ ] **Step 5: import 健全性確認**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "from grep_analyzer.fixedpoint import EngineOptions, run_fixedpoint; print('OK')"
```

Expected: `OK`

- [ ] **Step 6: 全テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`（変動なし）。

- [ ] **Step 7: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git rm src/grep_analyzer/fixedpoint.py 2>/dev/null || true && \
  git commit -m "refactor(fixedpoint): fixedpoint.py を fixedpoint/ サブパッケージ化＋ChaseState 導入（中間状態）"
```

---

### Task A2: _scan.py 抽出（worker + scan helper）

**Files:**
- Create: `src/grep_analyzer/fixedpoint/_scan.py`
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`（_scan_file/_file_meta/_kinds_of を移動）

- [ ] **Step 1: `_scan.py` を作成**

Create `src/grep_analyzer/fixedpoint/_scan.py`:

```python
"""scan worker と scan-hop オーケストレーション。

`_scan_file` は multiprocessing.Pool 用のトップレベル純関数（pickle 制約）。
ChaseState は worker に渡さず、main process で構築した args タプルのみ渡す。
scan_hop_single / scan_hop_chunked は ChaseState から必要なプリミティブを
取り出して Pool 実行し、戻り値を呼出側で ChaseState へ反映する。

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

    ストリーミング化＝親に bytes 非常駐・abspath から読む。
    automaton 走査は raw 行。
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


def scan_hop_single(scan_syms, scan_files, opts):
    """nchunks <= 1 経路: 全 sym を 1 度に走査して rel ソート結果を返す。"""
    args = [(rel, str(abspath), scan_syms, opts.lang_map, list(opts.encoding_fallback))
            for rel, abspath in scan_files]
    if opts.jobs > 1:
        with multiprocessing.Pool(opts.jobs) as pool:
            results = pool.map(_scan_file, args)
    else:
        results = [_scan_file(a) for a in args]
    return sorted(results, key=lambda r: r[0])


def scan_hop_chunked(scan_syms, scan_files, opts, nchunks):
    """nchunks > 1 経路: chunk 別に走査し rel 単位で結果を aggregate して返す。"""
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
    return [(rel, *meta[rel],
             sorted(agg[rel], key=lambda t: (t[1], t[0])))
            for rel in sorted(agg)], len(chunks)
```

- [ ] **Step 2: `__init__.py` から該当箇所を削除し import に置換**

Edit `src/grep_analyzer/fixedpoint/__init__.py`:
- 削除: `_file_meta`/`_scan_file`/`_kinds_of` の定義
- 削除: `import multiprocessing` （`__init__.py` 内では未使用になるため）
- 追加: `from grep_analyzer.fixedpoint._scan import _file_meta, _scan_file, _kinds_of, scan_hop_single, scan_hop_chunked`
- 旧 `nchunks <= 1`/`nchunks > 1` ブロック（`run_fixedpoint` 内）を以下に置換:

```python
            if nchunks <= 1:
                pass_results = scan_hop_single(scan_syms, scan_files, opts)
            else:
                pass_results, n_actual_chunks = scan_hop_chunked(scan_syms, scan_files, opts, nchunks)
                diag.add("automaton_split", f"hop={hop} chunks={n_actual_chunks}")
```

- [ ] **Step 3: import 健全性確認 + テスト**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "from grep_analyzer.fixedpoint import run_fixedpoint; from grep_analyzer.fixedpoint._scan import _scan_file; print('OK')" && \
  pytest -q 2>&1 | tail -5
```

Expected: `OK` + `249 passed, 5 skipped`。multiprocessing test も pass。

- [ ] **Step 4: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git commit -m "refactor(fixedpoint): scan worker と scan_hop_single/chunked を _scan.py へ抽出"
```

---

### Task A3: _ingest.py 抽出（旧クロージャ）

**Files:**
- Create: `src/grep_analyzer/fixedpoint/_ingest.py`
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`（`_ingest` クロージャを削除し import）

`_ingest` は元々クロージャだったが、ChaseState 経由ですべての state 操作が外出しできるため、トップレベル関数化できる。シグネチャは `(state, parent, language, dialect, line, hop, is_seed=False)` とする。

- [ ] **Step 1: `_ingest.py` を作成**

Create `src/grep_analyzer/fixedpoint/_ingest.py`:

```python
"""1 行から ChaseState への追跡シンボル投入（spec §8.1 手順）。

extract_chase_symbols で得た候補を stoplist.partition で chase / terminal /
rejected に分け、`introducers`（発見元）に親 Occurrence を記録する。
非 seed の自己定義行が自分自身を再抽出しても発見元にしない（spec §8.2）。

`absorb_results`: scan 結果を ChaseState に反映する（edge_store 追加、
encoding 記録、子の再 ingest）。

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
    """scan_hop の結果を ChaseState に反映する（edge 追加・diag・子の再 ingest）。"""
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

- [ ] **Step 2: `__init__.py` の `_ingest` クロージャを削除し、`ingest_one`/`absorb_results` を呼ぶ**

Edit `src/grep_analyzer/fixedpoint/__init__.py`:
- 削除: `def _ingest(parent, language, dialect, line, hop, is_seed=False):` 全体
- 追加: `from grep_analyzer.fixedpoint._ingest import absorb_results, ingest_one`
- seed ループ: `_ingest(occ, lang, dia, seed_line, hop=1, is_seed=True)` → `ingest_one(state, occ, lang, dia, seed_line, hop=1, is_seed=True)`
- メインループ末尾: `for rel, enc, replaced, language, dialect, found in pass_results: ...` ブロック全体を `absorb_results(state, pass_results, scan_chase, scan_term, hop)` に置換

- [ ] **Step 3: import 健全性確認 + テスト**

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

`_apply_global_cap` をトップレベル関数化し、spill 判定も同モジュールに集約。

- [ ] **Step 1: `_budget_control.py` を作成**

Create `src/grep_analyzer/fixedpoint/_budget_control.py`:

```python
"""グローバル cap と spill 判定（spec §8.2 L164 優先 1 / §8.3 決定的切り捨て）。

- apply_global_cap: --memory-limit / --max-symbols でシンボル集合を切り詰める。
  単調縮小・決定的（キー: (symbol_hop, len(s), s)）。
- maybe_spill: in-memory edge 数と introducers 数で予算超過判定し、超過時に
  edge_store.maybe_spill_now() を呼ぶ。1 度だけ diag を立てる。

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
    """予算超過時に edge_store を spill する（hop 単位で 1 度だけ diag 記録）。"""
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
    """予算と force_chunks から chunk 数を決める。1 経路なら 1 を返す。"""
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

- [ ] **Step 2: `__init__.py` から `_apply_global_cap` 削除 + nchunks 計算ブロックを差し替え**

Edit `src/grep_analyzer/fixedpoint/__init__.py`:
- 削除: `def _apply_global_cap():` 全体
- 削除: メインループ冒頭の spill 判定ブロック（`if not state.budget.unlimited and not state.edge_store.spilled: ...`）と nchunks 計算ブロック（`nchunks = 1; if opts.force_chunks ...`）
- 追加: `from grep_analyzer.fixedpoint._budget_control import apply_global_cap, compute_nchunks, maybe_spill`
- 置換: メインループ内
  ```python
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
      if nchunks <= 1:
          pass_results = scan_hop_single(scan_syms, scan_files, opts)
      else:
          pass_results, n_actual_chunks = scan_hop_chunked(scan_syms, scan_files, opts, nchunks)
          diag.add("automaton_split", f"hop={hop} chunks={n_actual_chunks}")
      absorb_results(state, pass_results, scan_chase, scan_term, hop)
      prog.hop(hop, len(scan_syms), len(scan_files))
      hop += 1
  ```

- [ ] **Step 3: テスト pass 確認**

Run: `cd /workspaces/grep_helpers2 && pytest -q 2>&1 | tail -5`

Expected: `249 passed, 5 skipped`。

- [ ] **Step 4: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git commit -m "refactor(fixedpoint): _apply_global_cap / spill / nchunks 計算を _budget_control.py へ抽出"
```

---

### Task A5: _seed.py + _finalize.py 抽出

**Files:**
- Create: `src/grep_analyzer/fixedpoint/_seed.py`
- Create: `src/grep_analyzer/fixedpoint/_finalize.py`
- Modify: `src/grep_analyzer/fixedpoint/__init__.py`

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
from grep_analyzer.fixedpoint._scan import _file_meta
from grep_analyzer.fixedpoint._state import ChaseState
from grep_analyzer.model import Hit
from grep_analyzer.provenance import Occurrence, ProvenanceGraph
from grep_analyzer.spill import EdgeStore
from grep_analyzer.stoplist import SymbolPolicy, load_stoplist


def initialize_state(seed_hits: list[Hit], source_root: Path, opts, diag: Diagnostics) -> ChaseState:
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

- [ ] **Step 3: `__init__.py` を orchestrator に縮約**

Edit `src/grep_analyzer/fixedpoint/__init__.py` to be:

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

from dataclasses import dataclass
from pathlib import Path

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
from grep_analyzer.fixedpoint._scan import scan_hop_chunked, scan_hop_single
from grep_analyzer.fixedpoint._seed import initialize_state
from grep_analyzer.model import Hit
from grep_analyzer.progress import Progress


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


def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions, diag: Diagnostics,
    *, files=None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    files 指定時は内部 walk を省き事前収集 (rel, abspath) 列を使う（同値）。
    """
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
            if nchunks <= 1:
                pass_results = scan_hop_single(scan_syms, scan_files, opts)
            else:
                pass_results, n_actual_chunks = scan_hop_chunked(
                    scan_syms, scan_files, opts, nchunks)
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

- [ ] **Step 5: Commit**

```bash
cd /workspaces/grep_helpers2 && \
  git add src/grep_analyzer/fixedpoint/ && \
  git commit -m "refactor(fixedpoint): _seed.py / _finalize.py 抽出 + __init__.py を orchestrator に縮約"
```

---

### Task A6: V6 性能リグレッション計測

**Files:**
- Modify: `docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md`

- [ ] **Step 1: Phase 3 [A] 完了後の計測**

Task A5 完了 commit hash を `git rev-parse HEAD` で取得。Task 0a と同じコマンドで 3 回計測:

```bash
cd /workspaces/grep_helpers2 && for i in 1 2 3; do
  /usr/bin/time -f '%e' pytest tests/integration/test_pipeline_phase3.py -q 2>&1 | tail -3
done
```

中央値を Phase 3 [A] 後の median とする。

- [ ] **Step 2: 判定**

`baseline_median + 10%` 又は `baseline_median + 5s` を超える場合は要因解析。
許容内なら `docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md` の「判定」セクションに OK と記載してコミット:

```bash
cd /workspaces/grep_helpers2 && \
  git add docs/superpowers/plans/2026-05-21-refactor-phase3-perf.md && \
  git commit -m "perf(phase3): V6 性能リグレッション計測結果（baseline 比 ±N%）"
```

- [ ] **Step 3: 超過時の対応**

差分要因の主候補:
- ChaseState 経由のフィールドアクセスオーバヘッド（dataclass の `__init__` / 属性参照）
- 関数境界の追加（_ingest / _scan / _budget_control の関数呼出）
- multiprocessing 経路に変更がないこと（worker は不変・args 構築のみ変化）を確認

要因が特定でき修正可能なら修正→再計測。修正不要と判断するならその根拠を `phase3-perf.md` に記載。

---

## Part [B]: Phase 2 引き継ぎ #3 + #4 の解消

### Task B1: chase.py docstring の書換 + _CHASERS の private/__all__ 整合

**Files:**
- Modify: `src/grep_analyzer/chase.py:20-22`（`extract_var_symbols` docstring）
- Modify: `src/grep_analyzer/classifiers/__init__.py`（`_CHASERS` の export 整理）

- [ ] **Step 1: chase.py docstring 書換**

Edit `src/grep_analyzer/chase.py`:
- `extract_var_symbols` docstring 内の「fixedpoint の `_ingest` が言語非依存の var シンボル列を必要とするため」→「`indirect:var` 追跡で左辺識別子のみを必要とする呼出元から使われるため」

実装は変更しない。

- [ ] **Step 2: `_CHASERS` の整合**

選択肢:
- (i) `_CHASERS` → `CHASERS`（public 化）
- (ii) `__all__` から `_CHASERS` を外して内部実装に格下げ

chase.py（dispatcher）が直接 import している（`from grep_analyzer.classifiers import _CHASERS`）ことを考えると、**(ii) `__all__` から外す**のが妥当。具体的には:

```python
__all__ = ["Chaser"]  # _CHASERS は private（chase.py のみが import する）
```

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
  grep -rn "from grep_analyzer" src/grep_analyzer/snippet/ src/grep_analyzer/fixedpoint/ src/grep_analyzer/classifiers/ src/grep_analyzer/patterns/ 2>&1
```

Expected:
- `patterns/*` は `grep_analyzer.*` を import しない（葉）
- `classifiers/*` は `patterns/*` と `model` のみ
- `snippet/*` は `chase`, `classifiers.ts_classifier`, `patterns.snippet_boundaries`, `proc_preprocess`, `tsv` のみ
- `fixedpoint/*` は `snippet`, `chase`, `classify`, `dispatch`, `encoding`, `model`, `walk`, `ripgrep`, `stoplist`, `spill`, `provenance`, `diagnostics`, `budget`, `automaton`, `progress` のみ
- 上位（pipeline, cli）への逆依存ゼロ

- [ ] **Step 2: cyclic import 実機検証**

Run:
```bash
cd /workspaces/grep_helpers2 && \
  python -c "import grep_analyzer; import grep_analyzer.cli; import grep_analyzer.fixedpoint; import grep_analyzer.snippet; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: pytest collection 確認**

Run: `cd /workspaces/grep_helpers2 && pytest --collect-only -q 2>&1 | tail -10`

Expected: コレクションエラーゼロ。

### V5 Phase 3 ゲート

実装完了後、批判的 AI レビュー（観点 A: 設計遵守＋仕様準拠／観点 B: 実装品質＋境界条件）を最低 2 巡実行し Critical/Major ゼロまで収束。

---

## V1〜V5 Phase 3 完了基準

- [ ] Inv-A: golden 22 全件 byte 一致
- [ ] Inv-B: pytest 全件 pass（249 passed, 5 skipped 維持）
- [ ] Inv-C: 公開 API（EngineOptions / run_fixedpoint / build_snippet / clamp_lines / heuristic_span / ts_span / proc_exec_span）シグネチャ・戻り値不変
- [ ] Inv-D: V3 で層分離違反ゼロ
- [ ] Inv-E: pyahocorasick 版差吸収・決定性保持
- [ ] V6: 性能リグレッション 10% / +5s 以内
- [ ] V5: AI レビュー Critical/Major ゼロに収束

---

## Phase 3 → Phase 4 引き継ぎ事項（予定枠）

Phase 3 で発生・残置する Minor は Phase 4 plan 冒頭に記録する:

- N1〜N4 違反（au / sym / cs / dia / prog / agg / meta 等のローカル変数）の全モジュール横断 rename
- Phase 2 引き継ぎ #5 `patterns/literal_masking.py` の java/c/proc 重複（Pro*C 個別化判定）
- Phase 2 引き継ぎ #6 `chase.py` / `snippet/*` / `fixedpoint/*` module docstring の `Phase 1.5` / `v9` 等マーカー除去（C5 違反）
- Phase 2 引き継ぎ #7 `classifiers/__init__.py` eager import 失敗時の挙動
- Phase 3 で抽出した `_state.py` の `_REF_KIND` 命名（`_REF_KIND` → `INDIRECT_REF_KIND_BY_KIND` 等の意図的命名）
