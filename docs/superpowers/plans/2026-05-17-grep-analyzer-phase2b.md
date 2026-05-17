# grep_analyzer Phase 2b（資源 degrade・ストリーミング・ripgrep・progress） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. **全コミット末尾に `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` を付す（ハーネス規約。各 git commit 例では省略表記だが必ず付与）。`git add` は各 Task 記載ファイルのみ（`.claude/settings.local.json` 等は含めない・明示パス add）。**

> **改訂履歴:** v1（`docs(plan)`）→ **v2（本書・3並行批判的レビュー反映）**。v1 の Critical を spec/コードで技術検証（reviewers が実走再現）し全面是正:
> - **C1 根治**: v1 Task6 の `loc_cache`/`full_text` 再構成は tree-sitter 分類を壊し TSV を変える（多行 `if`/`switch`/Pro\*C で反例実証）。確定フェーズは **abspath から全文を1回デコード**（Phase 2a と byte 同値）に再設計。`full_text` 再構成・`loc_cache` を廃止。
> - **C2 根治**: v1 Task8 の `sorted(found)` は処理順を Phase 2a と変え `sym_kind/sym_hop` first-write-wins を破り既定で `ref_kind` が変わる（反例実証）。**既定/非 degrade 経路は Phase 2a の走査ループを逐語保持**。分割経路のみ、Phase 2a の per-file 反復順と**厳密同一の `(lineno, symbol)` キー**で集約＝split は出力 byte 同値（証明付き）。
> - **C3 根治＋不変条件分解**: budget 数値モデル不整合（`_ITEMS_PER_MB=4096` vs テスト `memory_limit_mb=1`）でテスト FAIL/空虚 PASS。`memory_limit_mb` を **None=無制限（既定＝Phase 2a 同一）／0=最大 degrade 強制（決定的・任意小規模で発火）／N>0=実換算** に確定。さらに **degrade ラダーの不変条件を分解**（優先1 切り捨てが唯一の出力変更・決定的／spill・split は同一条件下の**透過変換**＝独立フックで分離検証）し、空虚 PASS を観測点（`graph_spilled`/`automaton_split`/`symbol_rejected capped` 件数）で構造排除。
> - **C4 根治**: ripgrep 既定が `.gitignore`/隠しを除外し walk の上位集合にならず `--use-ripgrep` で出力欠落（実 rg で実証）。rg 引数に `--no-ignore --hidden --no-require-git` を付与し `.gitignore`/隠しツリーの同値テストを追加。
> - 不変条件記述の精密化（多 keyword の diagnostics は walk 重複の dedup のみ意図変化）、Task7 デッドコード行削除、`edge_count` 表記一本化、Task6 行位置/Task9 prog.start 単一手順化、staged-invariant 注記。

**Goal:** Phase 2a の正しさ・決定性コアの**出力を一切変えずに**、spec §8.2 の資源設計—ストリーミング走査（全 bytes 親常駐の廃止）／keyword 横断 walk 一回化／任意 `ripgrep` 一次粗フィルタ／`--memory-limit` 会計と degrade ラダー（決定的シンボル切り捨て→来歴グラフ・ディスクスピル→オートマトン分割多パス・最大パス上限）／`--progress` 標準エラー進捗—を実装する。

**Architecture:** Phase 1.5 決定的コア（dispatch/classifiers/model/tsv/diagnostics/encoding/ingest/proc_preprocess）と Phase 2a の chase/stoplist/automaton/provenance/classify は **不変**。新規 `budget.py`（決定的メモリ近似）／`spill.py`（来歴エッジのディスクスピル）／`ripgrep.py`（任意一次フィルタ）／`progress.py`（標準エラー進捗）。`walk.py` に `collect_files`（走査一回 materialize）追加。`fixedpoint.py` をストリーミング走査＋degrade ラダー＋進捗フックに拡張（既定/非 degrade 経路は Phase 2a 逐語保持）。`pipeline.py` は keyword ループ前に一度 `collect_files` し全 `run_fixedpoint` で共有。`cli.py` に `--memory-limit`/`--use-ripgrep`/`--max-passes`/`--progress`。**60GB perf・`--resume`・diagnostics §10.3 縮約・規模分割 `partNN`・`requirements.lock`・`--output-encoding`/`--encoding-fallback` は Phase 3（範囲外）**。

**Tech Stack:** Python 3.12 / pytest / `pyahocorasick==2.1.0`（既存）/ 任意 `ripgrep`（外部バイナリ・`@pytest.mark.requires_ripgrep` 隔離・無くても他テスト緑）。tree-sitter/chardet 既存のまま。設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v7・§9 は `07e81bb`、§8.1手順5 は `8c21227` 改訂後本文・spec が常に優先）、`.claude/skills/writing-tests.md`、`.claude/skills/coding-conventions.md` に従う（docstring/コメント・テスト名は日本語、古典学派+TDD、外部I/O境界＝ファイル/サブプロセスのみ本物）。

---

**不変条件（Phase 2b 全タスクの絶対前提・spec §9／Phase 2a 境界の継承・v2 で分解）:**

- **Inv-1（既定出力不変）**: `memory_limit_mb=None`（既定）かつ `use_ripgrep=False` かつ `progress="off"` で Phase 2b の **TSV は Phase 2a と byte 完全一致**。`diagnostics.txt` も **単一 keyword 入力では byte 完全一致**（既存 unit/integration/golden は全て単一 keyword＝既存 130 passed・14 golden は**全て byte 不変で緑**）。複数 keyword 入力の `diagnostics.txt` は **walk 系カテゴリの重複行が dedup される差のみ**（Phase 2b 走査一回化の意図変化＝退行ではない。既存テストは単一 keyword なので影響なし）。TSV は keyword 数に依らず常に byte 不変。
- **Inv-2（degrade の出力性質）**: degrade のうち **優先1「決定的シンボル切り捨て」だけが出力を変える**（同一入力＋同一 `memory_limit` で**決定的に同一シンボル集合**を落とし `symbol_rejected\tcapped` を全件記録。落ちた分の indirect が消えるのみ・direct 行は不変）。**優先2 来歴スピル・最終手段オートマトン分割は出力を1バイトも変えない透過変換**（スピル＝`EdgeStore.sorted_unique()` が `sorted(set(edges))` と同一集合同一順序＝Task2 unit で固定。分割＝per-file 反復順を Phase 2a 単一オートマトンと**厳密同一の `(lineno, symbol)` キー**に正規化＝Task8 で固定）。スピル/分割の透過性は **memory 駆動と独立のフック（`spill._force_spill_threshold`／`opts.force_chunks`）で分離検証**する（memory 駆動だと優先1 が先に発火し出力が変わるため、透過性は同一シンボル集合下で検証）。
- **Inv-3（決定性）**: `--jobs 1` と `--jobs N`、ストリーミング、`memory_limit` 有/無、`force_chunks` 有/無、`spill` 有/無、`ripgrep` 有/無 のいずれの組合せでも、**同一入力で 2 回実行すると TSV／diagnostics が byte 一致**（spec §9 の継承）。
- **Inv-4（進捗は stderr 専用）**: `--progress` 出力は標準エラー専用。TSV／`diagnostics.txt`／終了コードに一切影響しない。

