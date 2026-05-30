# Phase 4: ロックステップ共有エンジン 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`). 本 Phase は本体の不動点を**転置**する最大の変更。各 Task は **golden 全件バイト一致＋jobs2==jobs1** を完了条件とし、転置の各単位で逐次版との同値を保つ。

**Goal:** 35 keyword を逐次でなく同時に1段ずつ前進させ、各グローバル hop で全 keyword の記号和集合に対し rg 1回＋候補デコード/automaton 走査/tree-sitter を共有することで、corpus 走査を `Σ hop_k`（≈245）から `max hop_k`（≈7）へ圧縮する。**keyword ごとの TSV 行は逐次版とバイト不変。**

**Architecture:** automaton 単調性（`automaton.py:35` の `iter()`・位置依存・sorted＝記号追加で既存ヒット不変）を要石に、`run_fixedpoint_multi(states_by_kw, ...)` を新設。各 keyword 別 `ChaseState`（`initialize_state` を keyword 別 seed で呼ぶ）と keyword 別 `Diagnostics` を保持し、グローバル hop ごとに union 走査 → 各 keyword の `absorb_results`（自記号フィルタは既存 `_ingest.py:78`）→ finalize。診断は「共有walk→direct(kw sorted)→indirect(kw sorted)」順でマージし逐次版バイト一致。

**Tech Stack:** Python 3.12 / pytest / multiprocessing。Phase 1/2/3 完了が前提（prefilter・enc-memo を共有走査で活かす）。

正本 spec: `docs/superpowers/specs/2026-05-30-perf-chardet-prefilter-design.md`（§4.1/§6.1/§6.2）。

> **実装方針（重要）**: 本 Phase は深い restructure。**逐次版を壊さず段階導入**する。まず「単一 keyword でも multi 経路を通す」同値を固め（Task 3）、次に複数 keyword の lock-step 同値（Task 6）を固める。各 Task は実コード（`__init__.py`/`_ingest.py`/`_budget_control.py`/`pipeline.py`）に照合しながら進める。

---

## ファイル構成

- Modify: `src/grep_analyzer/diagnostics.py` — `Diagnostics.merge_in_order(others)` 追加（カテゴリ内 detail を与えられた順で連結）。
- Create: `src/grep_analyzer/fixedpoint/_lockstep.py` — `run_fixedpoint_multi(states_by_kw, source_root, opts, files, unsafe_rels, enc_memo)`。
- Modify: `src/grep_analyzer/fixedpoint/__init__.py` — `run_fixedpoint` を `run_fixedpoint_multi` の単一keyword委譲に（後方互換）。
- Modify: `src/grep_analyzer/fixedpoint/_budget_control.py` — union 予算版 `compute_nchunks_union(states, union_symbols)`。
- Modify: `src/grep_analyzer/pipeline.py` — keyword 群を一括 seed → `run_fixedpoint_multi` → keyword 別 finalize＋診断マージ。
- Test: `tests/integration/test_lockstep.py`、既存 `tests/golden/test_golden.py`（不変）。

---

## Task 1: `Diagnostics.merge_in_order`（keyword 別診断の決定的結合）

**Files:** Modify `src/grep_analyzer/diagnostics.py` / Test `tests/unit/test_diagnostics.py`

逐次版の追記順「A 全部→B 全部」を再現するため、複数 `Diagnostics` をカテゴリごとに detail を順連結する。

- [ ] **Step 1: failing test**

```python
# tests/unit/test_diagnostics.py に追記
from grep_analyzer.diagnostics import Diagnostics


def test_merge_in_orderはカテゴリ内detailを与えた順で連結():
    base = Diagnostics()
    a = Diagnostics(); a.add("decode_replaced", "A.java")
    b = Diagnostics(); b.add("decode_replaced", "B.java"); b.add("missing_source", "X")
    base.merge_in_order([a, b])
    out = base.render(detail_limit=1000, exempt=frozenset())
    # decode_replaced は A→B の順
    assert out.index("A.java") < out.index("B.java")
    assert "missing_source" in out and "X" in out
```

