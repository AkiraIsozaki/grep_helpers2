# grep_analyzer Phase 2b（資源 degrade・ストリーミング・ripgrep・progress） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **全コミット末尾に `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` を付す（ハーネス規約。各 Task の git commit 例では簡潔化のため省略表記しているが必ず付与）。**

**Goal:** Phase 2a の正しさ・決定性コアの**出力を一切変えずに**、spec §8.2 の資源設計—ストリーミング走査（全 bytes 親常駐の廃止）／keyword 横断 walk 一回化／任意 `ripgrep` 一次粗フィルタ／`--memory-limit` 会計と degrade ラダー（決定的シンボル切り捨て→来歴グラフ・ディスクスピル→オートマトン分割多パス・最大パス上限）／差分走査（確定シンボルの再デコード/再走査の省略＝ファイル→該当行ローカライゼーション保持）／`--progress` 標準エラー進捗—を実装する。

**Architecture:** Phase 1.5 決定的コア（dispatch/classifiers/model/tsv/diagnostics/encoding/ingest/proc_preprocess）と Phase 2a の chase/stoplist/automaton/provenance/classify は **不変**。新規モジュール `budget.py`（決定的メモリ近似）／`spill.py`（来歴エッジのディスクスピル）／`ripgrep.py`（任意一次フィルタ）／`progress.py`（標準エラー進捗）を追加。`walk.py` に `collect_files`（走査一回・パスのみ materialize）を追加。`fixedpoint.py` をストリーミング走査（ワーカが abspath からバイト読込）＋degrade ラダー＋差分ローカライゼーション＋進捗フックに拡張。`pipeline.py` は keyword ループ前に **一度だけ** walk して file リストを共有し `run_fixedpoint` へ渡す。`cli.py` に `--memory-limit`/`--use-ripgrep`/`--max-passes`/`--progress` を追加。**60GB perf ベースライン・`--resume`・diagnostics §10.3 縮約・規模分割 `partNN`・`requirements.lock`・`--output-encoding`/`--encoding-fallback` は Phase 3（範囲外）**。

**Tech Stack:** Python 3.12 / pytest / `pyahocorasick==2.1.0`（既存）/ 任意 `ripgrep`（外部バイナリ・`@pytest.mark.requires_ripgrep` で隔離、無くても他テスト緑）。tree-sitter/chardet 既存のまま。設計書 `docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`（v7・§9 は `07e81bb`、§8.1手順5 は `8c21227` 改訂後本文・spec が常に優先）、`.claude/skills/writing-tests.md`、`.claude/skills/coding-conventions.md` に従う（docstring/コメント・テスト名は日本語、古典学派+TDD、外部I/O境界＝ファイル/サブプロセスのみ本物）。

---

**最重要不変条件（Phase 2b 全タスクの絶対前提・spec §9／Phase 2a 境界の継承）:**

1. **出力 byte 不変**: 既定オプション（`--memory-limit` 無し・`--use-ripgrep` 無し・`--progress off`）で Phase 2b の TSV／`diagnostics.txt` は Phase 2a と**完全一致**。既存 unit/integration/golden（Phase 2a 完了時 130 passed・14 golden）が**全て不変で緑**。
2. **degrade は出力保存（例外＝決定的切り捨てのみ）**: スピル・オートマトン分割・ripgrep フィルタ・ストリーミング化・差分走査・walk 一回化は **TSV を1バイトも変えない純粋な資源/性能変換**。唯一の例外は degrade 優先1「決定的シンボル切り捨て」で、これは Phase 2a の `_apply_global_cap` と**同一の決定的キー** `(発見ホップ, 識別子長, 文字列辞書順)` で落とし `symbol_rejected\tcapped` を記録する既存挙動を **memory 駆動でも発火させる**だけ（落とすシンボル集合は同一入力で決定的）。
3. **決定性**: `--jobs 1` と `--jobs N`、ストリーミング/非ストリーミング、スピル/非スピル、分割/非分割、ripgrep 有/無 のいずれの組合せでも TSV／diagnostics は **byte 一致**（spec §9「multiprocessing 完了順・走査順に依存しない」の継承。Phase 2a 境界で明文化済「ストリーミング化後も intro/edges の最終集合は走査順非依存」）。
4. **進捗は stderr のみ**: `--progress` 出力は標準エラー専用。TSV／`diagnostics.txt`／終了コードに一切影響しない（タイムスタンプ/ETA の非決定性は stderr に閉じる）。

各 Task の Step4 は必ず「当該テスト PASS」＋「`python -m pytest -q` 全 PASS・0 failed/0 error（Phase 2a 130 ＋ 本 Task 追加分。既存 golden 14 不変）」を要求する。golden が1ケースでも動いたら **commit せず停止し構造を疑う**（writing-tests「大量churn＝構造を疑う」。Phase 2b は出力保存が定義）。

**型・シグネチャ契約（全タスク共通・不変。Self-Review 3 で串刺し）:**

- `walk.collect_files(root, *, include, exclude, follow_symlinks, max_file_bytes, diag) -> list[tuple[str, pathlib.Path]]`（`walk_files` を一度 materialize・relpath 昇順・走査診断は1回のみ）
- `budget.MemoryBudget(limit_mb: int | None)`: `.unlimited: bool` / `.item_budget: int`（`limit_mb` から決定的換算。`None`→無制限）/ `.exceeded(n_items: int) -> bool`
- `budget.estimate_items(*, n_symbols: int, n_edges: int, n_intro: int) -> int`（決定的近似＝RSS 非依存）
- `spill.serialize_edge(p: provenance.Occurrence, c: provenance.Occurrence) -> str` / `spill.parse_edge(line: str) -> tuple[Occurrence, Occurrence]`（タブ＋制御文字エスケープで round-trip 完全可逆）
- `spill.EdgeStore(spill_dir: pathlib.Path | None, budget: MemoryBudget)`: `.add(p, c)` / `.maybe_spill()` / `.sorted_unique() -> Iterator[tuple[Occurrence, Occurrence]]`（in-memory/spill いずれでも `sorted(set(...))` と同一順序・同一集合）/ `.spilled: bool` / `.close()`
- `ripgrep.available() -> bool` / `ripgrep.prefilter(root: pathlib.Path, rel_to_abs: dict[str, pathlib.Path], symbols: list[str]) -> set[str] | None`（`rg` で「いずれかのシンボル**部分文字列**を含みうる」rel 集合の上位集合を返す。`rg` 不在/失敗時 `None`＝フィルタ無効＝全件走査）
- `progress.Progress(level: str, stream)`: `.start(total_files: int)` / `.hop(hop: int, n_symbols: int, scanned: int)` / `.done()`（`level=="off"` は完全無音。stderr のみ）
- `fixedpoint.EngineOptions` 追加フィールド（**末尾に既定値付き**＝既存キーワード構築は不変）: `memory_limit_mb: int | None = None`, `use_ripgrep: bool = False`, `max_passes: int = 8`, `progress: str = "off"`, `spill_dir: pathlib.Path | None = None`
- `fixedpoint.run_fixedpoint(seed_hits, source_root, opts, diag, *, files: list[tuple[str, pathlib.Path]] | None = None) -> list[Hit]`（`files=None` は従来どおり内部 walk＝後方互換。pipeline は共有 list を渡す）
- `fixedpoint._scan_file(args)` の `args` は `(rel: str, abspath: str, sym_list: list[str], lang_map: dict)`（**bytes でなく abspath**＝ストリーミング。ワーカが読む）

**spec 解釈の明示（次レビューで再検証可能）:**