各 Task の Step4 は必ず「当該テスト PASS」＋「`python -m pytest -q` 全 PASS・0 failed/0 error（Phase 2a 130 ＋ 本 Task 追加分。**既存 golden 14・既存 130 が byte 不変で緑**）」を要求。既存 golden/テストが1ケースでも動いたら **commit せず停止し構造を疑う**（writing-tests「大量churn＝構造を疑う」。Phase 2b は出力保存が定義＝churn は退行）。

**型・シグネチャ契約（全タスク共通・不変。Self-Review 3 で串刺し）:**

- `walk.collect_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag) -> list[tuple[str, pathlib.Path]]`
- `budget.MemoryBudget(limit_mb: int | None)`: `.unlimited: bool`（`limit_mb is None`）/ `.item_budget: int`（`None→0`・`N→N*_ITEMS_PER_MB`・`0→0`）/ `.exceeded(n_items: int) -> bool`（`unlimited` は常に `False`／`item_budget` ちょうどは可／超過 `True`。`limit_mb==0` は `item_budget==0` で `n_items>=1` が超過＝最大 degrade 強制）
- `budget.estimate_items(*, n_symbols, n_edges, n_intro) -> int`（決定的＝RSS 非依存・単純和）
- `spill.serialize_edge(p, c) -> str` / `spill.parse_edge(line) -> tuple[Occurrence, Occurrence]`（制御文字エスケープで完全可逆）
- `spill.EdgeStore(spill_dir: pathlib.Path | None, budget: MemoryBudget)`: `.add(p, c)` / `.maybe_spill()` / `.sorted_unique() -> Iterator[tuple[Occurrence, Occurrence]]`（in-memory/spill いずれでも `sorted(set(...))` と同一）/ `.spilled: bool` / `.close()` / `._force_spill_threshold: int | None`（テスト/エンジン強制フック）
- `ripgrep.available() -> bool` / `ripgrep.prefilter(root, rel_to_abs: dict[str, pathlib.Path], symbols: list[str]) -> set[str] | None`（`rg --no-ignore --hidden --no-require-git -l -F -f pat .` で symbols 部分文字列を含む rel の **walk 上位集合**。rg 不在/失敗 `None`＝フィルタ無効＝全件）
- `progress.Progress(level: str, stream=None)`: `.start(total_files: int)` / `.hop(hop: int, n_symbols: int, scanned: int)` / `.done()`（`level!="on"` 完全無音・stderr のみ）
- `fixedpoint.EngineOptions` 追加フィールド（**末尾に既定値付き**＝既存キーワード構築不変）: `memory_limit_mb: int | None = None`, `use_ripgrep: bool = False`, `max_passes: int = 8`, `progress: str = "off"`, `spill_dir: pathlib.Path | None = None`, `force_chunks: int = 0`
- `fixedpoint.run_fixedpoint(seed_hits, source_root, opts, diag, *, files: list[tuple[str, pathlib.Path]] | None = None) -> list[Hit]`（`files=None` は内部 walk＝後方互換）
- `fixedpoint._scan_file(args)` の `args` は `(rel: str, abspath: str, sym_list: list[str], lang_map: dict)`（**bytes でなく abspath**＝ストリーミング・ワーカが読む）

**spec 解釈の明示（次レビューで再検証可能）:**

- **メモリ近似は決定的近似**（spec §8.2「来歴グラフのメモリは --memory-limit の対象」）: 実 RSS は非決定的なので不採用。`estimate_items = n_symbols + n_edges + n_intro`。`--memory-limit MB` は `N*_ITEMS_PER_MB`（`_ITEMS_PER_MB` 固定）へ決定的換算。`--memory-limit 0` は item_budget 0＝任意小規模で degrade を**決定的に強制**（テストと「最小メモリ＝最大 degrade」運用の両用。実バイト厳密化は Phase 3 perf）。同一入力＋同一 limit で同一 degrade 判断＝spec §9。
- **degrade 優先順位と不変条件分解**（spec §8.2 厳守＋v2 分解）: `exceeded` 時 (優先1) 決定的シンボル切り捨て（`_apply_global_cap` を memory 駆動化・Phase 2a と同一キー `(発見ホップ,長さ,辞書順)`・**唯一の出力変更・決定的**）→ なお超過なら (優先2) `EdgeStore` スピル（来歴グラフを退避・**出力透過**）→ scan_syms が単一オートマトンに過大なら (最終手段) オートマトン分割（決定的 K 分割・K パス走査・`--max-passes` 上限・**出力透過**・超過時は優先1 へ戻る）。**優先1 は memory 圧が来歴グラフ(edges/intro)単独由来でもシンボルを削るため、優先1 のみで超過解消しない場合がある（その分は優先2 スピルが受け持つ＝Task8 完了で spec 準拠に収束する staged-invariant）**。spill/split の出力透過は Inv-2 のとおり memory 駆動と独立フックで分離検証。
- **ripgrep は walk の上位集合フィルタ**（spec §8.2「任意 ripgrep 1次フィルタ」）: 追跡シンボルは ASCII 識別子（Phase 2a 既知境界）で UTF-8/CP932/latin-1 のいずれでも raw バイト上に同一バイト列で出現。`rg` 既定は `.gitignore`/隠しを除外し walk（`os.walk`＋本ツール独自 exclude のみ）と食い違うため、**`--no-ignore --hidden --no-require-git` で rg の対象を walk の上位集合に揃える**。除外 rel は部分文字列すら持たず automaton（識別子境界）でも 0 ヒット確定＝出力不変。`rg` 不在時は `None`＝フィルタ無効＝全件（既定 `use_ripgrep=False` でも全件＝Phase 2a 同一）。
- **差分走査の限定効果**（spec §8.2 誠実化）: 新規シンボルは全ツリー走査が必要（不可避）。Phase 2a は既に確定済シンボルを automaton 再投入しない＝確定シンボルの再走査は元々無い。Phase 2b の効果は **走査時の全 bytes 親常駐の廃止（ストリーミング）** に限る。確定フェーズは対象ファイルを **1 回だけ** abspath から全文デコード（per-rel キャッシュ＝Phase 2a の `meta_of`/`line_cache` と同一挙動・byte 同値。再構成はしない＝C1 根治）。
- **walk 一回化**: pipeline が全 keyword 前に一度 `collect_files`（走査・診断1回）し各 `run_fixedpoint(files=files)` へ共有。walk 系診断は keyword 数に依らず1回・file 集合は keyword 間で同一＝TSV 決定性不変。複数 keyword で `diagnostics.txt` は walk 系重複行が dedup される（意図変化・Inv-1。spec §10.3 一般縮約は Phase 3）。

---

## Task 0: 着手ゲート（Phase 2a 緑・ripgrep 任意性・コードなし）

