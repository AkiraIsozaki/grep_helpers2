# grep_analyzer Phase 2b（資源 degrade・ストリーミング・ripgrep・progress） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`). **全コミット末尾に `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` を付す。`git add` は各 Task 記載ファイルのみ（明示パス・`.claude/settings.local.json` 等を含めない）。テスト関数名に全角丸カッコ `（）` を使わない（Python SyntaxError。区切りは `_`）。**

> **改訂履歴:** v1 → v2（1巡目反映）→ v3（2巡目反映）→ **v4（本書・3巡目3並行レビュー反映）**。3巡目で「2巡目収束 Critical 4件は v3 で機構解消（Reviewer 実走 161 passed・既存 byte 不変・temp リークなし）」確認。ただし spec §8.2 L164 を逐語精読した結果、**v3 が priority-1 を `--memory-limit` 超過応答から外した再構成は spec 誤読**（L164 の主語節「`--memory-limit` 超過時は」は優先1〜最終手段の3段すべてを統べる＝memory 超過の第一応答は §8.3 シンボル切り捨て）と確定。v4 で是正:
> - **degrade ラダー spec §8.2 L164 厳密化（最重要・C1/C2/H1/H2/M3 連鎖解消）**: priority-1（§8.3 決定的シンボル切り捨て）を **`max_symbols`（常設・Phase 2a）と `--memory-limit`（超過時の連動駆動）の両方**で動かす。memory 超過時は決定的キー `(発見ホップ,長さ,辞書順)` 不変のまま keep を単調縮小（edges は priority-2 spill で退避＝budget 計算は in-memory edges、intro はシンボルに連動縮小）。**シンボル切り捨ては唯一の出力変更で spec §8.4 全件 diagnostics に記録**（spec §8.3 L176・§1「絶対的ゼロ見落としは保証しない」＝memory degrade で出力が決定的に変わるのを spec は許容・記録で可視化）。`--memory-limit=None`（既定）でのみ Phase 2a TSV/diagnostics byte 不変。intro はシンボル切り捨てに連動して縮小＝§8.2 L163「来歴グラフのメモリ」退避を充足（C2 解消）。
> - **`memory_limit_mb=0` の意味確定**: 「最小メモリ＝priority-1 を最大限決定的に切り捨て＋来歴スピル＋オートマトン最大分割」。切り捨ては §8.4 全件記録・決定的・direct 行不変＝v2 の「silent 全滅」とは異なる**記録付き決定的 degrade**（spec §8.2/§8.4/§1 整合・ユーザが 0 を明示選択した結果）。出力透過ではない（priority-1 で indirect が決定的に減る）。
> - Reviewer1 H-1 是正: `EdgeStore` に内部 `_spill_now()` を切り出し、engine の priority-2 は `maybe_spill_now()`→`_spill_now()`（`_force_spill_threshold` を本番経路で**設定しない**）。`_force_spill_threshold` は Task2 unit 専用。
> - Reviewer1 H-2 是正: `run_fixedpoint` の走査〜確定を `try/finally: estore.close()` で包み例外時 temp リーク防止。
> - Reviewer3 M2 是正: 全テスト関数名から全角丸カッコを除去（SyntaxError 回避・区切りは `_`）。
> - M-1（automaton_split 診断を実パス数 `len(chunks)` に）・M-2（spill/split の budget n_symbols 意味を `n_live` に統一）・複数 keyword の §8.4 全件性が walk dedup に巻き込まれない契約テスト追加・`automaton.scan_line` 昇順ユニーク前提固定テスト。

**Goal:** Phase 2a の正しさ・決定性コアの**出力を `--memory-limit=None`（既定）で一切変えずに**、spec §8.2 の資源設計—ストリーミング走査（全 bytes 親常駐の廃止）／keyword 横断 walk 一回化／任意 `ripgrep` 一次粗フィルタ／`--memory-limit` 会計と degrade ラダー（**spec §8.2 L164: 優先1 §8.3 決定的シンボル切り捨て→優先2 来歴グラフのディスクスピル→最終手段オートマトン分割多パス・最大パス上限**）／`--progress` 標準エラー進捗—を実装する。

**Architecture:** Phase 1.5 決定的コア（dispatch/classifiers/model/tsv/diagnostics/encoding/ingest/proc_preprocess）と Phase 2a の chase/stoplist/automaton/provenance/classify は不変。新規 `budget.py`（決定的メモリ近似）／`spill.py`（来歴エッジのディスクスピル＝priority-2）／`ripgrep.py`（任意一次フィルタ）／`progress.py`（標準エラー進捗）。`walk.py` に `collect_files`。`fixedpoint.py` をストリーミング走査＋memory 連動 priority-1 切り捨て＋priority-2 スピル＋最終手段分割＋進捗フックに拡張（既定 `--memory-limit=None` 経路は Phase 2a 逐語）。`pipeline.py` は keyword ループ前に一度 `collect_files` し共有。`cli.py` に `--memory-limit`/`--use-ripgrep`/`--max-passes`/`--progress`。**60GB perf・`--resume`・diagnostics §10.3 縮約・規模分割 `partNN`・`requirements.lock`・`--output-encoding`/`--encoding-fallback` は Phase 3（範囲外）**。

**Tech Stack:** Python 3.12 / pytest / `pyahocorasick==2.1.0`（既存）/ 任意 `ripgrep`（外部バイナリ・`@pytest.mark.requires_ripgrep` 隔離・無くても他テスト緑）。設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v7・§9 は `07e81bb`、§8.1手順5 は `8c21227` 改訂後・spec が常に優先）、`.claude/skills/writing-tests.md`、`.claude/skills/coding-conventions.md` に従う（docstring/コメント・テスト名は日本語、古典学派+TDD、外部I/O境界＝ファイル/サブプロセスのみ本物）。

---

**不変条件（Phase 2b 全タスクの絶対前提・spec §8.2 L164／§9／Phase 2a 境界の継承）:**

- **Inv-1（既定出力不変）**: `memory_limit_mb=None`（既定）かつ `use_ripgrep=False` かつ `progress="off"` かつ `force_chunks=0` で TSV は Phase 2a と **byte 完全一致**。`diagnostics.txt` も **単一 keyword 入力では byte 完全一致**（既存 unit/integration/golden は全て単一 keyword＝既存 130 passed・14 golden は**全て byte 不変で緑**）。複数 keyword の `diagnostics.txt` は **walk 系カテゴリの重複行が dedup される差のみ**（Phase 2b 走査一回化の意図変化・退行ではない・既存テストは単一 keyword なので影響なし）。TSV は keyword 数に依らず常に byte 不変。
- **Inv-2（degrade の出力性質・spec §8.2 L164 準拠）**: **出力を変える degrade は priority-1（§8.3 決定的シンボル切り捨て）だけ**。priority-1 は `max_symbols`／`--min-specificity`／`--stoplist`（常設・Phase 2a）に加え **`--memory-limit` 超過時に決定的に連動駆動**（キー `(発見ホップ,長さ,辞書順)` 不変・落とした全シンボルを `symbol_rejected\tcapped` で **§8.4 全件記録**）。`--memory-limit=None`（既定）では priority-1=Phase 2a の `max_symbols` キャップそのもの＝TSV/diagnostics byte 不変。`--memory-limit` 超過時は **indirect が決定的に減り得る**（direct 行は不変・同一入力＋同一 limit で 2 回実行 byte 一致・落とした分は §8.4 全件記録）＝spec §8.2 L164 優先1・§8.3 L176・§1 が許容する記録付き決定的 degrade（no-limit と byte 一致は要求しない＝それが degrade の定義）。**priority-2 来歴スピル・最終手段オートマトン分割は priority-1 通過後の生存シンボル集合に対し出力を1バイトも変えない透過変換**（spec §9 走査順非依存の継承。スピル＝`EdgeStore.sorted_unique()`＝`sorted(set(edges))`／分割＝per-file 反復順を Phase 2a 単一オートマトンと厳密同一の `(lineno,symbol)` キーに正規化）。
- **Inv-3（決定性）**: `--jobs 1`/`N`、ストリーミング、`memory_limit` 有/無（0含む）、`force_chunks` 有/無、spill 有/無、ripgrep 有/無 のいずれの組合せでも、同一入力＋同一オプションで 2 回実行すると TSV／diagnostics が byte 一致（複数 keyword 含む）。
- **Inv-4（進捗は stderr 専用）**: `--progress` 出力は標準エラー専用。TSV／`diagnostics.txt`／終了コードに一切影響しない。