- **メモリ近似は決定的近似**（spec §8.2「来歴グラフのメモリは --memory-limit の対象」）: 実 RSS は非決定的なので採らない。`estimate_items` ＝ `n_symbols + n_edges + n_intro`（各概念1件＝固定重み）。`--memory-limit MB` は `item_budget = limit_mb * _ITEMS_PER_MB`（`_ITEMS_PER_MB` は固定定数）へ決定的換算。これにより「同一入力・同一 limit で同一の degrade 判断」＝決定性（spec §9）。実バイト厳密性は Phase 3 perf の領分（本近似は degrade 発火の決定的トリガとしてのみ機能）。
- **degrade 優先順位**（spec §8.2 厳守）: `exceeded` 時 (優先1) 決定的シンボル切り捨て（`_apply_global_cap` を memory 駆動化＝再走査を増やさず決定性維持）→ なお超過なら (優先2) `EdgeStore` のディスクスピル（来歴グラフのメモリを退避・出力不変）→ scan_syms が単一オートマトンに対し過大なら (最終手段) オートマトン分割＝scan_syms を決定的 K 分割し K パス走査（`--max-passes` 上限。超過時は優先1 へ戻り更に切り捨て）。スピル・分割は **出力保存**、切り捨てのみ決定的にシンボルを落とす（spec §8.3／§8.2）。
- **ripgrep は上位集合フィルタ**（spec §8.2「任意 ripgrep 1次フィルタ」）: 追跡シンボルは ASCII 識別子（Phase 2a 既知境界）で UTF-8/CP932/latin-1 のいずれでも raw バイト上に同一バイト列で出現する。`rg -F`（固定文字列・複数パターン）で「いずれかのシンボル部分文字列を含むファイル」を絞ると、除外ファイルは**部分文字列すら持たない**＝automaton（識別子境界）でも 0 ヒットが確定。よって絞り込み後の automaton 走査は全件走査と**同一ヒット**＝出力不変（ripgrep は決定性・正しさに影響しない純フィルタ）。`rg` 不在時はフィルタ無効＝全件（既定 `--use-ripgrep` 無しでも全件＝Phase 2a 同一）。
- **差分走査の限定効果**（spec §8.2 誠実化）: 新規シンボルは全ツリー走査が必要（不可避）。Phase 2a は既に「確定済（chase_done/term_done）シンボルを automaton へ再投入しない」ため確定シンボルの**再走査**は元々していない。Phase 2b の差分効果は **確定フェーズの再デコード/再読込の排除**＝走査で得た `(sym,lineno,line)` を `loc_cache` に蓄積し、ヒット確定で当該行を**再 I/O せず**再利用する（Phase 2a の `raw_of`/`line_cache` 再デコードを廃す）。出力は完全不変（同じ行文字列・分類）。
- **walk 一回化**: `pipeline.run` が keyword ごとに `run_fixedpoint`→`walk_files` を呼ぶため同一ツリーの walk 診断（`walk_excluded` 等）が keyword 数ぶん重複していた。Phase 2b は pipeline が**全 keyword 前に一度** `collect_files`（走査・診断1回）し、その list を各 `run_fixedpoint` に渡す。walk 系診断は 1 回・file 集合は keyword 間で同一＝決定性不変、診断重複解消。spec §10.3 の一般的診断縮約は Phase 3（本件は重複の構造的解消のみ）。

---

## Task 0: 着手ゲート（Phase 2a 緑・ripgrep 任意性・コードなし）

spec §15 フェーズ2 のうち 2b 着手前提＝Phase 2a 完了（決定性基盤の上に資源層を積む）。

- [ ] **Step 1: Phase 2a ベースライン全緑**

Run: `cd /workspaces/grep_helpers2 && python -m pytest -q`
Expected: `130 passed`（0 failed / 0 error。Phase 2a 完了状態）。130 と異なるなら着手しない。

- [ ] **Step 2: Phase 2a 完了記録の存在**

Run: `grep -nF '## Phase 2a 完了記録' docs/superpowers/plans/phase0-gate-result.md`
Expected: 1 行ヒット。

- [ ] **Step 3: ripgrep 任意性の確認（必須でない）**

Run: `command -v rg && rg --version | head -1 || echo "rg absent (OK: --use-ripgrep は任意・既定無効)"`
Expected: いずれでも可。`rg` 不在でも Phase 2b は着手可（`--use-ripgrep` は任意・既定無効・`@pytest.mark.requires_ripgrep` で隔離）。**新規 wheel/必須依存は無い**（pyahocorasick G1 は Phase 2 で PASS 済・本 Phase で追加依存なし）。

- [ ] **Step 4: ゲート記録しコミット**

`docs/superpowers/plans/phase0-gate-result.md` 末尾に「## Phase 2b 着手ゲート記録」（UTC 日付・`130 passed`・Phase 2a 完了参照・`rg` 有無と任意性・新規必須依存なし・判定 PASS）追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2b 着手ゲート記録（130 passed / Phase 2a 完了 / ripgrep 任意）"
```

---

## Task 1: 決定的メモリ近似 `budget.py`

**Files:** Create `src/grep_analyzer/budget.py` / Test `tests/unit/test_budget.py`

spec §8.2「来歴グラフのメモリは --memory-limit の対象」。実 RSS は非決定的なので採らず、`(n_symbols + n_edges + n_intro)` の決定的アイテム近似と、`--memory-limit MB`→item 予算の決定的換算を提供（同一入力・同一 limit で同一 degrade 判断＝spec §9）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_budget.py` を新規作成:
```python
"""決定的メモリ近似の仕様（spec §8.2・degrade トリガの決定性）。"""

from grep_analyzer.budget import MemoryBudget, estimate_items


def test_estimate_itemsは各要素数の単純和():
    assert estimate_items(n_symbols=3, n_edges=10, n_intro=4) == 17
    assert estimate_items(n_symbols=0, n_edges=0, n_intro=0) == 0


def test_limit_None は無制限で超過しない():
    b = MemoryBudget(None)
    assert b.unlimited is True
    assert b.exceeded(10**9) is False


def test_limit_MBは決定的にitem予算へ換算され超過判定する():
    b = MemoryBudget(1)  # 1 MB
    assert b.unlimited is False
    assert b.item_budget == MemoryBudget(1).item_budget  # 決定的・再現一致
    assert b.exceeded(b.item_budget) is False        # 上限ちょうどは可
    assert b.exceeded(b.item_budget + 1) is True      # 超過は True


def test_予算は単調():
    assert MemoryBudget(2).item_budget > MemoryBudget(1).item_budget
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_budget.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/budget.py` を新規作成:
```python
"""決定的メモリ近似（spec §8.2）。来歴グラフ等のメモリを RSS でなく

アイテム数の決定的近似で見積もり、--memory-limit を degrade の決定的
トリガに換算する。同一入力・同一 limit で同一判断＝spec §9 決定性。
"""

# 1 MB あたりの近似アイテム上限（固定定数＝決定的換算）。実バイト厳密性は
# Phase 3 perf の領分。本定数は degrade 発火の決定的トリガとしてのみ機能する。
_ITEMS_PER_MB = 4096


def estimate_items(*, n_symbols: int, n_edges: int, n_intro: int) -> int:
    """来歴グラフ常駐の決定的アイテム近似（各概念を1件＝固定重み）。"""
    return n_symbols + n_edges + n_intro


class MemoryBudget:
    """--memory-limit(MB) を決定的 item 予算へ換算し超過判定する。"""

    def __init__(self, limit_mb: int | None) -> None:
        self._limit_mb = limit_mb
        self.unlimited = limit_mb is None
        self.item_budget = 0 if limit_mb is None else limit_mb * _ITEMS_PER_MB

    def exceeded(self, n_items: int) -> bool:
        """予算超過か（無制限は常に False、上限ちょうどは可）。"""
        if self.unlimited:
            return False
        return n_items > self.item_budget
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_budget.py -q` → PASS（4本）／`python -m pytest -q` → 全 PASS（130＋4）・0 failed/0 error・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/budget.py tests/unit/test_budget.py
git commit -m "feat(budget): 決定的メモリ近似と--memory-limit換算（spec §8.2）"
```

---

## Task 2: 来歴エッジのディスクスピル `spill.py`

**Files:** Create `src/grep_analyzer/spill.py` / Test `tests/unit/test_spill.py`

spec §8.2「上限超過時はディスクスピル」。`EdgeStore` は予算内ではメモリ保持、超過で一時ファイルへ追記スピルし、`sorted_unique()` で in-memory/spill いずれでも **`sorted(set(edges))` と同一順序・同一集合**を返す（出力保存・決定的）。`Occurrence` は frozen・order=True（Phase 2a 既存）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_spill.py` を新規作成:
```python
"""来歴エッジのディスクスピルの仕様（spec §8.2・出力保存・決定的）。"""

from grep_analyzer.budget import MemoryBudget
from grep_analyzer.provenance import Occurrence
from grep_analyzer.spill import EdgeStore, parse_edge, serialize_edge


def test_エッジは制御文字込みで完全往復可逆():
    p = Occurrence("A\tB", "a\nb.c", 3)   # タブ・改行を含む病的入力
    c = Occurrence("C", "d.c", 9)
    assert parse_edge(serialize_edge(p, c)) == (p, c)


def test_メモリ内でもsorted_uniqueはsorted_setと同一(tmp_path):
    s = EdgeStore(tmp_path, MemoryBudget(None))  # 無制限＝スピルしない
    e1 = (Occurrence("Q", "q.c", 2), Occurrence("H", "h.c", 9))
    e2 = (Occurrence("P", "p.c", 1), Occurrence("H", "h.c", 9))
    for p, c in [e1, e2, e1]:  # 重複含む
        s.add(p, c)
    assert s.spilled is False
    assert list(s.sorted_unique()) == sorted({e1, e2})
    s.close()


def test_予算超過でスピルしても同一集合同一順序(tmp_path):
    # item 予算 0 相当（1MB だが add ごとに maybe_spill で即超過させる）
    s = EdgeStore(tmp_path, MemoryBudget(None))
    s._force_spill_threshold = 1  # テスト用に閾値1へ（2件目でスピル）
    edges = [(Occurrence(f"S{i}", f"s{i}.c", i), Occurrence("H", "h.c", 9))
             for i in (3, 1, 2, 1)]  # S1 重複
    for p, c in edges:
        s.add(p, c)
    assert s.spilled is True
    assert list(s.sorted_unique()) == sorted(set(edges))
    s.close()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_spill.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/spill.py` を新規作成:
```python
"""来歴エッジのディスクスピル（spec §8.2）。予算内はメモリ、超過で一時

ファイルへ追記退避。sorted_unique は in-memory/spill いずれでも
sorted(set(edges)) と同一順序・同一集合を返す（出力保存・決定的）。
"""

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

from grep_analyzer.provenance import Occurrence

# 制御文字を含む symbol/relpath を可逆化するエスケープ（タブ区切りを壊さない）。
_ESC = {"\\": "\\\\", "\t": "\\t", "\n": "\\n", "\r": "\\r"}
_UNESC = {"\\\\": "\\", "\\t": "\t", "\\n": "\n", "\\r": "\r"}


def _enc(s: str) -> str:
    out = []
    for ch in s:
        out.append(_ESC.get(ch, ch))
    return "".join(out)


def _dec(s: str) -> str:
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            out.append(_UNESC.get(s[i:i + 2], s[i + 1]))
            i += 2
        else:
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
    """来歴エッジを予算内はメモリ、超過でディスクへスピルして保持する。"""

    def __init__(self, spill_dir: Path | None, budget) -> None:
        self._mem: list[tuple[Occurrence, Occurrence]] = []
        self._budget = budget
        self._dir = Path(spill_dir) if spill_dir is not None else Path(tempfile.gettempdir())
        self._fh = None
        self._path: Path | None = None
        self.spilled = False
        self._force_spill_threshold: int | None = None  # テスト用フック

    def add(self, p: Occurrence, c: Occurrence) -> None:
        """1 エッジを追加。予算超過で以降スピルへ切替。"""
        if self.spilled:
            self._fh.write(serialize_edge(p, c) + "\n")
            return
        self._mem.append((p, c))
        self.maybe_spill()

    def maybe_spill(self) -> None:
        """予算/閾値超過ならメモリ内容を一時ファイルへ退避しスピル状態へ。"""
        thr = self._force_spill_threshold
        over = (thr is not None and len(self._mem) >= thr) or \
               self._budget.exceeded(len(self._mem))
        if not over or self.spilled:
            return
        fd, p = tempfile.mkstemp(dir=str(self._dir), prefix="ga_edges_", suffix=".tsv")
        self._path = Path(p)
        self._fh = os.fdopen(fd, "w", encoding="utf-8")
        for pp, cc in self._mem:
            self._fh.write(serialize_edge(pp, cc) + "\n")
        self._mem = []
        self.spilled = True

    def sorted_unique(self) -> Iterator[tuple[Occurrence, Occurrence]]:
        """sorted(set(edges)) と同一順序・同一集合を返す（出力保存・決定的）。"""
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

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_spill.py -q` → PASS（3本）／`python -m pytest -q` → 全 PASS（前 Task ＋3）・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/spill.py tests/unit/test_spill.py
git commit -m "feat(spill): 来歴エッジのディスクスピル（spec §8.2・出力保存決定的）"
```

---

## Task 3: 任意 ripgrep 一次フィルタ `ripgrep.py`

**Files:** Create `src/grep_analyzer/ripgrep.py` / Test `tests/unit/test_ripgrep.py` / Modify `tests/conftest.py`

spec §8.2「任意 ripgrep 1次フィルタ」。`rg -l -F -f patternfile` で「いずれかのシンボル**部分文字列**を含む rel」上位集合を返す。除外 rel は部分文字列すら無く automaton でも 0 ヒット確定＝出力不変。`rg` 不在/失敗は `None`（フィルタ無効＝全件）。テストは `@pytest.mark.requires_ripgrep`（CI に rg 無くても他テスト緑）。

- [ ] **Step 1: マーカ登録（conftest）と失敗テストを書く**

`tests/conftest.py` の末尾に追記（既存内容は不変）:
```python
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_ripgrep: 実 ripgrep バイナリを要するテスト（無ければ skip）",
    )


def pytest_collection_modifyitems(config, items):
    import shutil
    if shutil.which("rg") is not None:
        return
    skip = pytest.mark.skip(reason="ripgrep 不在のため skip（任意機能）")
    for item in items:
        if "requires_ripgrep" in item.keywords:
            item.add_marker(skip)
```

`tests/unit/test_ripgrep.py` を新規作成:
```python
"""任意 ripgrep 一次フィルタの仕様（spec §8.2・出力保存の上位集合）。"""

import pytest

from grep_analyzer.ripgrep import available, prefilter


def test_利用不可時はNoneでフィルタ無効扱い(monkeypatch):
    monkeypatch.setattr("grep_analyzer.ripgrep._RG", None)
    assert available() is False
    assert prefilter(__import__("pathlib").Path("."), {}, ["CODE"]) is None


@pytest.mark.requires_ripgrep
def test_部分文字列を含むファイルのみ上位集合で返す(tmp_path):
    (tmp_path / "a.c").write_text("int CODE = 1;\n", "utf-8")
    (tmp_path / "b.c").write_text("int other = 2;\n", "utf-8")
    (tmp_path / "c.c").write_text("// DECODE here\n", "utf-8")  # 部分文字列含む＝上位集合に入る
    rel_abs = {p.name: p for p in tmp_path.glob("*.c")}
    got = prefilter(tmp_path, rel_abs, ["CODE"])
    assert "a.c" in got and "b.c" not in got
    assert "c.c" in got  # 部分一致でも残す（automaton が境界判定＝出力不変）


@pytest.mark.requires_ripgrep
def test_空シンボルや空ファイル集合は安全(tmp_path):
    assert prefilter(tmp_path, {}, []) == set()
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_ripgrep.py -q` → FAIL（ModuleNotFound。rg 無い環境では requires_ripgrep 2本は skip、`test_利用不可時は…` が ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/ripgrep.py` を新規作成:
```python
"""任意 ripgrep 一次粗フィルタ（spec §8.2）。シンボル部分文字列を含む

rel の上位集合を返す（除外 rel は部分文字列すら無く automaton でも 0 ヒット
確定＝出力不変）。rg 不在/失敗は None＝フィルタ無効（全件走査）。
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
    """symbols のいずれかの部分文字列を含む rel 集合（上位集合）を返す。

    rg 不在/失敗は None（呼び出し側はフィルタ無効＝全 rel を走査）。
    symbols 空は空集合（走査対象なし）。
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
            [_RG, "-l", "-F", "--no-messages", "-f", pat_path, "."],
            cwd=str(root), capture_output=True, text=True, check=False)
    except OSError:
        Path(pat_path).unlink(missing_ok=True)
        return None
    Path(pat_path).unlink(missing_ok=True)
    if proc.returncode not in (0, 1):  # 0=hit, 1=no hit, それ以外=異常
        return None
    hit = set()
    for ln in proc.stdout.splitlines():
        rel = ln[2:] if ln.startswith("./") else ln
        if rel in rel_to_abs:
            hit.add(rel)
    return hit
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_ripgrep.py -q`（rg 有: 3本 PASS／rg 無: 1本 PASS＋2本 skip）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/ripgrep.py tests/unit/test_ripgrep.py tests/conftest.py
git commit -m "feat(ripgrep): 任意一次粗フィルタ＋requires_ripgrepマーカ（spec §8.2・出力保存）"
```

---

## Task 4: 標準エラー進捗 `progress.py`

**Files:** Create `src/grep_analyzer/progress.py` / Test `tests/unit/test_progress.py`

spec §8.2「標準エラーへ定期進捗（処理済みファイル/バイト、現ホップ、シンボル集合サイズ、ETA）。--progress で粒度調整」。`level=="off"` は完全無音。出力は **stderr 専用**（TSV/diagnostics/終了コードに無影響＝最重要不変条件4）。決定性が要らない（stderr 専用）が、テスト容易性のため出力先 stream を注入可能にし、ETA 等の非決定要素はテストで構造のみ検証。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_progress.py` を新規作成:
```python
"""標準エラー進捗の仕様（spec §8.2・stderr 専用・off は無音）。"""

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
    out = buf.getvalue()
    assert "files=2" in out          # 総ファイル数
    assert "hop=1" in out and "symbols=4" in out and "scanned=2" in out
    assert "done" in out


def test_未知levelはoff扱いで無音():
    buf = io.StringIO()
    Progress("verbose-unknown", buf).hop(1, 1, 1)
    assert buf.getvalue() == ""
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_progress.py -q` → FAIL（ModuleNotFound）