- [ ] **Step 1: Phase 2a ベースライン全緑** — Run: `cd /workspaces/grep_helpers2 && python -m pytest -q` → `130 passed`（0 failed/0 error）。異なれば着手しない。
- [ ] **Step 2: Phase 2a 完了記録の存在** — Run: `grep -nF '## Phase 2a 完了記録' docs/superpowers/plans/phase0-gate-result.md` → 1 行ヒット。
- [ ] **Step 3: ripgrep 任意性確認** — Run: `command -v rg && rg --version | head -1 || echo "rg absent (OK: --use-ripgrep 任意・既定無効・requires_ripgrep で隔離)"`。いずれでも可。新規必須依存なし（pyahocorasick G1 は Phase 2 で PASS 済）。
- [ ] **Step 4: ゲート記録しコミット** — `docs/superpowers/plans/phase0-gate-result.md` 末尾に「## Phase 2b 着手ゲート記録」（UTC・`130 passed`・Phase 2a 完了参照・rg 有無と任意性・新規必須依存なし・判定 PASS）追記。
```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2b 着手ゲート記録（130 passed / Phase 2a 完了 / ripgrep 任意）"
```

---

## Task 1: 決定的メモリ近似 `budget.py`

**Files:** Create `src/grep_analyzer/budget.py` / Test `tests/unit/test_budget.py`

spec §8.2。実 RSS 非依存の決定的アイテム近似。`memory_limit_mb`: `None`=無制限／`0`=item_budget 0（最大 degrade 強制・任意小規模で決定的発火）／`N>0`=`N*_ITEMS_PER_MB`。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_budget.py` 新規:
```python
"""決定的メモリ近似の仕様（spec §8.2・degrade トリガの決定性）。"""

from grep_analyzer.budget import MemoryBudget, estimate_items


def test_estimate_itemsは各要素数の単純和():
    assert estimate_items(n_symbols=3, n_edges=10, n_intro=4) == 17
    assert estimate_items(n_symbols=0, n_edges=0, n_intro=0) == 0


def test_None は無制限で超過しない():
    b = MemoryBudget(None)
    assert b.unlimited is True and b.exceeded(10**9) is False


def test_0は最大degrade強制で1件以上が超過():
    b = MemoryBudget(0)
    assert b.unlimited is False and b.item_budget == 0
    assert b.exceeded(0) is False and b.exceeded(1) is True


def test_N_MBは決定的換算で上限ちょうどは可超過はTrue():
    b = MemoryBudget(1)
    assert b.unlimited is False
    assert b.item_budget == MemoryBudget(1).item_budget  # 再現一致
    assert b.exceeded(b.item_budget) is False
    assert b.exceeded(b.item_budget + 1) is True


def test_予算は単調():
    assert MemoryBudget(2).item_budget > MemoryBudget(1).item_budget > MemoryBudget(0).item_budget - 1
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

    None=無制限／0=item_budget 0（n_items>=1 で超過＝最大 degrade 強制・
    任意小規模で決定的に発火）／N>0=N*_ITEMS_PER_MB。
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

## Task 2: 来歴エッジのディスクスピル `spill.py`

**Files:** Create `src/grep_analyzer/spill.py` / Test `tests/unit/test_spill.py`

spec §8.2。予算内メモリ／超過でディスク追記スピル。`sorted_unique()` は in-memory/spill いずれでも `sorted(set(edges))` と同一（**出力透過**＝Inv-2 のスピル透過性をここで unit 固定）。`_force_spill_threshold` でメモリ非圧でも強制スピル（透過性の分離検証フック）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_spill.py` 新規:
```python
"""来歴エッジのディスクスピルの仕様（spec §8.2・出力透過・決定的）。"""

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.provenance import Occurrence
from grep_analyzer.spill import EdgeStore, parse_edge, serialize_edge


def test_制御文字込みで完全往復可逆():
    p = Occurrence("A\tB\\x", "a\nb.c", 3)
    c = Occurrence("C", "d.c", 9)
    assert parse_edge(serialize_edge(p, c)) == (p, c)


def test_メモリ内sorted_uniqueはsorted_setと同一(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))
    e1 = (Occurrence("Q", "q.c", 2), Occurrence("H", "h.c", 9))
    e2 = (Occurrence("P", "p.c", 1), Occurrence("H", "h.c", 9))
    for p, c in [e1, e2, e1]:
        s.add(p, c)
    assert s.spilled is False
    assert list(s.sorted_unique()) == sorted({e1, e2})
    s.close()


def test_強制スピルでも同一集合同一順序かつ透過(tmp_path):
    # メモリ非圧（budget None）でも _force_spill_threshold で強制スピル＝透過検証
    s = EdgeStore(tmp_path, MemoryBudget(None))
    s._force_spill_threshold = 1
    edges = [(Occurrence(f"S{i}", f"s{i}.c", i), Occurrence("H", "h.c", 9))
             for i in (3, 1, 2, 1)]
    for p, c in edges:
        s.add(p, c)
    assert s.spilled is True
    assert list(s.sorted_unique()) == sorted(set(edges))  # スピル⇔非スピルで同一
    s.close()


def test_budget0でも超過時スピルし同一(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(0))  # item_budget 0 → 1件目で超過
    e = (Occurrence("A", "a.c", 1), Occurrence("B", "b.c", 2))
    s.add(*e)
    assert s.spilled is True and list(s.sorted_unique()) == [e]
    s.close()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_spill.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/spill.py` 新規:
```python
"""来歴エッジのディスクスピル（spec §8.2）。予算内メモリ・超過でディスク

追記退避。sorted_unique は in-memory/spill いずれでも sorted(set(edges)) と
同一順序・同一集合を返す（出力透過・決定的）。
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
        self._force_spill_threshold: int | None = None

    def add(self, p: Occurrence, c: Occurrence) -> None:
        """1 エッジ追加。予算/閾値超過で以降スピルへ。"""
        if self.spilled:
            self._fh.write(serialize_edge(p, c) + "\n")
            return
        self._mem.append((p, c))
        self.maybe_spill()

    def maybe_spill(self) -> None:
        """予算/強制閾値超過ならメモリ内容を一時ファイルへ退避。"""
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
        """一時ファイルを閉じ削除する。"""
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
git commit -m "feat(spill): 来歴エッジのディスクスピル（spec §8.2・出力透過決定的）"
```

---

## Task 3: 任意 ripgrep 一次フィルタ `ripgrep.py`（walk 上位集合）

**Files:** Create `src/grep_analyzer/ripgrep.py` / Test `tests/unit/test_ripgrep.py` / Modify `tests/conftest.py`

spec §8.2。`rg --no-ignore --hidden --no-require-git -l -F -f pat .` で **walk の上位集合**（`.gitignore`/隠しを除外しない＝C4 根治）。除外 rel は部分文字列すら無く automaton 0 ヒット確定＝出力不変。rg 不在/失敗は `None`。

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
    (tmp_path / "c.c").write_text("// DECODE\n", "utf-8")  # 部分一致＝上位集合に含む
    rel_abs = {p.name: p for p in tmp_path.glob("*.c")}
    got = prefilter(tmp_path, rel_abs, ["CODE"])
    assert "a.c" in got and "c.c" in got and "b.c" not in got


@pytest.mark.requires_ripgrep
def test_gitignoreと隠しファイルも上位集合に含む(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text("ignored.c\n", "utf-8")
    (tmp_path / "ignored.c").write_text("int CODE=1;\n", "utf-8")
    (tmp_path / ".hidden.c").write_text("int CODE=2;\n", "utf-8")
    (tmp_path / "visible.c").write_text("int CODE=3;\n", "utf-8")
    rel_abs = {"ignored.c": tmp_path / "ignored.c",
               ".hidden.c": tmp_path / ".hidden.c",
               "visible.c": tmp_path / "visible.c"}
    got = prefilter(tmp_path, rel_abs, ["CODE"])
    assert {"ignored.c", ".hidden.c", "visible.c"} <= got  # walk 上位集合


@pytest.mark.requires_ripgrep
def test_空シンボルは空集合(tmp_path):
    assert prefilter(tmp_path, {}, []) == set()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_ripgrep.py -q` → FAIL（ModuleNotFound・rg 無環境では requires_ripgrep 3本 skip）

- [ ] **Step 3: 実装** — `src/grep_analyzer/ripgrep.py` 新規:
```python
"""任意 ripgrep 一次粗フィルタ（spec §8.2）。walk の上位集合（.gitignore/