各 Task の Step4 は必ず「当該テスト PASS」＋「`python -m pytest -q` 全 PASS・0 failed/0 error（Phase 2a 130 ＋ 本 Task 追加分。**`--memory-limit=None` 既定で既存 golden 14・既存 130 が byte 不変で緑**）」を要求。既存が1ケースでも動いたら **commit せず停止し構造を疑う**。

**型・シグネチャ契約（全タスク共通・不変。Self-Review 3 で串刺し）:**

- `walk.collect_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag) -> list[tuple[str, pathlib.Path]]`
- `budget.MemoryBudget(limit_mb: int | None)`: `.unlimited`（`None`）/ `.item_budget`（`None→0`・`N>=0→N*_ITEMS_PER_MB`）/ `.exceeded(n_items) -> bool`（`unlimited` 常 `False`／`item_budget` ちょうど可／超過 `True`。`0`＝`item_budget 0`＝`n>=1` 超過）
- `budget.estimate_items(*, n_symbols, n_edges, n_intro) -> int`（決定的・RSS 非依存・単純和）
- `spill.serialize_edge(p,c)->str` / `spill.parse_edge(line)->tuple[Occurrence,Occurrence]`（制御文字エスケープで完全可逆）
- `spill.EdgeStore(spill_dir: pathlib.Path | None, budget)`: `.add(p,c)` / `.maybe_spill()`（予算/`_force_spill_threshold` 判定）/ `.maybe_spill_now()`（engine priority-2 用・内部 `_spill_now()` 直呼び・**`_force_spill_threshold` を介さない**）/ `.in_memory_len() -> int`（常駐エッジ数・spill 後 0）/ `.sorted_unique() -> Iterator[...]`（in-memory/spill いずれも `sorted(set(...))` 同一）/ `.spilled: bool` / `.close()` / `._force_spill_threshold: int | None`（**Task2 unit 専用・本番経路から設定しない**）
- `ripgrep.available()->bool` / `ripgrep.prefilter(root, rel_to_abs: dict[str, pathlib.Path], symbols: list[str]) -> set[str] | None`（`rg -l -F -a --no-messages --no-ignore --hidden --no-require-git -f pat .`＝walk 上位集合・バイナリ境界は walk の `_is_binary` 単一。rg 不在/失敗 `None`＝フィルタ無効＝全件）
- `progress.Progress(level, stream=None)`: `.start(total_files)` / `.hop(hop, n_symbols, scanned)` / `.done()`（`level!="on"` 無音・stderr のみ）
- `fixedpoint.EngineOptions` 追加フィールド（**末尾既定値付き**＝既存キーワード構築不変）: `memory_limit_mb: int | None = None`, `use_ripgrep: bool = False`, `max_passes: int = 8`, `progress: str = "off"`, `spill_dir: pathlib.Path | None = None`, `force_chunks: int = 0`
- `fixedpoint.run_fixedpoint(seed_hits, source_root, opts, diag, *, files: list[tuple[str, pathlib.Path]] | None = None) -> list[Hit]`
- `fixedpoint._scan_file(args)` の `args` は `(rel: str, abspath: str, sym_list: list[str], lang_map: dict)`（abspath＝ストリーミング）
- `fixedpoint._apply_global_cap`：**`--memory-limit=None` のとき Phase 2a と命令同値**（memory 連動分岐は `budget.unlimited` で完全スキップ）。memory 超過時のみ keep を決定的単調縮小（キー不変・edges は priority-2 spill 退避＝budget 計算で `n_edges=0`、intro はシンボル連動＝`n_intro≈keep`）

**spec 解釈の明示（次レビューで再検証可能）:**