- [ ] **Step 2: run fail** — FAIL（`merge_in_order` 未定義）

- [ ] **Step 3: implement** — `diagnostics.py` の内部表現（カテゴリ→detail list、件数カウンタ）を確認し、`merge_in_order(others)` で各 other のカテゴリ detail を順に自身へ append、件数も合算。実装時に既存 `add`/`render` の内部構造（`_details: dict[str, list]`・`_counts` 等）に合わせる。

- [ ] **Step 4: run pass** — PASS

- [ ] **Step 5: commit** — `git commit -am "feat(diag): merge_in_order で keyword 別診断を決定的結合（Phase4 Task1）"`

---

## Task 2: union 予算版 `compute_nchunks_union`

**Files:** Modify `src/grep_analyzer/fixedpoint/_budget_control.py` / Test `tests/unit/test_budget.py`

spec §4.1 の一意式: `n_live=|union記号|`、`n_intro=Σ_kw len(introducers)`、`in_memory_len=Σ_kw edge_store.in_memory_len()`、予算 `--memory-limit` 全体。

- [ ] **Step 1: failing test**

```python
# tests/unit/test_budget.py に追記
def test_compute_nchunks_unionは予算無制限なら1():
    from grep_analyzer.fixedpoint._budget_control import compute_nchunks_union
    # states=[] / union 任意でも budget unlimited なら 1
    assert compute_nchunks_union([], ["A", "B"], unlimited=True, max_passes=8) == 1
```

> 完全な多 state ケースは Task6 e2e で担保。本 Task は式の骨子を固定。

- [ ] **Step 2: run fail** — FAIL

- [ ] **Step 3: implement** — `compute_nchunks` を参考に、`n_live/n_intro/in_memory_len` を**複数 state 合算**で算出する版を追加（`unlimited=True` で即 1）。シグネチャ `compute_nchunks_union(states, union_symbols, *, unlimited, max_passes, budget=None)`。

- [ ] **Step 4: run pass** — PASS

- [ ] **Step 5: commit** — `git commit -am "feat(budget): union 予算版 nchunks（Phase4 Task2）"`

---

## Task 3: `run_fixedpoint_multi`（単一keyword で逐次版と同値）

**Files:** Create `src/grep_analyzer/fixedpoint/_lockstep.py`, Modify `fixedpoint/__init__.py` / Test `tests/integration/test_lockstep.py`

まず **単一 keyword** で `run_fixedpoint_multi` が現 `run_fixedpoint` とバイト同値の indirect を返すことを固める（転置の土台）。

- [ ] **Step 1: failing test**

```python
# tests/integration/test_lockstep.py
def test_multiは単一keywordで逐次版とindirect一致(tmp_path):
    from grep_analyzer.pipeline import _default_opts
    from grep_analyzer.fixedpoint import run_fixedpoint
    from grep_analyzer.fixedpoint._lockstep import run_fixedpoint_multi
    from grep_analyzer.fixedpoint._seed import initialize_state
    from grep_analyzer.diagnostics import Diagnostics
    from grep_analyzer.walk import collect_files
    from grep_analyzer.model import Hit
    from pathlib import Path
    src = tmp_path; (src / "A.java").write_text(
        "class A { static final int KCODE=1; int r=KCODE; }\n", "utf-8")
    opts = _default_opts()
    seed = [Hit(keyword="K", language="java", file="A.java", lineno=1,
                ref_kind="direct", category="定義", category_sub="",
                usage_summary="", via_symbol="", chain="", snippet="",
                encoding="utf-8", confidence="high")]
    files, _, unsafe = collect_files(src, include=[], exclude=[], follow_symlinks=False,
                                     max_file_bytes=5_000_000, diag=Diagnostics())
    # 逐次
    st1 = initialize_state(seed, src, opts, Diagnostics())
    seq = run_fixedpoint(seed, src, opts, st1.diagnostics, files=files)
    # multi（単一keyword）
    st2 = initialize_state(seed, src, opts, Diagnostics())
    multi = run_fixedpoint_multi({"K": st2}, src, opts, files=files,
                                 unsafe_rels=unsafe, enc_memo=None)["K"]
    assert [h.chain for h in seq] == [h.chain for h in multi]
    assert [h.file for h in seq] == [h.file for h in multi]
```