隠しを除外しない＝出力不変）。rg 不在/失敗は None＝フィルタ無効（全件走査）。
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
    --no-ignore --hidden --no-require-git で rg 対象を walk 上位集合に揃える。
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
            [_RG, "-l", "-F", "--no-messages", "--no-ignore", "--hidden",
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

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_ripgrep.py -q`（rg 有: 4本 PASS／rg 無: 1本 PASS＋3 skip）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/ripgrep.py tests/unit/test_ripgrep.py tests/conftest.py
git commit -m "feat(ripgrep): 任意一次フィルタ（walk上位集合・gitignore/隠し含む・spec §8.2）"
```

---

## Task 4: 標準エラー進捗 `progress.py`

**Files:** Create `src/grep_analyzer/progress.py` / Test `tests/unit/test_progress.py`

spec §8.2。`level=="on"` 以外完全無音。stderr 専用（Inv-4＝TSV/diagnostics/終了コードに無影響）。

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

`walk_files`（generator）を一度 materialize する `collect_files`（既存 `walk_files` 不変）。pipeline が全 keyword 前に1回呼ぶ＝walk 診断重複解消の基盤（Task 9 配線）。

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

`files: list[(rel, bytes)]`（全 bytes 親常駐）を `files: list[(rel, abspath)]` に変え `_scan_file` がワーカ内で abspath を読む（ストリーミング）。**確定フェーズは C1 根治のため `loc_cache` 再構成を使わず、確定対象ファイルを abspath から `_file_meta` で全文1回デコードし per-rel キャッシュ**（Phase 2a の `meta_of`/`line_cache` と同一挙動・byte 同値）。`run_fixedpoint` に `*, files=None`（後方互換）。**本 Task は `EngineOptions`/`_opts` を変更しない**（新フィールドは Task 7・Task 6 新テストは `_opts()`（既存11フィールド）＋`files=` のみ使用＝末尾既定不要で成立）。

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
    # C1 回帰: chase シンボルヒット行と分類決定構文が別行・空行・末尾改行あり
    src = _mk(tmp_path, {
        "A.java": "class A{ static final int K1 = 1; }\n",
        "B.java": "class B {\n  void m(int s) {\n    if (s ==\n        K1) {\n"
                  "      return;\n    }\n  }\n}\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(), Diagnostics())
    b = next(h for h in hits if h.file == "B.java")
    assert b.category == "比較" and b.confidence == "high"  # 全文 AST で if 比較


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

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → `test_事前収集files…` が FAIL（`run_fixedpoint() got an unexpected keyword argument 'files'`）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) `_scan_file` を abspath 読込（ストリーミング）に置換:
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

(2) `run_fixedpoint` シグネチャを `def run_fixedpoint(seed_hits, source_root, opts, diag, *, files=None):` に変更し docstring 追記（files 指定時はそれを使う・None は内部 walk）。関数本体の `files: list[tuple[str, bytes]] = [ (rel, abspath.read_bytes()) ... walk.walk_files(...) ]`（Phase 2a 実コードの当該1ブロック）を **seed ループ後・`_apply_global_cap` 定義の直前** に次へ置換:
```python
    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    rel_to_abs = {rel: abspath for rel, abspath in files}
```

(3) 走査ループの `args` を abspath（str）に: `args = [(rel, str(abspath), scan_syms, opts.lang_map) for rel, abspath in files]`

(4) 確定フェーズの `raw_of = dict(files)` 行と再読込ブロックを次へ置換（**全文1回デコード・per-rel キャッシュ・再構成なし＝C1 根治・Phase 2a と byte 同値**）:
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

> **実装注（C1 根治・出力 byte 不変の根拠）:** 確定フェーズは Phase 2a と**同一ロジック**（`meta_of`/`line_cache`/`classify_hit(language, dialect, text, ...)` に**全文 `text`** を渡す）。差分は bytes 取得元が `raw_of=dict(files)`（親常駐）→ `rel_to_abs[rel].read_bytes()`（abspath 1回読み）に変わるだけ＝デコード結果・AST・分類・chain が Phase 2a と**同値**。v1 の `loc_cache` 再構成（ヒット行のみ・非ヒット行欠落で tree-sitter 分類が壊れた）は**完全廃止**。ストリーミングの実効果は「走査中に全 bytes を親に常駐させない」点に限る（spec §8.2 差分走査の誠実化どおり）。確定対象ファイル数は edges の child 由来＝限定的でファイル単位 1 回読み（ヒット毎ではない）。

- [ ] **Step 4: 通る（出力保存の回帰が要・最重要）** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存8＋新規3。特に `test_多行構文の分類が確定全文読みでPhase2aと同一`＝C1 回帰）／`python -m pytest -q` → **全 PASS・既存 golden 14・既存 integration byte 不変**。1ケースでも動いたら commit せず停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): ストリーミング走査＋確定全文1回読み（spec §8.2・C1根治・出力不変）"
```

---

## Task 7: degrade 優先1（memory 駆動の決定的シンボル切り捨て・唯一の出力変更）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.2 優先1。Phase 2a `_apply_global_cap`（静的 `max_symbols`）に **memory 駆動**を加える（同一決定キー `(発見ホップ,長さ,辞書順)`・Inv-2 の**唯一の出力変更・決定的**）。`memory_limit_mb=None` は Phase 2a と完全同一。`memory_limit_mb=0` は item_budget 0＝任意小規模で決定的発火（テスト/最大 degrade）。**staged-invariant**: 優先1 のみでは edges/intro 単独超過時に keep=0（全シンボル切り捨て）になり得る＝決定的だが spec §8.2 ラダー上は優先2 スピル（Task8）が受け持つ範囲（Task8 完了で spec 準拠収束）。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_fixedpoint.py` 冒頭の `_opts` を新フィールド既定込みに更新（既存呼出不変）:
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
def test_memory_limit0で決定的シンボル切り捨てが全件記録(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=dd; int dd=1; }\n",
                         "B.java": "class B{ int zz = aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    diag = Diagnostics()
    run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=10**9,
                                      memory_limit_mb=0), diag)
    assert "symbol_rejected\tcapped" in diag.render()