- **degrade ラダー（spec §8.2 L164 逐語準拠・v4 確定）**: L164「`--memory-limit` 超過時は (優先1) §8.3 の決定的シンボル切り捨て（再走査を増やさず決定性維持）→ (優先2) 来歴グラフのスピル → (最終手段) オートマトン分割」。主語節「`--memory-limit` 超過時は」は3段すべてを統べる＝**memory 超過の第一応答は §8.3 シンボル切り捨て**（v3 が priority-1 を memory 非依存とした再構成は誤読＝v4 で是正）。本ツールでは priority-1＝`_apply_global_cap`（§8.3 キー `(発見ホップ,長さ,辞書順)`）を `max_symbols`（常設）と `--memory-limit`（超過時連動）の双方で駆動。memory 超過時 keep を `estimate_items(n_symbols=keep, n_edges=0, n_intro=keep) <= item_budget` を満たす最大値へ決定的単調縮小（`n_edges=0`＝priority-2 spill で edges 退避を前提、`n_intro≈keep`＝intro はシンボルに連動縮小）。落とした全シンボルを `symbol_rejected\tcapped` で **§8.4 全件記録**（spec §8.3 L176）。priority-1 通過後、なお in-memory edges で超過なら priority-2 `EdgeStore` スピル（圧解消・出力透過）→ scan_syms が単一オートマトンに過大なら最終手段オートマトン分割（決定的 K 分割・`--max-passes` 上限・出力透過）。
- **`memory_limit_mb` 意味（None/0/N）**: `None`＝無制限（既定・Phase 2a 同一・golden byte 不変）。`N>0`＝`N*_ITEMS_PER_MB` item 予算。`0`＝item 予算 0＝priority-1 が keep=0 まで決定的に切り捨て（**§8.4 全件記録・決定的・direct 行不変**）＋来歴スピル＋最大分割。`0` は spec §10.4 MB スケール下端で「最小メモリ・記録付き決定的最大 degrade」＝ユーザが 0 を明示選択した結果として spec §8.2/§8.4/§1 整合（v2 の silent 全滅とは異なり全件記録・決定的）。`--memory-limit` 超過時 indirect が減るのは spec §8.2 L164 優先1 の正規挙動＝出力透過ではない（透過なのは priority-2/最終手段のみ）。
- **メモリ近似は決定的近似**（spec §8.2 L163「来歴グラフのメモリは --memory-limit の対象」）: 実 RSS は非決定的なので不採用。`estimate_items = n_symbols + n_edges + n_intro`。priority-1 連動の budget 評価では edges は priority-2 spill 退避を前提に `n_edges=0`、intro はシンボル連動で `n_intro≈keep`。priority-2 spill 判定では `n_edges=estore.in_memory_len()`（spill 後 0＝圧解消反映）。`--memory-limit MB` は `N*_ITEMS_PER_MB`（`_ITEMS_PER_MB` 固定）へ決定的換算。同一入力＋同一 limit で同一 degrade 判断＝spec §9。実バイト厳密化は Phase 3 perf。
- **intro の memory 管理（C2 解消）**: `intro`（symbol→親 Occurrence リスト群）は spec §8.2 L163「来歴グラフのメモリ」の一部。v4 は intro を独立スピルせず、**priority-1 のシンボル切り捨てに連動して縮小**させる（切り捨てたシンボルの intro エントリは以後増えない＝symbol 数に比例）。priority-1 を `--memory-limit` 連動にしたことで intro メモリも memory 制約下で決定的に抑制＝§8.2 L163 を充足（v3 の「intro 常駐で圧解消しない」を根治）。
- **ripgrep は walk の上位集合フィルタ**（spec §8.2「任意 ripgrep 1次フィルタ」）: 追跡シンボルは ASCII 識別子（Phase 2a 既知境界）で UTF-8/CP932/latin-1 のいずれでも raw バイト上に同一バイト列で出現。`rg --no-ignore --hidden --no-require-git -a`（`-a`＝バイナリも走査＝rg 既定バイナリ skip を無効化し**バイナリ境界を walk の `_is_binary` 単一に統一**）で rg の対象を walk の上位集合に揃える。除外 rel は部分文字列すら持たず automaton（識別子境界）でも 0 ヒット確定＝出力不変。rg 不在は `None`＝フィルタ無効＝全件（既定 `use_ripgrep=False` でも全件＝Phase 2a 同一）。
- **差分走査の限定効果**（spec §8.2 L162 逐語「ファイル→該当行ローカリゼーション保持で省けるのは『**確定済みシンボルの再ヒット再走査**』のみ。『段数≠走査回数』はこの限定的効果を指す」）: Phase 2a は既に active のみ走査・`chase_done` 非再投入＝確定済シンボルの再走査は構造的に既達。Phase 2b の効果は「走査時の全 bytes 親常駐廃止（ストリーミング）」に限る（取りこぼしでない）。確定フェーズは対象ファイルを 1 回だけ abspath 全文デコード（per-rel キャッシュ＝Phase 2a `meta_of`/`line_cache` と命令同値・byte 同値）。
- **walk 一回化**: pipeline が全 keyword 前に一度 `collect_files`（走査・診断1回）し各 `run_fixedpoint(files=files)` へ共有。walk 系診断は keyword 数に依らず1回・file 集合は keyword 間同一＝TSV 決定性不変。複数 keyword で `diagnostics.txt` は walk 系重複行が dedup（意図変化・Inv-1）。**§8.4 全件性を持つシンボル系診断（`symbol_rejected`/`getter_setter_no_expand`/`prov_*`）は keyword 毎 `run_fixedpoint` で独立生成＝dedup 対象外＝§8.4 全件性不変**（spec §8.4「唯一の正本・全件」継承）。spec §10.3 一般縮約は Phase 3。

---

## Task 0: 着手ゲート（Phase 2a 緑・ripgrep 任意性・コードなし）

- [ ] **Step 1: Phase 2a 全緑** — Run: `cd /workspaces/grep_helpers2 && python -m pytest -q` → `130 passed`（0 failed/0 error）。異なれば着手しない。
- [ ] **Step 2: Phase 2a 完了記録の存在** — Run: `grep -nF '## Phase 2a 完了記録' docs/superpowers/plans/phase0-gate-result.md` → 1 行ヒット。**ヒット0なら Phase 2a 未完了＝着手不可で停止**。
- [ ] **Step 3: ripgrep 任意性確認** — Run: `python -c "import shutil; print(shutil.which('rg'))"`。`None` でも着手可（`--use-ripgrep` 任意・既定無効・`requires_ripgrep` 隔離）。**`shutil.which('rg')` が None の環境では ripgrep 経路テストは skip＝CI 等 rg 実体のある環境で `pytest -m requires_ripgrep` を別途必ず実行（Task11 受入条件）**。新規必須依存なし。
- [ ] **Step 4: ゲート記録しコミット** — `phase0-gate-result.md` 末尾に「## Phase 2b 着手ゲート記録」（UTC・`130 passed`・Phase 2a 完了参照・`shutil.which('rg')` 値と任意性・rg 経路 skip 注記・新規必須依存なし・判定 PASS）追記。
```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2b 着手ゲート記録（130 passed / Phase 2a 完了 / ripgrep 任意）"
```

---

## Task 1: 決定的メモリ近似 `budget.py`

**Files:** Create `src/grep_analyzer/budget.py` / Test `tests/unit/test_budget.py`

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

来歴グラフ等のメモリを見積もり、--memory-limit を degrade の決定的トリガに
換算する。同一入力・同一 limit で同一判断＝spec §9 決定性。
"""

# 1 MB あたりの近似アイテム上限（固定定数＝決定的換算）。実バイト厳密性は
# Phase 3 perf の領分。本定数は degrade 発火の決定的トリガとしてのみ機能。
_ITEMS_PER_MB = 4096


def estimate_items(*, n_symbols: int, n_edges: int, n_intro: int) -> int:
    """来歴グラフ常駐の決定的アイテム近似（各概念1件＝固定重み）。"""
    return n_symbols + n_edges + n_intro


class MemoryBudget:
    """--memory-limit(MB) を決定的 item 予算へ換算し超過判定する。

    None=無制限／0=item予算0（priority-1 最大切り捨て＋スピル＋分割）／
    N>0=N*_ITEMS_PER_MB。
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

spec §8.2 priority-2。予算内メモリ／超過でディスク追記スピル。`sorted_unique()` は in-memory/spill いずれでも `sorted(set(edges))` と同一（出力透過＝Inv-2）。`maybe_spill_now()` は内部 `_spill_now()` 直呼び（`_force_spill_threshold` を介さない＝本番経路で unit 専用フックを設定しない）。`_force_spill_threshold` は本 unit 専用。

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


