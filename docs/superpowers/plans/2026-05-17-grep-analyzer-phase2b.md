# grep_analyzer Phase 2b（資源 degrade・ストリーミング・ripgrep・progress） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`). **全コミット末尾に `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` を付す。`git add` は各 Task 記載ファイルのみ（明示パス・`.claude/settings.local.json` 等を含めない）。**

> **改訂履歴:** v1 → v2（1巡目3並行レビュー反映）→ **v3（本書・2巡目3並行レビュー反映）**。2巡目で C1/C2/C4 は根治確認（Reviewer がv2を実リポジトリ適用し 159 passed・既存 byte 不変を実走実証）。新規収束 Critical を spec §8.2 精読のうえ是正:
> - **degrade ラダー誤読の根治（最重要）**: v2 は `_apply_global_cap` の memory 予算に edges/intro を含め `keep` を 0 まで削った＝spec §8.2 が優先2スピルに割り当てた来歴グラフのメモリ責務を優先1が侵食（staged-invariant は v2 コードで到達不能）。**v3: priority-1 ＝ §8.3 の `max_symbols` 決定的キャップ（Phase 2a `_apply_global_cap` を一切変更しない・memory 非依存・唯一の出力変更）。`--memory-limit` は priority-2 来歴スピル＋最終手段オートマトン分割のみを駆動し、両者は出力透過（網羅性＝indirect を保持）**。spec §8.2「(優先1) §8.3 切り捨て → (優先2) スピル → (最終手段) 分割」に厳密整合。staged-invariant の概念を廃止。
> - **`memory_limit_mb=0` の意味確定**: v2 の「0=最大 degrade 強制でシンボル全滅」は spec §10.4 逸脱＋PRD 網羅性衝突だった。**v3: 0 は「最小メモリ＝来歴を即スピル・オートマトンを最大分割（いずれも出力透過）」＝網羅性は保持（indirect 不変）・PRD 無害**。spec §10.4 の MB スケール下端として自然・特別な「coverage を落とす」値ではない。小規模で決定的に spill/split を発火させる検証手段としても機能（空虚 PASS 排除）。
> - `graph_spilled` の発火点を engine 実コードで確定し spill テストで assert（v2 は未 assert・非実装可能だった）。spill_dir+unlimited→`_force_spill_threshold` の本番混入を削除（spill 透過性は Task2 unit＋memory 駆動 spill＋graph_spilled 観測で担保）。ripgrep に `-a`（`--text`）追加（バイナリ境界を walk の `_is_binary` 単一に統一＝rg 既定バイナリ skip 非対称を解消）。`scan_files=files` を Task8 コードに明示・`edge_count` 指示一本化・`prog.done()`/`estore.close()` 行位置特定・`automaton.scan_line` 昇順ユニーク契約の固定テスト追加・複数 keyword diagnostics 決定性テスト追加。

**Goal:** Phase 2a の正しさ・決定性コアの**出力を一切変えずに**、spec §8.2 の資源設計—ストリーミング走査（全 bytes 親常駐の廃止）／keyword 横断 walk 一回化／任意 `ripgrep` 一次粗フィルタ／`--memory-limit` 会計と degrade（**来歴グラフのディスクスピル→オートマトン分割多パス・最大パス上限**。いずれも出力透過＝網羅性保持）／`--progress` 標準エラー進捗—を実装する。シンボル集合の決定的切り捨ては Phase 2a の §8.3 `max_symbols` キャップ（不変・唯一の出力変更）が引き続き担う。