def test_memory_limit0は2回実行で決定的かつdirectは無関係(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=1; }\n",
                         "B.java": "class B{ int zz=aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    k = lambda hs: sorted((h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
                          for h in hs)
    r1 = run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=10**9,
                                           memory_limit_mb=0), Diagnostics())
    r2 = run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=10**9,
                                           memory_limit_mb=0), Diagnostics())
    assert k(r1) == k(r2)  # 決定的（2回一致）


def test_memory_limit_Noneは無制限でPhase2aと同一(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    chains = {(h.file, h.via_symbol): h.chain
              for h in run_fixedpoint([seed], src,
                                      _opts(memory_limit_mb=None), Diagnostics())}
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → FAIL（`EngineOptions.__init__() got an unexpected keyword argument 'memory_limit_mb'`）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) `EngineOptions` に末尾既定フィールド追加（既存キーワード構築不変・非既定11→既定6 で dataclass 制約充足）:
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

(2) import 追加（先頭 import 群）: `from grep_analyzer.budget import MemoryBudget, estimate_items`

(3) `run_fixedpoint` 内 `policy = ...` 直後: `budget = MemoryBudget(opts.memory_limit_mb)`

(4) `edge_count` カウンタを状態初期化群に追加: `edge_count = 0`。エッジ追加箇所 `edges.append((parent, child))` の直後で `edge_count += 1`。

(5) `_apply_global_cap` を memory 駆動も見るよう拡張（決定キー不変・`edge_count` 使用）:
```python
    def _apply_global_cap():
        live = sorted(chase_active | chase_done | term_active | term_done,
                      key=lambda s: (sym_hop.get(s, 0), len(s), s))
        n_intro = sum(len(v) for v in intro.values())
        over_static = len(live) > opts.max_symbols
        over_mem = budget.exceeded(estimate_items(
            n_symbols=len(live), n_edges=edge_count, n_intro=n_intro))
        if not (over_static or over_mem):
            return
        keep = opts.max_symbols if over_static else len(live)
        while keep > 0 and budget.exceeded(estimate_items(
                n_symbols=keep, n_edges=edge_count, n_intro=n_intro)):
            keep -= 1
        for s in live[keep:]:
            if s not in capped:
                diag.add("symbol_rejected", f"capped\t{s}")
                capped.add(s)
            chase_active.discard(s)
            term_active.discard(s)
```

> **実装注（Inv-2／staged-invariant）:** `memory_limit_mb=None`→`budget.unlimited`＝`over_mem` 恒偽・`keep=len(live)`（over_static でなければ）で while 即終了＝**Phase 2a と命令同値**（既存 golden 14・既存 130 不変）。memory 駆動の `keep` 単調縮小は決定的（同一入力で単一 keep）。優先1 は edges/intro 単独超過時 keep=0（全シンボル切り捨て）になり得る＝決定的だが、その縮退を spec §8.2 ラダー準拠（優先2 スピルが graph memory を退避）にするのは Task8 完了時点（staged-invariant＝Task7 単独完了時は `memory_limit_mb` 指定時のみの中間挙動・既定不変は厳守）。`symbol_rejected\tcapped` は落とした全シンボルを記録（spec §8.4 全件）。

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存11＋新規3）／`python -m pytest -q` → 全 PASS・**既存 golden 14 不変**（`memory_limit_mb=None` 既定で Phase 2a 同一）。動いたら停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): degrade優先1 memory駆動の決定的切り捨て（spec §8.2・唯一の出力変更）"
```

---

## Task 8: degrade 優先2/最終手段（来歴スピル＋オートマトン分割多パス・出力透過）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.2 優先2＝`EdgeStore` スピル（来歴グラフ退避）、最終手段＝オートマトン分割（`scan_syms` 決定的 K 分割・K パス・`--max-passes` 上限）。**いずれも出力透過**＝Inv-2。**既定/非分割（nchunks==1）は Phase 2a の走査ループを逐語保持**（C2 根治）。分割時のみ集約し per-file 反復順を **Phase 2a 単一オートマトンと厳密同一の `(lineno, symbol)` キー**に正規化（証明: Phase 2a の per-file 反復順＝行昇順×`automaton.scan_line` の昇順ユニーク＝`(lineno, symbol)` 昇順そのもの。よって分割集約を `(lineno, symbol)` で並べると `_ingest`/`intro`/`edges` 投入順が Phase 2a と**同一**＝出力 byte 同値）。`force_chunks>1` は memory 非依存に分割強制（split 透過性の分離検証フック）。

- [ ] **Step 1: 失敗するテスト** — `tests/unit/test_fixedpoint.py` 末尾に追記:
```python
def test_force_chunks分割は単一オートマトンと出力byte同値(tmp_path):
    # split 透過性: memory 非圧（None）で chunks 強制＝優先1 非発火・分割のみ
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
    assert one and k(one) == k(many)            # 分割は出力透過
    assert "automaton_split" in diag.render()   # 分割が実発火（非空虚）