def test_unitフック強制スピルでも同一集合同一順序かつin_memory_len0(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    s._force_spill_threshold = 1
    edges = [(Occurrence(f"S{i}", f"s{i}.c", i), Occurrence("H", "h.c", 9))
             for i in (3, 1, 2, 1)]
    for p, c in edges:
        s.add(p, c)
    assert s.spilled is True and s.in_memory_len() == 0
    assert list(s.sorted_unique()) == sorted(set(edges))
    s.close()


def test_maybe_spill_nowは閾値非経由で即スピルし透過(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    e = (Occurrence("A", "a.c", 1), Occurrence("B", "b.c", 2))
    s.add(*e)
    assert s.spilled is False and s._force_spill_threshold is None
    s.maybe_spill_now()
    assert s.spilled is True and s._force_spill_threshold is None  # フック不使用
    assert list(s.sorted_unique()) == [e] and s.in_memory_len() == 0
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
（スピル後 0＝estimate_items にスピルが圧解消として反映）。maybe_spill_now は
engine priority-2 用で内部 _spill_now 直呼び（_force_spill_threshold は
Task2 unit 専用・本番経路から設定しない）。
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
        """1 エッジ追加。予算/unit フック超過で以降スピルへ。"""
        if self.spilled:
            self._fh.write(serialize_edge(p, c) + "\n")
            return
        self._mem.append((p, c))
        self.maybe_spill()

    def in_memory_len(self) -> int:
        """メモリ常駐エッジ数（スピル後は 0）。"""
        return 0 if self.spilled else len(self._mem)

    def maybe_spill(self) -> None:
        """予算/unit フック超過ならスピル。"""
        if self.spilled:
            return
        thr = self._force_spill_threshold
        over = (thr is not None and len(self._mem) >= thr) or \
               self._budget.exceeded(len(self._mem))
        if over:
            self._spill_now()

    def maybe_spill_now(self) -> None:
        """engine priority-2 用＝予算判定に依らず即スピル（フック非経由）。"""
        if not self.spilled:
            self._spill_now()

    def _spill_now(self) -> None:
        """メモリ内容を一時ファイルへ退避しスピル状態へ（内部）。"""
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
        """一時ファイルを閉じ削除する（確定ループ完了後・例外時も finally で）。"""
        if self._fh is not None:
            self._fh.close()
            self._fh = None
        if self._path is not None and self._path.exists():
            self._path.unlink()
            self._path = None
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_spill.py -q` → PASS（5本）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/spill.py tests/unit/test_spill.py
git commit -m "feat(spill): 来歴エッジのディスクスピル（spec §8.2 priority-2・閾値非経由maybe_spill_now）"
```

---

## Task 3: 任意 ripgrep 一次フィルタ `ripgrep.py`（walk 上位集合・-a でバイナリ境界統一）

**Files:** Create `src/grep_analyzer/ripgrep.py` / Test `tests/unit/test_ripgrep.py` / Modify `tests/conftest.py`

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
def test_gitignore隠しNUL含みも上位集合に含む(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.c\n", "utf-8")
    (tmp_path / "ignored.c").write_text("int CODE=1;\n", "utf-8")
    (tmp_path / ".hidden.c").write_text("int CODE=2;\n", "utf-8")
    (tmp_path / "nul.c").write_bytes(b"int CODE=3;\n\x00trailer\n")
    (tmp_path / "visible.c").write_text("int CODE=4;\n", "utf-8")
    rel_abs = {n: tmp_path / n for n in
               ("ignored.c", ".hidden.c", "nul.c", "visible.c")}
    got = prefilter(tmp_path, rel_abs, ["CODE"])
    assert {"ignored.c", ".hidden.c", "nul.c", "visible.c"} <= got


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

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_ripgrep.py -q`（rg 有: 4本／rg 無: 1本＋3 skip）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/ripgrep.py tests/unit/test_ripgrep.py tests/conftest.py
git commit -m "feat(ripgrep): 任意一次フィルタ（walk上位集合・-aでバイナリ境界統一・spec §8.2）"
```

---

## Task 4: 標準エラー進捗 `progress.py`

**Files:** Create `src/grep_analyzer/progress.py` / Test `tests/unit/test_progress.py`

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

`files: list[(rel, bytes)]` を `files: list[(rel, abspath)]` に変え `_scan_file` がワーカ内で abspath を読む。確定フェーズは abspath から全文1回デコードし per-rel キャッシュ（Phase 2a `meta_of`/`line_cache` と命令同値・byte 同値・C1 根治）。`run_fixedpoint` に `*, files=None`。**本 Task は `EngineOptions`/`_opts`/`_apply_global_cap` を変更しない**（新フィールド・degrade は Task7/8）。

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
    automaton 走査は raw 行。出力は Phase 2a と byte 不変。
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

(2) `run_fixedpoint` シグネチャを `def run_fixedpoint(seed_hits, source_root, opts, diag, *, files=None):` に変更（docstring 追記）。Phase 2a 実コードの `files: list[tuple[str, bytes]] = [ (rel, abspath.read_bytes()) ... walk.walk_files(...) ]` ブロック（seed ループ後・`_apply_global_cap` 定義直前）を次へ置換:
```python
    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    rel_to_abs = {rel: abspath for rel, abspath in files}
```

(3) 走査ループの `args` を abspath（str）に: `args = [(rel, str(abspath), scan_syms, opts.lang_map) for rel, abspath in files]`

(4) 確定フェーズの `raw_of = dict(files)` 行と再読込ブロックを次へ置換（全文1回デコード・per-rel キャッシュ・Phase 2a byte 同値）:
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

> **実装注（C1 根治・出力 byte 不変）:** 確定フェーズは Phase 2a と同一ロジック（`meta_of`/`line_cache`/`classify_hit(..., text=全文, ...)`）。差分は bytes 取得元が `raw_of=dict(files)` → `rel_to_abs[rel].read_bytes()`。デコード結果・AST・分類・chain は Phase 2a と同値。ストリーミングの実効果は走査中の全 bytes 親非常駐に限る（spec §8.2 差分走査の誠実化）。

- [ ] **Step 4: 通る（出力保存の回帰が要）** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存8＋新規3。特に `test_多行構文…`＝C1 回帰）／`python -m pytest -q` → **全 PASS・既存 golden 14・既存 integration byte 不変**。動いたら commit せず停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): ストリーミング走査＋確定全文1回読み（spec §8.2・C1根治・出力不変）"
```

---

## Task 7: degrade priority-1（memory 連動の §8.3 決定的切り捨て）＋priority-2 来歴スピル

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.2 L164。**priority-1（`_apply_global_cap`＝§8.3 キー不変）を `max_symbols`（常設・Phase 2a）と `--memory-limit`（超過時連動）の双方で駆動**。memory 超過時 keep を `estimate_items(n_symbols=keep, n_edges=0, n_intro=keep) <= item_budget` の最大値へ決定的単調縮小（落とした全シンボルを §8.4 全件記録・唯一の出力変更）。**`--memory-limit=None` のとき `budget.unlimited` で memory 分岐スキップ＝Phase 2a と命令同値・既定 byte 不変**。priority-1 通過後なお in-memory edges で超過なら priority-2 `EdgeStore` スピル（圧解消・生存集合に対し出力透過）。`edges` を `EdgeStore` 化。`run_fixedpoint` を `try/finally: estore.close()` で包む（例外時 temp リーク防止＝Reviewer1 H-2）。

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
末尾に追記（**関数名に全角カッコを使わない**）:
```python
def test_memory_limit_Noneは無制限でPhase2aと同一_priority1不変(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    chains = {(h.file, h.via_symbol): h.chain
              for h in run_fixedpoint([seed], src,
                                      _opts(memory_limit_mb=None), Diagnostics())}
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"


def test_max_symbolsキャップは従来通り出力変更_priority1常設(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=1; }\n",
                         "B.java": "class B{ int zz=aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    diag = Diagnostics()
    run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=1), diag)
    assert "symbol_rejected\tcapped" in diag.render()


def test_memory_limit0はpriority1で決定的に切り捨て全件記録_directは不変(tmp_path):
    src = _mk(tmp_path, {"C.java": 'class C { static final String S_OK = "x"; }\n',
                         "U.java": "class U { String x = S_OK; }\n"})
    seed = _seed("S_OK", "java", "C.java", 1, 'static final String S_OK = "x";')
    base = run_fixedpoint([seed], src, _opts(), Diagnostics())
    diag = Diagnostics()
    deg = run_fixedpoint([seed], src,
                         _opts(memory_limit_mb=0, spill_dir=tmp_path), diag)
    assert "symbol_rejected\tcapped" in diag.render()      # priority-1 連動発火・全件
    assert deg == [] and base                              # memory0=keep0 で indirect 全切り
    # direct は fixedpoint の責務外＝呼出側 pipeline 不変（本 unit は indirect のみ検証）


def test_memory_limit0は2回実行で決定的(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1=1; }\n",
                         "B.java": "class B{ static final int K2=K1; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1=1;")
    k = lambda hs: sorted((h.file, h.via_symbol, h.chain) for h in hs)
    r1 = run_fixedpoint([seed], src, _opts(memory_limit_mb=0, spill_dir=tmp_path),
                        Diagnostics())
    r2 = run_fixedpoint([seed], src, _opts(memory_limit_mb=0, spill_dir=tmp_path),
                        Diagnostics())
    assert k(r1) == k(r2)
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → FAIL（`EngineOptions … unexpected keyword argument 'memory_limit_mb'`）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) `EngineOptions` に末尾既定フィールド追加（非既定11→既定6・既存キーワード構築不変）:
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