- [ ] **Step 3: 実装** — `src/grep_analyzer/progress.py` を新規作成:
```python
"""標準エラー進捗（spec §8.2）。level=="on" 以外は完全無音。出力は注入

された stream（既定 sys.stderr）専用で TSV/diagnostics/終了コードに無影響。
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
        """1 ホップ進捗（現ホップ・シンボル集合サイズ・走査済ファイル数）。"""
        if self._on:
            print(f"[grep_analyzer] hop={hop} symbols={n_symbols} "
                  f"scanned={scanned}/{self._total}",
                  file=self._stream, flush=True)

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

`walk_files`（generator・診断を都度 add）を一度 materialize して relpath 昇順の `list[(rel, abspath)]` を返す `collect_files` を追加（既存 `walk_files` は不変）。pipeline が全 keyword 前に1回呼ぶことで walk 診断重複を解消（Task 9 で配線）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_walk.py` の末尾に追記:
```python
from grep_analyzer.walk import collect_files


def test_collect_filesは走査を一度materializeしrelpath昇順(tmp_path):
    (tmp_path / "b.c").write_text("x", "utf-8")
    (tmp_path / "a.c").write_text("y", "utf-8")
    diag = Diagnostics()
    got = collect_files(tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
                        follow_symlinks=False, max_file_bytes=1_000_000, diag=diag)
    assert [r for r, _ in got] == ["a.c", "b.c"]
    assert all(hasattr(p, "is_file") for _, p in got)  # Path を返す


def test_collect_filesの診断はwalk_filesと同一で一回だけ(tmp_path):
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "G.c").write_text("x", "utf-8")
    (tmp_path / "k.c").write_text("y", "utf-8")
    d1 = Diagnostics()
    collect_files(tmp_path, include=[], exclude=list(DEFAULT_EXCLUDE),
                  follow_symlinks=False, max_file_bytes=1_000_000, diag=d1)
    assert d1.render().count("walk_excluded\tbuild/G.c") == 1
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_walk.py -q` → FAIL（ImportError collect_files）

- [ ] **Step 3: 実装** — `src/grep_analyzer/walk.py` の末尾に追記:
```python
def collect_files(
    root: Path, *, include: list[str], exclude: list[str],
    follow_symlinks: bool, max_file_bytes: int, diag: Diagnostics,
) -> list[tuple[str, Path]]:
    """walk_files を一度だけ materialize し relpath 昇順の list を返す。

    走査・診断は1回のみ（pipeline が keyword 横断で共有＝診断重複解消・
    spec §8.2 走査一回化）。出力 list は walk_files の yield と同一・決定的。
    """
    return list(walk_files(
        root, include=include, exclude=exclude, follow_symlinks=follow_symlinks,
        max_file_bytes=max_file_bytes, diag=diag))
```

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_walk.py -q` → PASS（既存5＋新規2）／`python -m pytest -q` → 全 PASS・既存 golden 14 不変。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/walk.py tests/unit/test_walk.py
git commit -m "feat(walk): collect_files で走査一回materialize（spec §8.2・診断重複解消基盤）"
```

---

## Task 6: fixedpoint ストリーミング走査（bytes 親常駐の廃止・出力不変）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

`files: list[(rel, bytes)]`（全 bytes 親常駐）を `files: list[(rel, abspath)]`（パスのみ）に変え、`_scan_file` がワーカ内で `abspath` を読む（ストリーミング）。確定フェーズの `raw_of`/`line_cache` 再デコードを `loc_cache`（走査で得た `(sym,lineno,line)`）再利用へ置換（差分走査の限定効果＝再 I/O 排除）。**出力 byte 完全不変**（同じ行・分類・chain）。`run_fixedpoint` に `files=None` 引数追加（後方互換）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_fixedpoint.py` の末尾に追記:
```python
def test_ストリーミング化後も出力はPhase2aと同一(tmp_path):
    # 既存 test_多ホップ… と同じ入力で結果不変＝出力保存の回帰
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(), Diagnostics())
    chains = {(h.file, h.via_symbol): h.chain for h in hits}
    assert chains[("B.java", "K1")] == "K1@A.java:1 -> K1@B.java:1"
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"


def test_事前収集filesを渡しても内部walkと同一結果(tmp_path):
    from grep_analyzer.walk import DEFAULT_EXCLUDE, collect_files
    src = _mk(tmp_path, {"C.java": 'class C { static final String STATUS_OK = "S"; }\n',
                         "U.java": "class U { String x = STATUS_OK; }\n"})
    seed = _seed("STATUS_OK", "java", "C.java", 1,
                 'static final String STATUS_OK = "S";')
    a = run_fixedpoint([seed], src, _opts(), Diagnostics())
    files = collect_files(src, include=[], exclude=list(DEFAULT_EXCLUDE),
                          follow_symlinks=False, max_file_bytes=1_000_000,
                          diag=Diagnostics())
    b = run_fixedpoint([seed], src, _opts(), Diagnostics(), files=files)
    key = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    assert sorted(map(key, a)) == sorted(map(key, b)) and a
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → `test_事前収集files…` が FAIL（`run_fixedpoint() got an unexpected keyword argument 'files'`）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) `_scan_file` を abspath 読込（ストリーミング）に置換:
```python
def _scan_file(args):
    """1 ファイルをワーカ内で読み走査しヒット素片を返す純関数。

    ストリーミング化: 親に bytes を常駐させず abspath から読む（spec §8.2）。
    automaton 走査は raw 行（マスク非対称根拠）。出力は Phase 2a と byte 不変。
    """
    rel, abspath, sym_list, lang_map = args
    raw = Path(abspath).read_bytes()
    text, enc, replaced, language, dialect = _file_meta(rel, raw, lang_map)
    au = automaton.build(sym_list)
    found = []  # (sym, lineno, line)
    if au is not None:
        for i, line in enumerate(text.split("\n"), start=1):
            for sym in automaton.scan_line(au, line):
                found.append((sym, i, line))
    return rel, enc, replaced, language, dialect, found
```

(2) `run_fixedpoint` シグネチャに `*, files=None` を追加し、`files` 収集を差し替え。`run_fixedpoint` 内の該当ブロックを次へ置換:
```python
def run_fixedpoint(
    seed_hits: list[Hit], source_root: Path, opts: EngineOptions,
    diag: Diagnostics, *, files: list[tuple[str, Path]] | None = None
) -> list[Hit]:
    """seed から不動点まで多ホップ追跡し indirect Hit を決定的に返す（spec §8.1）。

    files 指定時はその (rel, abspath) list を使う（pipeline が walk 一回共有）。
    None は従来どおり内部 walk（後方互換）。ストリーミング＝親に bytes 非常駐。
    """
```
（関数本体の `files: list[tuple[str, bytes]] = [ (rel, abspath.read_bytes()) ... walk.walk_files(...) ]` を以下へ置換）:
```python
    if files is None:
        files = list(walk.walk_files(
            source_root, include=opts.include, exclude=opts.exclude,
            follow_symlinks=opts.follow_symlinks,
            max_file_bytes=opts.max_file_bytes, diag=diag))
    rel_to_abs = {rel: abspath for rel, abspath in files}
```

(3) 走査ループの `args` を bytes でなく abspath（str）に:
```python
        args = [(rel, str(abspath), scan_syms, opts.lang_map)
                for rel, abspath in files]
```

(4) 走査結果集約時に `loc_cache` へ蓄積（差分走査・確定フェーズ再 I/O 排除）。`for rel, enc, replaced, language, dialect, found in sorted(results, key=lambda r: r[0]):` ブロックの先頭で:
```python
            loc_cache.setdefault(rel, (language, dialect, {}))
            for sym, i, line in found:
                loc_cache[rel][2].setdefault(i, line)
```
かつ関数冒頭の状態初期化群（`enc_of` 付近）に追加:
```python
    loc_cache: dict[str, tuple[str, str, dict[int, str]]] = {}
```