**Architecture:** Phase 1.5 決定的コア（dispatch/classifiers/model/tsv/diagnostics/encoding/ingest/proc_preprocess）と Phase 2a の chase/stoplist/automaton/provenance/classify/**`_apply_global_cap`（priority-1=§8.3 キャップ）は不変**。新規 `budget.py`（決定的メモリ近似）／`spill.py`（来歴エッジのディスクスピル＝priority-2）／`ripgrep.py`（任意一次フィルタ）／`progress.py`（標準エラー進捗）。`walk.py` に `collect_files`。`fixedpoint.py` をストリーミング走査＋memory 駆動スピル＋最終手段分割＋進捗フックに拡張（既定/非 degrade 経路は Phase 2a 逐語保持）。`pipeline.py` は keyword ループ前に一度 `collect_files` し共有。`cli.py` に `--memory-limit`/`--use-ripgrep`/`--max-passes`/`--progress`。**60GB perf・`--resume`・diagnostics §10.3 縮約・規模分割 `partNN`・`requirements.lock`・`--output-encoding`/`--encoding-fallback` は Phase 3（範囲外）**。

**Tech Stack:** Python 3.12 / pytest / `pyahocorasick==2.1.0`（既存）/ 任意 `ripgrep`（外部バイナリ・`@pytest.mark.requires_ripgrep` 隔離・無くても他テスト緑）。設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v7・§9 は `07e81bb`、§8.1手順5 は `8c21227` 改訂後・spec が常に優先）、`.claude/skills/writing-tests.md`、`.claude/skills/coding-conventions.md` に従う（docstring/コメント・テスト名は日本語、古典学派+TDD、外部I/O境界＝ファイル/サブプロセスのみ本物）。

---

**不変条件（Phase 2b 全タスクの絶対前提・spec §9／Phase 2a 境界の継承）:**

- **Inv-1（既定出力不変）**: `memory_limit_mb=None`（既定）かつ `use_ripgrep=False` かつ `progress="off"` かつ `force_chunks=0` で TSV は Phase 2a と **byte 完全一致**。`diagnostics.txt` も **単一 keyword 入力では byte 完全一致**（既存 unit/integration/golden は全て単一 keyword＝既存 130 passed・14 golden は**全て byte 不変で緑**）。複数 keyword の `diagnostics.txt` は **walk 系カテゴリの重複行が dedup される差のみ**（Phase 2b 走査一回化の意図変化・退行ではない・既存テストは単一 keyword なので影響なし）。TSV は keyword 数に依らず常に byte 不変。
- **Inv-2（degrade の出力性質・v3 で単純化）**: **出力を変える degrade は priority-1（§8.3 シンボル集合キャップ）だけ**。これは Phase 2a の `_apply_global_cap`（`max_symbols`／`--min-specificity`／`--stoplist` による決定的切り捨て・Phase 2a と完全同一・**v3 で一切変更しない**・`--memory-limit` に非依存）。**`--memory-limit` が駆動する priority-2 来歴スピル・最終手段オートマトン分割は出力を1バイトも変えない透過変換**（網羅性＝indirect・chain を完全保持）。スピル＝`EdgeStore.sorted_unique()` が `sorted(set(edges))` と同一集合同一順序（Task2 unit で固定）。分割＝per-file 反復順を Phase 2a 単一オートマトンと**厳密同一の `(lineno, symbol)` キー**に正規化（Task8 で固定・`automaton.scan_line` の昇順ユニーク契約に依存＝別途固定テスト）。
- **Inv-3（決定性）**: `--jobs 1`/`N`、ストリーミング、`memory_limit` 有/無（0含む）、`force_chunks` 有/無、spill 有/無、ripgrep 有/無 のいずれの組合せでも、同一入力で 2 回実行すると TSV／diagnostics が byte 一致（複数 keyword 含む）。
- **Inv-4（進捗は stderr 専用）**: `--progress` 出力は標準エラー専用。TSV／`diagnostics.txt`／終了コードに一切影響しない。

各 Task の Step4 は必ず「当該テスト PASS」＋「`python -m pytest -q` 全 PASS・0 failed/0 error（Phase 2a 130 ＋ 本 Task 追加分。**既存 golden 14・既存 130 が byte 不変で緑**）」を要求。既存が1ケースでも動いたら **commit せず停止し構造を疑う**。

**型・シグネチャ契約（全タスク共通・不変。Self-Review 3 で串刺し）:**

- `walk.collect_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag) -> list[tuple[str, pathlib.Path]]`
- `budget.MemoryBudget(limit_mb: int | None)`: `.unlimited`（`None`）/ `.item_budget`（`None→0`・`N>=0→N*_ITEMS_PER_MB`）/ `.exceeded(n_items) -> bool`（`unlimited` 常 `False`／`item_budget` ちょうど可／超過 `True`。`0` は `item_budget 0`＝`n>=1` で超過＝スピル/分割を即発火するが**出力透過**＝網羅性保持）
- `budget.estimate_items(*, n_symbols, n_edges, n_intro) -> int`（決定的・RSS 非依存・単純和）
- `spill.serialize_edge(p,c)->str` / `spill.parse_edge(line)->tuple[Occurrence,Occurrence]`（制御文字エスケープで完全可逆）
- `spill.EdgeStore(spill_dir: pathlib.Path | None, budget)`: `.add(p,c)` / `.maybe_spill()` / `.in_memory_len() -> int`（メモリ常駐エッジ数・spill 後 0） / `.sorted_unique() -> Iterator[...]`（in-memory/spill いずれも `sorted(set(...))` 同一） / `.spilled: bool` / `.close()` / `._force_spill_threshold: int | None`（**Task2 unit 専用フック・本番経路から設定しない**）
- `ripgrep.available()->bool` / `ripgrep.prefilter(root, rel_to_abs: dict[str, pathlib.Path], symbols: list[str]) -> set[str] | None`（`rg -l -F -a --no-messages --no-ignore --hidden --no-require-git -f pat .` で symbols 部分文字列を含む rel の **walk 上位集合**。バイナリ境界は walk の `_is_binary` に統一＝rg は `-a` で全ファイル走査。rg 不在/失敗 `None`＝フィルタ無効＝全件）
- `progress.Progress(level, stream=None)`: `.start(total_files)` / `.hop(hop, n_symbols, scanned)` / `.done()`（`level!="on"` 無音・stderr のみ）
- `fixedpoint.EngineOptions` 追加フィールド（**末尾既定値付き**＝既存キーワード構築不変）: `memory_limit_mb: int | None = None`, `use_ripgrep: bool = False`, `max_passes: int = 8`, `progress: str = "off"`, `spill_dir: pathlib.Path | None = None`, `force_chunks: int = 0`
- `fixedpoint.run_fixedpoint(seed_hits, source_root, opts, diag, *, files: list[tuple[str, pathlib.Path]] | None = None) -> list[Hit]`
- `fixedpoint._scan_file(args)` の `args` は `(rel: str, abspath: str, sym_list: list[str], lang_map: dict)`（abspath＝ストリーミング）
- **`fixedpoint._apply_global_cap`（priority-1=§8.3 キャップ）は Phase 2a の実装を一切変更しない**（`--memory-limit` を参照しない）

**spec 解釈の明示（次レビューで再検証可能）:**

- **degrade ラダー（spec §8.2 厳密整合・v3 確定）**: spec §8.2「`--memory-limit` 超過時は (優先1) §8.3 の決定的シンボル切り捨て → (優先2) 来歴グラフのスピル → (最終手段) オートマトン分割」。**priority-1（§8.3 切り捨て）は本ツールでは `max_symbols`/`--min-specificity`/`--stoplist` による Phase 2a の常設キャップ（`_apply_global_cap`）が担い、これは `--memory-limit` の有無に関係なく常に適用される標準ガバナ**。`--memory-limit` 超過時の追加 degrade 応答は **priority-2 来歴グラフのスピル（`EdgeStore` をディスクへ＝メモリ常駐エッジを退避し圧を実際に解消）→ なお scan_syms が単一オートマトンに過大なら最終手段オートマトン分割（決定的 K 分割・`--max-passes` 上限）**。spill/split は最終 edges/intro 集合・走査ヒット集合を変えない＝**出力透過（spec §9 走査順非依存の継承）・網羅性保持**。「`--memory-limit` でシンボルを追加削除する」設計は v2 の spec §8.2 誤読として**廃止**（priority-1=§8.3 キャップは memory 非依存・唯一の出力変更）。
- **`memory_limit_mb` 意味（None/0/N）**: `None`＝無制限（既定・Phase 2a 同一）。`N>0`＝`N*_ITEMS_PER_MB` item 予算。`0`＝item 予算 0＝来歴を即スピル・オートマトンを最大分割（**いずれも出力透過＝indirect/chain を1件も落とさない**）。`0` は spec §10.4 の MB スケール下端（最小メモリで完走）であり「coverage を落とす特別値」ではない＝PRD 網羅性無害。テストは `0` で spill/split を任意小規模・決定的に発火させ観測点（`graph_spilled`/`automaton_split`）で空虚 PASS を構造排除する（symbol 切り捨ては `max_symbols` 小値で別途・Phase 2a パターン）。
- **メモリ近似は決定的近似**（spec §8.2「来歴グラフのメモリは --memory-limit の対象」）: 実 RSS は非決定的なので不採用。`estimate_items = n_symbols + n_edges + n_intro`（`n_edges` は **`estore.in_memory_len()`**＝スピル済は計上しない＝スピルが圧を実際に解消する）。`--memory-limit MB` は `N*_ITEMS_PER_MB`（`_ITEMS_PER_MB` 固定）へ決定的換算。同一入力＋同一 limit で同一 degrade 判断＝spec §9。実バイト厳密化は Phase 3 perf。
- **ripgrep は walk の上位集合フィルタ**（spec §8.2「任意 ripgrep 1次フィルタ」）: 追跡シンボルは ASCII 識別子（Phase 2a 既知境界）で UTF-8/CP932/latin-1 のいずれでも raw バイト上に同一バイト列で出現。`rg --no-ignore --hidden --no-require-git -a`（`-a`＝バイナリも走査＝rg 既定バイナリ skip を無効化し**バイナリ境界を walk の `_is_binary` 単一に統一**）で rg の対象を walk の上位集合に揃える。除外 rel は部分文字列すら持たず automaton（識別子境界）でも 0 ヒット確定＝出力不変。rg 不在は `None`＝フィルタ無効＝全件（既定 `use_ripgrep=False` でも全件＝Phase 2a 同一）。
- **差分走査の限定効果**（spec §8.2 L162 逐語「ファイル→該当行ローカリゼーション保持で省けるのは『**確定済みシンボルの再ヒット再走査**』のみ。『段数≠走査回数』はこの限定的効果を指す」）: Phase 2a は既に `scan_chase = {s for s in chase_active if s not in capped}` と active のみ走査・`chase_done` 非再投入＝**確定済シンボルの再走査は Phase 2a で構造的に既達**。よって loc 局所化は spec が要求する独立機能ではなく性能最適化の一手段にすぎず、Phase 2b の効果は「走査時の全 bytes 親常駐廃止（ストリーミング）」に限る（取りこぼしでない）。確定フェーズは対象ファイルを 1 回だけ abspath 全文デコード（per-rel キャッシュ＝Phase 2a `meta_of`/`line_cache` と命令同値・byte 同値）。
- **walk 一回化**: pipeline が全 keyword 前に一度 `collect_files`（走査・診断1回）し各 `run_fixedpoint(files=files)` へ共有。walk 系診断は keyword 数に依らず1回・file 集合は keyword 間同一＝TSV 決定性不変。複数 keyword で `diagnostics.txt` は walk 系重複行が dedup（意図変化・Inv-1。spec §10.3 一般縮約は Phase 3）。

---

## Task 0: 着手ゲート（Phase 2a 緑・ripgrep 任意性・コードなし）

- [ ] **Step 1: Phase 2a 全緑** — Run: `cd /workspaces/grep_helpers2 && python -m pytest -q` → `130 passed`（0 failed/0 error）。異なれば着手しない。
- [ ] **Step 2: Phase 2a 完了記録の存在** — Run: `grep -nF '## Phase 2a 完了記録' docs/superpowers/plans/phase0-gate-result.md` → 1 行ヒット。**ヒット0なら Phase 2a 未完了＝着手不可で停止**（Step1 と二重ゲート）。
- [ ] **Step 3: ripgrep 任意性確認** — Run: `python -c "import shutil; print(shutil.which('rg'))"`。`None` でも着手可（`--use-ripgrep` 任意・既定無効・`requires_ripgrep` で隔離）。**注: `shutil.which('rg')` が None の環境では ripgrep 経路テストは skip され未検証となる＝CI 等 rg 実体のある環境で `requires_ripgrep` を別途必ず実行すること（Task11 受入条件）**。新規必須依存なし。
- [ ] **Step 4: ゲート記録しコミット** — `phase0-gate-result.md` 末尾に「## Phase 2b 着手ゲート記録」（UTC・`130 passed`・Phase 2a 完了参照・`shutil.which('rg')` 値と任意性・rg 経路は当該環境では skip 注記・新規必須依存なし・判定 PASS）追記。
```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2b 着手ゲート記録（130 passed / Phase 2a 完了 / ripgrep 任意）"
```

---

## Task 1: 決定的メモリ近似 `budget.py`

**Files:** Create `src/grep_analyzer/budget.py` / Test `tests/unit/test_budget.py`

spec §8.2。実 RSS 非依存の決定的近似。`memory_limit_mb`: `None`=無制限／`0`=item 予算0（来歴を即スピル・最大分割＝**出力透過**）／`N>0`=`N*_ITEMS_PER_MB`。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_budget.py` 新規:
```python
"""決定的メモリ近似の仕様（spec §8.2・degrade トリガの決定性）。"""

from grep_analyzer.budget import MemoryBudget, estimate_items


def test_estimate_itemsは各要素数の単純和():
    assert estimate_items(n_symbols=3, n_edges=10, n_intro=4) == 17
    assert estimate_items(n_symbols=0, n_edges=0, n_intro=0) == 0


def test_Noneは無制限で超過しない():
    b = MemoryBudget(None)
    assert b.unlimited is True and b.exceeded(10**9) is False


def test_0はitem予算0で1件以上超過():
    b = MemoryBudget(0)
    assert b.unlimited is False and b.item_budget == 0
    assert b.exceeded(0) is False and b.exceeded(1) is True


def test_N_MBは決定的換算で上限ちょうどは可超過はTrue():
    b = MemoryBudget(1)
    assert b.unlimited is False
    assert b.item_budget == MemoryBudget(1).item_budget
    assert b.exceeded(b.item_budget) is False
    assert b.exceeded(b.item_budget + 1) is True


def test_予算は単調():
    assert MemoryBudget(2).item_budget > MemoryBudget(1).item_budget >= MemoryBudget(0).item_budget
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_budget.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/budget.py` 新規:
```python
"""決定的メモリ近似（spec §8.2）。RSS でなくアイテム数の決定的近似で

来歴グラフ等のメモリを見積もり、--memory-limit を degrade（スピル/分割）の
決定的トリガに換算する。同一入力・同一 limit で同一判断＝spec §9 決定性。
"""

# 1 MB あたりの近似アイテム上限（固定定数＝決定的換算）。実バイト厳密性は
# Phase 3 perf の領分。本定数は degrade 発火の決定的トリガとしてのみ機能。
_ITEMS_PER_MB = 4096


def estimate_items(*, n_symbols: int, n_edges: int, n_intro: int) -> int:
    """来歴グラフ常駐の決定的アイテム近似（各概念1件＝固定重み）。

    n_edges はメモリ常駐エッジ数（スピル済は計上しない＝スピルが圧を解消）。
    """
    return n_symbols + n_edges + n_intro


class MemoryBudget:
    """--memory-limit(MB) を決定的 item 予算へ換算し超過判定する。

    None=無制限／0=item予算0（来歴を即スピル・最大分割＝出力透過で網羅性
    保持）／N>0=N*_ITEMS_PER_MB。
    """

    def __init__(self, limit_mb: int | None) -> None:
        self.unlimited = limit_mb is None
        self.item_budget = 0 if limit_mb is None else limit_mb * _ITEMS_PER_MB

    def exceeded(self, n_items: int) -> bool:
        """予算超過か（無制限は常に False・上限ちょうどは可）。"""
        if self.unlimited:
            return False
        return n_items > self.item_budget
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_budget.py -q` → PASS（5本）／`python -m pytest -q` → 全 PASS（130＋5）・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/budget.py tests/unit/test_budget.py
git commit -m "feat(budget): 決定的メモリ近似と--memory-limit換算（spec §8.2）"
```

---

## Task 2: 来歴エッジのディスクスピル `spill.py`（priority-2・出力透過）

**Files:** Create `src/grep_analyzer/spill.py` / Test `tests/unit/test_spill.py`

spec §8.2 priority-2。予算内メモリ／超過でディスク追記スピル。`sorted_unique()` は in-memory/spill いずれでも `sorted(set(edges))` と同一（**出力透過**＝Inv-2）。`in_memory_len()` で常駐数を返し、`estimate_items` がスピル後 0 計上＝圧解消を反映。`_force_spill_threshold` は **本 unit 専用フック**（本番経路では設定しない）。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_spill.py` 新規:
```python
"""来歴エッジのディスクスピルの仕様（spec §8.2 priority-2・出力透過・決定的）。"""

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.provenance import Occurrence
from grep_analyzer.spill import EdgeStore, parse_edge, serialize_edge


def test_制御文字込みで完全往復可逆():
    p = Occurrence("A\tB\\x", "a\nb.c", 3)
    c = Occurrence("C", "d.c", 9)
    assert parse_edge(serialize_edge(p, c)) == (p, c)


def test_メモリ内sorted_uniqueはsorted_setと同一かつin_memory_len(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    e1 = (Occurrence("Q", "q.c", 2), Occurrence("H", "h.c", 9))
    e2 = (Occurrence("P", "p.c", 1), Occurrence("H", "h.c", 9))
    for p, c in [e1, e2, e1]:
        s.add(p, c)
    assert s.spilled is False and s.in_memory_len() == 3
    assert list(s.sorted_unique()) == sorted({e1, e2})
    s.close()


def test_強制スピルでも同一集合同一順序かつin_memory_len0(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    s._force_spill_threshold = 1
    edges = [(Occurrence(f"S{i}", f"s{i}.c", i), Occurrence("H", "h.c", 9))
             for i in (3, 1, 2, 1)]
    for p, c in edges:
        s.add(p, c)
    assert s.spilled is True and s.in_memory_len() == 0
    assert list(s.sorted_unique()) == sorted(set(edges))
    s.close()


def test_budget0は1件目でスピルし同一(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(0))
    e = (Occurrence("A", "a.c", 1), Occurrence("B", "b.c", 2))
    s.add(*e)
    assert s.spilled is True and s.in_memory_len() == 0
    assert list(s.sorted_unique()) == [e]
    s.close()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_spill.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/spill.py` 新規:
```python
"""来歴エッジのディスクスピル（spec §8.2 priority-2）。予算内メモリ・超過で

ディスク追記退避。sorted_unique は in-memory/spill いずれでも
sorted(set(edges)) と同一（出力透過・決定的）。in_memory_len はメモリ常駐数
（スピル後 0＝estimate_items にスピルが圧解消として反映される）。
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.provenance import Occurrence

_ESC = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"}
_UNESC = {"\\\\": "\\", "\\t": "\t", "\\n": "\n", "\\r": "\r"}


def _enc(s: str) -> str:
    return "".join(_ESC.get(ch, ch) for ch in s)


def _dec(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            two = s[i:i + 2]
            if two in _UNESC:
                out.append(_UNESC[two])
                i += 2
                continue
        out.append(s[i])
        i += 1
    return "".join(out)


def serialize_edge(p: Occurrence, c: Occurrence) -> str:
    """1 エッジを 6 フィールドのタブ区切り1行へ（制御文字エスケープ）。"""
    return "\t".join((_enc(p.symbol), _enc(p.relpath), str(p.lineno),
                      _enc(c.symbol), _enc(c.relpath), str(c.lineno)))


def parse_edge(line: str) -> tuple[Occurrence, Occurrence]:
    """serialize_edge の逆。完全可逆。"""
    f = line.rstrip("\n").split("\t")
    return (Occurrence(_dec(f[0]), _dec(f[1]), int(f[2])),
            Occurrence(_dec(f[3]), _dec(f[4]), int(f[5])))


class EdgeStore:
    """来歴エッジを予算内メモリ、超過でディスクへ退避して保持する。"""

    def __init__(self, spill_dir: Path | None, budget) -> None:
        self._mem: list[tuple[Occurrence, Occurrence]] = []
        self._budget = budget
        self._dir = Path(spill_dir) if spill_dir is not None else Path(tempfile.gettempdir())
        self._fh = None
        self._path: Path | None = None
        self.spilled = False
        self._force_spill_threshold: int | None = None  # Task2 unit 専用

    def add(self, p: Occurrence, c: Occurrence) -> None:
        """1 エッジ追加。予算/フック超過で以降スピルへ。"""
        if self.spilled:
            self._fh.write(serialize_edge(p, c) + "\n")
            return
        self._mem.append((p, c))
        self.maybe_spill()

    def in_memory_len(self) -> int:
        """メモリ常駐エッジ数（スピル後は 0）。"""
        return 0 if self.spilled else len(self._mem)

    def maybe_spill(self) -> None:
        """予算/フック超過ならメモリ内容を一時ファイルへ退避。"""
        if self.spilled:
            return
        thr = self._force_spill_threshold
        over = (thr is not None and len(self._mem) >= thr) or \
               self._budget.exceeded(len(self._mem))
        if not over:
            return
        fd, p = tempfile.mkstemp(dir=str(self._dir), prefix="ga_edges_", suffix=".tsv")
        self._path = Path(p)
        self._fh = os.fdopen(fd, "w", encoding="utf-8")
        for pp, cc in self._mem:
            self._fh.write(serialize_edge(pp, cc) + "\n")
        self._mem = []
        self.spilled = True

    def sorted_unique(self) -> Iterator[tuple[Occurrence, Occurrence]]:
        """sorted(set(edges)) と同一順序・同一集合（出力透過・決定的）。"""
        if not self.spilled:
            yield from sorted(set(self._mem))
            return
        self._fh.flush()
        seen: set[tuple[Occurrence, Occurrence]] = set()
        with open(self._path, encoding="utf-8") as r:
            for line in r:
                if line.strip():
                    seen.add(parse_edge(line))
        yield from sorted(seen)

    def close(self) -> None:
        """一時ファイルを閉じ削除する（確定ループ完了後に呼ぶ）。"""
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        if self._path is not None and self._path.exists():
            self._path.unlink()
            self._path = None
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_spill.py -q` → PASS（4本）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/spill.py tests/unit/test_spill.py
git commit -m "feat(spill): 来歴エッジのディスクスピル（spec §8.2 priority-2・出力透過）"
```

---

## Task 3: 任意 ripgrep 一次フィルタ `ripgrep.py`（walk 上位集合・-a でバイナリ境界統一）

**Files:** Create `src/grep_analyzer/ripgrep.py` / Test `tests/unit/test_ripgrep.py` / Modify `tests/conftest.py`

spec §8.2。`rg -l -F -a --no-messages --no-ignore --hidden --no-require-git -f pat .` で **walk 上位集合**（`.gitignore`/隠し/バイナリを除外しない＝バイナリ境界は walk の `_is_binary` 単一＝C4 完全根治）。rg 不在/失敗は `None`。

- [ ] **Step 1: マーカ登録（conftest）＋失敗テスト**

`tests/conftest.py` 末尾に追記（既存 `sys.path.insert` は不変）:
```python
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "requires_ripgrep: 実 ripgrep を要する（無ければ skip）")


def pytest_collection_modifyitems(config, items):
    import shutil
    if shutil.which("rg") is not None:
        return
    skip = pytest.mark.skip(reason="ripgrep 不在のため skip（任意機能）")
    for item in items:
        if "requires_ripgrep" in item.keywords:
            item.add_marker(skip)
```

`tests/unit/test_ripgrep.py` 新規:
```python
"""任意 ripgrep 一次フィルタの仕様（spec §8.2・walk 上位集合・出力保存）。"""

from pathlib import Path

import pytest

from grep_analyzer.ripgrep import available, prefilter


def test_利用不可時はNoneでフィルタ無効(monkeypatch):
    monkeypatch.setattr("grep_analyzer.ripgrep._RG", None)
    assert available() is False
    assert prefilter(Path("."), {}, ["CODE"]) is None


@pytest.mark.requires_ripgrep
def test_部分文字列を含むrelの上位集合を返す(tmp_path):
    (tmp_path / "a.c").write_text("int CODE = 1;\n", "utf-8")
    (tmp_path / "b.c").write_text("int other = 2;\n", "utf-8")
    (tmp_path / "c.c").write_text("// DECODE\n", "utf-8")
    rel_abs = {p.name: p for p in tmp_path.glob("*.c")}
    got = prefilter(tmp_path, rel_abs, ["CODE"])
    assert "a.c" in got and "c.c" in got and "b.c" not in got


@pytest.mark.requires_ripgrep
def test_gitignore隠しバイナリ様も上位集合に含む(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.c\n", "utf-8")
    (tmp_path / "ignored.c").write_text("int CODE=1;\n", "utf-8")
    (tmp_path / ".hidden.c").write_text("int CODE=2;\n", "utf-8")
    (tmp_path / "nul.c").write_bytes(b"int CODE=3;\n\x00trailer\n")  # NUL 含み
    (tmp_path / "visible.c").write_text("int CODE=4;\n", "utf-8")
    rel_abs = {n: tmp_path / n for n in
               ("ignored.c", ".hidden.c", "nul.c", "visible.c")}
    got = prefilter(tmp_path, rel_abs, ["CODE"])
    assert {"ignored.c", ".hidden.c", "nul.c", "visible.c"} <= got  # 全て上位集合


@pytest.mark.requires_ripgrep
def test_空シンボルは空集合(tmp_path):
    assert prefilter(tmp_path, {}, []) == set()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_ripgrep.py -q` → FAIL（ModuleNotFound・rg 無環境では requires_ripgrep 3本 skip）

- [ ] **Step 3: 実装** — `src/grep_analyzer/ripgrep.py` 新規:
```python
"""任意 ripgrep 一次粗フィルタ（spec §8.2）。walk の上位集合（.gitignore/

隠し/バイナリを除外しない＝バイナリ境界は walk の _is_binary 単一）。rg
不在/失敗は None＝フィルタ無効（全件走査）。出力不変（除外 rel は部分
文字列すら持たず automaton 0 ヒット確定）。
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

_RG = shutil.which("rg")


def available() -> bool:
    """実 ripgrep バイナリが利用可能か。"""
    return _RG is not None


def prefilter(
    root: Path, rel_to_abs: dict[str, Path], symbols: list[str]
) -> set[str] | None:
    """symbols のいずれかの部分文字列を含む rel 集合（walk 上位集合）を返す。

    rg 不在/失敗は None（呼出側はフィルタ無効＝全 rel 走査）。symbols 空は空集合。
    -a で rg のバイナリ skip を無効化し walk の _is_binary を唯一の境界に統一。
    """
    if _RG is None:
        return None
    if not symbols:
        return set()
    with tempfile.NamedTemporaryFile("w", suffix=".pat", delete=False,
                                     encoding="utf-8") as pf:
        pf.write("\n".join(symbols))
        pat_path = pf.name
    try:
        proc = subprocess.run(
            [_RG, "-l", "-F", "-a", "--no-messages", "--no-ignore", "--hidden",
             "--no-require-git", "-f", pat_path, "."],
            cwd=str(root), capture_output=True, text=True, check=False)
    except OSError:
        Path(pat_path).unlink(missing_ok=True)
        return None
    Path(pat_path).unlink(missing_ok=True)
    if proc.returncode not in (0, 1):
        return None
    hit = set()
    for ln in proc.stdout.splitlines():
        rel = ln[2:] if ln.startswith("./") else ln
        if rel in rel_to_abs:
            hit.add(rel)
    return hit
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_ripgrep.py -q`（rg 有: 4本 PASS／rg 無: 1本＋3 skip）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/ripgrep.py tests/unit/test_ripgrep.py tests/conftest.py
git commit -m "feat(ripgrep): 任意一次フィルタ（walk上位集合・-aでバイナリ境界統一・spec §8.2）"
```

---

## Task 4: 標準エラー進捗 `progress.py`

**Files:** Create `src/grep_analyzer/progress.py` / Test `tests/unit/test_progress.py`

spec §8.2。`level=="on"` 以外完全無音。stderr 専用（Inv-4）。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_progress.py` 新規:
```python
"""標準エラー進捗の仕様（spec §8.2・stderr 専用・off 無音）。"""

import io

from grep_analyzer.progress import Progress


def test_offは完全無音():
    buf = io.StringIO()
    p = Progress("off", buf)
    p.start(10); p.hop(1, 5, 3); p.done()
    assert buf.getvalue() == ""


def test_onは各局面でstderrへ構造化出力():
    buf = io.StringIO()
    p = Progress("on", buf)
    p.start(2); p.hop(1, 4, 2); p.done()
    o = buf.getvalue()
    assert "files=2" in o and "hop=1" in o and "symbols=4" in o
    assert "scanned=2" in o and "done" in o


def test_未知levelはoff扱いで無音():
    buf = io.StringIO()
    Progress("verbose-unknown", buf).hop(1, 1, 1)
    assert buf.getvalue() == ""
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_progress.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/progress.py` 新規:
```python
"""標準エラー進捗（spec §8.2）。level=="on" 以外は完全無音。注入された

stream（既定 sys.stderr）専用で TSV/diagnostics/終了コードに無影響。
"""

import sys


class Progress:
    """走査進捗を stderr へ出す（off/未知 level は無音）。"""

    def __init__(self, level: str, stream=None) -> None:
        self._on = level == "on"
        self._stream = stream if stream is not None else sys.stderr
        self._total = 0

    def start(self, total_files: int) -> None:
        """走査開始（総ファイル数）。"""
        self._total = total_files
        if self._on:
            print(f"[grep_analyzer] start files={total_files}",
                  file=self._stream, flush=True)

    def hop(self, hop: int, n_symbols: int, scanned: int) -> None:
        """1 ホップ進捗。"""
        if self._on:
            print(f"[grep_analyzer] hop={hop} symbols={n_symbols} "
                  f"scanned={scanned}/{self._total}", file=self._stream, flush=True)

    def done(self) -> None:
        """走査完了。"""
        if self._on:
            print("[grep_analyzer] done", file=self._stream, flush=True)
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_progress.py -q` → PASS（3本）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/progress.py tests/unit/test_progress.py
git commit -m "feat(progress): 標準エラー進捗（spec §8.2・stderr専用・off無音）"
```

---

## Task 5: walk 一回 materialize `walk.collect_files`

**Files:** Modify `src/grep_analyzer/walk.py` / Test `tests/unit/test_walk.py`

`walk_files`（generator・既存不変）を一度 materialize する `collect_files`。pipeline が全 keyword 前に1回呼ぶ＝walk 診断重複解消の基盤（Task 9 配線）。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_walk.py` 末尾に追記:
```python
from grep_analyzer.walk import collect_files


def test_collect_filesは走査一度materializeしrelpath昇順(tmp_path):
    (tmp_path / "b.c").write_text("x", "utf-8")
    (tmp_path / "a.c").write_text("y", "utf-8")
    diag = Diagnostics()
    got = collect_files(tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
                        follow_symlinks=False, max_file_bytes=1_000_000, diag=diag)
    assert [r for r, _ in got] == ["a.c", "b.c"]
    assert all(hasattr(p, "is_file") for _, p in got)


def test_collect_filesの診断は一回だけ(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "G.c").write_text("x", "utf-8")
    (tmp_path / "k.c").write_text("y", "utf-8")
    d = Diagnostics()
    collect_files(tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
                  follow_symlinks=False, max_file_bytes=1_000_000, diag=d)
    assert d.render().count("walk_excluded\tbuild/G.c") == 1
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_walk.py -q` → FAIL（ImportError collect_files）

- [ ] **Step 3: 実装** — `src/grep_analyzer/walk.py` 末尾に追記:
```python
def collect_files(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics,
) -> list[tuple[str, Path]]:
    """walk_files を一度だけ materialize し relpath 昇順の list を返す。

    走査・診断は1回（pipeline が keyword 横断で共有＝診断重複解消・§8.2）。
    """
    return list(walk_files(
        root, include=include, exclude=exclude, follow_symlinks=follow_symlinks,
        max_file_bytes=max_file_bytes, diag=diag))
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_walk.py -q` → PASS（既存5＋新規2）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/walk.py tests/unit/test_walk.py
git commit -m "feat(walk): collect_files で走査一回materialize（spec §8.2基盤）"
```

---

## Task 6: fixedpoint ストリーミング走査（bytes 親常駐廃止・確定は全文1回読み・出力不変）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

`files: list[(rel, bytes)]`（全 bytes 親常駐）を `files: list[(rel, abspath)]` に変え `_scan_file` がワーカ内で abspath を読む（ストリーミング）。**確定フェーズは abspath から全文1回デコードし per-rel キャッシュ**（Phase 2a `meta_of`/`line_cache` と命令同値・byte 同値）。`run_fixedpoint` に `*, files=None`（後方互換）。**本 Task は `EngineOptions`/`_opts`/`_apply_global_cap` を変更しない**（新フィールド・degrade は Task7/8。Task6 新テストは `_opts()`（既存11フィールド）＋`files=` のみ使用）。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_fixedpoint.py` 末尾に追記:
```python
def test_ストリーミング化後も多ホップ出力はPhase2aと同一(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    chains = {(h.file, h.via_symbol): h.chain
              for h in run_fixedpoint([seed], src, _opts(), Diagnostics())}
    assert chains[("B.java", "K1")] == "K1@A.java:1 -> K1@B.java:1"
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"


def test_多行構文の分類が確定全文読みでPhase2aと同一(tmp_path):
    # 多行 if（chase ヒット行と分類決定構文が別行・空行・末尾改行あり）
    src = _mk(tmp_path, {
        "A.java": "class A{ static final int K1 = 1; }\n",
        "B.java": "class B {\n  void m(int s) {\n    if (s ==\n        K1) {\n"
                  "      return;\n    }\n  }\n}\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(), Diagnostics())
    b = next(h for h in hits if h.file == "B.java")
    assert b.category == "比較" and b.confidence == "high"


def test_事前収集filesでも内部walkと同一(tmp_path):
    from grep_analyzer.walk import DEFAULT_EXCLUDE, collect_files
    src = _mk(tmp_path, {"C.java": 'class C { static final String S_OK = "x"; }\n',
                         "U.java": "class U { String x = S_OK; }\n"})
    seed = _seed("S_OK", "java", "C.java", 1, 'static final String S_OK = "x";')
    a = run_fixedpoint([seed], src, _opts(), Diagnostics())
    files = collect_files(src, include=[], exclude=list(DEFAULT_EXCLUDE),
                          follow_symlinks=False, max_file_bytes=1_000_000,
                          diag=Diagnostics())
    b = run_fixedpoint([seed], src, _opts(), Diagnostics(), files=files)
    k = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    assert a and sorted(map(k, a)) == sorted(map(k, b))
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → `test_事前収集files…` FAIL（`unexpected keyword argument 'files'`）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) `_scan_file` を abspath 読込に置換:
```python
def _scan_file(args):
    """1 ファイルをワーカ内で読み走査しヒット素片を返す純関数。

    ストリーミング化＝親に bytes 非常駐・abspath から読む（spec §8.2）。
    automaton 走査は raw 行（マスク非対称根拠）。出力は Phase 2a と byte 不変。
    """
    rel, abspath, sym_list, lang_map = args
    raw = Path(abspath).read_bytes()
    text, enc, replaced, language, dialect = _file_meta(rel, raw, lang_map)
    au = automaton.build(sym_list)
    found = []
    if au is not None:
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(au, line):
                found.append((sym, i, line))
    return rel, enc, replaced, language, dialect, found
```

(2) `run_fixedpoint` シグネチャを `def run_fixedpoint(seed_hits, source_root, opts, diag, *, files=None):` に変更し docstring 追記。Phase 2a 実コードの `files: list[tuple[str, bytes]] = [ (rel, abspath.read_bytes()) ... walk.walk_files(...) ]` ブロック（**seed ループ後・`_apply_global_cap` 定義の直前**にある当該1ブロック）を次へ置換:
```python
    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    rel_to_abs = {rel: abspath for rel, abspath in files}
```

(3) 走査ループの `args` を abspath（str）に: `args = [(rel, str(abspath), scan_syms, opts.lang_map) for rel, abspath in files]`

(4) 確定フェーズの `raw_of = dict(files)` 行と再読込ブロックを次へ置換（**全文1回デコード・per-rel キャッシュ・再構成なし・Phase 2a byte 同値**）:
```python
    indirect: list[Hit] = []
    seen: set[Occurrence] = set()
    line_cache: dict[str, list[str]] = {}
    meta_of: dict[str, tuple[str, str, str]] = {}
    for _, c in sorted(set(edges)):
        if c in seen or c.symbol not in (chase_done | term_done):
            continue
        if graph.is_seed_location(c.relpath, c.lineno):
            continue
        seen.add(c)
        if c.relpath not in line_cache:
            raw = rel_to_abs[c.relpath].read_bytes() if c.relpath in rel_to_abs else b""
            text, enc, replaced, lang, dia = _file_meta(c.relpath, raw, opts.lang_map)
            line_cache[c.relpath] = text.split("\n")
            meta_of[c.relpath] = (text, lang, dia)
            enc_of.setdefault(c.relpath, (enc, replaced))
        text, language, dialect = meta_of[c.relpath]
        lines = line_cache[c.relpath]
        line = lines[c.lineno - 1] if 0 <= c.lineno - 1 < len(lines) else ""
        kind = sym_kind.get(c.symbol, "var")
        cat, conf = classify_hit(language, dialect, text, c.lineno, line)
        if kind in ("getter", "setter"):
            conf = "low"
        enc, replaced = enc_of.get(c.relpath, ("utf-8", False))
        for chain in graph.chains_to(c, max_depth=opts.max_depth,
                                     max_paths=opts.max_paths, diag=diag):
            indirect.append(Hit(
                keyword=keyword, language=language, file=c.relpath, lineno=c.lineno,
                ref_kind=_REF_KIND[kind], category=cat, category_sub="",
                usage_summary=f"{cat} ({language})", via_symbol=c.symbol,
                chain=chain, snippet=line,
                encoding=enc + (" 要確認" if replaced else ""), confidence=conf))
    return indirect
```

> **実装注（C1 根治・出力 byte 不変）:** 確定フェーズは Phase 2a と**同一ロジック**（`meta_of`/`line_cache`/`classify_hit(language,dialect,text=全文,...)`）。差分は bytes 取得元が `raw_of=dict(files)`（親常駐）→ `rel_to_abs[rel].read_bytes()`（abspath 1回読み）だけ＝デコード結果・AST・分類・chain が Phase 2a と**同値**。v1 の `loc_cache` 再構成は完全廃止。ストリーミングの実効果は「走査中に全 bytes を親に常駐させない」点に限る（spec §8.2 差分走査の誠実化どおり）。

- [ ] **Step 4: 通る（出力保存の回帰が要）** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存8＋新規3。特に `test_多行構文…`＝C1 回帰）／`python -m pytest -q` → **全 PASS・既存 golden 14・既存 integration byte 不変**。動いたら commit せず停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): ストリーミング走査＋確定全文1回読み（spec §8.2・C1根治・出力不変）"
```

---

## Task 7: degrade priority-2＝memory 駆動の来歴スピル（出力透過・priority-1 は不変）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.2 priority-2。**priority-1（`_apply_global_cap`＝§8.3 `max_symbols` キャップ）は Phase 2a を一切変更しない**（memory 非依存・唯一の出力変更・既定で Phase 2a 同一）。`--memory-limit` 超過時は `edges` リストを `EdgeStore` 化し**ディスクスピル**（来歴グラフのメモリを退避＝圧を実際に解消・`in_memory_len()` を `estimate_items` に反映）。スピルは `sorted_unique()=sorted(set())` で **出力透過**（網羅性＝indirect/chain を1件も落とさない）。`graph_spilled` を engine 実コードの確定点で記録。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_fixedpoint.py` 冒頭 `_opts` を新フィールド既定込みに更新（既存呼出不変）:
```python
def _opts(**kw):
    base = dict(max_depth=5, min_specificity=2, stoplist_path=None, lang_map={},
                include=[], exclude=[], jobs=1, follow_symlinks=False,
                max_file_bytes=1_000_000, max_symbols=1000, max_paths=100,
                memory_limit_mb=None, use_ripgrep=False, max_passes=8,
                progress="off", spill_dir=None, force_chunks=0)
    base.update(kw)
    return EngineOptions(**base)
```
末尾に追記:
```python
def test_memory_limit0で来歴スピルしても出力はPhase2aと同一(tmp_path):
    # priority-2 spill 透過性: memory 0 で即スピル・indirect は1件も落ちない
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1=1; }\n",
                         "B.java": "class B{ static final int K2=K1; }\n",
                         "C.java": "class C{ int z2=K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1=1;")
    k = lambda hs: sorted((h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
                          for h in hs)
    base = run_fixedpoint([seed], src, _opts(), Diagnostics())
    diag = Diagnostics()
    sp = run_fixedpoint([seed], src,
                        _opts(memory_limit_mb=0, spill_dir=tmp_path), diag)
    assert base and k(base) == k(sp)               # 出力透過（網羅性保持）
    assert "graph_spilled" in diag.render()        # スピル実発火（非空虚）


def test_memory_limit0は2回実行で決定的(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1=1; }\n",
                         "B.java": "class B{ int z=K1; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1=1;")
    k = lambda hs: sorted((h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
                          for h in hs)
    r1 = run_fixedpoint([seed], src, _opts(memory_limit_mb=0, spill_dir=tmp_path),
                        Diagnostics())
    r2 = run_fixedpoint([seed], src, _opts(memory_limit_mb=0, spill_dir=tmp_path),
                        Diagnostics())
    assert k(r1) == k(r2)


def test_memory_limit_Noneは無制限でPhase2aと同一_priority1不変(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    chains = {(h.file, h.via_symbol): h.chain
              for h in run_fixedpoint([seed], src,
                                      _opts(memory_limit_mb=None), Diagnostics())}
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"


def test_max_symbolsキャップは従来通り出力変更（priority1不変の回帰）(tmp_path):
    # priority-1 は Phase 2a のまま＝max_symbols で決定的に切り捨て（memory 非依存）
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=1; }\n",
                         "B.java": "class B{ int zz=aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    diag = Diagnostics()
    run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=1), diag)
    assert "symbol_rejected\tcapped" in diag.render()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → FAIL（`EngineOptions … unexpected keyword argument 'memory_limit_mb'`）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) `EngineOptions` に末尾既定フィールド追加（既存キーワード構築不変・非既定11→既定6＝dataclass 制約充足）:
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
```

(2) import 追加（先頭 import 群）:
```python
from grep_analyzer.budget import MemoryBudget, estimate_items
from grep_analyzer.spill import EdgeStore
```

(3) `run_fixedpoint` 内 `policy = ...` 直後に budget 構築:
```python
    budget = MemoryBudget(opts.memory_limit_mb)
```

(4) 状態初期化群の `edges: list[tuple[Occurrence, Occurrence]] = []` を `EdgeStore` に置換し `spill_logged` を併設:
```python
    estore = EdgeStore(opts.spill_dir, budget)
    spill_logged = False
```
エッジ追加箇所（Phase 2a の `edges.append((parent, child))`）を `estore.add(parent, child)` に置換。

(5) **`_apply_global_cap` は変更しない**（Phase 2a の `max_symbols` キャップ＝priority-1・memory 非依存）。走査ループ各反復の**先頭**（`_apply_global_cap()` 呼出の直後）に **memory 駆動スピル（priority-2）** を追加:
```python
        if not budget.unlimited:
            n_intro = sum(len(v) for v in intro.values())
            n_live = len(chase_active | chase_done | term_active | term_done)
            if budget.exceeded(estimate_items(
                    n_symbols=n_live, n_edges=estore.in_memory_len(),
                    n_intro=n_intro)) and not estore.spilled:
                estore.maybe_spill_now()
                if estore.spilled and not spill_logged:
                    diag.add("graph_spilled", f"hop={hop}")
                    spill_logged = True
```
`EdgeStore` に強制スピル公開メソッドを `spill.py` へ追加（Task2 のクラス末尾に・本 Task で追記）:
```python
    def maybe_spill_now(self) -> None:
        """予算判定に依らず即スピルする（engine の priority-2 駆動用）。"""
        if self.spilled:
            return
        self._force_spill_threshold = 0
        self.maybe_spill()
```

(6) グラフ構築 `for p, c in edges:` を `for p, c in estore.sorted_unique():` に、確定ループ `for _, c in sorted(set(edges)):`（Task6 で置換済の確定ブロック先頭）を `for _, c in estore.sorted_unique():` に置換（`sorted_unique` は `sorted(set())` 同値＝child 単位走査は従来同様）。**確定ループ完了後・`return indirect` の直前**に `estore.close()` を置く。

> **実装注（spec §8.2 整合・出力透過・staged-invariant 廃止）:** priority-1（§8.3 シンボルキャップ＝`_apply_global_cap`）は Phase 2a を**1行も変えない**＝`--memory-limit` でシンボルを追加削除しない（v2 誤読の根治・staged-invariant 概念は存在しない）。`--memory-limit` 超過の degrade 応答は priority-2 来歴スピルのみ（最終手段分割は Task8）。スピルは `EdgeStore.sorted_unique()=sorted(set(edges))` で `graph`/確定が順序非依存＝**indirect/chain を1件も落とさない出力透過**（網羅性保持・PRD 無害）。`in_memory_len()` がスピル後 0 を返すので `estimate_items` の `n_edges` が圧解消を反映し、優先1 を侵食しない。`memory_limit_mb=None` で `budget.unlimited`＝本ブロックは丸ごと no-op＝Phase 2a 完全同一（既存 golden 14・既存 130 不変）。`graph_spilled` は engine 確定点（走査反復先頭でスピル遷移検出時1回）で記録＝spill テストで assert 可能（v2 の非実装可能指示を解消）。

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存11＋新規4。`test_memory_limit0で来歴スピルしても出力はPhase2aと同一`＝spill 透過＋`graph_spilled` 実発火・`test_max_symbolsキャップは従来通り…`＝priority-1 不変）／`python -m pytest -q` → **全 PASS・既存 golden 14 不変**（`memory_limit_mb=None` 既定で Phase 2a 同一）。動いたら停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py src/grep_analyzer/spill.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): degrade priority-2 memory駆動来歴スピル（spec §8.2・出力透過・priority1不変）"
```

---

## Task 8: degrade 最終手段＝オートマトン分割多パス（出力透過・C2 根治）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.2 最終手段。`scan_syms` が単一オートマトンに過大（または `force_chunks>1`）なら決定的 K 分割・K パス走査（`--max-passes` 上限）。**既定/非分割（nchunks==1）は Phase 2a の走査ループを逐語保持**（C2 根治）。分割時のみ集約し per-file 反復順を **Phase 2a 単一オートマトンと厳密同一の `(lineno, symbol)` キー**に正規化（証明: Phase 2a per-file 反復順＝行昇順×`automaton.scan_line` の昇順ユニーク＝`(lineno,symbol)` 昇順そのもの）。`force_chunks>1` は memory 非依存に分割強制（split 透過性の分離検証フック）。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_fixedpoint.py` 末尾に追記:
```python
def test_automatonのscan_lineは行内シンボル昇順ユニーク（分割正規化の前提固定）():
    # Task8 の (lineno,symbol) 正規化が Phase2a 反復順と一致する前提を直接固定
    from grep_analyzer.automaton import build, scan_line
    au = build(["AA", "BB", "CC"])
    assert scan_line(au, "BB CC AA AA BB") == ["AA", "BB", "CC"]


def test_force_chunks分割は単一オートマトンと出力byte同値(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int ZED=1; }\n",
                         "T.java": "class T{ static final int ABE=2; }\n",
                         "F.java": "class F{ static final int G1=ZED;"
                                   " static final int G2=ABE; int u=G1; int w=G2; }\n"})
    seeds = [_seed("ZED", "java", "A.java", 1, "static final int ZED=1;"),
             _seed("ABE", "java", "T.java", 1, "static final int ABE=2;")]
    k = lambda hs: sorted((h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
                          for h in hs)
    one = run_fixedpoint(seeds, src, _opts(), Diagnostics())
    diag = Diagnostics()
    many = run_fixedpoint(seeds, src, _opts(force_chunks=3), diag)
    assert one and k(one) == k(many)
    assert "automaton_split" in diag.render()


def test_memory_limit0は分割スピル併発でも出力透過かつ決定的(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1=1; }\n",
                         "B.java": "class B{ static final int K2=K1; }\n",
                         "C.java": "class C{ int z2=K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1=1;")
    k = lambda hs: sorted((h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
                          for h in hs)
    base = run_fixedpoint([seed], src, _opts(), Diagnostics())
    d1 = Diagnostics()
    r1 = run_fixedpoint([seed], src, _opts(memory_limit_mb=0, spill_dir=tmp_path,
                                           max_passes=8), d1)
    r2 = run_fixedpoint([seed], src, _opts(memory_limit_mb=0, spill_dir=tmp_path,
                                           max_passes=8), Diagnostics())
    assert k(base) == k(r1) == k(r2)              # 分割+スピル併発でも出力透過
    assert "graph_spilled" in d1.render()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → 新規3本 FAIL（force_chunks/分割未実装）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` の走査ループを「nchunks==1 は Phase 2a 逐語・nchunks>1 のみ集約」に変更。Task6/7 で `args=[...]; if jobs>1: pool.map else [...]; for rel,...,found in sorted(results,key=r[0]): (estore.add/_ingest...)` となっている走査ブロックを次へ置換:
```python
        scan_files = files  # Task9 で ripgrep 絞り込みに差し替え
        n_intro = sum(len(v) for v in intro.values())
        nchunks = 1
        if opts.force_chunks and opts.force_chunks > 1:
            nchunks = min(opts.force_chunks, opts.max_passes,
                          max(1, len(scan_syms)))
        elif not budget.unlimited and budget.exceeded(estimate_items(
                n_symbols=len(scan_syms), n_edges=estore.in_memory_len(),
                n_intro=n_intro)):
            while nchunks < opts.max_passes and budget.exceeded(estimate_items(
                    n_symbols=-(-len(scan_syms) // (nchunks + 1)),
                    n_edges=estore.in_memory_len(), n_intro=n_intro)):
                nchunks += 1
        if nchunks <= 1:
            args = [(rel, str(abspath), scan_syms, opts.lang_map)
                    for rel, abspath in scan_files]
            if opts.jobs > 1:
                with multiprocessing.Pool(opts.jobs) as pool:
                    results = pool.map(_scan_file, args)
            else:
                results = [_scan_file(a) for a in args]
            pass_results = sorted(results, key=lambda r: r[0])
        else:
            diag.add("automaton_split", f"hop={hop} chunks={nchunks}")
            size = -(-len(scan_syms) // nchunks)
            chunks = [scan_syms[i:i + size]
                      for i in range(0, len(scan_syms), size)] or [[]]
            agg: dict[str, list] = {}
            meta: dict[str, tuple] = {}
            for chunk in chunks:
                args = [(rel, str(abspath), chunk, opts.lang_map)
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
            enc_of.setdefault(rel, (enc, replaced))
            if replaced and rel not in replaced_logged:
                diag.add("decode_replaced", rel)
                replaced_logged.add(rel)
            for sym, i, line in found:
                if sym not in scan_chase and sym not in scan_term:
                    continue
                child = Occurrence(sym, rel, i)
                for parent in intro.get(sym, []):
                    if parent != child:
                        estore.add(parent, child)
                if sym in scan_term:
                    if sym not in no_expand_logged:
                        diag.add("getter_setter_no_expand", sym)
                        no_expand_logged.add(sym)
                    continue
                _ingest(child, language, dialect, line, hop + 1)
        hop += 1
```

> **実装注（C2 根治・出力透過の証明・max_passes 閉路）:** `nchunks==1`（既定 `memory_limit_mb=None`／`force_chunks=0`）は Phase 2a 走査ループと**逐語同一**（`sorted(results,key=r[0])`→各 rel の found は `_scan_file` 生成順＝行昇順×`scan_line` 昇順）。`nchunks>1` のときのみ `agg` 集約し `sorted(agg[rel], key=(t[1],t[0]))`＝**`(lineno,symbol)` 昇順**に正規化。`automaton.scan_line` は行内 symbol 昇順ユニーク（`test_automatonのscan_lineは…` で固定）なので Phase 2a の per-file 反復順＝`(lineno,symbol)` 昇順そのもの＝**`_ingest`/`intro`/`estore.add` 投入順が Phase 2a と同一＝`sym_kind/sym_hop` first-write-wins も同値＝出力 byte 同値**。`while nchunks < opts.max_passes` で上限頭打ち（上限到達後はそれ以上分割せず当該 nchunks で走査＝超過容認・決定的。spec §8.2「最大走査パス数の上限を実装計画で明示」＝`--max-passes` で形式充足。上限超過時に優先1 へ戻る挙動は本ツールでは priority-1=§8.3 常設キャップが既に各反復先頭で適用済＝追加配線不要）。スピル（Task7）と分割は独立に出力透過なので併発しても出力不変・決定的。

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存15＋新規3。`test_force_chunks分割は…byte同値`＝split 透過＋`automaton_split` 実発火・`test_automatonのscan_lineは…`＝正規化前提固定・`test_memory_limit0は分割スピル併発でも…`＝併発透過決定的）／`python -m pytest -q` → **全 PASS・既存 golden 14・既存 integration byte 不変**（既定 nchunks=1・estore 非スピル＝Phase 2a 逐語）。動いたら停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): degrade最終手段オートマトン分割多パス（spec §8.2・出力透過C2根治）"
```

---

## Task 9: pipeline 配線（walk 一回共有・進捗・ripgrep・CLI）

**Files:** Modify `src/grep_analyzer/pipeline.py` / Modify `src/grep_analyzer/cli.py` / Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/integration/test_pipeline_phase2b.py`

pipeline が全 keyword 前に `collect_files` で一度 walk し各 `run_fixedpoint(files=files)` へ共有（診断重複解消）。`run_fixedpoint` に進捗（`Progress`）と任意 ripgrep 一次フィルタ（`scan_files` を絞る・出力不変＝walk 上位集合）。`cli.py` に `--memory-limit`/`--use-ripgrep`/`--max-passes`/`--progress`。既定は Phase 2a 完全同一。

- [ ] **Step 1: 失敗するテスト** — `tests/integration/test_pipeline_phase2b.py` 新規:
```python
"""Phase 2b 配線の境界契約（spec §8.2・出力不変・診断重複解消）。in-process。"""

import io
from contextlib import redirect_stderr
from pathlib import Path

from grep_analyzer.cli import main


def _tree(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "C.java").write_text('class C { static final String S_OK = "x"; }\n', "utf-8")
    (src / "U.java").write_text("class U { String x = S_OK; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "S_OK.grep").write_text('C.java:1:static final String S_OK = "x";\n', "utf-8")
    (inp / "OTHER.grep").write_text('C.java:1:static final String S_OK = "x";\n', "utf-8")
    return src, inp


def test_既定オプションは決定的でindirectが出る(tmp_path: Path):
    src, inp = _tree(tmp_path)
    o1, o2 = tmp_path / "o1", tmp_path / "o2"
    assert main(["--input", str(inp), "--output", str(o1),
                 "--source-root", str(src)]) == 0
    main(["--input", str(inp), "--output", str(o2), "--source-root", str(src)])
    a = (o1 / "S_OK.tsv").read_text("utf-8-sig")
    assert "indirect:constant" in a and "S_OK@C.java:1 -> S_OK@U.java:1" in a
    assert a == (o2 / "S_OK.tsv").read_text("utf-8-sig")


def test_walk診断はkeyword数によらず重複しない(tmp_path: Path):
    src, inp = _tree(tmp_path)
    (src / "build").mkdir()
    (src / "build" / "G.java").write_text("class G{}\n", "utf-8")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    d = (out / "diagnostics.txt").read_text("utf-8")
    assert d.count("walk_excluded\tbuild/G.java") == 1


def test_progress_onはstderrのみでTSV不変(tmp_path: Path):
    src, inp = _tree(tmp_path)
    b = tmp_path / "b"; main(["--input", str(inp), "--output", str(b),
                              "--source-root", str(src)])
    p = tmp_path / "p"
    err = io.StringIO()
    with redirect_stderr(err):
        main(["--input", str(inp), "--output", str(p),
              "--source-root", str(src), "--progress", "on"])
    assert "[grep_analyzer]" in err.getvalue()
    assert (b / "S_OK.tsv").read_text("utf-8-sig") == \
           (p / "S_OK.tsv").read_text("utf-8-sig")


def test_memory_limit0でも出力透過_indirect保持(tmp_path: Path):
    src, inp = _tree(tmp_path)
    a = tmp_path / "a"; main(["--input", str(inp), "--output", str(a),
                              "--source-root", str(src)])
    b = tmp_path / "b"
    main(["--input", str(inp), "--output", str(b), "--source-root", str(src),
          "--memory-limit", "0", "--max-passes", "8"])
    assert (a / "S_OK.tsv").read_text("utf-8-sig") == \
           (b / "S_OK.tsv").read_text("utf-8-sig")  # memory0 でも byte 同値（透過）
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/integration/test_pipeline_phase2b.py -q` → FAIL（`--memory-limit`/`--progress` 未知 or walk_excluded 2回）

- [ ] **Step 3: 実装**

`src/grep_analyzer/fixedpoint.py`:
- import: `from grep_analyzer.progress import Progress` / `from grep_analyzer import ripgrep as _rg`
- `rel_to_abs = {...}`（Task6 (2)）構築の直後に **1 回だけ**: `prog = Progress(opts.progress); prog.start(len(files))`
- 走査ループ先頭の `scan_files = files`（Task8 (3) 冒頭）行を次へ差し替え:
```python
        scan_files = files
        if opts.use_ripgrep:
            keep = _rg.prefilter(source_root, rel_to_abs, scan_syms)
            if keep is not None:
                scan_files = [(r, a) for r, a in files if r in keep]
```
- 反復末尾 `hop += 1` の**直前**に `prog.hop(hop, len(scan_syms), len(scan_files))`。`while` ループ脱出後・**確定ループ完了後・`estore.close()` の直後・`return indirect` の直前**に `prog.done()`。

`src/grep_analyzer/pipeline.py`:
- import: `from grep_analyzer.walk import DEFAULT_EXCLUDE, collect_files`（既存 `DEFAULT_EXCLUDE` import と統合）
- `lang_map = opts.lang_map` 直後:
```python
    files = collect_files(
        Path(source_root), include=opts.include, exclude=opts.exclude,
        follow_symlinks=opts.follow_symlinks,
        max_file_bytes=opts.max_file_bytes, diag=diag)
```
- `indirect = run_fixedpoint(hits, Path(source_root), opts, diag)` →
  `indirect = run_fixedpoint(hits, Path(source_root), opts, diag, files=files)`

`src/grep_analyzer/cli.py`: `--max-paths` 引数直後に追記:
```python
    p.add_argument("--memory-limit", type=int, default=None, dest="memory_limit_mb")
    p.add_argument("--use-ripgrep", action="store_true", dest="use_ripgrep")
    p.add_argument("--max-passes", type=int, default=8, dest="max_passes")
    p.add_argument("--progress", default="off")
```
`EngineOptions(...)` 構築に追記: `memory_limit_mb=args.memory_limit_mb, use_ripgrep=args.use_ripgrep, max_passes=args.max_passes, progress=args.progress,`（`spill_dir`/`force_chunks` は CLI 非公開＝既定 None/0＝Phase 2a 同一）

- [ ] **Step 4: 通る（不変条件総点検）** — `python -m pytest tests/integration/test_pipeline_phase2b.py -q` → PASS（4本）／`python -m pytest -q` → **全 PASS・0 failed/0 error・既存 golden 14・既存 integration（test_pipeline_fixedpoint/test_diagnostics_phase2/test_pipeline_dialect/test_pipeline/test_cli）byte 不変**。1ケースでも動いたら commit せず停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/cli.py src/grep_analyzer/fixedpoint.py tests/integration/test_pipeline_phase2b.py
git commit -m "feat(pipeline): walk一回共有＋progress＋ripgrep配線＋CLI（spec §8.2・出力不変）"
```

---

## Task 10: 不変条件の総合回帰（jobs×memory×ripgrep×split×複数keyword）

**Files:** Test `tests/integration/test_phase2b_invariants.py`

Inv-1〜3 の総合契約（複数 keyword diagnostics 決定性含む）。実装追加なし（満たさない契約は原因 Task に戻る・テストは緩めない）。

- [ ] **Step 1: 失敗するテスト** — `tests/integration/test_phase2b_invariants.py` 新規:
```python
"""Phase 2b 不変条件の総合契約（spec §8.2/§9・出力透過と決定性）。"""

import hashlib
from pathlib import Path

import pytest

from grep_analyzer.cli import main


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ static final int K1 = 1; }\n", "utf-8")
    (src / "B.java").write_text("class B{ static final int K2 = K1; }\n", "utf-8")
    (src / "C.java").write_text("class C{ int z2 = K2; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:static final int K1 = 1;\n", "utf-8")
    (inp / "K9.grep").write_text("A.java:1:static final int K1 = 1;\n", "utf-8")
    return src, inp


def _h(tmp_path, src, inp, name, extra, fn="K1.tsv"):
    out = tmp_path / name
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)] + extra) == 0
    return hashlib.sha256((out / fn).read_bytes()).hexdigest()


def test_既定とjobsとmemory0はTSV完全一致_出力透過(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _h(tmp_path, src, inp, "base", [])
    assert _h(tmp_path, src, inp, "j4", ["--jobs", "4"]) == base
    assert _h(tmp_path, src, inp, "m0", ["--memory-limit", "0",
                                         "--max-passes", "8"]) == base
    assert _h(tmp_path, src, inp, "m0j4", ["--memory-limit", "0", "--jobs", "4",
                                           "--max-passes", "8"]) == base
    assert _h(tmp_path, src, inp, "base2", []) == base  # 2回実行決定的


def test_複数keyword_diagnosticsは2回実行で決定的(tmp_path: Path):
    src, inp = _setup(tmp_path)
    o1 = tmp_path / "d1"; o2 = tmp_path / "d2"
    main(["--input", str(inp), "--output", str(o1), "--source-root", str(src)])
    main(["--input", str(inp), "--output", str(o2), "--source-root", str(src)])
    assert (o1 / "diagnostics.txt").read_bytes() == \
           (o2 / "diagnostics.txt").read_bytes()  # 複数 keyword でも決定的


@pytest.mark.requires_ripgrep
def test_ripgrep有無でTSV完全一致(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _h(tmp_path, src, inp, "norg", [])
    assert _h(tmp_path, src, inp, "rg", ["--use-ripgrep"]) == base
    assert _h(tmp_path, src, inp, "rgj4", ["--use-ripgrep", "--jobs", "4"]) == base
```

- [ ] **Step 2: 失敗を確認 → 満たさない契約は原因 Task へ** — `python -m pytest tests/integration/test_phase2b_invariants.py -q` → PASS（rg 無: 2本＋1 skip／rg 有: 3本）。FAIL があれば**テストは緩めず**原因 Task（6/7/8/9）の出力透過・決定性を修正（spec §9 違反＝退行）。

- [ ] **Step 3: 全体回帰** — `python -m pytest -q` → 全 PASS・0 failed/0 error・既存 golden 14 不変。

- [ ] **Step 4: コミット**
```bash
git add tests/integration/test_phase2b_invariants.py
git commit -m "test(phase2b): jobs×memory×ripgrep×複数kw の出力透過・決定性契約（spec §8.2/§9）"
```

---

## Task 11: Phase 2b 全テスト緑化と完了確認

**Files:** Modify `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テスト実行** — `python -m pytest -q` → 全 PASS（Phase 2a 130 ＋ Phase 2b 追加分・0 failed/0 error）。`python -m grep_analyzer --help` exit 0（新オプション usage 出力）。失敗あれば該当 Task へ戻る（完了主張しない）。**rg 環境受入: `shutil.which('rg')` が None でない環境で `pytest -m requires_ripgrep` を別途実行し全 PASS を確認・記録（Task0 Step3 申し送り）**。

- [ ] **Step 2: spec §8.2／Inv 充足チェックリスト照合**

- §8.2 ストリーミング走査（bytes 親非常駐・確定全文1回読み＝C1根治）→ Task6（`test_多行構文…`）
- §8.2 walk 一回化（keyword 横断診断重複解消・複数 keyword 決定性）→ Task5/9/10（`test_walk診断…`/`test_複数keyword_diagnostics…`）
- §8.2 任意 ripgrep（walk 上位集合・gitignore/隠し/バイナリ含む＝-a でバイナリ境界統一）→ Task3/9/10（`@requires_ripgrep`・rg 環境受入）
- §8.2 --memory-limit 会計（決定的近似・in_memory_len で圧解消反映）→ Task1/2/7
- §8.2 priority-1（§8.3 シンボルキャップ＝唯一の出力変更）は Phase 2a 不変 → Task7（`test_max_symbolsキャップは従来通り…`・`test_memory_limit_Noneは…priority1不変`）
- §8.2 priority-2 来歴スピル（出力透過）→ Task2/7（`test_memory_limit0で来歴スピルしても出力はPhase2aと同一`＋`graph_spilled`）
- §8.2 最終手段 オートマトン分割多パス（出力透過＝C2根治）＋--max-passes 上限 → Task8（`test_force_chunks分割は…byte同値`＋`automaton_split`・`test_automatonのscan_lineは…`）
- §8.2 --progress 標準エラー進捗 → Task4/9（`test_progress_onはstderrのみでTSV不変`）
- Inv-1〜3（既定 byte 不変・degrade 出力透過・jobs/memory/ripgrep/複数kw 決定性）→ Task10＋既存 golden 14・既存 130 不変

- [ ] **Step 3: 完了記録を追記しコミット** — `phase0-gate-result.md` 末尾に「## Phase 2b 完了記録」（完了日 UTC、コミット範囲、全テスト結果、上記対応表、Inv-1〜4 充足＝既存 golden 14・既存 130 不変・複数 keyword diagnostics は walk 重複 dedup の意図変化、rg 環境受入結果、Phase 3 申し送り）を追記。
```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2b 完了（資源degrade・ストリーミング・ripgrep・progress）"
```

---

## Phase 2b の境界（Phase 3 は別計画）

- **Phase 3 に送る**: 60GB perf ベースライン（`tests/perf/` `@pytest.mark.perf` 非ゲート・本近似 budget の実バイト厳密化）、`--resume`、diagnostics §10.3 縮約（カテゴリ別集約＋代表サンプル）、規模分割 `<keyword>.partNN.tsv`（§9）、`requirements.lock`（§4.1・ユーザ決定。Phase 2a/2b は再現ビルドを `pip download` 明示 `==`＋wheelhouse で担保・lock 正式化は Phase 3）、`--output-encoding`/`--encoding-fallback`（§10.1 正本だが decode は Phase 1.5 確立済）。
- **Phase 2b 既知境界（spec 引用付き・仕様固定）**: (1) メモリ近似は決定的アイテム近似（実 RSS 非依存＝spec §9 決定性優先・実バイト厳密化 Phase 3）。(2) ripgrep は ASCII 識別子前提の walk 上位集合（Phase 2a の ASCII 識別子既知境界継承・`-a` でバイナリ境界を walk の `_is_binary` に統一＝§8.2）。(3) 差分走査効果は spec §8.2 L162 逐語「省けるのは確定済みシンボルの再ヒット再走査のみ」＝Phase 2a の active/done 分離で既達・Phase 2b 効果は bytes 親非常駐に限る（取りこぼしでない）。(4) `--progress` は stderr 専用・非決定要素（ETA 等）は出力契約外（Inv-4）。(5) 複数 keyword の `diagnostics.txt` は walk 系重複の dedup 差のみ＝意図変化（Inv-1。spec §10.3 一般縮約は Phase 3）。(6) priority-1（§8.3 シンボルキャップ）は `--memory-limit` 非依存の常設ガバナで Phase 2a 不変＝唯一の出力変更。`--memory-limit`（0 含む）の degrade はスピル/分割のみ＝出力透過で網羅性（indirect/chain）を保持（PRD 無害）。(7) `--max-passes` 上限到達後はそれ以上分割せず当該パスを実行（超過容認・決定的。priority-1=§8.3 常設キャップは各反復先頭で適用済）。
- 成果物: 「Phase 2a の出力・決定性を1バイトも変えずに（既定）、`--memory-limit` 超過で来歴スピル→オートマトン分割多パスへ degrade（いずれも出力透過＝網羅性保持）し、シンボル切り捨ては Phase 2a の §8.3 `max_symbols` キャップ（不変・唯一の出力変更）が担い、ストリーミング走査・任意 ripgrep・標準エラー進捗・walk 一回化を備えた、メモリ制約下でも決定的かつ網羅性を保って動くツール」。単体でテスト可能・出荷可能。

---

## Self-Review（v3・本計画著者によるチェック）

**1. spec coverage（§8.2 全項目）:** ネイティブ AC＋ripgrep（`-a` でバイナリ境界統一）＋multiprocessing → 既存＋Task3/9 ✓。差分走査の誠実な限定効果（L162 逐語・Phase 2a active/done 分離で既達）→ Task6 ✓。来歴 memory を --memory-limit 対象・上限超過スピル（in_memory_len で圧解消反映）→ Task1/2/7 ✓。degrade 優先順位（**priority-1=§8.3 常設キャップ不変／priority-2 スピル→最終手段分割・--max-passes 上限**）→ Task7/8（spec §8.2 厳密整合・v2 誤読根治）✓。size/binary skip・include/exclude・symlink・realpath（既存 walk 規則不変）→ Task5 collect_files 化のみ ✓。進捗 stderr・--progress 粒度 → Task4/9 ✓。§15 フェーズ2 資源 degrade を 2b（Phase 2a 境界の §15 根拠付き分割継承）✓。§10.4 CLI（--memory-limit/--use-ripgrep/--max-passes/--progress）→ Task9 ✓。Phase 3 送りは境界に spec §番号付き明記 ✓。

**2. Placeholder scan:** 全 Task に実コード・実コマンド・期待出力。fixedpoint 改変は「Phase 2a 実コードの当該1ブロックを次へ置換」＋行位置特定（seed ループ後・`_apply_global_cap` 前／`policy=` 直後／走査ループ先頭／`hop+=1` 直前／確定ループ後 `return` 直前 等）＝プレースホルダでない。`graph_spilled` 発火点・`prog.done()`/`estore.close()` 位置・`scan_files=files` を実コードで特定（v2 の非実装可能指示を解消）。`...`/「TBD」なし。

**3. Type consistency（串刺し）:** `MemoryBudget`(None/0/N)/`estimate_items`(n_edges=in_memory_len)/`EdgeStore`(`in_memory_len`/`maybe_spill_now`/`_force_spill_threshold`=unit専用)/`serialize_edge`/`parse_edge`/`ripgrep.prefilter`(-a等)/`Progress`/`collect_files`/`EngineOptions`(末尾既定6・非既定11先行で dataclass 制約充足・cli/pipeline/test の keyword 構築不変)/`run_fixedpoint(*, files=None)`/`_scan_file`(abspath)/`force_chunks`/**`_apply_global_cap` は Phase 2a 不変** を冒頭契約と全 Task で一致。`memory_limit_mb=None`＆`force_chunks=0`＆`spill_dir=None` で degrade 機構全 no-op＝Phase 2a 完全同一（nchunks=1 で走査ループ逐語・estore 非スピル・スピルブロック `budget.unlimited` で no-op・priority-1 不変）＝既存 golden 14・既存 130 不変を Task6/7/8/9/10 各 Step4 が要求。`_opts` 新6フィールド既定追加は Task7 Step1（Task6 新テストは `_opts()`＋`files=` のみ＝末尾既定不要で成立）。

**4. v2 批判的レビュー（2巡目3並行）指摘の解消対応:** **C1 根治**=確定 abspath 全文1回読み（Reviewer 実走で Phase2a 同値実証）✓ / **C2 根治**=nchunks==1 Phase2a 逐語・分割 `(lineno,symbol)` 正規化＋`scan_line` 昇順ユニーク固定テスト ✓ / **C4 根治**=rg `--no-ignore --hidden --no-require-git -a`＋gitignore/隠し/NUL ツリー上位集合テスト ✓ / **degrade ラダー誤読（Reviewer1 C-1＋Reviewer2 C1 収束）根治**=priority-1 を §8.3 `max_symbols` 常設キャップに確定し `--memory-limit` から完全分離（`_apply_global_cap` 不変）・staged-invariant 概念廃止・spill が `in_memory_len` で圧を実際に解消 ✓ / **memory=0 spec §10.4 逸脱（Reviewer2 C2）根治**=0 は「スピル/分割を即発火するが出力透過＝網羅性保持」＝coverage を落とす特別値でない・PRD 無害・spec MB スケール下端として自然 ✓ / **`graph_spilled` 未 assert/非実装可能（Reviewer1 H1/H2）根治**=engine 確定点（走査反復先頭でスピル遷移検出）で1回記録・spill テストで assert ✓ / **spill_dir+force_spill 本番混入（全 reviewer/自己指摘）根治**=`maybe_spill_now()` を engine の priority-2 駆動専用にし `_force_spill_threshold` は Task2 unit 専用に限定（本番経路で設定しない）✓ / rg binary 非対称（Reviewer2 H2）→`-a` で walk `_is_binary` 単一境界 ✓ / scan_files NameError（Reviewer2 H3）→Task8 コードに `scan_files=files` 明示 ✓ / edge_count 表記揺れ（Reviewer1 M2）→`edges`→`estore.add` 一本化（edge_count 自体を廃し `estimate_items` は live/in_memory_len/intro で算出）✓ / prog.done/estore.close 位置（Reviewer2 H3/Reviewer3 L4）→行位置特定 ✓ / scan_line 昇順ユニーク前提（Reviewer1 H1）→`test_automatonのscan_lineは…` で固定 ✓ / 複数 keyword diagnostics 決定性（Reviewer2 M1）→`test_複数keyword_diagnosticsは2回実行で決定的` 追加 ✓ / spec §8.2 L162 逐語（Reviewer2 M2）→境界(3)/spec解釈に逐語引用 ✓ / max_passes 上限後挙動（Reviewer2 M3）→境界(7)/Task8 注で確定 ✓ / rg 環境 skip 受入（Reviewer3 M1）→Task0 Step3/Task11 に CI 受入条件 ✓。

> 次レビュー重点候補: ① priority-1 を `--memory-limit` から完全分離した結果、「来歴グラフが巨大だがシンボル数は max_symbols 内」のとき spill のみで圧を吸収しきれない極限（spill 後も intro が大）で何が起きるか（spec §8.2 はその先を規定せず＝決定的に走査続行＝網羅性優先で spec §1/PRD と整合か）。② `maybe_spill_now()` が `_force_spill_threshold=0` を設定して `maybe_spill()` を呼ぶ実装が Task2 unit の `_force_spill_threshold` 契約（unit 専用）と概念衝突しないか（engine は専用メソッド経由＝テストフック直設定でない、を明示済だが命名整理の余地）。③ 分割時 `chunks` が空 scan_syms で `[[]]` になる経路（`automaton.build([])→None`＝0 ヒット）の決定性。④ 複数 keyword で pipeline が `run_fixedpoint(files=files)` を keyword 毎に呼ぶとき `estore`/`prog` が keyword 毎に新規生成され keyword 間でリークしないこと（run_fixedpoint ローカル＝OK の確認）。⑤ memory0 で spill 即発火時、確定フェーズの `estore.sorted_unique()` がファイル経由でも seed→chain の決定性を Phase2a と完全一致で保つこと（Task2 unit＋Task7/8 統合で二重担保）。