(3) `run_fixedpoint` 内 `policy = ...` 直後に: `budget = MemoryBudget(opts.memory_limit_mb)`。状態初期化群の `edges: list[...] = []` を `estore = EdgeStore(opts.spill_dir, budget)` ＋ `spill_logged = False` に置換。エッジ追加箇所 `edges.append((parent, child))` を `estore.add(parent, child)` に置換。

(4) `_apply_global_cap` を Phase 2a から **memory 連動分岐のみ追加**（`--memory-limit=None` は Phase 2a 命令同値）に置換:
```python
    def _apply_global_cap():
        live = sorted(chase_active | chase_done | term_active | term_done,
                      key=lambda s: (sym_hop.get(s, 0), len(s), s))
        keep = opts.max_symbols
        if not budget.unlimited:
            # spec §8.2 L164 優先1: --memory-limit 超過時の §8.3 決定的切り捨て。
            # edges は priority-2 spill で退避(n_edges=0)、intro はシンボル連動
            # (n_intro≈keep)。キー不変・単調縮小・決定的。keep=0 は memory 0 等。
            while keep > 0 and budget.exceeded(estimate_items(
                    n_symbols=keep, n_edges=0, n_intro=keep)):
                keep -= 1
        if len(live) <= keep:
            return
        for s in live[keep:]:
            if s not in capped:
                diag.add("symbol_rejected", f"capped\t{s}")
                capped.add(s)
            chase_active.discard(s)
            term_active.discard(s)  # chase_done 単調維持・scan は capped で除外
```

(5) 走査ループ各反復の**先頭**（`_apply_global_cap()` 呼出の直後）に priority-2 spill を追加:
```python
        if not budget.unlimited and not estore.spilled:
            n_intro = sum(len(v) for v in intro.values())
            n_live = len(chase_active | chase_done | term_active | term_done)
            if budget.exceeded(estimate_items(
                    n_symbols=n_live, n_edges=estore.in_memory_len(),
                    n_intro=n_intro)):
                estore.maybe_spill_now()
                if not spill_logged:
                    diag.add("graph_spilled", f"hop={hop}")
                    spill_logged = True
```

(6) グラフ構築 `for p, c in edges:` → `for p, c in estore.sorted_unique():`、確定ループ `for _, c in sorted(set(edges)):`（Task6 (4)）→ `for _, c in estore.sorted_unique():`。**`run_fixedpoint` の seed ループ後（`files` 確定以降）から `return indirect` までを `try:` で包み、`finally: estore.close()` を置く**（例外時 temp リーク防止）。`return indirect` は try 内・`finally` で close。

> **実装注（spec §8.2 L164 整合・Inv-2・C1/C2/H1/H2 解消）:** `--memory-limit=None`→`budget.unlimited`→(4) の while スキップで `keep=opts.max_symbols`＝Phase 2a `_apply_global_cap` と**命令同値**（既存 golden 14・既存 130 byte 不変）。memory 超過時は (4) が keep を決定的単調縮小（edges は (5) priority-2 spill で退避＝budget 計算 `n_edges=0`、intro はシンボル連動＝`n_intro≈keep`）＝spec §8.2 L164 優先1。落とした全シンボルは `symbol_rejected\tcapped` で §8.4 全件記録（spec §8.3 L176）。memory 0 は keep=0 まで切り捨て＝indirect 決定的に全切り（記録付き・direct は pipeline 側で不変）＝spec §8.2/§8.4/§1 整合の記録付き決定的 degrade（v2 silent 全滅と異なる）。priority-2 spill は `maybe_spill_now()`（内部 `_spill_now()`・`_force_spill_threshold` 非経由＝本番混入なし＝Reviewer1 H-1）で edges 退避＝`in_memory_len()` が以後 0＝budget 圧解消反映。`sorted_unique()`＝`sorted(set())` で graph/確定が順序非依存＝生存集合に対し出力透過。intro はシンボル切り捨て連動縮小＝§8.2 L163 充足（C2 解消）。`try/finally: estore.close()` で例外時 temp 削除（Reviewer1 H-2）。

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存11＋新規4。`test_memory_limit_Noneは…priority1不変`＝既定 Phase2a 同一・`test_memory_limit0はpriority1で決定的に切り捨て全件記録…`＝memory 連動切り捨て＋§8.4 全件・`test_memory_limit0は2回実行で決定的`＝Inv-3）／`python -m pytest -q` → **全 PASS・既存 golden 14 不変**（`memory_limit_mb=None` 既定で Phase 2a 同一）。動いたら停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): degrade priority-1 memory連動§8.3切り捨て＋priority-2スピル（spec §8.2 L164）"
```

---

## Task 8: degrade 最終手段＝オートマトン分割多パス（生存集合に対し出力透過・C2根治）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.2 最終手段。`scan_syms` が単一オートマトンに過大（または `force_chunks>1`）なら決定的 K 分割・K パス走査（`--max-passes` 上限）。**既定/非分割（nchunks==1）は Phase 2a の走査ループを逐語保持**（C2 根治）。分割時のみ集約し per-file 反復順を Phase 2a 単一オートマトンと厳密同一の `(lineno,symbol)` キーに正規化。`automaton_split` 診断は**実パス数 `len(chunks)`**（Reviewer1 M-1）。`force_chunks>1` は memory 非依存に分割強制（priority-1 非発火＝split 透過性の分離検証）。priority-2 spill 判定の `n_symbols` を priority-1 と整合させ `n_live`（Reviewer1 M-2）。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_fixedpoint.py` 末尾に追記（**全角カッコ不使用**）:
```python
def test_automatonのscan_lineは行内シンボル昇順ユニーク_分割正規化前提固定():
    from grep_analyzer.automaton import build, scan_line
    au = build(["AA", "BB", "CC"])
    assert scan_line(au, "BB CC AA AA BB") == ["AA", "BB", "CC"]


def test_force_chunks分割は単一オートマトンと出力byte同値_memory非依存(tmp_path):
    # split 透過性: memory=None で priority-1 非発火・分割のみ isolate
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


def test_memory_limit0は分割スピル切り捨て併発でも2回実行決定的(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1=1; }\n",
                         "B.java": "class B{ static final int K2=K1; }\n",
                         "C.java": "class C{ int z2=K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1=1;")
    k = lambda hs: sorted((h.file, h.via_symbol, h.chain) for h in hs)
    r1 = run_fixedpoint([seed], src, _opts(memory_limit_mb=0, spill_dir=tmp_path,
                                           max_passes=8), Diagnostics())
    r2 = run_fixedpoint([seed], src, _opts(memory_limit_mb=0, spill_dir=tmp_path,
                                           max_passes=8), Diagnostics())
    assert k(r1) == k(r2)
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → 新規3本 FAIL（force_chunks/分割未実装）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` の走査ループを「nchunks==1 は Phase 2a 逐語・nchunks>1 のみ集約」に変更。Task6/7 の走査ブロック（`args=[...]; if jobs>1 ... else ...; for rel,...,found in sorted(results,key=r[0]): (estore.add/_ingest...)`）を次へ置換:
```python
        scan_files = files  # Task9 で ripgrep 絞り込みに差し替え
        n_intro = sum(len(v) for v in intro.values())
        n_live = len(chase_active | chase_done | term_active | term_done)
        nchunks = 1
        if opts.force_chunks and opts.force_chunks > 1:
            nchunks = min(opts.force_chunks, opts.max_passes,
                          max(1, len(scan_syms)))
        elif not budget.unlimited and budget.exceeded(estimate_items(
                n_symbols=n_live, n_edges=estore.in_memory_len(),
                n_intro=n_intro)):
            while nchunks < opts.max_passes and nchunks < len(scan_syms) and \
                    budget.exceeded(estimate_items(
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
            size = -(-len(scan_syms) // nchunks)
            chunks = [scan_syms[i:i + size]
                      for i in range(0, len(scan_syms), size)] or [[]]
            diag.add("automaton_split", f"hop={hop} chunks={len(chunks)}")
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

> **実装注（C2 根治・出力透過の証明・M-1/M-2）:** `nchunks==1`（既定 `memory_limit_mb=None`／`force_chunks=0`）は Phase 2a 走査ループと逐語同一。`nchunks>1` のみ `agg` 集約し `sorted(agg[rel], key=(t[1],t[0]))`＝`(lineno,symbol)` 昇順。`automaton.scan_line` は行内 symbol 昇順ユニーク（`test_automatonのscan_lineは…` で固定）＝Phase 2a per-file 反復順＝`(lineno,symbol)` 昇順そのもの＝`_ingest`/`estore.add` 投入順が Phase 2a と同一＝`sym_kind/sym_hop` first-write-wins 同値＝**生存シンボル集合に対し出力 byte 透過**。`automaton_split` 診断は実パス数 `len(chunks)`（`nchunks` でなく＝Reviewer1 M-1。`while nchunks < len(scan_syms)` クランプで `nchunks` も実分割可能数を超えない）。priority-2 spill（Task7 (5)）と本分割の budget 判定 `n_symbols` は共に `n_live`＝整合（Reviewer1 M-2）。`memory_limit_mb=0` は priority-1（Task7）が先に keep=0 まで切り捨てるため分割発火時の scan_syms は空に近いが、決定性（2回一致）は保たれる。

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存15＋新規3。`test_force_chunks分割は…byte同値_memory非依存`＝split 透過＋`automaton_split` 実発火・`test_automatonのscan_lineは…`＝正規化前提固定・`test_memory_limit0は分割スピル切り捨て併発でも2回実行決定的`＝Inv-3）／`python -m pytest -q` → **全 PASS・既存 golden 14・既存 integration byte 不変**（既定 nchunks=1・estore 非スピル＝Phase 2a 逐語）。動いたら停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): degrade最終手段オートマトン分割多パス（spec §8.2・出力透過C2根治）"
```