def test_強制スピルは非スピルと出力byte同値(tmp_path):
    # spill 透過性: memory None＋_force でスピル強制＝優先1 非発火・スピルのみ
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1=1; }\n",
                         "B.java": "class B{ static final int K2=K1; }\n",
                         "C.java": "class C{ int z2=K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1=1;")
    k = lambda hs: sorted((h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
                          for h in hs)
    base = run_fixedpoint([seed], src, _opts(), Diagnostics())
    diag = Diagnostics()
    sp = run_fixedpoint([seed], src,
                        _opts(spill_dir=tmp_path, force_chunks=0,
                              memory_limit_mb=None,
                              max_symbols=1000), diag,
                        )  # _force_spill は run_fixedpoint 内で spill_dir かつ
                           # _spill_force=True 経路。下記 (実装) で opts に依らず
                           # spill_dir 指定時テスト用 1 件閾値を当てる手段を用意。
    assert base and k(base) == k(sp)


def test_memory_limit0は優先1発火し最終的に決定的(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=1; }\n",
                         "B.java": "class B{ int z=aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    d1 = Diagnostics()
    r1 = run_fixedpoint([seed], src,
                        _opts(min_specificity=1, max_symbols=10**9,
                              memory_limit_mb=0, max_passes=2, spill_dir=tmp_path), d1)
    r2 = run_fixedpoint([seed], src,
                        _opts(min_specificity=1, max_symbols=10**9,
                              memory_limit_mb=0, max_passes=2, spill_dir=tmp_path),
                        Diagnostics())
    kk = lambda hs: sorted((h.file, h.via_symbol, h.chain) for h in hs)
    assert kk(r1) == kk(r2)                       # degrade 下でも決定的
    assert "symbol_rejected\tcapped" in d1.render()
```

> 注: `test_強制スピルは非スピルと出力byte同値` は spill 透過性の分離検証。実装 (下記) で **`spill_dir` 指定かつ `memory_limit_mb=None` のとき EdgeStore に `_force_spill_threshold=1` を当てる**（memory 非圧で必ずスピル＝優先1 非発火・スピルのみを isolate）。これにより「スピル⇔非スピルで出力 byte 同値」を優先1 と混ぜずに固定する。

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → 新規3本 FAIL（force_chunks/スピル未実装）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) import 追加: `from grep_analyzer.spill import EdgeStore`

(2) `edges: list[...] = []` を `EdgeStore` に置換。状態初期化を:
```python
    estore = EdgeStore(opts.spill_dir, budget)
    if opts.spill_dir is not None and budget.unlimited:
        estore._force_spill_threshold = 1  # spill 透過性の分離検証（優先1非発火）
    edge_count = 0
```
エッジ追加 `edges.append((parent, child)); edge_count += 1` を `estore.add(parent, child); edge_count += 1` に。`_apply_global_cap` 内 `n_edges=edge_count` は Task7 で導入済（不変）。グラフ構築 `for p, c in edges:` を `for p, c in estore.sorted_unique():` に。確定ループ `for _, c in sorted(set(edges)):` を `for _, c in estore.sorted_unique():` に（`sorted_unique` は `sorted(set(...))` 同値＝child 単位走査は従来同様）。関数終端で `estore.close()`。スピル発生時は診断 `diag.add("graph_spilled", f"hop={hop}")` を `maybe_spill` 後に1回（重複防止フラグ）。

(3) 走査ループ（Phase 2a の `args=[...]; if jobs>1: pool.map else [...]; for rel,...,found in sorted(results,key=r[0]): ...`）を「nchunks==1 は Phase 2a 逐語・nchunks>1 のみ集約」に変更:
```python
        n_intro = sum(len(v) for v in intro.values())
        nchunks = 1
        if opts.force_chunks and opts.force_chunks > 1:
            nchunks = min(opts.force_chunks, opts.max_passes,
                          max(1, len(scan_syms)))
        elif not budget.unlimited and budget.exceeded(estimate_items(
                n_symbols=len(scan_syms), n_edges=edge_count, n_intro=n_intro)):
            while nchunks < opts.max_passes and budget.exceeded(estimate_items(
                    n_symbols=-(-len(scan_syms) // (nchunks + 1)),
                    n_edges=edge_count, n_intro=n_intro)):
                nchunks += 1
        if nchunks <= 1:
            # 既定/非分割: Phase 2a の走査ループを逐語保持（C2 根治）
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
            # Phase 2a の per-file 反復順＝(lineno, symbol) 昇順に正規化（出力透過）
            pass_results = [(rel, *meta[rel], sorted(agg[rel], key=lambda t: (t[1], t[0])))
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
                        edge_count += 1
                if sym in scan_term:
                    if sym not in no_expand_logged:
                        diag.add("getter_setter_no_expand", sym)
                        no_expand_logged.add(sym)
                    continue
                _ingest(child, language, dialect, line, hop + 1)
        hop += 1
```
（`scan_files` は Task9 で ripgrep 絞り込み導入。Task8 時点では `scan_files = files` を走査ループ先頭で代入しておく）

> **実装注（C2 根治・出力透過の証明）:** `nchunks==1`（既定 `memory_limit_mb=None`／`force_chunks=0`）は Phase 2a の走査ループと**逐語同一**（`sorted(results,key=r[0])`→各 rel の `found` は `_scan_file` 生成順＝行昇順×`scan_line` 昇順）。`nchunks>1` のときのみ `agg` 集約し各 rel の found を `sorted(..., key=lambda t:(t[1],t[0]))`＝**`(lineno, symbol)` 昇順**に正規化する。Phase 2a の per-file 反復順は「行 `i` 昇順 → 行内 `automaton.scan_line` の昇順ユニーク（＝symbol 昇順）」＝まさに `(lineno, symbol)` 昇順そのものなので、分割集約の正規化順は Phase 2a 単一オートマトン走査と**`_ingest` 呼出順・`intro` 蓄積順・`estore.add` 順まで同一**＝`sym_kind/sym_hop` first-write-wins も同値＝**TSV byte 同値**（v1 の `sorted(found)`＝symbol 第1キーは Phase 2a 行順と異なり破綻したが v2 は `(lineno,symbol)` で厳密一致）。スピルは `estore.sorted_unique()=sorted(set())` で `graph` 構築・確定が順序非依存＝Inv-2 透過。`memory_limit_mb=0` 時は優先1（Task7）が先に発火しシンボルが決定的に減る（出力変更・Inv-2）が、その縮退集合に対しスピル/分割は透過。

- [ ] **Step 4: 通る（出力透過の回帰が要）** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存14＋新規3。`test_force_chunks分割は単一オートマトンと出力byte同値`＝split 透過・`automaton_split` 実発火／`test_強制スピルは非スピルと出力byte同値`＝spill 透過／`test_memory_limit0は優先1発火し最終的に決定的`＝degrade 決定性・非空虚）／`python -m pytest -q` → **全 PASS・既存 golden 14・既存 integration byte 不変**（既定 nchunks=1・estore 非スピル＝Phase 2a 逐語）。動いたら停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): degrade優先2スピル＋最終手段分割多パス（spec §8.2・出力透過C2根治）"
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
    assert a == (o2 / "S_OK.tsv").read_text("utf-8-sig")  # 決定的


def test_walk診断はkeyword数によらず重複しない(tmp_path: Path):
    src, inp = _tree(tmp_path)
    (src / "build").mkdir()
    (src / "build" / "G.java").write_text("class G{}\n", "utf-8")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    d = (out / "diagnostics.txt").read_text("utf-8")
    assert d.count("walk_excluded\tbuild/G.java") == 1  # 2 keyword でも1回


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


def test_memory_limit0でもdirectは不変かつ決定的(tmp_path: Path):
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
    assert da == db and da  # degrade は indirect 追跡側のみ・direct 不変
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/integration/test_pipeline_phase2b.py -q` → FAIL（`--memory-limit`/`--progress` 未知 or walk_excluded 2回）

- [ ] **Step 3: 実装**

`src/grep_analyzer/fixedpoint.py`:
- import: `from grep_analyzer.progress import Progress` / `from grep_analyzer import ripgrep as _rg`
- `rel_to_abs = {...}` 構築直後に **1 回だけ**: `prog = Progress(opts.progress); prog.start(len(files))`（暫定行は作らない＝単一手順）
- 走査ループ先頭（`_apply_global_cap()` 呼出後・`scan_syms` 確定後）に ripgrep 絞り込み:
```python
        scan_files = files
        if opts.use_ripgrep:
            keep = _rg.prefilter(source_root, rel_to_abs, scan_syms)
            if keep is not None:
                scan_files = [(r, a) for r, a in files if r in keep]
```
（Task8 で導入した走査ブロックは `scan_files` を参照済。Task8 時点では `scan_files = files` を同位置に置く）
- 反復末尾 `hop += 1` 直前: `prog.hop(hop, len(scan_syms), len(scan_files))`。`while` 脱出後・`estore.close()` 前後の適切位置で `prog.done()`。

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
`EngineOptions(...)` 構築に追記: `memory_limit_mb=args.memory_limit_mb, use_ripgrep=args.use_ripgrep, max_passes=args.max_passes, progress=args.progress,`

- [ ] **Step 4: 通る（不変条件総点検）** — `python -m pytest tests/integration/test_pipeline_phase2b.py -q` → PASS（4本）／`python -m pytest -q` → **全 PASS・0 failed/0 error・既存 golden 14・既存 integration（test_pipeline_fixedpoint/test_diagnostics_phase2/test_pipeline_dialect/test_pipeline）byte 不変**。1ケースでも動いたら commit せず停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/cli.py src/grep_analyzer/fixedpoint.py tests/integration/test_pipeline_phase2b.py
git commit -m "feat(pipeline): walk一回共有＋progress＋ripgrep配線＋CLI（spec §8.2・出力不変）"
```

---

## Task 10: 不変条件の総合回帰（jobs×degrade×ripgrep×split 直交）

**Files:** Test `tests/integration/test_phase2b_invariants.py`

Inv-1〜3 の総合契約。実装追加なし（前 Task で満たす設計＝満たさない契約があれば原因 Task に戻る・テストは緩めない）。

- [ ] **Step 1: 失敗するテスト** — `tests/integration/test_phase2b_invariants.py` 新規:
```python
"""Phase 2b 不変条件の総合契約（spec §8.2/§9・出力保存と決定性）。"""

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
    return src, inp


def _h(tmp_path, src, inp, name, extra):
    out = tmp_path / name
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)] + extra) == 0
    return hashlib.sha256((out / "K1.tsv").read_bytes()).hexdigest()