- [ ] **Step 2: run fail** — FAIL（`_lockstep` 不在）

- [ ] **Step 3: implement**（中核ループ。`__init__.py:run_fixedpoint` を参考に転置）

```python
# src/grep_analyzer/fixedpoint/_lockstep.py
from pathlib import Path
from grep_analyzer import ripgrep as _rg
from grep_analyzer.fixedpoint._budget_control import apply_global_cap, maybe_spill, compute_nchunks_union
from grep_analyzer.fixedpoint._finalize import build_indirect_hits
from grep_analyzer.fixedpoint._ingest import absorb_results
from grep_analyzer.fixedpoint._scan import make_file_cache, make_pool, scan_hop


def run_fixedpoint_multi(states_by_kw, source_root, opts, *, files,
                         unsafe_rels=None, enc_memo=None):
    """全 keyword を lock-step で前進させ keyword 別 indirect Hit を返す。"""
    source_root = Path(source_root)
    unsafe_rels = unsafe_rels or set()
    rel_to_abs = {r: a for r, a in files}
    for st in states_by_kw.values():
        st.rel_to_abs = rel_to_abs
    file_cache = make_file_cache()
    pool = make_pool(opts)
    try:
        ghop = 1
        while any(st.chase_active or st.terminal_active for st in states_by_kw.values()):
            # 各 state を 1 段分 advance 準備（cap/spill は per-state）
            per_kw = {}   # kw -> (scan_chase, scan_term)
            union = set()
            for kw, st in states_by_kw.items():
                apply_global_cap(st); maybe_spill(st, ghop)
                sc = {s for s in st.chase_active if s not in st.capped}
                stm = {s for s in st.terminal_active if s not in st.capped}
                st.chase_done |= st.chase_active; st.chase_active = set()
                st.terminal_done |= st.terminal_active; st.terminal_active = set()
                per_kw[kw] = (sc, stm)
                union |= sc | stm
            scan_symbols = sorted(union)
            if not scan_symbols or ghop > opts.max_depth:
                break
            scan_files = files
            if opts.use_ripgrep:
                keep = _rg.prefilter(source_root, rel_to_abs, scan_symbols)
                if keep is not None:
                    safe = keep | unsafe_rels
                    scan_files = [(r, a) for r, a in files if r in safe]
            nchunks = compute_nchunks_union(
                list(states_by_kw.values()), scan_symbols,
                unlimited=next(iter(states_by_kw.values())).budget.unlimited,
                max_passes=opts.max_passes)
            pass_results, _ = scan_hop(scan_symbols, scan_files, opts, nchunks,
                                       file_cache=file_cache, pool=pool)
            for kw, st in states_by_kw.items():
                sc, stm = per_kw[kw]
                absorb_results(st, pass_results, sc, stm, ghop)
            ghop += 1
        return {kw: build_indirect_hits(st) for kw, st in states_by_kw.items()}
    finally:
        if pool is not None:
            pool.close(); pool.join()
        for st in states_by_kw.values():
            st.edge_store.close()
```

`__init__.py` の `run_fixedpoint(seed_hits, ...)` は、内部で `initialize_state`→`run_fixedpoint_multi({kw: state})` に委譲する薄いラッパへ（後方互換・既存テスト不変）。

> **検証ポイント**: 逐次版 `__init__.py:60-85` と本ループの差は「per-state を辞書反復するか単一か」だけ。`apply_global_cap`/`maybe_spill`/`absorb_results` は state 単位の既存純度を保つ。automaton 単調性で union 走査→per-kw フィルタ＝単独走査と同値。

- [ ] **Step 4: run pass** — `python -m pytest tests/integration/test_lockstep.py -q` → PASS

- [ ] **Step 5: 全回帰（run_fixedpoint 委譲が既存を壊さない）** — `python -m pytest -q` → PASS（golden 含む不変）

- [ ] **Step 6: commit** — `git commit -am "feat(lockstep): run_fixedpoint_multi（単一keyword同値）（Phase4 Task3）"`