---

## Task 9: pipeline 配線（walk 一回共有・進捗・ripgrep・CLI）

**Files:** Modify `src/grep_analyzer/pipeline.py` / Modify `src/grep_analyzer/cli.py` / Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/integration/test_pipeline_phase2b.py`

pipeline が全 keyword 前に `collect_files` で一度 walk し各 `run_fixedpoint(files=files)` へ共有。`run_fixedpoint` に進捗（`Progress`）と任意 ripgrep 一次フィルタ（`scan_files` を絞る・出力不変＝walk 上位集合）。`cli.py` に `--memory-limit`/`--use-ripgrep`/`--max-passes`/`--progress`。既定は Phase 2a 完全同一。

- [ ] **Step 1: 失敗するテスト** — `tests/integration/test_pipeline_phase2b.py` 新規:
```python
"""Phase 2b 配線の境界契約（spec §8.2・既定出力不変・診断重複解消）。in-process。"""

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


def test_memory_limit0はdirect不変でindirectは決定的に減る(tmp_path: Path):
    src, inp = _tree(tmp_path)
    a = tmp_path / "a"; main(["--input", str(inp), "--output", str(a),
                              "--source-root", str(src)])
    b = tmp_path / "b"
    main(["--input", str(inp), "--output", str(b), "--source-root", str(src),
          "--memory-limit", "0", "--max-passes", "8"])
    da = [ln for ln in (a / "S_OK.tsv").read_text("utf-8-sig").splitlines()
          if "\tdirect\t" in ln]
    db = [ln for ln in (b / "S_OK.tsv").read_text("utf-8-sig").splitlines()
          if "\tdirect\t" in ln]
    assert da == db and da                                  # direct 行不変
    a2 = (b / "S_OK.tsv").read_text("utf-8-sig")
    b2 = tmp_path / "b2"
    main(["--input", str(inp), "--output", str(b2), "--source-root", str(src),
          "--memory-limit", "0", "--max-passes", "8"])
    assert a2 == (b2 / "S_OK.tsv").read_text("utf-8-sig")    # memory0 も決定的
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/integration/test_pipeline_phase2b.py -q` → FAIL（`--memory-limit`/`--progress` 未知 or walk_excluded 2回）

- [ ] **Step 3: 実装**

`src/grep_analyzer/fixedpoint.py`:
- import: `from grep_analyzer.progress import Progress` / `from grep_analyzer import ripgrep as _rg`
- `rel_to_abs = {...}`（Task6 (2)）構築直後に **1 回だけ**: `prog = Progress(opts.progress); prog.start(len(files))`
- 走査ループ先頭 `scan_files = files`（Task8 (3) 冒頭）行を次へ差し替え:
```python
        scan_files = files
        if opts.use_ripgrep:
            keep = _rg.prefilter(source_root, rel_to_abs, scan_syms)
            if keep is not None:
                scan_files = [(r, a) for r, a in files if r in keep]
```
- 反復末尾 `hop += 1` の**直前**に `prog.hop(hop, len(scan_syms), len(scan_files))`。`while` ループ脱出後・**確定ループ完了後・`return indirect` の直前（`try` 内・`finally: estore.close()` の前）**に `prog.done()`。

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
git commit -m "feat(pipeline): walk一回共有＋progress＋ripgrep配線＋CLI（spec §8.2・既定出力不変）"
```

---

## Task 10: 不変条件の総合回帰（jobs×memory×ripgrep×複数keyword）

**Files:** Test `tests/integration/test_phase2b_invariants.py`

Inv-1〜3 の総合契約（複数 keyword diagnostics 決定性・§8.4 全件性が walk dedup に巻き込まれない含む）。実装追加なし（満たさない契約は原因 Task に戻る・テストは緩めない）。