(5) 確定フェーズの再デコード（`line_cache`/`meta_of`/`raw_of`）を `loc_cache` 再利用へ置換。`raw_of = dict(files)` 行と確定 for ループ内の再読込ブロックを以下へ置換:
```python
    indirect: list[Hit] = []
    seen: set[Occurrence] = set()
    for _, c in sorted(set(edges)):
        if c in seen or c.symbol not in (chase_done | term_done):
            continue
        if graph.is_seed_location(c.relpath, c.lineno):
            continue  # direct 既出
        seen.add(c)
        cached = loc_cache.get(c.relpath)
        if cached is None:
            # 走査でヒットしたが seed 由来等で loc 未取得＝当該ファイルを1度だけ読む
            raw = rel_to_abs[c.relpath].read_bytes() if c.relpath in rel_to_abs else b""
            text, enc, replaced, language, dialect = _file_meta(
                c.relpath, raw, opts.lang_map)
            loc_cache[c.relpath] = (language, dialect,
                                    {n: ln for n, ln in enumerate(
                                        text.split("\n"), start=1)})
            enc_of.setdefault(c.relpath, (enc, replaced))
            language_, dialect_, lines_ = loc_cache[c.relpath]
            full_text = text
        else:
            language_, dialect_, lines_ = cached
            full_text = "\n".join(lines_.get(n, "")
                                  for n in range(1, (max(lines_) if lines_ else 0) + 1))
        line = lines_.get(c.lineno, "")
        kind = sym_kind.get(c.symbol, "var")
        cat, conf = classify_hit(language_, dialect_, full_text, c.lineno, line)
        if kind in ("getter", "setter"):
            conf = "low"
        enc, replaced = enc_of.get(c.relpath, ("utf-8", False))
        for chain in graph.chains_to(c, max_depth=opts.max_depth,
                                     max_paths=opts.max_paths, diag=diag):
            indirect.append(Hit(
                keyword=keyword, language=language_, file=c.relpath,
                lineno=c.lineno, ref_kind=_REF_KIND[kind], category=cat,
                category_sub="", usage_summary=f"{cat} ({language_})",
                via_symbol=c.symbol, chain=chain, snippet=line,
                encoding=enc + (" 要確認" if replaced else ""), confidence=conf))
    return indirect
```

> **実装注（出力不変の根拠・次レビュー重点）:** `loc_cache` は走査が見た行を蓄積するのみで、`classify_hit` に渡す `full_text` は (a) 走査済ファイルは loc から行を連結再構成、(b) seed 由来で未走査なら1度だけ読む、のいずれかで Phase 2a の `text` と**同一文字列**（tree-sitter は全文必要なため `full_text` を渡す）。`line`/`cat`/`conf`/`chain` は Phase 2a と同値＝**TSV byte 不変**。差分効果＝確定フェーズで走査済ファイルを再デコードしない（spec §8.2「確定済シンボルの再ヒット再走査の省略」の現実的実体）。`(b)` の seed 未走査ファイル再読込は確定対象が seed 物理行（`is_seed_location` で除外）なので実際にはほぼ発生せず、発生しても出力同値。

- [ ] **Step 4: 通る（出力保存の回帰が要・最重要）**

Run: `python -m pytest tests/unit/test_fixedpoint.py -q`
Expected: PASS（既存8＋新規2）。特に `test_ストリーミング化後も出力はPhase2aと同一`／`test_事前収集files…` PASS。

Run: `python -m pytest -q`
Expected: **全 PASS・0 failed/0 error**。**既存 golden 14・既存 integration（test_pipeline_fixedpoint 等）が byte 不変**。golden が1ケースでも動いたら **commit せず停止し構造を疑う**（Phase 2b は出力保存が定義＝churn は退行）。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): ストリーミング走査＋差分ローカライゼーション（spec §8.2・出力不変）"
```

---

## Task 7: degrade ラダー優先1（memory 駆動の決定的シンボル切り捨て）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.2 degrade 優先1。Phase 2a の `_apply_global_cap`（静的 `max_symbols`）に加え、`MemoryBudget` 超過時も**同一の決定的キー** `(発見ホップ, 識別子長, 文字列辞書順)` で active 集合を切り捨て `symbol_rejected\tcapped` を記録（再走査を増やさず決定性維持）。`memory_limit_mb=None` は Phase 2a と完全同一挙動（無制限）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_fixedpoint.py` の末尾に追記:
```python
def test_memory_limitでも決定的シンボル切り捨てが発火し記録(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=dd; int dd=1; }\n",
                         "B.java": "class B{ int zz = aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    diag = Diagnostics()
    # max_symbols は緩く、memory_limit_mb で切り捨てを駆動
    o = _opts(min_specificity=1, max_symbols=10**9, memory_limit_mb=1)
    object.__setattr__(o, "memory_limit_mb", 1)  # dataclass frozen 経由不要なら _opts 側で渡す
    run_fixedpoint([seed], src, o, diag)
    assert "symbol_rejected\tcapped" in diag.render()


def test_memory_limit_Noneは無制限でPhase2aと同一(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    hits = run_fixedpoint([seed], src, _opts(memory_limit_mb=None), Diagnostics())
    chains = {(h.file, h.via_symbol): h.chain for h in hits}
    assert chains[("C.java", "K2")] == "K1@A.java:1 -> K1@B.java:1 -> K2@C.java:1"
```

`tests/unit/test_fixedpoint.py` 冒頭の `_opts` ヘルパに新フィールド既定を追加（既存呼び出し不変）:
```python
def _opts(**kw):
    base = dict(max_depth=5, min_specificity=2, stoplist_path=None, lang_map={},
                include=[], exclude=[], jobs=1, follow_symlinks=False,
                max_file_bytes=1_000_000, max_symbols=1000, max_paths=100,
                memory_limit_mb=None, use_ripgrep=False, max_passes=8,
                progress="off", spill_dir=None)
    base.update(kw)
    return EngineOptions(**base)
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → FAIL（`EngineOptions.__init__() got an unexpected keyword argument 'memory_limit_mb'`）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) `EngineOptions` に末尾既定フィールド追加（既存キーワード構築不変）:
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
```

(2) import 追加（ファイル先頭の import 群へ）:
```python
from grep_analyzer.budget import MemoryBudget, estimate_items
```

(3) `run_fixedpoint` 内、`policy = ...` の直後に budget を構築:
```python
    budget = MemoryBudget(opts.memory_limit_mb)
```

(4) `_apply_global_cap` を memory 駆動も見るよう拡張（静的 `max_symbols` か budget 超過のいずれかで切り捨て。決定的キーは不変）:
```python
    def _apply_global_cap():
        live = sorted(chase_active | chase_done | term_active | term_done,
                      key=lambda s: (sym_hop.get(s, 0), len(s), s))
        n_items = estimate_items(n_symbols=len(live), n_edges=len(edges),
                                 n_intro=sum(len(v) for v in intro.values()))
        over_static = len(live) > opts.max_symbols
        over_mem = budget.exceeded(n_items)
        if not (over_static or over_mem):
            return
        # 決定的キー (発見ホップ, 長さ, 辞書順) で上限内を残す。memory 駆動時は
        # budget 内に収まる最大 prefix を二分なしの単調縮小で決定（決定的）。
        keep = opts.max_symbols if over_static else len(live)
        while keep > 0 and budget.exceeded(estimate_items(
                n_symbols=keep, n_edges=len(edges),
                n_intro=sum(len(v) for v in intro.values()))):
            keep -= 1
        for s in live[keep:]:
            if s not in capped:
                diag.add("symbol_rejected", f"capped\t{s}")
                capped.add(s)
            chase_active.discard(s)
            term_active.discard(s)
```

> **実装注:** `memory_limit_mb=None` のとき `budget.unlimited` で `over_mem` 恒偽・`keep=len(live)` で while 即終了＝Phase 2a の挙動と**完全同一**（既存 `test_大域集合上限超過`／全 golden 不変）。memory 駆動の `keep` 縮小は単調・決定的（同一入力で同一 keep）。

- [ ] **Step 4: 通る** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存10＋新規2）／`python -m pytest -q` → 全 PASS・**既存 golden 14 不変**（`memory_limit_mb=None` 既定で Phase 2a 同一）。動いたら停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): degrade優先1 memory駆動の決定的シンボル切り捨て（spec §8.2）"
```

---

## Task 8: degrade ラダー優先2/最終手段（来歴スピル＋オートマトン分割多パス）

**Files:** Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/unit/test_fixedpoint.py`