---

## Task 4: `pipeline.run` を keyword 一括 seed → multi → keyword 別 finalize に転置

**Files:** Modify `src/grep_analyzer/pipeline.py` / Test `tests/integration/test_lockstep.py`

- [ ] **Step 1: failing test（複数 keyword で逐次出力と各 TSV 一致）**

```python
def test_pipeline_lockstepは複数keywordで各TSV逐次版一致(tmp_path):
    import dataclasses
    from grep_analyzer.pipeline import run, _default_opts
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text(
        "class A { static final int K1=1; int a=K1; static final int K2=2; int b=K2; }\n", "utf-8")
    inp = tmp_path / "in"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:    static final int K1=1;\n", "utf-8")
    (inp / "K2.grep").write_text("A.java:1:    static final int K2=2;\n", "utf-8")
    # lock-step（新 run）
    out_new = tmp_path / "new"; run(inp, out_new, src, _default_opts())
    # 逐次相当（1 keyword ずつ別 input で実行＝旧経路の同値物）
    out_seq = tmp_path / "seq"
    for kw in ("K1", "K2"):
        sub = tmp_path / f"in_{kw}"; sub.mkdir()
        (sub / f"{kw}.grep").write_text((inp / f"{kw}.grep").read_text("utf-8"), "utf-8")
        run(sub, out_seq, src, _default_opts())
    assert (out_new / "K1.tsv").read_bytes() == (out_seq / "K1.tsv").read_bytes()
    assert (out_new / "K2.tsv").read_bytes() == (out_seq / "K2.tsv").read_bytes()
```

- [ ] **Step 2: run fail** — まず現状（逐次 pipeline）で**この test は PASS してしまう**（旧経路でも各 TSV は同値）。よって本 Task は「lock-step 転置後も同値維持」の回帰として置く。Step3 実装後に再確認。

- [ ] **Step 3: implement** — `pipeline.run` の keyword ループを転置:
  1. 全 `.grep` から keyword 別 `seed_hits[kw]`（direct Hit）を構築（resume 完了は除外）。direct 構築は現行ロジック（`pipeline.py:61-128` の direct 部）を keyword ごとに回し、run 共有 enc-memo（Phase3）を使う。
  2. keyword 別 `Diagnostics` と `initialize_state(seed_hits[kw], ...)` で `states_by_kw` を構築。
  3. `run_fixedpoint_multi(states_by_kw, source_root, opts, files=files, unsafe_rels=unsafe_rels, enc_memo=enc_memo)` で indirect を取得。
  4. keyword sorted 順に finalize（`output_writer.finalize`）＋ direct/indirect の行を結合（現行と同じ `src_abs` 絶対化）。
  5. 診断は「共有 walk 診断（collect_files 由来の1個）→ keyword sorted 順に各 keyword の direct 診断→indirect 診断」を `merge_in_order` で結合し `diagnostics.txt` 出力。

- [ ] **Step 4: run pass ＋ 全回帰** — `python -m pytest -q` → PASS（golden 不変・jobs2==jobs1 不変）

- [ ] **Step 5: commit** — `git commit -am "feat(lockstep): pipeline を keyword 一括 lock-step に転置（Phase4 Task4）"`

---

## Task 5: 診断順序の逐次版一致（diagnostics.txt バイト一致）

**Files:** Test `tests/integration/test_lockstep.py`

- [ ] **Step 1: failing/regression test**

```python
def test_lockstepのdiagnosticsは逐次版とバイト一致(tmp_path):
    # Task4 と同じ 2 keyword 構成で diagnostics.txt を比較
    ...  # out_new/diagnostics.txt（automaton_split 行を除外比較） == out_seq 相当
```

> `automaton_split` は走査構造依存で逐次合算と一致しない（spec §6.2＝§8.4 全件性対象外）。比較時はこの行を除外、その他カテゴリは完全一致を要求。

- [ ] **Step 2-4: 実装調整** — 不一致なら `merge_in_order` の結合順（共有→direct(kw)→indirect(kw)）と keyword sorted を見直す。