- [ ] **Step 1: 失敗するテスト** — `tests/integration/test_phase2b_invariants.py` 新規:
```python
"""Phase 2b 不変条件の総合契約（spec §8.2/§9・既定出力不変と決定性）。"""

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


def test_既定とjobsは完全一致_既定出力不変かつ決定的(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _h(tmp_path, src, inp, "base", [])
    assert _h(tmp_path, src, inp, "j4", ["--jobs", "4"]) == base
    assert _h(tmp_path, src, inp, "base2", []) == base


def test_memory0は2回実行決定的_degrade決定性(tmp_path: Path):
    src, inp = _setup(tmp_path)
    a = _h(tmp_path, src, inp, "m1", ["--memory-limit", "0", "--max-passes", "8"])
    b = _h(tmp_path, src, inp, "m2", ["--memory-limit", "0", "--max-passes", "8"])
    c = _h(tmp_path, src, inp, "m3", ["--memory-limit", "0", "--jobs", "4",
                                      "--max-passes", "8"])
    assert a == b == c


def test_複数keyword_diagnosticsは2回実行で決定的(tmp_path: Path):
    src, inp = _setup(tmp_path)
    o1 = tmp_path / "d1"; o2 = tmp_path / "d2"
    main(["--input", str(inp), "--output", str(o1), "--source-root", str(src)])
    main(["--input", str(inp), "--output", str(o2), "--source-root", str(src)])
    assert (o1 / "diagnostics.txt").read_bytes() == \
           (o2 / "diagnostics.txt").read_bytes()


@pytest.mark.requires_ripgrep
def test_ripgrep有無でTSV完全一致(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _h(tmp_path, src, inp, "norg", [])
    assert _h(tmp_path, src, inp, "rg", ["--use-ripgrep"]) == base
    assert _h(tmp_path, src, inp, "rgj4", ["--use-ripgrep", "--jobs", "4"]) == base
```

- [ ] **Step 2: 失敗を確認 → 満たさない契約は原因 Task へ** — `python -m pytest tests/integration/test_phase2b_invariants.py -q` → PASS（rg 無: 3本＋1 skip／rg 有: 4本）。FAIL があれば**テストは緩めず**原因 Task（6/7/8/9）を修正（spec §8.2/§9 違反＝退行）。

- [ ] **Step 3: 全体回帰** — `python -m pytest -q` → 全 PASS・0 failed/0 error・既存 golden 14 不変。

- [ ] **Step 4: コミット**
```bash
git add tests/integration/test_phase2b_invariants.py
git commit -m "test(phase2b): jobs×memory×ripgrep×複数kw の既定出力不変・決定性契約（spec §8.2/§9）"
```

---

## Task 11: Phase 2b 全テスト緑化と完了確認