def test_既定とjobsとsplitはTSV完全一致_出力透過(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _h(tmp_path, src, inp, "base", [])
    # jobs 並列・split 強制（force_chunks は CLI 非公開なので jobs/既定のみ CLI 経路）
    assert _h(tmp_path, src, inp, "j4", ["--jobs", "4"]) == base
    # 2 回実行決定性
    assert _h(tmp_path, src, inp, "base2", []) == base


def test_memory_limit0は2回実行決定的_degrade決定性(tmp_path: Path):
    src, inp = _setup(tmp_path)
    a = _h(tmp_path, src, inp, "m1", ["--memory-limit", "0", "--max-passes", "8"])
    b = _h(tmp_path, src, inp, "m2", ["--memory-limit", "0", "--max-passes", "8"])
    assert a == b  # degrade 下でも決定的（Inv-3）


@pytest.mark.requires_ripgrep
def test_ripgrep有無でTSV完全一致(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _h(tmp_path, src, inp, "norg", [])
    assert _h(tmp_path, src, inp, "rg", ["--use-ripgrep"]) == base
    assert _h(tmp_path, src, inp, "rgj4", ["--use-ripgrep", "--jobs", "4"]) == base
```

- [ ] **Step 2: 失敗を確認 → 満たさない契約は原因 Task へ** — `python -m pytest tests/integration/test_phase2b_invariants.py -q` → PASS（rg 無: 2本＋1 skip／rg 有: 3本）。FAIL があれば**テストは緩めず**原因 Task（6/7/8/9）の出力不変・決定性を修正（spec §9 違反＝退行）。

- [ ] **Step 3: 全体回帰** — `python -m pytest -q` → 全 PASS・0 failed/0 error・既存 golden 14 不変。

- [ ] **Step 4: コミット**
```bash
git add tests/integration/test_phase2b_invariants.py
git commit -m "test(phase2b): jobs×memory×ripgrep 直交の出力不変・決定性契約（spec §8.2/§9）"
```

---

## Task 11: Phase 2b 全テスト緑化と完了確認

**Files:** Modify `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テスト実行** — `python -m pytest -q` → 全 PASS（Phase 2a 130 ＋ Phase 2b 追加分・0 failed/0 error）。`python -m grep_analyzer --help` exit 0（新オプション usage 出力）。失敗あれば該当 Task へ戻る（完了主張しない）。

- [ ] **Step 2: spec §8.2／Inv 充足チェックリスト照合**

- §8.2 ストリーミング走査（bytes 親非常駐・確定全文1回読み＝C1根治）→ Task6（`test_多行構文の分類が確定全文読みでPhase2aと同一`）
- §8.2 walk 一回化（keyword 横断診断重複解消）→ Task5/9（`test_walk診断はkeyword数によらず重複しない`）
- §8.2 任意 ripgrep（walk 上位集合・gitignore/隠し含む）→ Task3/9/10（`@pytest.mark.requires_ripgrep`）
- §8.2 --memory-limit 会計（決定的近似・None/0/N）→ Task1/7
- §8.2 degrade 優先1 決定的切り捨て（唯一の出力変更）→ Task7（`test_memory_limit0で…全件記録`/`test_memory_limit0は2回実行で決定的`）
- §8.2 degrade 優先2 来歴スピル（出力透過）→ Task2/8（`test_強制スピルは非スピルと出力byte同値`）
- §8.2 最終手段 オートマトン分割多パス（出力透過＝C2根治）＋--max-passes 上限 → Task8（`test_force_chunks分割は単一オートマトンと出力byte同値`・`automaton_split` 実発火）
- §8.2 --progress 標準エラー進捗 → Task4/9（`test_progress_onはstderrのみでTSV不変`）
- Inv-1〜3（既定 byte 不変・degrade 出力性質・jobs/degrade/ripgrep 直交決定性）→ Task10＋既存 golden 14・既存 130 不変

- [ ] **Step 3: 完了記録を追記しコミット** — `phase0-gate-result.md` 末尾に「## Phase 2b 完了記録」（完了日 UTC、コミット範囲、全テスト結果、上記対応表、Inv-1〜4 充足＝既存 golden 14・既存 130 不変・多 keyword diagnostics は walk 重複 dedup の意図変化、Phase 3 申し送り）を追記。
```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2b 完了（資源degrade・ストリーミング・ripgrep・progress）"
```

---

## Phase 2b の境界（Phase 3 は別計画）

- **Phase 3 に送る**: 60GB perf ベースライン（`tests/perf/` `@pytest.mark.perf` 非ゲート・本近似 budget の実バイト厳密化）、`--resume`、diagnostics §10.3 縮約（カテゴリ別集約＋代表サンプル）、規模分割 `<keyword>.partNN.tsv`（§9）、`requirements.lock`（§4.1・ユーザ決定。Phase 2a/2b は再現ビルドを `pip download` 明示 `==`＋wheelhouse で担保・lock 正式化は Phase 3）、`--output-encoding`/`--encoding-fallback`（§10.1 正本だが decode は Phase 1.5 確立済）。
- **Phase 2b 既知境界（spec 引用付き・仕様固定）**: (1) メモリ近似は決定的アイテム近似（実 RSS 非依存＝spec §9 決定性優先・実バイト厳密化 Phase 3）。(2) ripgrep は ASCII 識別子前提の walk 上位集合（Phase 2a の ASCII 識別子既知境界継承＝§8.2）。(3) 差分走査効果は spec §8.2 誠実化どおり限定（新規シンボル全走査不可避・効果は bytes 親非常駐に限る・確定はファイル単位1回読み）。(4) `--progress` は stderr 専用・非決定要素（ETA 等）は出力契約外（Inv-4）。(5) 複数 keyword の `diagnostics.txt` は walk 系重複の dedup 差のみ＝意図変化（Inv-1。spec §10.3 一般縮約は Phase 3）。(6) 優先1 切り捨ては edges/intro 単独超過時 keep=0 になり得るが決定的（spec §8.2 ラダーで優先2 スピルが graph memory を退避＝Task8 完了で収束）。
- 成果物: 「Phase 2a の出力・決定性を1バイトも変えずに（既定）、`--memory-limit` 超過で決定的切り捨て→来歴スピル→オートマトン分割多パスへ degrade し（スピル/分割は出力透過・切り捨てのみ決定的に出力変更）、ストリーミング走査・任意 ripgrep・標準エラー進捗・walk 一回化を備えた、メモリ制約下でも決定的に動くツール」。単体でテスト可能・出荷可能。

---

## Self-Review（v2・本計画著者によるチェック）

**1. spec coverage（§8.2 全項目）:** ネイティブ AC＋ripgrep＋multiprocessing → 既存＋Task3/9 ✓。差分走査の誠実な限定効果 → Task6（ストリーミングのみ・確定全文1回読み・spec 誠実化を実装注明記）✓。来歴 memory を --memory-limit 対象・上限超過スピル → Task1/2/7/8 ✓。degrade 優先順位（決定的切り捨て→スピル→分割・最大パス上限）→ Task7/8 ✓。size/binary skip・include/exclude・symlink・realpath（既存 walk 規則不変）→ Task5 collect_files 化のみ ✓。進捗 stderr・--progress 粒度 → Task4/9 ✓。§15 フェーズ2 資源 degrade を 2b（Phase 2a 境界の §15 根拠付き分割継承）✓。§10.4 CLI（--memory-limit/--use-ripgrep/--max-passes/--progress）→ Task9 ✓。Phase 3 送りは境界に spec §番号付き明記 ✓。

**2. Placeholder scan:** 全 Task に実コード・実コマンド・期待出力。fixedpoint 改変は「Phase 2a 実コードの当該1ブロックを次へ置換」＋行位置特定（seed ループ後・`_apply_global_cap` 前 等）＝プレースホルダでない。`...`/「TBD」なし。

**3. Type consistency（串刺し）:** `MemoryBudget`(None/0/N)/`estimate_items`/`EdgeStore`(`_force_spill_threshold`)/`serialize_edge`/`parse_edge`/`ripgrep.prefilter`(--no-ignore等)/`Progress`/`collect_files`/`EngineOptions`(末尾既定6・非既定11先行で dataclass 制約充足・cli/pipeline/test の keyword 構築不変)/`run_fixedpoint(*, files=None)`/`_scan_file`(abspath)/`force_chunks` を冒頭契約と全 Task で一致。`memory_limit_mb=None`＆`force_chunks=0`＆`spill_dir=None` で全 degrade 機構が Phase 2a と完全同一（nchunks=1 で Phase 2a 走査ループ逐語・estore 非スピル・over_mem 恒偽）＝既存 golden 14・既存 130 不変を Task6/7/8/9/10 各 Step4 が要求。`test_fixedpoint._opts` への新6フィールド既定追加は Task7 Step1（Task6 新テストは `_opts()`＋`files=` のみ＝末尾既定不要で成立）。

**4. v1 批判的レビュー（3並行）指摘の解消対応:** C1（`full_text` 再構成で tree-sitter 分類破壊）→ **`loc_cache` 廃止・確定は abspath 全文1回読み（Phase 2a 同値）**＋`test_多行構文…`回帰 ✓ / C2（`sorted(found)` で sym_kind/sym_hop first-write-wins 破壊）→ **nchunks==1 は Phase 2a 逐語・分割は `(lineno,symbol)` キーで Phase 2a 反復順厳密一致**＋`test_force_chunks分割は…byte同値` ✓ / C3（budget 数値不整合・空虚 PASS）→ **memory_limit_mb=0=最大 degrade 強制**＋`automaton_split`/`graph_spilled`/capped 観測点・**degrade 不変条件を分解（優先1=唯一の出力変更決定的／spill・split=独立フックで透過性分離検証）** ✓ / C4（ripgrep gitignore/隠し除外で非上位集合）→ **`--no-ignore --hidden --no-require-git`**＋`test_gitignoreと隠しファイルも上位集合に含む` ✓ / Task7 `object.__setattr__` デッドコード → **削除（テストは `_opts(... memory_limit_mb=0)` のみ）** ✓ / `edge_count` 表記一本化（`estore_len()` 不使用）✓ / Task6 行位置特定・Task9 prog.start 単一手順 ✓ / 多 keyword diagnostics dedup の意図変化を Inv-1/境界(5) に明記 ✓ / staged-invariant（優先1 のみ keep=0）を Task7 実装注/境界(6) に明記 ✓ / requirements.lock を境界に Phase 3・再現担保手段付きで明記 ✓。

> 次レビュー重点候補: ① Task6 確定全文1回読みが Phase 2a `meta_of`/`line_cache` と命令同値で 14 golden・多行 java/Pro\*C で byte 一致するか（`test_多行構文…` に加え既存 golden 全緑で検証）。② Task8 分割の `(lineno,symbol)` 正規化が Phase 2a per-file 反復順と厳密同一である証明の妥当性（`automaton.scan_line` が昇順ユニーク＝行内 symbol 昇順、行は `text.split` 昇順、を前提に成立）。③ `force_chunks` を内部/テスト用フックとし CLI 非公開にした YAGNI 判断（spec §8.2 分割の透過性回帰固定に必要・ユーザ機能ではない）。④ `spill_dir` 指定＋`budget.unlimited` で `_force_spill_threshold=1` を当てる設計が本番運用（spill_dir 指定だが memory 無制限）で意図せぬ常時スピルを招かないか（運用上 spill_dir は degrade 時のみ意味を持つ前提・要明記）。⑤ memory_limit_mb=0 優先1 で keep=0 全切り捨て時に scan_syms 空→break で indirect 0・direct のみになる挙動の決定性と妥当性。