- [ ] **Step 5: commit** — `git commit -am "test(lockstep): diagnostics 順序の逐次版一致（Phase4 Task5）"`

---

## Task 6: lock-step 共有の効果と決定性の総合回帰

**Files:** Test `tests/integration/test_lockstep.py`, `tests/golden`

- [ ] **Step 1: 共有走査の効果（scan_hop 呼び出し回数 ≤ max hop）**

```python
def test_lockstepはcorpus走査をmax_hopに圧縮(tmp_path, monkeypatch):
    """scan_hop 呼び出し回数が Σhop でなく max hop（≈グローバルhop数）であることを固定。"""
    import grep_analyzer.fixedpoint._lockstep as ls
    calls = {"n": 0}; real = ls.scan_hop
    monkeypatch.setattr(ls, "scan_hop",
                        lambda *a, **k: calls.__setitem__("n", calls["n"]+1) or real(*a, **k))
    # 2 keyword・各 2 hop 相当を構成 → scan_hop は ≤ 2(グローバルhop) であって 4 ではない
    ...
    assert calls["n"] <= 2
```

- [ ] **Step 2: golden 全件＋jobs2==jobs1** — `python -m pytest tests/golden -q` → PASS（keyword 別 TSV・診断バイト一致）。

- [ ] **Step 3: commit** — `git commit -am "test(lockstep): 走査圧縮と決定性の総合回帰（Phase4 Task6）"`

---

## 自己レビュー

- **spec 被覆**: §4.1（lock-step・automaton 単調性・union 予算・seed 転置・resume 除外）→ Task2/3/4。§6.2（診断 keyword 別マージ・automaton_split 共有）→ Task1/5。§6.1（keyword 別 TSV 不変）→ Task3/4/6 の同値テスト＋golden。✓
- **プレースホルダ**: Task5/6 の一部テストは骨子（`...`）。実装時に Task4 構成を再利用して具体化（注記済）。中核ループ・マージ・予算は実コード。
- **型整合**: `run_fixedpoint_multi(states_by_kw, source_root, opts, *, files, unsafe_rels, enc_memo)`、`compute_nchunks_union(states, union_symbols, *, unlimited, max_passes, budget=None)`、`merge_in_order(others)`、`run_fixedpoint` は委譲ラッパ。
- **リスク（明記）**: 本 Phase は深い restructure。Task3（単一keyword同値）→Task4（複数同値）→Task5（診断）→Task6（効果）の順で**各単位を golden/同値テストで固めながら**進め、一括変更を避ける。automaton 単調性が崩れる兆候（同値テスト失敗）が出たら即停止し `automaton.scan_line` 経路のバイパスを疑う。

---

## rev.2 補遺（計画レビュー第1R反映・確定上書き）

### C-2【最重要・診断汚染】共有 pass_results を keyword 別に relpath 絞りしてから absorb

`absorb_results`（`_ingest.py:72-75`）は **pass_results の全 relpath** に対し `encoding_of.setdefault` と `decode_replaced` 診断を発火する（found の symbol フィルタ `:78` より前）。lock-step では pass_results が union ヒットを含むため、**keyword K2 が、K1 の記号だけがヒットした relpath の `decode_replaced` を記録**してしまい、keyword 別 diagnostics が逐次版と割れる。

**対策（必須）**: 各 keyword の `absorb_results` 呼出前に、pass_results を **「その keyword の scan 集合（sc∪stm）の記号が found に1件でもある relpath」に絞る**:

```python
for kw, st in states_by_kw.items():
    sc, stm = per_kw[kw]
    want = sc | stm
    kw_results = [(rel, enc, rep, lang, dia,
                   [t for t in found if t[0] in want])      # t=(symbol,lineno,line,cs)
                  for (rel, enc, rep, lang, dia, found) in pass_results
                  if any(t[0] in want for t in found)]      # K がヒットした relpath のみ
    absorb_results(st, kw_results, sc, stm, ghop)
```

これで encoding_of/decode_replaced が逐次版（K は自記号でヒットした relpath のみ走査）と一致。automaton 単調性により found 自体は単独走査と同値ゆえ TSV も不変。