spec §8.2 degrade 優先2＝来歴グラフのディスクスピル（`EdgeStore`）、最終手段＝オートマトン分割（scan_syms を決定的 K 分割し K パス走査・`--max-passes` 上限）。**いずれも出力 byte 不変**（スピルは `sorted_unique`＝`sorted(set(edges))` 同値、分割は各チャンク走査の和＝全走査と同一ヒット集合）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/unit/test_fixedpoint.py` の末尾に追記:
```python
def test_スピル発生でも出力はPhase2aと同一(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int K1 = 1; }\n",
                         "B.java": "class B{ static final int K2 = K1; }\n",
                         "C.java": "class C{ int z2 = K2; }\n"})
    seed = _seed("K1", "java", "A.java", 1, "static final int K1 = 1;")
    o = _opts(spill_dir=tmp_path, memory_limit_mb=1)  # 早期スピル誘発（小限度）
    base = run_fixedpoint([seed], src, _opts(), Diagnostics())
    spilled = run_fixedpoint([seed], src, o, Diagnostics())
    k = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    assert sorted(map(k, base)) == sorted(map(k, spilled))


def test_オートマトン分割多パスでも出力不変かつ診断記録(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ static final int aa=bb; static final int bb=cc;"
                                   " static final int cc=dd; static final int dd=1; }\n",
                         "B.java": "class B{ int z = aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "static final int aa=bb;")
    diag = Diagnostics()
    base = run_fixedpoint([seed], src, _opts(min_specificity=1), Diagnostics())
    split = run_fixedpoint([seed], src,
                           _opts(min_specificity=1, max_passes=8,
                                 memory_limit_mb=1, spill_dir=tmp_path), diag)
    k = lambda h: (h.file, h.lineno, h.ref_kind, h.via_symbol, h.chain)
    assert sorted(map(k, base)) == sorted(map(k, split))


def test_max_passes超過は優先1へ戻り決定的に切り捨て(tmp_path):
    src = _mk(tmp_path, {"A.java": "class A{ int aa=bb; int bb=cc; int cc=dd; int dd=1; }\n",
                         "B.java": "class B{ int z=aa; }\n"})
    seed = _seed("aa", "java", "A.java", 1, "int aa=bb;")
    diag = Diagnostics()
    run_fixedpoint([seed], src, _opts(min_specificity=1, max_symbols=10**9,
                   memory_limit_mb=1, max_passes=1, spill_dir=tmp_path), diag)
    assert "symbol_rejected\tcapped" in diag.render()  # 分割上限超過→優先1
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/unit/test_fixedpoint.py -q` → 新規3本が FAIL（スピル/分割未実装）

- [ ] **Step 3: 実装** — `src/grep_analyzer/fixedpoint.py` を編集。

(1) import 追加:
```python
from grep_analyzer.spill import EdgeStore
```

(2) `edges: list[...] = []` を `EdgeStore` 化。`edges` 参照箇所を `estore` に置換:
- 状態初期化: `estore = EdgeStore(opts.spill_dir, budget)`
- エッジ追加箇所 `edges.append((parent, child))` → `estore.add(parent, child)`
- `_apply_global_cap` の `n_edges=len(edges)` → `n_edges=estore_len()`（下記ヘルパ）。スピル後は件数推定で代替（決定的近似で可）。
- グラフ構築 `for p, c in edges: graph.add_edge(p, c)` → `for p, c in estore.sorted_unique(): graph.add_edge(p, c)`
- 確定ループ `for _, c in sorted(set(edges)):` → `for _, c in estore.sorted_unique():`（`sorted_unique` は既に `sorted(set(...))` 同値・child 単位走査は従来同様）
- 関数終端で `estore.close()`

エッジ件数ヘルパ（スピル後はメモリ非保持なので加算カウンタを併設）。状態初期化に:
```python
    estore = EdgeStore(opts.spill_dir, budget)
    edge_count = 0
```
`estore.add(...)` の各所を:
```python
                    estore.add(parent, child)
                    edge_count += 1
```
`_apply_global_cap` 内の `len(edges)` を `edge_count` に置換。

(3) オートマトン分割多パス: 走査ループの automaton 構築箇所を「scan_syms が budget 過大なら決定的 K 分割し K パス」に変更。走査ループ本体（`args = [...]; if opts.jobs>1: ... else: ...; for rel,... in sorted(results...)`）を次の構造へ:
```python
        # scan_syms を budget に応じ決定的に分割（最終手段＝オートマトン分割）。
        n_probe = estimate_items(n_symbols=len(scan_syms), n_edges=edge_count,
                                 n_intro=sum(len(v) for v in intro.values()))
        nchunks = 1
        if not budget.unlimited and budget.exceeded(n_probe):
            # 1 チャンクが budget 内に収まる最小分割数（決定的・単調増加）
            while nchunks < opts.max_passes and budget.exceeded(estimate_items(
                    n_symbols=-(-len(scan_syms) // (nchunks + 1)),
                    n_edges=edge_count,
                    n_intro=sum(len(v) for v in intro.values()))):
                nchunks += 1
        size = -(-len(scan_syms) // nchunks) if scan_syms else 0
        chunks = [scan_syms[i:i + size] for i in range(0, len(scan_syms), size)] \
            if size else [scan_syms]
        if nchunks > 1:
            diag.add("automaton_split", f"hop={hop} chunks={len(chunks)}")
        agg: dict[str, tuple] = {}
        for chunk in chunks:
            args = [(rel, str(abspath), chunk, opts.lang_map)
                    for rel, abspath in files]
            if opts.jobs > 1:
                with multiprocessing.Pool(opts.jobs) as pool:
                    results = pool.map(_scan_file, args)
            else:
                results = [_scan_file(a) for a in args]
            for rel, enc, replaced, language, dialect, found in results:
                if rel not in agg:
                    agg[rel] = (enc, replaced, language, dialect, [])
                agg[rel][4].extend(found)
        for rel in sorted(agg):
            enc, replaced, language, dialect, found = agg[rel]
            found = sorted(found)  # チャンク跨ぎの決定的順序（走査順非依存）
            loc_cache.setdefault(rel, (language, dialect, {}))
            for sym, i, line in found:
                loc_cache[rel][2].setdefault(i, line)
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

> **実装注（出力不変の根拠）:** 分割は scan_syms を **decode/走査の単位**だけ分けるもので、`agg` で rel ごとに全チャンクの found を集約し `sorted(found)` で**走査順・チャンク順・jobs 完了順に非依存**の決定的順序へ正規化（spec §9）。全チャンクの和＝単一オートマトン走査と同一ヒット集合（automaton は部分集合シンボルでも各シンボルの一致は不変）。よって `nchunks==1`（既定 `memory_limit_mb=None`）でも `nchunks>1` でも **TSV byte 完全一致**。`max_passes` で `nchunks` を頭打ちにし、なお過大なら `_apply_global_cap`（優先1）が次反復先頭で決定的に切り捨て＝spec §8.2 ラダー（優先1→2→最終手段→優先1 へ収束）。

- [ ] **Step 4: 通る（出力保存が要）** — `python -m pytest tests/unit/test_fixedpoint.py -q` → PASS（既存12＋新規3）／`python -m pytest -q` → **全 PASS・既存 golden 14 byte 不変**（`memory_limit_mb=None` で nchunks=1・estore 非スピル＝Phase 2a 同一）。動いたら停止し構造を疑う。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/fixedpoint.py tests/unit/test_fixedpoint.py
git commit -m "feat(fixedpoint): degrade優先2スピル＋最終手段オートマトン分割多パス（spec §8.2・出力不変）"
```

---

## Task 9: pipeline 配線（walk 一回共有・進捗・ripgrep・CLI）

**Files:** Modify `src/grep_analyzer/pipeline.py` / Modify `src/grep_analyzer/cli.py` / Modify `src/grep_analyzer/fixedpoint.py` / Test `tests/integration/test_pipeline_phase2b.py`

pipeline が全 keyword 前に `collect_files` で **一度** walk（診断1回・file 共有）し各 `run_fixedpoint(..., files=files)` へ渡す。`run_fixedpoint` に進捗フック（`progress.Progress`）と任意 ripgrep 一次フィルタ（走査対象 rel を絞る・出力不変）を配線。`cli.py` に `--memory-limit`/`--use-ripgrep`/`--max-passes`/`--progress`。既定は Phase 2a 完全同一。

- [ ] **Step 1: 失敗するテストを書く** — `tests/integration/test_pipeline_phase2b.py` を新規作成:
```python
"""Phase 2b 配線の境界契約（spec §8.2・出力不変・診断重複解消）。in-process。"""

import io
from contextlib import redirect_stderr
from pathlib import Path

from grep_analyzer.cli import main


def _tree(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "C.java").write_text('class C { static final String STATUS_OK = "S"; }\n', "utf-8")
    (src / "U.java").write_text("class U { String x = STATUS_OK; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "STATUS_OK.grep").write_text(
        'C.java:1:static final String STATUS_OK = "S";\n', "utf-8")
    (inp / "OTHER.grep").write_text(
        'C.java:1:static final String STATUS_OK = "S";\n', "utf-8")
    return src, inp


def test_既定オプションはPhase2aと同一TSV(tmp_path: Path):
    src, inp = _tree(tmp_path)
    o1 = tmp_path / "o1"
    assert main(["--input", str(inp), "--output", str(o1),
                 "--source-root", str(src)]) == 0
    a = (o1 / "STATUS_OK.tsv").read_text("utf-8-sig")
    assert "indirect:constant" in a and "STATUS_OK@C.java:1 -> STATUS_OK@U.java:1" in a
    # 2回実行で完全一致（決定性不変）
    o2 = tmp_path / "o2"
    main(["--input", str(inp), "--output", str(o2), "--source-root", str(src)])
    assert a == (o2 / "STATUS_OK.tsv").read_text("utf-8-sig")


def test_walk診断はkeyword数によらず重複しない(tmp_path: Path):
    src, inp = _tree(tmp_path)
    (src / "build").mkdir()
    (src / "build" / "G.java").write_text("class G{}\n", "utf-8")
    out = tmp_path / "o"
    main(["--input", str(inp), "--output", str(out), "--source-root", str(src)])
    d = (out / "diagnostics.txt").read_text("utf-8")
    # keyword 2個でも walk_excluded は1回（collect_files 共有）
    assert d.count("walk_excluded\tbuild/G.java") == 1


def test_progress_onはstderrのみでTSV不変(tmp_path: Path):
    src, inp = _tree(tmp_path)
    base = tmp_path / "b"; main(["--input", str(inp), "--output", str(base),
                                 "--source-root", str(src)])
    prog = tmp_path / "p"
    err = io.StringIO()
    with redirect_stderr(err):
        main(["--input", str(inp), "--output", str(prog),
              "--source-root", str(src), "--progress", "on"])
    assert "[grep_analyzer]" in err.getvalue()
    assert (base / "STATUS_OK.tsv").read_text("utf-8-sig") == \
           (prog / "STATUS_OK.tsv").read_text("utf-8-sig")  # TSV 不変


def test_memory_limit極小でも決定的かつdirectは不変(tmp_path: Path):
    src, inp = _tree(tmp_path)
    a = tmp_path / "a"; main(["--input", str(inp), "--output", str(a),
                              "--source-root", str(src)])
    b = tmp_path / "b"
    main(["--input", str(inp), "--output", str(b), "--source-root", str(src),
          "--memory-limit", "1", "--max-passes", "8"])
    # direct 行は memory-limit に依らず不変（degrade はシンボル追跡側のみ）
    da = [ln for ln in (a / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()
          if "\tdirect\t" in ln]
    db = [ln for ln in (b / "STATUS_OK.tsv").read_text("utf-8-sig").splitlines()
          if "\tdirect\t" in ln]
    assert da == db and da
```

- [ ] **Step 2: 失敗を確認** — `python -m pytest tests/integration/test_pipeline_phase2b.py -q` → FAIL（`--memory-limit`/`--progress` 未知引数 or walk_excluded 2回）

- [ ] **Step 3: 実装**

`src/grep_analyzer/fixedpoint.py`: `run_fixedpoint` に進捗・ripgrep 配線。
- import 追加: `from grep_analyzer.progress import Progress` / `from grep_analyzer import ripgrep as _rg`
- `budget = MemoryBudget(...)` の直後:
```python
    prog = Progress(opts.progress)
    prog.start(0 if files is None else len(files))
```
- 走査ループの `files` 確定後（`rel_to_abs` 構築後）、`prog.start` を実 len で再通知してよいが簡潔化のため `files` 確定直後に1度のみ:
```python
    if files is None:
        files = list(walk.walk_files(... diag=diag))
    rel_to_abs = {rel: abspath for rel, abspath in files}
    prog.start(len(files))
```
（先の暫定 `prog.start(0...)` 行は削除し、この1箇所に統一）
- 各反復のチャンク走査前に ripgrep 一次フィルタで `files` を絞る（`--use-ripgrep` かつ `rg` 利用可時のみ。出力不変＝上位集合）:
```python
        scan_files = files
        if opts.use_ripgrep:
            keep = _rg.prefilter(source_root, rel_to_abs, scan_syms)
            if keep is not None:
                scan_files = [(r, a) for r, a in files if r in keep]
```
そして `args = [(rel, str(abspath), chunk, opts.lang_map) for rel, abspath in scan_files]` に置換（`files`→`scan_files`）。
- 反復末尾 `hop += 1` の直前に `prog.hop(hop, len(scan_syms), len(scan_files))`、`while` ループ脱出後に `prog.done()`。

`src/grep_analyzer/pipeline.py`: keyword ループ前に walk 一回。`run` を編集:
- import 追加: `from grep_analyzer.walk import DEFAULT_EXCLUDE, collect_files`（`DEFAULT_EXCLUDE` は既存 import 済なら統合）
- `lang_map = opts.lang_map` の直後に:
```python
    files = collect_files(
        Path(source_root), include=opts.include, exclude=opts.exclude,
        follow_symlinks=opts.follow_symlinks,
        max_file_bytes=opts.max_file_bytes, diag=diag)
```
- `indirect = run_fixedpoint(hits, Path(source_root), opts, diag)` を:
```python
        indirect = run_fixedpoint(hits, Path(source_root), opts, diag, files=files)
```

`src/grep_analyzer/cli.py`: オプション追加。`p.add_argument("--max-paths", ...)` の直後に追記:
```python
    p.add_argument("--memory-limit", type=int, default=None, dest="memory_limit_mb")
    p.add_argument("--use-ripgrep", action="store_true", dest="use_ripgrep")
    p.add_argument("--max-passes", type=int, default=8, dest="max_passes")
    p.add_argument("--progress", default="off")
```
`EngineOptions(...)` 構築に追記:
```python
        memory_limit_mb=args.memory_limit_mb, use_ripgrep=args.use_ripgrep,
        max_passes=args.max_passes, progress=args.progress,
```

- [ ] **Step 4: 通る（最重要不変条件の総点検）**

Run: `python -m pytest tests/integration/test_pipeline_phase2b.py -q` → PASS（4本）

Run: `python -m pytest -q`
Expected: **全 PASS・0 failed/0 error**。**既存 golden 14・既存 integration（test_pipeline_fixedpoint/test_diagnostics_phase2/test_pipeline_dialect/test_pipeline）すべて byte 不変**。1ケースでも動いたら **commit せず停止し構造を疑う**。

- [ ] **Step 5: コミット**
```bash
git add src/grep_analyzer/pipeline.py src/grep_analyzer/cli.py src/grep_analyzer/fixedpoint.py tests/integration/test_pipeline_phase2b.py
git commit -m "feat(pipeline): walk一回共有＋progress＋ripgrep配線＋CLI（spec §8.2・出力不変）"
```

---

## Task 10: 出力不変・決定性の総合回帰（jobs×degrade×ripgrep 直交）

**Files:** Test `tests/integration/test_phase2b_invariants.py`

最重要不変条件1〜3の総合契約。`--jobs 1/4` × `--memory-limit 有/無` × `--use-ripgrep 有/無`（rg 隔離）× ストリーミング の直交組合せで TSV／`diagnostics.txt`（degrade 由来カテゴリ除く決定性）が byte 一致することを境界テストで固定。実装追加なし（前 Task で満たす設計＝満たさない契約があれば該当 Task に戻る）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/integration/test_phase2b_invariants.py` を新規作成:
```python
"""Phase 2b 最重要不変条件の総合契約（spec §8.2/§9・出力保存と決定性）。"""

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


def _run(tmp_path, src, inp, name, extra):
    out = tmp_path / name
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)] + extra) == 0
    return hashlib.sha256((out / "K1.tsv").read_bytes()).hexdigest()


def test_jobsとmemory_limitの直交組合せでTSV完全一致(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _run(tmp_path, src, inp, "base", [])
    variants = {
        "j4": ["--jobs", "4"],
        "mem": ["--memory-limit", "1", "--max-passes", "8"],
        "j4mem": ["--jobs", "4", "--memory-limit", "1", "--max-passes", "8"],
    }
    for name, extra in variants.items():
        assert _run(tmp_path, src, inp, name, extra) == base, name


@pytest.mark.requires_ripgrep
def test_ripgrep有無でTSV完全一致(tmp_path: Path):
    src, inp = _setup(tmp_path)
    base = _run(tmp_path, src, inp, "norg", [])
    assert _run(tmp_path, src, inp, "rg", ["--use-ripgrep"]) == base
    assert _run(tmp_path, src, inp, "rgj4",
                ["--use-ripgrep", "--jobs", "4"]) == base
```

- [ ] **Step 2: 失敗を確認 → 満たさない契約があれば該当 Task に戻る**

Run: `python -m pytest tests/integration/test_phase2b_invariants.py -q`
Expected: PASS（rg 無: 1本 PASS＋1本 skip／rg 有: 2本 PASS）。FAIL する組合せがあれば **テストは緩めず**、原因 Task（6/7/8/9）の出力不変・決定性実装を修正（spec §9 違反＝退行）。

- [ ] **Step 3: 全体回帰** — `python -m pytest -q` → 全 PASS・0 failed/0 error・既存 golden 14 不変。

- [ ] **Step 4: コミット**
```bash
git add tests/integration/test_phase2b_invariants.py
git commit -m "test(phase2b): jobs×memory×ripgrep 直交の出力不変・決定性契約（spec §8.2/§9）"
```

---

## Task 11: Phase 2b 全テスト緑化と完了確認

**Files:** Modify `docs/superpowers/plans/phase0-gate-result.md`

- [ ] **Step 1: 全テスト実行** — `cd /workspaces/grep_helpers2 && python -m pytest -q` → 全 PASS（Phase 2a 130 ＋ Phase 2b 追加分。0 failed/0 error）。`python -m grep_analyzer --help` exit 0（新オプションが usage に出る）。失敗あれば該当 Task へ戻る（完了主張しない）。

- [ ] **Step 2: spec §8.2／最重要不変条件 充足チェックリスト照合**

- §8.2 ストリーミング走査（bytes 親非常駐） → Task6（`test_ストリーミング化後も出力はPhase2aと同一`）
- §8.2 差分走査（確定済の再 I/O 省略・ローカライゼーション保持） → Task6（`loc_cache`）
- §8.2 walk 一回化（keyword 横断診断重複解消） → Task5/9（`test_walk診断はkeyword数によらず重複しない`）
- §8.2 任意 ripgrep 一次フィルタ（出力保存上位集合） → Task3/9/10（`@pytest.mark.requires_ripgrep`）
- §8.2 --memory-limit 会計（決定的近似） → Task1/7
- §8.2 degrade 優先1 決定的切り捨て → Task7（memory 駆動 cap・同一決定キー）
- §8.2 degrade 優先2 来歴スピル → Task2/8（`test_スピル発生でも出力はPhase2aと同一`）
- §8.2 最終手段 オートマトン分割多パス＋--max-passes 上限 → Task8（`test_オートマトン分割多パスでも出力不変`/`test_max_passes超過は優先1へ戻り…`）
- §8.2 --progress 標準エラー進捗 → Task4/9（`test_progress_onはstderrのみでTSV不変`）
- 最重要不変条件1〜3（出力 byte 不変・degrade 出力保存・jobs/degrade/ripgrep 直交決定性）→ Task10＋既存 golden 14 不変＋既存 130 不変

- [ ] **Step 3: 完了記録を追記しコミット**

`phase0-gate-result.md` 末尾に「## Phase 2b 完了記録」（完了日 UTC、コミット範囲、全テスト結果、上記対応表、最重要不変条件の充足＝既存 golden 14・既存 130 不変、Phase 3 申し送り）を追記。

```bash
git add docs/superpowers/plans/phase0-gate-result.md
git commit -m "chore: Phase 2b 完了（資源degrade・ストリーミング・ripgrep・progress）"
```

---

## Phase 2b の境界（Phase 3 は別計画）

- **Phase 3 に送る**: 60GB perf ベースライン（`tests/perf/` `@pytest.mark.perf` 非ゲート・本近似 budget の実バイト厳密化検証）、`--resume` キーワード単位再開、diagnostics の上限超過時 §10.3 縮約（カテゴリ別集約＋代表サンプル）、規模分割 `<keyword>.partNN.tsv`（spec §9）、`requirements.lock`（spec §4.1・ユーザ決定）、`--output-encoding`/`--encoding-fallback`（spec §10.1 正本だが decode は Phase 1.5 確立済）。
- **Phase 2b 既知境界（spec 引用付き・仕様固定）**: (1) メモリ近似は決定的アイテム近似（実 RSS 非依存＝spec §9 決定性優先。実バイト厳密性は Phase 3 perf）。(2) ripgrep は ASCII 識別子前提の上位集合フィルタ（Phase 2a の ASCII 識別子既知境界を継承＝§8.2）。(3) 差分走査の効果は spec §8.2 誠実化どおり限定的（新規シンボルは全ツリー走査不可避。Phase 2b の効果は確定フェーズ再 I/O 排除に限る）。(4) `--progress` は stderr 専用・非決定要素（ETA 等）は出力契約外（最重要不変条件4）。
- 成果物: 「Phase 2a の出力・決定性を1バイトも変えずに、`--memory-limit` 超過で決定的切り捨て→来歴スピル→オートマトン分割多パスへ degrade し、ストリーミング走査・任意 ripgrep・標準エラー進捗・walk 一回化を備えた、メモリ制約下でも動く決定的ツール」。単体でテスト可能・出荷可能。

---

## Self-Review（v1・本計画著者によるチェック）

**1. spec coverage（§8.2 全項目）:** ネイティブ Aho-Corasick＋ripgrep＋multiprocessing → 既存＋Task3/9 ✓。差分走査の誠実な限定効果 → Task6（loc_cache・spec 誠実化を実装注で明記）✓。来歴グラフ memory を --memory-limit 対象・上限超過スピル → Task1/2/7/8 ✓。degrade 優先順位（決定的切り捨て→スピル→オートマトン分割・最大パス上限）→ Task7/8 ✓。ファイルサイズ/バイナリ skip・include/exclude・symlink・realpath 重複（既存 walk・不変）→ Task5 で collect_files 化のみ（規則不変）✓。進捗ログ stderr・--progress 粒度 → Task4/9 ✓。§15 フェーズ2 のうち資源 degrade を 2b として（Phase 2a 境界の §15 根拠付き分割を継承）✓。§10.4 CLI（--memory-limit/--use-ripgrep/--max-passes/--progress）→ Task9 ✓。Phase 3 送り（perf/resume/§10.3 縮約/partNN/requirements.lock/output-encoding）は境界に spec 根拠付き明記 ✓。

**2. Placeholder scan:** 全 Task に実コード・実コマンド・期待出力。`...`/「TBD」/「後で」なし。fixedpoint の改変は「該当ブロックを次へ置換」と置換対象を特定（Phase 2a 実コードを引用）＝プレースホルダでない。

**3. Type consistency（串刺し）:** `MemoryBudget`/`estimate_items`/`EdgeStore`/`serialize_edge`/`parse_edge`/`ripgrep.prefilter`/`Progress`/`collect_files`/`EngineOptions`（末尾既定追加で既存キーワード構築不変）/`run_fixedpoint(*, files=None)`/`_scan_file`（args=abspath）を冒頭契約と全 Task で一致。`memory_limit_mb=None` で全 degrade 機構が Phase 2a と完全同一挙動（unlimited で over_mem 恒偽・nchunks=1・estore 非スピル）＝既存 golden 14・既存 130 不変を Task6/7/8/9/10 の各 Step4 が要求。`test_fixedpoint._opts` ヘルパに新フィールド既定追加（Task7 Step1）で既存全 fixedpoint テスト不変。

> 次レビュー重点候補: ① `loc_cache` 由来の `full_text` 再構成が tree-sitter 分類で Phase 2a の `text` と厳密同値か（行欠落・末尾改行・空行の扱い）。② オートマトン分割の `agg`＋`sorted(found)` が jobs 並列・チャンク順非依存で Phase 2a 単一走査と byte 同値か。③ `_apply_global_cap` の memory 駆動 `keep` 単調縮小が `edge_count`（スピル後メモリ非保持）と整合し決定的か。④ ripgrep 上位集合の安全性（非 ASCII/エンコーディング差で取りこぼさないか＝ASCII 識別子前提の明文と一致するか）。⑤ `EngineOptions` 末尾既定追加が Phase 2a の全 `EngineOptions(...)` 構築（cli/pipeline/test）と後方互換か。