**Files:** Modify `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テスト実行** — `python -m pytest -q` → 全 PASS（Phase 2a 130 ＋ Phase 2b 追加分・0 failed/0 error）。`python -m grep_analyzer --help` exit 0。失敗あれば該当 Task へ戻る（完了主張しない）。**rg 環境受入: `shutil.which('rg')` が None でない環境で `pytest -m requires_ripgrep` を別途実行し全 PASS を確認・記録**。
- [ ] **Step 2: spec §8.2 L164／Inv 充足チェックリスト照合**

- §8.2 ストリーミング走査（bytes 親非常駐・確定全文1回読み＝C1根治）→ Task6
- §8.2 walk 一回化（重複解消・複数kw決定性・§8.4全件性は kw 毎独立で不変）→ Task5/9/10
- §8.2 任意 ripgrep（walk 上位集合・-a でバイナリ境界統一）→ Task3/9/10（rg 環境受入）
- §8.2 L164 priority-1（§8.3 切り捨て＝唯一の出力変更・`max_symbols`常設＋`--memory-limit`連動）→ Task7（`test_max_symbolsキャップは従来通り…`/`test_memory_limit0はpriority1で決定的に切り捨て全件記録…`/`test_memory_limit_Noneは…priority1不変`）
- §8.2 L164 priority-2 来歴スピル（生存集合に出力透過）→ Task2/7（`graph_spilled`）
- §8.2 L164 最終手段 オートマトン分割多パス（出力透過＝C2根治）＋--max-passes 上限・実パス数診断 → Task8（`test_force_chunks…byte同値`＋`automaton_split`）
- §8.2 --progress 標準エラー進捗 → Task4/9
- Inv-1〜3（既定 byte 不変・priority-1 のみ出力変更で決定的記録・priority-2/分割透過・jobs/memory/ripgrep/複数kw 決定性）→ Task10＋既存 golden 14・既存 130 不変

- [ ] **Step 3: 完了記録を追記しコミット** — `phase0-gate-result.md` 末尾に「## Phase 2b 完了記録」（完了日 UTC、コミット範囲、全テスト結果、上記対応表、Inv-1〜4 充足＝`--memory-limit=None` で既存 golden 14・既存 130 不変・`--memory-limit` 超過で indirect 決定的減（§8.4全件記録）・複数 kw diagnostics は walk 重複 dedup の意図変化、rg 環境受入結果、Phase 3 申し送り）を追記。
```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2b 完了（資源degrade・ストリーミング・ripgrep・progress）"
```

---

## Phase 2b の境界（Phase 3 は別計画）

- **Phase 3 に送る**: 60GB perf ベースライン（`tests/perf/` `@pytest.mark.perf` 非ゲート・本近似 budget の実バイト厳密化）、`--resume`、diagnostics §10.3 縮約、規模分割 `<keyword>.partNN.tsv`（§9）、`requirements.lock`（§4.1・ユーザ決定。Phase 2a/2b は再現ビルドを `pip download` 明示 `==`＋wheelhouse で担保・lock 正式化は Phase 3）、`--output-encoding`/`--encoding-fallback`（§10.1 正本だが decode は Phase 1.5 確立済）。
- **Phase 2b 既知境界（spec 引用付き・仕様固定）**: (1) メモリ近似は決定的アイテム近似（実 RSS 非依存＝spec §9 決定性優先・実バイト厳密化 Phase 3）。(2) ripgrep は ASCII 識別子前提の walk 上位集合（Phase 2a の ASCII 識別子既知境界継承・`-a` でバイナリ境界を walk の `_is_binary` に統一＝§8.2）。(3) 差分走査効果は spec §8.2 L162 逐語「省けるのは確定済みシンボルの再ヒット再走査のみ」＝Phase 2a active/done 分離で既達・Phase 2b 効果は bytes 親非常駐に限る（取りこぼしでない）。(4) `--progress` は stderr 専用・非決定要素（ETA 等）は出力契約外（Inv-4）。(5) 複数 keyword の `diagnostics.txt` は walk 系重複の dedup 差のみ＝意図変化（Inv-1）。§8.4 全件性シンボル系診断は keyword 毎独立生成で dedup 非対象＝不変。spec §10.3 一般縮約は Phase 3。(6) **`--memory-limit` 超過時 priority-1（§8.3 切り捨て）が indirect を決定的に減らすのは spec §8.2 L164 優先1 の正規挙動**（§8.4 全件記録・決定的・direct 不変・`--memory-limit=None` 既定で Phase 2a byte 不変）。intro はシンボル切り捨て連動で縮小＝§8.2 L163 来歴メモリ退避を充足。priority-2 spill/最終手段分割は生存集合に対し出力透過。(7) `--max-passes` 上限到達後はそれ以上分割せず当該 nchunks で走査（超過容認・決定的。spec §8.2「最大走査パス数の上限を実装計画で明示」＝`--max-passes` で充足。上限後の超過容認は spec §8.2 が「最終手段の先」を規定しないことに基づく v1 既知境界＝決定性・網羅性優先の設計判断）。
- 成果物: 「`--memory-limit=None`（既定）で Phase 2a の出力・決定性を1バイトも変えず、`--memory-limit` 超過で spec §8.2 L164 のラダー（優先1 §8.3 決定的切り捨て〔記録付き・唯一の出力変更〕→優先2 来歴スピル→最終手段分割〔生存集合に透過〕）で degrade し、ストリーミング走査・任意 ripgrep・標準エラー進捗・walk 一回化を備えた、メモリ制約下でも決定的に動くツール」。単体でテスト可能・出荷可能。

---

## Self-Review（v4・本計画著者によるチェック）

**1. spec coverage（§8.2 全項目・L164 ラダー）:** ネイティブ AC＋ripgrep（`-a`）＋multiprocessing → Task3/9 ✓。差分走査限定効果（L162 逐語）→ Task6 ✓。来歴 memory を --memory-limit 対象（priority-1 でシンボル連動縮小＝intro 縮小・priority-2 で edges スピル）→ Task1/2/7 ✓。**degrade 優先順位（L164 逐語: 優先1 §8.3 決定的切り捨て〔max_symbols常設＋--memory-limit連動〕→優先2 スピル→最終手段分割・--max-passes 上限）** → Task7/8（v3 の priority-1 memory 非依存誤読を根治）✓。size/binary skip・include/exclude・symlink・realpath（既存 walk 不変）→ Task5 ✓。進捗 stderr → Task4/9 ✓。§15 フェーズ2 資源 degrade を 2b ✓。§10.4 CLI → Task9 ✓。Phase 3 送りは境界に spec §番号付き明記 ✓。

**2. Placeholder scan:** 全 Task に実コード・実コマンド・期待出力。`graph_spilled` 発火点・`prog.done()`/`estore.close()` 位置（`try/finally`）・`scan_files=files`・`maybe_spill_now`（`_spill_now` 直呼び）を実コードで一意特定。テスト関数名は全角カッコ不使用（SyntaxError 回避）。`...`/「TBD」なし。

**3. Type consistency（串刺し）:** `MemoryBudget`(None/0/N)/`estimate_items`/`EdgeStore`(`in_memory_len`/`maybe_spill_now`=`_spill_now`直呼び/`_force_spill_threshold`=unit専用)/`serialize_edge`/`parse_edge`/`ripgrep.prefilter`(-a)/`Progress`/`collect_files`/`EngineOptions`(末尾既定6・非既定11先行・後方互換)/`run_fixedpoint(*, files=None)`/`_scan_file`(abspath)/`force_chunks`/`_apply_global_cap`（`--memory-limit=None` で Phase 2a 命令同値・超過時のみ keep 単調縮小） を冒頭契約と全 Task で一致。`memory_limit_mb=None`＆`force_chunks=0`＆`spill_dir=None` で degrade 全 no-op＝Phase 2a 完全同一（_apply_global_cap memory 分岐 `budget.unlimited` でスキップ・nchunks=1 で走査ループ逐語・estore 非スピル）＝既存 golden 14・既存 130 byte 不変を各 Step4 が要求。`_opts` 新6フィールド既定追加は Task7 Step1（Task6 新テストは `_opts()`＋`files=` のみ＝末尾既定不要で成立）。`try/finally: estore.close()` で例外時 temp リーク防止。

**4. 3巡目批判的レビュー（3並行）指摘の解消対応:** **Reviewer2 C1（v3 が priority-1 を --memory-limit 超過応答から外したのは spec §8.2 L164 誤読）根治**=priority-1 を `max_symbols`常設＋`--memory-limit`連動の §8.3 切り捨てに再設計（L164 主語節が3段統べる逐語準拠・既定 None は Phase 2a 命令同値）✓ / **Reviewer2 C2（intro が §8.2 L163 来歴メモリだが退避せず）根治**=priority-1 のシンボル切り捨て連動で intro 縮小（symbol 連動）＝§8.2 L163 充足 ✓ / **Reviewer2 H1（memory=0 が C2 で空証文）根治**=0 は priority-1 で keep=0 まで記録付き決定的切り捨て＋スピル＋分割（intro もシンボル連動で抑制）＝spec §8.2/§8.4/§1 整合の記録付き degrade ✓ / **Reviewer2 H2（Inv-2 が C1 解釈依存の循環）根治**=Inv-2 を「priority-1（§8.3・memory連動も）が唯一の出力変更で §8.4 全件記録・既定 None で byte 不変／spill・split は生存集合に §9 演繹で透過」と spec §8.2 L164 準拠で再記述 ✓ / **Reviewer1 H-1（maybe_spill_now が _force_spill_threshold を本番設定＝契約虚偽）根治**=`_spill_now()` 内部切り出し・`maybe_spill_now` は閾値非経由・契約も「unit 専用」明記 ✓ / **Reviewer1 H-2（estore 例外時 temp リーク）根治**=`try/finally: estore.close()` ✓ / **Reviewer3 M2（テスト名 全角カッコ SyntaxError）根治**=全テスト関数名から全角カッコ除去（区切り `_`）✓ / Reviewer1 M-1（automaton_split 診断＝nchunks vs 実パス数）→`len(chunks)` 記録＋`while nchunks<len(scan_syms)` クランプ ✓ / Reviewer1 M-2（spill/split の budget n_symbols 不整合）→共に `n_live` ✓ / Reviewer2 M2（複数kw §8.4 全件性 walk dedup 非巻き込み論証不足）→spec解釈/境界(5)に明記＋`test_複数keyword_diagnosticsは2回実行で決定的` ✓ / Reviewer1 H1（scan_line 昇順ユニーク前提固定）→`test_automatonのscan_lineは…分割正規化前提固定` ✓ / Reviewer2 M3/境界(7)（max_passes 上限後挙動）→境界(7) 設計判断格上げ＋Task8 注 ✓ / Reviewer3 M1（rg 環境 skip 受入）→Task0 Step3/Task11 受入条件 ✓ / Reviewer1/2 L（`or [[]]` 防御死コード・`--max-passes` spec文法外）→境界・実装注で既知明示（実害なし）✓。

> 次レビュー重点候補: ① priority-1 連動 `while keep>0` の `estimate_items(n_symbols=keep, n_edges=0, n_intro=keep)` の `n_intro≈keep` 近似（intro は実際は symbol 毎の親 Occurrence リスト長和＝keep 比例の決定的近似で妥当か）。② `memory_limit_mb=0` で keep=0→indirect 全切りが PRD 網羅性目的と spec §1「最大限追跡（ただしポリシー範囲・絶対ゼロ見落とし非保証）」の許容範囲か（ユーザが 0 を明示選択＋§8.4 全件記録＋direct 不変＝記録付き決定的 degrade として spec 整合と判断）。③ priority-1 memory 連動切り捨て後の golden（`--memory-limit` 指定の新規 golden を Phase 2b で足すか／既定 None の既存 golden 不変のみで足り memory degrade は unit/integration の決定性テストで担保＝後者を採用）。④ `--memory-limit` 小 N>0（>0 だが小）で keep がわずかに縮小するケースの小規模決定的検証（_ITEMS_PER_MB=4096 で N=1→4096 予算＝小規模 fixture では発火せず＝memory0 で keep=0 と max_symbols 小値の双方で priority-1 連動/常設を担保し中間 N は Phase 3 perf で実測）。⑤ `try/finally` 導入で Phase 2a の関数構造（seed ループ・走査・確定）が逐語保持されインデント変更のみで既定 byte 不変が崩れないこと（実装時 diff 最小化）。