### C-1【Phase2 依存の明記】unsafe_rels と collect_files_ex

`unsafe_rels`・3-tuple `collect_files_ex` は **Phase 2 で導入済み前提**（本 Phase は Phase 1/2/3 完了後に着手）。`run_fixedpoint_multi` の `unsafe_rels` 引数・prefilter の `keep | unsafe_rels` は Phase 2 と同一。**Phase 2 未適用の環境では本 Phase を着手しない**（依存を冒頭に明記）。

### C-3【委譲ラッパの機能保持】run_fixedpoint は walk/Progress/automaton_split を保持

`run_fixedpoint` を `run_fixedpoint_multi` 委譲ラッパにする際、**(a) `files is None` の内部 walk フォールバック、(b) `Progress` 駆動、(c) `automaton_split` 診断**を保持する。具体的には:
- `run_fixedpoint_multi` 自身に **`automaton_split` 診断**（`scan_hop` の `n_actual_chunks` 戻り＞1 のとき `diag.add("automaton_split", f"hop={ghop} chunks={n}")`）と **`Progress`** を持たせる。union 走査は **グローバル hop 単位で1回**なので automaton_split も**共有診断としてグローバル hop ごと1回**（spec §6.2＝§8.4 全件性対象外）。
- 単一 keyword 委譲時、既存 golden の diagnostics.txt が automaton_split を含む場合、**逐次版と件数が変わり得る**。→ 既存 golden に automaton_split を含むケースが無いことを確認（dev で `grep -rl automaton_split tests/golden` ＝無ければ問題なし）。在る場合はそのケースの diagnostics 期待を更新。
- `files is None` フォールバックはラッパ側で walk して `run_fixedpoint_multi` に渡す。

### C-2 連鎖【hop 番号入り診断のグローバル hop 化】

`graph_spilled`（`_budget_control.py:54` `hop=N`）・`prov_max_depth` 等 **hop 番号を文字列に含む診断**は lock-step で**グローバル hop 値**になり逐次版（keyword 別 hop）とズレる。単一 keyword では一致（グローバル hop=局所 hop）。複数 keyword の diagnostics 比較（Task5）では、これらを **§8.4 走査構造依存として除外比較**するか、グローバル hop 表記を許容と spec §6.2 に明記。**Task5 の除外カテゴリ確定リスト: `automaton_split`・`graph_spilled`（hop 表記）**。その他カテゴリ（decode_replaced/symbol_rejected/missing_source 等）は C-2 の relpath 絞りで完全一致を要求。

### H-1: compute_nchunks_union のシグネチャ統一

`compute_nchunks_union(states, union_symbols, *, opts, budget)` に統一。`force_chunks`（`opts.force_chunks`）分岐・`budget.exceeded` 判定（`budget=states[0].budget`＝run 共有）・`max_passes`（`opts.max_passes`）を一貫供給。Task2 テストを「unlimited=True→1」「force_chunks>1→min(...)」の2分岐に拡張。

### H-2: resume 完了 keyword の全経路除外

resume 完了 keyword は **(a) direct 構築スキップ (b) `states_by_kw` 非投入 (c) finalize 非呼出 (d) `resume_skipped` 診断を逐次版と同順（keyword sorted）で add**。既存 resume spy テスト（MEMORY #C-2）を回帰として維持。

### H-3: merge_in_order の規約

`_counts[cat] += other._counts[cat]`、`_detail[cat]` は `_MAX_RETAINED` を尊重して extend（超過分は捨て render の retained 行で表現）。逐次版は単一 diag に直列 add ゆえ総数一致。

### M-1: Task4 完了条件

Task4 の完了条件は「Task4 test PASS」でなく **「golden 全件＋jobs2==jobs1 バイト不変」**に一本化（転置の真の回帰ガードは golden）。

## 実行ハンドオフ

Phase 4 完了で本体最適化は完了。**実コーパスで再計測**（walk・初回chardet・rg走査総量・RAMピーク）し1時間目標を確認。未達なら Phase 5（option B / cchardet）。
