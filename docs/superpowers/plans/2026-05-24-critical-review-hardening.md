# 批判的レビュー対応・堅牢化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 2026-05-24 の批判的 AI レビューで実証された DoS/堅牢性・セキュリティ・正確性・テスト網・ドキュメントの欠陥を、設計不変条件（決定的＝バイト同一出力）を壊さずに塞ぐ。

**Architecture:** 既存の `src/grep_analyzer/` を局所改修。A-1〜A-6 は「ハング/OOM/クラッシュの有限化」であり**正常系の出力バイトは不変**（安全弁が実際に効くようにするだけ）。B-1/B-2 は分類・抽出の正確性改善で**既存 golden 46 件はバイト不変**（病的入力のみ改善）。C-1〜C-4 はテスト網の穴埋め。E はドキュメントの誠実化。

**Tech Stack:** Python 3.12 / pytest / tree-sitter 0.23 / multiprocessing。テストは既存様式（日本語テスト名・`tests/unit`・`tests/integration`・`tests/golden`）に合わせる。

**検証の土台（全タスク共通）:** 各タスク完了時に必ず以下が緑であること。
- `python -m pytest -q` → 既存 **437 passed, 9 skipped** を割らない（新規テストぶん増える）。
- `python -m pytest tests/golden -q` → **46 passed**（バイト不変の最終アンカー）。

---

## File Structure（改修・新規ファイルの責務）

| ファイル | 役割 | 本計画での変更 |
|---|---|---|
| `src/grep_analyzer/provenance.py` | 来歴グラフ・chain 列挙 | A-1: `_dfs` を生成時打ち切りへ |
| `src/grep_analyzer/diagnostics.py` | 診断蓄積 | A-2: 詳細保持件数の上限化（カウントは全件維持） |
| `src/grep_analyzer/chase.py` | 追跡シンボル抽出 dispatcher | A-4: 行長クランプ（ReDoS 無害化） |
| `src/grep_analyzer/walk.py` | ツリー走査 | A-3: relpath 封じ込め helper / A-6: dir-symlink ループ枝刈り |
| `src/grep_analyzer/pipeline.py` | direct＋不動点併合 | A-3: direct 対象を walk 収集集合へ限定 |
| `src/grep_analyzer/fixedpoint/_seed.py` | seed 初期化 | A-3: seed ソース読込の封じ込め |
| `src/grep_analyzer/fixedpoint/_scan.py` | ワーカ走査 | A-5: per-file 例外を `found=[]`＋診断へ降格 |
| `src/grep_analyzer/classifiers/python_chaser.py` | Python AST chaser | B-1: `bindings_at_line` 統一 |
| `src/grep_analyzer/classifiers/javascript_chaser.py` | JS AST chaser | B-1: 同上 |
| `src/grep_analyzer/classifiers/typescript_chaser.py` | TS/TSX AST chaser | B-1: 同上 |
| `src/grep_analyzer/proc_preprocess.py` | Pro*C EXEC マスク | B-2: 区間検出をリテラル空白化コピーに統一 |
| `src/grep_analyzer/fixedpoint/_options.py` | EngineOptions | C-1: `force_spill` テスト用ノブ追加 |
| `tests/unit/test_provenance.py` | A-1 回帰 | 経路爆発の有限化テスト追加 |
| `tests/unit/test_diagnostics.py` | A-2 回帰 | 保持上限テスト追加 |
| `tests/unit/test_chase.py` | A-4 回帰 | 行長クランプテスト追加 |
| `tests/integration/test_cli.py` | A-3 回帰 | パストラバーサル拒否テスト追加 |
| `tests/unit/test_scan_worker.py`（新規） | A-5 回帰 | ワーカ例外降格テスト |
| `tests/unit/test_walk.py` | A-6 回帰 | dir-symlink ループ終了性テスト |
| `tests/unit/test_ast_chaser.py` | B-1 回帰 | 1行複数文抽出テスト |
| `tests/unit/test_proc_preprocess.py`（新規） | B-2 回帰 | リテラル `;` 区間テスト |
| `tests/integration/test_spill_e2e.py`（新規） | C-1 | spill 経由の非空出力バイト同値 |
| `tests/integration/test_resume_skip.py`（新規） | C-2 | resume の実スキップ spy |
| `tests/golden/test_golden.py` | C-3 | jobs 横断のバイト同値追加 |
| `README.md` / spec / 差分設計書 | E | 数値陳腐化・over-claim 是正 |

---

## Phase 1: DoS／堅牢性の有限化（正常系の出力は不変）

### Task 1: A-1 chains_to の経路爆発を生成時打ち切りへ

**問題（実証済）:** `provenance.py:49-65` の `_dfs` は**全単純パスを列挙し終えてから** `max_paths` で切る。密 DAG で `max_paths=10` を渡しても depth8/width5 で 5.07 秒・深さ+1 で約16倍。`_finalize.py:63` が終端 occurrence ごとに呼ぶため人気シンボル1つで事実上ハング。

**設計不変条件への影響:** 生成時に打ち切ると、capping が**実際に発火するケースに限り**「残す max_paths 本」の選択が「DFS 順の先頭 max_paths 本」へ変わる（従来は全列挙後の辞書順最小 max_paths 本）。DFS 順自体は決定的（seed `sorted`・隣接 `sort`）なので**決定性は維持**。golden 46 件は max_paths(=1000) に到達しないため**出力バイト不変**。capping は spec §9 で「打ち切りを diagnostics 記録」とされた安全弁であり、どの部分集合を残すかは不変条件ではない＝意図的・文書化された挙動変更。

**Files:**
- Modify: `src/grep_analyzer/provenance.py:49-81`
- Test: `tests/unit/test_provenance.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_provenance.py` の末尾に追記:

```python
import time

from grep_analyzer.provenance import ProvenanceGraph, Occurrence
from grep_analyzer.diagnostics import Diagnostics


def _dense_dag(depth: int, width: int):
    """各層 width ノードを全結合した DAG（単純パスが指数的）。"""
    g = ProvenanceGraph()
    seed = Occurrence("s", "f", 0)
    g.add_seed(seed)
    layers = [[seed]]
    for d in range(1, depth + 1):
        layer = [Occurrence(f"n{d}_{w}", "f", d * 100 + w) for w in range(width)]
        for p in layers[-1]:
            for ch in layer:
                g.add_edge(p, ch)
        layers.append(layer)
    target = Occurrence("TGT", "f", 9999)
    for p in layers[-1]:
        g.add_edge(p, target)
    return g, target


def test_chains_to_は密DAGでも有限時間で打ち切る():
    g, target = _dense_dag(depth=14, width=4)   # 旧実装は列挙が事実上終わらない規模
    diag = Diagnostics()
    t0 = time.perf_counter()
    res = g.chains_to(target, max_depth=20, max_paths=10, diag=diag)
    elapsed = time.perf_counter() - t0
    assert len(res) == 10                         # 上限ちょうどで返る
    assert elapsed < 5.0                          # 生成時打ち切り＝瞬時（旧実装は分オーダ）
    assert diag._counts.get("prov_path_capped", 0) == 1


def test_chains_to_小グラフの出力は打ち切りで不変():
    # max_paths に達しない小グラフでは従来と同一の辞書順 chain を返す。
    g = ProvenanceGraph()
    s = Occurrence("S", "f", 1)
    a = Occurrence("A", "f", 2)
    t = Occurrence("T", "f", 3)
    g.add_seed(s)
    g.add_edge(s, a)
    g.add_edge(a, t)
    diag = Diagnostics()
    res = g.chains_to(t, max_depth=10, max_paths=1000, diag=diag)
    assert res == ["S@f:1 -> A@f:2 -> T@f:3"]
    assert diag._counts.get("prov_path_capped", 0) == 0


def test_chains_to_は巨大max_depthでも例外を出さない():
    # 深い線形連鎖＋巨大 max_depth でも RecursionError をユーザへ送出しない。
    g = ProvenanceGraph()
    prev = Occurrence("s", "f", 0)
    g.add_seed(prev)
    for i in range(1, 4000):                       # Python 既定再帰上限(~1000)を超える深さ
        cur = Occurrence(f"n{i}", "f", i)
        g.add_edge(prev, cur)
        prev = cur
    diag = Diagnostics()
    g.chains_to(prev, max_depth=10 ** 9, max_paths=10, diag=diag)  # 例外なし
    assert diag._counts.get("prov_recursion_skipped", 0) >= 1
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest tests/unit/test_provenance.py::test_chains_to_は密DAGでも有限時間で打ち切る -v`
Expected: FAIL（旧実装は `elapsed < 5.0` を満たさず時間切れ／ハング）

- [ ] **Step 3: 最小実装**

`provenance.py` の `chains_to` と `_dfs` を次に置換:

```python
    def chains_to(
        self, target: Occurrence, *, max_depth: int, max_paths: int, diag: Diagnostics
    ) -> list[str]:
        """各 seed から target への単純パスを chain 文字列の決定的リストで返す。

        生成時打ち切り（spec §9 安全弁）: 収集本数が max_paths+1 に達した時点で
        DFS を停止する（+1 は「真に超過したか」を判定し prov_path_capped の誤発火を
        防ぐため＝旧 `> max_paths` 意味を厳密復元）。DFS 順は seed `sorted`・隣接
        `sort` で決定的なので打ち切り後の集合も決定的。max_paths 未達は従来と同値。
        深い連鎖での RecursionError は捕捉し prov_recursion_skipped を記録のうえ
        ここまでの結果で打ち切る（巨大 --max-depth クラッシュの防御。再帰上限は固定で
        入力も固定ゆえ打ち切り点・部分結果とも決定的）。
        """
        limit = max_paths + 1
        results: list[str] = []
        try:
            for seed in sorted(self._seeds):
                if len(results) >= limit:
                    break
                self._dfs(seed, target, [seed], {seed}, set(),
                          max_depth, limit, diag, results)
        except RecursionError:
            diag.add("prov_recursion_skipped", _hop(target))
        results = sorted(set(results))
        if len(results) > max_paths:
            diag.add("prov_path_capped", f"{_hop(target)}\t>={max_paths}")
            results = results[:max_paths]
        return results

    def _dfs(self, node, target, path, visited_occurrences, visited_symbols,
             max_depth, limit, diag, results) -> None:
        if len(results) >= limit:               # 生成時打ち切り（指数爆発の根治）
            return
        if node == target:
            results.append(" -> ".join(_hop(o) for o in path))
            return
        if len(path) - 1 >= max_depth:
            diag.add("prov_max_depth", _hop(path[0]) + " ... " + _hop(node))
            return
        for next_occ in self._adj.get(node, []):
            if len(results) >= limit:
                return
            if next_occ in visited_occurrences or next_occ.symbol in visited_symbols:
                diag.add("prov_cycle_cut", _hop(node) + " -> " + _hop(next_occ))
                continue
            self._dfs(next_occ, target, path + [next_occ],
                      visited_occurrences | {next_occ},
                      visited_symbols | {next_occ.symbol},
                      max_depth, limit, diag, results)
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/unit/test_provenance.py -v`
Expected: PASS（新規2件含む全件）

- [ ] **Step 5: 回帰確認（出力バイト不変）**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed・全体は従来件数＋新規2件で緑

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/provenance.py tests/unit/test_provenance.py
git commit -m "fix(prov): #A-1 chains_to を生成時打ち切りへ（経路爆発の有限化・出力不変）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: A-2 diagnostics の詳細保持を上限化（カウントは全件維持）

**問題（精読確認）:** `diagnostics.py:26-29` の `add()` は全メッセージを `_detail` に無条件 append。`detail_limit` は render 時に切るだけでメモリは減らない。さらに `prov_*`/`symbol_rejected` は縮約完全免除で render でも全件。A-1 の `prov_cycle_cut` 大量発火と連動し `--memory-limit` の予算外で OOM し得る。

**設計不変条件への影響:** カウンタ `_counts` は従来どおり全件（summary は不変＝golden の `diagnostics_summary.txt` 照合は不変）。保持上限 `_MAX_RETAINED` は十分高く（既定 200,000）、実運用・全テストで到達しない＝**通常の detail 出力は不変**。Inv-6（`--diagnostics-detail-limit 0` がバイト同値）は「1カテゴリが 20万件を超える病的ケースを除き不変」へ but-clause 化（Task 12/E で明記）。

**Files:**
- Modify: `src/grep_analyzer/diagnostics.py:19-49`
- Test: `tests/unit/test_diagnostics.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_diagnostics.py` の末尾に追記:

```python
from grep_analyzer.diagnostics import Diagnostics, _MAX_RETAINED


def test_詳細保持はカテゴリごとに上限化されカウントは全件():
    d = Diagnostics()
    n = _MAX_RETAINED + 50
    for i in range(n):
        d.add("prov_cycle_cut", f"e{i}")        # 免除カテゴリでも保持は上限内
    assert d._counts["prov_cycle_cut"] == n      # summary は真総数
    assert len(d._detail["prov_cycle_cut"]) <= _MAX_RETAINED
    text = d.render(detail_limit=0)              # 無制限指定でも保持上限で OOM しない
    assert f"prov_cycle_cut\t{n}" in text         # summary 行は真総数
    assert "retained" in text                     # 保持打ち切りマーカが出る


def test_保持上限内は従来どおり全件詳細():
    d = Diagnostics()
    d.add("decode_replaced", "a.c")
    d.add("decode_replaced", "b.c")
    text = d.render(detail_limit=0)
    assert "decode_replaced\ta.c" in text
    assert "decode_replaced\tb.c" in text
    assert "retained" not in text
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest tests/unit/test_diagnostics.py::test_詳細保持はカテゴリごとに上限化されカウントは全件 -v`
Expected: FAIL（`_MAX_RETAINED` 未定義 ImportError）

- [ ] **Step 3: 最小実装**

`diagnostics.py` を次に改修。`_MAX_RETAINED` 定数を追加し、`add()` で保持を上限化、`render()` で打ち切りマーカを出す。

`SECTION_8_4_CATEGORIES` 定義の直後（line 8 付近）に追加:

```python
# メモリ安全のための「カテゴリごとの詳細保持上限」。カウント(_counts)は常に全件で
# 正確だが、明細(_detail)はこの件数で頭打ちにして OOM を防ぐ（A-2）。実運用・
# 全テストで到達しない高さに設定。render の縮約（detail_limit）とは独立。
_MAX_RETAINED = 200_000
```

`add()` を置換（明細は厳密に `_MAX_RETAINED` 件で頭打ち＝marker はデータに混ぜない）:

```python
    def add(self, category: str, message: str) -> None:
        """1件の診断を記録する（カウントは全件、明細は _MAX_RETAINED 件で頭打ち）。"""
        self._counts[category] += 1
        lst = self._detail[category]
        if len(lst) < _MAX_RETAINED:
            lst.append(message)
```

`render()` を置換（真総数 `_counts` を基準に縮約／保持上限マーカを出す。非縮約・保持上限内のケースは**従来とバイト同一**＝Inv-6 維持）:

```python
    def render(self, detail_limit: int = 0, exempt=None) -> str:
        """spec §10.3 スキーマ。detail_limit=0 は無制限＝保持上限内なら現行と完全同一。"""
        is_exempt = (lambda c: _is_exempt(c, exempt)) \
            if exempt is not None else (lambda c: False)  # prov_ ロジック単一源
        out = ["# summary"]
        for cat in sorted(self._counts):
            out.append(f"{cat}\t{self._counts[cat]}")   # 常に真総数
        out.append("# detail")
        for cat in sorted(self._detail):
            msgs = self._detail[cat]
            total = self._counts[cat]                    # 真総数（保持上限で msgs より大のことあり）
            if detail_limit > 0 and not is_exempt(cat) and total > detail_limit:
                for msg in msgs[:detail_limit]:
                    out.append(f"{cat}\t{msg}")
                out.append(f"{cat}\t(... {total - detail_limit} more, {total} total)")
            else:
                for msg in msgs:
                    out.append(f"{cat}\t{msg}")
                if total > len(msgs):                    # 保持上限で落ちた明細を明示
                    out.append(f"{cat}\t(... retained cap {_MAX_RETAINED}, {total} total)")
        return "\n".join(out) + "\n"
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/unit/test_diagnostics.py -v`
Expected: PASS

- [ ] **Step 5: 回帰確認**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed・全体緑（summary 不変ゆえ diagnostics_summary golden も緑）

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/diagnostics.py tests/unit/test_diagnostics.py
git commit -m "fix(diag): #A-2 詳細保持をカテゴリ上限化（カウント全件維持・OOM 防止）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A-4 行長クランプで GROOVY 正規表現の ReDoS を無害化

**問題（実証済）:** `patterns/symbol_extraction.py:35-37` の `GROOVY_CONST_RE` は修飾子反復群と型トークン群が `\s` で曖昧競合し、約2KBの1行（`public static static…x`）で 3.4 秒・超線形。ヒット行長のクランプがどこにも無く、minify/生成された長い Groovy/Gradle 1 行でワーカがハング。

**設計不変条件への影響:** クランプ閾値 `_MAX_CHASE_LINE`（既定 8192 文字）は通常のソース行を超える。snippet が既に 800 文字でクランプ済の思想に合わせ、追跡抽出への入力行のみクランプ。automaton 走査（ヒット検出）には適用しない＝**ヒット検出は不変**。クランプは抽出対象を「行頭 8192 文字」に限るだけで通常コードでは到達せず**出力不変**。

**Files:**
- Modify: `src/grep_analyzer/chase.py:17-48`
- Test: `tests/unit/test_chase.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_chase.py` の末尾に追記:

```python
import time

from grep_analyzer.chase import extract_chase_symbols, _MAX_CHASE_LINE


def test_groovy_長行でもクランプで有限時間():
    pathological = "public " + "static " * 4000 + "x"   # 約 2.8 万文字・末尾 = 無し
    t0 = time.perf_counter()
    extract_chase_symbols("groovy", "bourne", pathological)
    assert time.perf_counter() - t0 < 2.0               # 旧実装は数十秒〜（クランプ 800 で <0.5s）


def test_クランプ閾値内のgroovyは従来どおり抽出():
    cs = extract_chase_symbols("groovy", "bourne", "public static final int MAX = 1")
    assert "MAX" in cs.constants
    assert len("public static final int MAX = 1") < _MAX_CHASE_LINE
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest tests/unit/test_chase.py::test_groovy_長行でもクランプで有限時間 -v`
Expected: FAIL（ImportError: `_MAX_CHASE_LINE` 未定義／または時間超過）

- [ ] **Step 3: 最小実装**

`chase.py` のインポート直後（line 15 付近）に定数追加:

```python
# 追跡シンボル抽出（行ベース正規表現 chaser）への入力行の最大長。これを超える行は
# 先頭のみを見る。正規表現のバックトラッキング爆発（ReDoS）を構造的に無害化する
# 安全弁。snippet の文字数クランプ（_clamp.CHAR_MAX=800）と同値に揃える＝通常の
# ソース行長を上回るため出力は実質不変（A-4）。8192 等の大きい値では GROOVY 正規
# 表現が依然 ReDoS する（実測: 8192字は 60s 超）ため必ず 800 とする。automaton 走査
# （ヒット検出）には適用しないためヒットの取りこぼしは生じない。
_MAX_CHASE_LINE = 800
```

`extract_var_symbols` の本体先頭（`if language == "sql":` の前）に1行追加:

```python
    line = line[:_MAX_CHASE_LINE]
```

`extract_chase_symbols` の本体先頭（`chaser = _CHASERS.get(language)` の前）に1行追加:

```python
    line = line[:_MAX_CHASE_LINE]
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/unit/test_chase.py -v`
Expected: PASS

- [ ] **Step 5: 回帰確認**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed・全体緑

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/chase.py tests/unit/test_chase.py
git commit -m "fix(chase): #A-4 行ベース chaser に行長クランプ（GROOVY ReDoS 無害化・出力不変）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: A-3 direct/seed のパス封じ込め（トラバーサル／絶対パス注入）

**問題（実証済）:** `pipeline.py:88`・`fixedpoint/_seed.py:57` は `Path(source_root) / relpath` に封じ込め検査が無い。grep 入力の `../../../../etc/hostname` は root 外を実読し、絶対パス `/etc/shadow` は左辺を捨てて source_root を完全無視して読む。内容は snippet 列に出力される。

**修正方針:** `walk.is_contained_relpath` を追加し、**direct/seed の読込前に「絶対パス・`..` 脱出」を拒否する封じ込めガード**を入れる。収容（source_root 配下）の relpath は従来どおり読む＝golden 不変を最優先。
（注: 「direct を walk 収集集合に限定」案は size/binary/exclude フィルタも共有できて理論上は綺麗だが、バイナリ除外される `grep_jar_artifact` 等の golden 出力を変えるリスクがあるため**採らない**。封じ込めガードのみで A-3 は完全に解消する。）

**設計不変条件への影響:** 収容ファイル（全 golden の src 配下）は従来どおり読むため**出力バイト不変**。絶対パス・`..` 脱出のみ拒否され `missing_source` 診断へ降格する。

**Files:**
- Modify: `src/grep_analyzer/walk.py`（helper 追加）、`src/grep_analyzer/pipeline.py:26,86-89`、`src/grep_analyzer/fixedpoint/_seed.py:57-58`
- Test: `tests/integration/test_cli.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_cli.py` の末尾に追記:

```python
import hashlib


def test_grep入力の絶対パスはsource_root外を読まない(tmp_path):
    from grep_analyzer.cli import main
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ int x=1; }\n", "utf-8")
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP_SECRET_TOKEN\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    # 絶対パスと .. トラバーサルの両方を仕込む
    (inp / "x.grep").write_text(
        f"{secret}:1:TOP_SECRET_TOKEN\n"
        f"../../secret.txt:1:TOP_SECRET_TOKEN\n", "utf-8")
    out = tmp_path / "o"
    assert main(["--input", str(inp), "--output", str(out),
                 "--source-root", str(src)]) == 0
    tsv = (out / "x.tsv").read_text("utf-8-sig")
    assert "TOP_SECRET_TOKEN" not in tsv          # 秘密の内容が漏れない
    assert str(secret) not in tsv
    diag = (out / "diagnostics.txt").read_text("utf-8")
    assert "missing_source" in diag               # 拒否は診断へ
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest "tests/integration/test_cli.py::test_grep入力の絶対パスはsource_root外を読まない" -v`
Expected: FAIL（現状は秘密内容が TSV に漏れる）

- [ ] **Step 3: 最小実装**

`walk.py` に helper を追加（`_is_binary` の前、line 46 付近）:

```python
def is_contained_relpath(relpath: str) -> bool:
    """relpath が source_root 配下に収まる安全な相対パスか。

    絶対パス・空・`..` を含むパスを拒否する（パストラバーサル／絶対パス注入の防御）。
    """
    if not relpath or os.path.isabs(relpath):
        return False
    return ".." not in Path(relpath).parts
```

`pipeline.py:26` の walk import に `is_contained_relpath` を追加:

```python
from grep_analyzer.walk import DEFAULT_EXCLUDE, collect_files, is_contained_relpath
```

`pipeline.py:88-89` の direct 読込ガードに封じ込め検査を追加（`Path(source_root) / relpath` 自体は維持＝収容ファイルは従来どおり読む）:

```python
                target = Path(source_root) / relpath
                if is_contained_relpath(relpath) and target.is_file():
```

`_seed.py:57-58` の seed 読込ガードに封じ込め検査を追加:

```python
        from grep_analyzer.walk import is_contained_relpath
        sp = source_root / s.file
        if is_contained_relpath(s.file) and sp.is_file():
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest "tests/integration/test_cli.py::test_grep入力の絶対パスはsource_root外を読まない" -v`
Expected: PASS

- [ ] **Step 5: 回帰確認（出力バイト不変）**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed・全体緑

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/walk.py src/grep_analyzer/pipeline.py src/grep_analyzer/fixedpoint/_seed.py tests/integration/test_cli.py
git commit -m "fix(security): #A-3 direct/seed をパス封じ込め（トラバーサル/絶対パス注入を拒否）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: A-5 ワーカの per-file 例外を `found=[]`＋診断へ降格

**問題（精読確認）:** `_scan.py:93`（`_scan_one`）に per-file try/except が無く、`Path(abspath).read_bytes()` の `OSError`（walk 後の TOCTOU 消失・権限変化）が `pool.map`（`__init__.py:78`）からそのまま送出され、その keyword が全滅。`decode_bytes` は必ず成功・`parse_tree` は try 済なので主因は読込 I/O。

**設計不変条件への影響:** 正常ファイルは従来経路（例外なし）＝**出力不変**。失敗ファイルのみ空ヒット＋診断へ。診断は worker からは返せない（pickle/集約外）ため、`found` に診断用の番兵は乗せず、`_scan_one` の戻り値 `relpath, enc, replaced, language, dialect, found` の `found=[]` で握る（読めない＝ヒット0 は正しい）。

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_scan.py:93-101`
- Test: `tests/unit/test_scan_worker.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_scan_worker.py`（新規）:

```python
"""A-5: ワーカ走査の per-file 例外降格（読めないファイルで run 全体を落とさない）。"""

from grep_analyzer import automaton
from grep_analyzer.fixedpoint._scan import _scan_one


def test_読めないファイルは例外でなく空ヒットを返す(tmp_path):
    missing = tmp_path / "ghost.java"            # walk 後に消えた想定（存在しない）
    auto = automaton.build(["K1"])
    rel, enc, replaced, lang, dialect, found = _scan_one(
        "ghost.java", str(missing), auto, {}, ["cp932", "euc-jp", "latin-1"])
    assert rel == "ghost.java"
    assert found == []                            # 例外送出せず空


def test_読めるファイルは従来どおりヒットを返す(tmp_path):
    f = tmp_path / "A.java"
    f.write_text("int K1 = 1;\n", "utf-8")
    auto = automaton.build(["K1"])
    rel, enc, replaced, lang, dialect, found = _scan_one(
        "A.java", str(f), auto, {}, ["cp932", "euc-jp", "latin-1"])
    assert any(sym == "K1" for sym, *_ in found)
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest tests/unit/test_scan_worker.py::test_読めないファイルは例外でなく空ヒットを返す -v`
Expected: FAIL（`FileNotFoundError` が送出される）

- [ ] **Step 3: 最小実装**

`_scan.py` の `_scan_one` 冒頭（line 100-101 の `_read_meta` 呼出）を try/except で包む:

```python
    try:
        text, enc, replaced, language, dialect = _read_meta(
            relpath, abspath, lang_map, fallback, cache)
    except OSError:
        # walk 後の TOCTOU（消失/権限変化）等。run 全体を落とさず空ヒットへ降格。
        return relpath, "utf-8", False, "c", "bourne", []
```

（`found = []` 以降は現状のまま。`automaton_obj is not None` 分岐へ進むが text が無いので空のまま返る経路にはならない＝早期 return で確定。）

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/unit/test_scan_worker.py -v`
Expected: PASS（2件）

- [ ] **Step 5: 回帰確認**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed・全体緑

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/fixedpoint/_scan.py tests/unit/test_scan_worker.py
git commit -m "fix(scan): #A-5 ワーカの per-file I/O 例外を空ヒットへ降格（run 全体の巻き添え防止）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: A-6 `--follow-symlinks` 時のディレクトリ symlink ループ枝刈り

**問題（精読確認）:** `walk.py:60` の `os.walk(root, followlinks=True)` はディレクトリ循環を検出しない。`a/b -> a` のような循環で第1ループが無限に深いパスを生成し、ファイル単位の `seen_real` 重複排除（第2ループ）に到達しない＝ハング。`--follow-symlinks` は opt-in だが終了性が無保証。

**設計不変条件への影響:** `--follow-symlinks` を使わない既定経路は `followlinks=False`＝**完全不変**。循環が無いツリーでも訪問済みディレクトリ realpath を覚えるだけで yield 集合は不変。

**Files:**
- Modify: `src/grep_analyzer/walk.py:60-73`
- Test: `tests/unit/test_walk.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_walk.py` の末尾に追記:

```python
import os

from grep_analyzer.walk import walk_files
from grep_analyzer.diagnostics import Diagnostics


def test_dirシンボリックリンクのループを枝刈りして再走査しない(tmp_path):
    root = tmp_path / "root"; root.mkdir()
    (root / "a.c").write_text("int x=1;\n", "utf-8")
    sub = root / "sub"; sub.mkdir()
    (sub / "b.c").write_text("int y=1;\n", "utf-8")
    os.symlink(root, sub / "loop")               # sub/loop -> root（ディレクトリ循環）
    diag = Diagnostics()
    rels = [r for r, _ in walk_files(
        root, include=[], exclude=[], follow_symlinks=True,
        max_file_bytes=5_000_000, diag=diag)]
    # 実ファイルは relpath 辞書順で決定的に1回ずつ
    assert rels == ["a.c", "sub/b.c"]
    # 枝刈りの観測可能効果: ループ配下を再走査しない＝symlink_dedup が発火しない。
    # （fix 前は Linux の ELOOP で約40段まで降り loop 配下を再走査→symlink_dedup 多数）
    assert diag._counts.get("symlink_dedup", 0) == 0
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest "tests/unit/test_walk.py::test_dirシンボリックリンクのループを枝刈りして再走査しない" -v`
Expected: FAIL（`symlink_dedup` が >0＝fix 前は ELOOP でループ配下を再走査し dedup が多数発火）

> 注: Linux では `os.walk(followlinks=True)` はカーネルの ELOOP（symlink 約40段）で
> 自然終了するためハングはしない。よって本テストは「終了性」ではなく**枝刈りの
> 観測可能効果（`symlink_dedup` 非発火）**で fix 前後を判別する。`visited_dirs` 枝刈りは
> ELOOP 非依存・移植的な終了性も同時に与える。

- [ ] **Step 3: 最小実装**

`walk.py` の第1ループ（line 58-73）を次に置換。訪問済みディレクトリ realpath を覚え、再訪ディレクトリへは降りない（`dirnames` を in-place フィルタ）:

```python
    seen_real: dict[str, str] = {}
    candidates: list[tuple[str, Path]] = []
    visited_dirs: set[str] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
        if follow_symlinks:
            # ディレクトリ symlink 循環の無限再帰を枝刈り（os.walk は検出しない）。
            real_dir = os.path.realpath(dirpath)
            if real_dir in visited_dirs:
                dirnames[:] = []
                continue
            visited_dirs.add(real_dir)
        dirnames.sort()
        for name in sorted(filenames):
            abspath = Path(dirpath) / name
            relpath = abspath.relative_to(root).as_posix()
            if abspath.is_symlink() and not follow_symlinks:
                diag.add("symlink_skipped", relpath)
                continue
            if _match_any(relpath, exclude):
                diag.add("walk_excluded", relpath)
                continue
            if include and not _match_any(relpath, include):
                continue
            candidates.append((relpath, abspath))
```

**重要**: 第2ループ（`for relpath, abspath in sorted(candidates):` 以降＝`seen_real` による
realpath 重複排除・サイズ/バイナリ skip・yield）は**現状のまま不変**。上記置換は第1ループ
（candidates 収集）のみを対象とする。`seen_real` の宣言（第1ループ冒頭）も維持する。

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest "tests/unit/test_walk.py::test_dirシンボリックリンクのループを枝刈りして再走査しない" -v`
Expected: PASS

- [ ] **Step 5: 回帰確認（既定経路不変）**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed（`symlink_dedup` 含む）・全体緑

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/walk.py tests/unit/test_walk.py
git commit -m "fix(walk): #A-6 follow-symlinks のディレクトリ循環を枝刈り（無限走査の終了性確保）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 2: 正確性（過小抽出・誤区間の解消／golden 不変）

### Task 7: B-1 Python/JS/TS chaser を `bindings_at_line` へ統一（1行複数文の取りこぼし解消）

**問題（実証済）:** `python_chaser.py:68`・`javascript_chaser.py:91`・`typescript_chaser.py:37` は `binding_at_line`（最小スパン**単一**ノード）を使い、`a = 1; b = 2; c = 3` で `a` のみ抽出。Java/C は `bindings_at_line`（行交差**全件**）で整合済。本ツールの存在意義＝間接参照の追跡に直結する過小抽出。

**設計不変条件への影響:** 既存 golden（py_chain / js_kinds / ts_enum_readonly 等）は1行に複数文を持たないため**バイト不変**。複数文・複数束縛が同居する行のみ抽出が増える（取りこぼし解消）。連鎖代入 `a = b = 1` で外側＋内側ノードが二重に取れ得るため**名前を出現順 dedup** して吸収する（Java の const/var dedup と同思想）。

**Files:**
- Modify: `src/grep_analyzer/classifiers/python_chaser.py:8,67-76`、`src/grep_analyzer/classifiers/javascript_chaser.py:5,90-96`、`src/grep_analyzer/classifiers/typescript_chaser.py:8,36-42`
- Test: `tests/unit/test_ast_chaser.py`

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_ast_chaser.py` の末尾に追記:

```python
from grep_analyzer.chase import extract_chase_symbols_tree


def test_python_1行複数代入を全て抽出():
    cs = extract_chase_symbols_tree("python", "a = 1; b = 2; c = 3\n", 1)
    assert set(cs.vars) == {"a", "b", "c"}


def test_javascript_1行複数宣言を全て抽出():
    cs = extract_chase_symbols_tree("javascript", "let a = 1; let b = 2; c = 3;\n", 1)
    assert {"a", "b", "c"} <= set(cs.vars)


def test_python_連鎖代入は重複なく抽出():
    cs = extract_chase_symbols_tree("python", "a = b = 1\n", 1)
    assert sorted(cs.vars) == ["a", "b"]          # 重複しない
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest tests/unit/test_ast_chaser.py -k "1行複数 or 連鎖代入" -v`
Expected: FAIL（`a` のみで `b`,`c` 欠落）

- [ ] **Step 3: 最小実装**

共通 dedup helper を各 chaser に導入し、`binding_at_line`（単一）を `bindings_at_line`（全件）へ。

`python_chaser.py`: import 行（line 8）を変更し `extract_tree`（line 67-76）を置換:

```python
from grep_analyzer.classifiers.ts_classifier import bindings_at_line
```

```python
def extract_tree(language, root, lineno):
    consts, vars_, getters, setters = [], [], [], []
    for node in bindings_at_line(root, lineno, _BINDING):
        if node.type == "decorated_definition":
            _from_decorated(node, getters, setters)
        else:
            _from_assignment(node, consts, vars_)
    return _dedup_symbols(consts, vars_, getters, setters)
```

`python_chaser.py` の末尾に dedup helper を追加:

```python
def _dedup_symbols(consts, vars_, getters, setters):
    """出現順を保ちつつ重複を除く（1行複数束縛・連鎖代入の二重取り対策）。"""
    def uniq(xs):
        seen = set()
        return tuple(x for x in xs if not (x in seen or seen.add(x)))
    cset = set(consts)
    return ChaseSymbols(uniq(consts), uniq(v for v in vars_ if v not in cset),
                        uniq(getters), uniq(setters))
```

`javascript_chaser.py`: import 行（line 5）を変更し `extract_tree`（line 90-96）を置換:

```python
from grep_analyzer.classifiers.ts_classifier import bindings_at_line
```

```python
def extract_tree(language, root, lineno):
    consts, vars_, getters, setters = [], [], [], []
    for node in bindings_at_line(root, lineno, _BINDING):
        handle_binding(node, consts, vars_, getters, setters)
    return _dedup_symbols(consts, vars_, getters, setters)


def _dedup_symbols(consts, vars_, getters, setters):
    """出現順を保ちつつ重複除去（1行複数束縛対策・DRY で typescript からも再利用）。"""
    def uniq(xs):
        seen = set()
        return tuple(x for x in xs if not (x in seen or seen.add(x)))
    cset = set(consts)
    return ChaseSymbols(uniq(consts), uniq(v for v in vars_ if v not in cset),
                        uniq(getters), uniq(setters))
```

`typescript_chaser.py`: import 行（line 6-8）と `extract_tree`（line 36-42）を置換:

```python
from grep_analyzer.classifiers.javascript_chaser import _BINDING as _JS_BINDING
from grep_analyzer.classifiers.javascript_chaser import handle_binding as _handle_js
from grep_analyzer.classifiers.javascript_chaser import _dedup_symbols
from grep_analyzer.classifiers.ts_classifier import bindings_at_line
from grep_analyzer.model import ChaseSymbols
```

```python
def extract_tree(language, root, lineno):
    consts, vars_, getters, setters = [], [], [], []
    for node in bindings_at_line(root, lineno, _BINDING):
        _handle_ts(node, consts, vars_, getters, setters)
    return _dedup_symbols(consts, vars_, getters, setters)
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/unit/test_ast_chaser.py -v`
Expected: PASS（新規3件含む）

- [ ] **Step 5: 回帰確認（golden バイト不変）**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed・全体緑

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/classifiers/python_chaser.py src/grep_analyzer/classifiers/javascript_chaser.py src/grep_analyzer/classifiers/typescript_chaser.py tests/unit/test_ast_chaser.py
git commit -m "fix(chaser): #B-1 py/js/ts chaser を bindings_at_line 統一（1行複数束縛の取りこぼし解消・golden 不変）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: B-2 `mask_exec_sql` の区間検出をリテラル空白化コピーに統一

**問題（精読確認）:** `proc_preprocess.py:20-27` の `mask_exec_sql`（classify/chase の C パース入力）は生ソースに `_EXEC_RE` を当て、文字列内 `;`（例 `VALUES (';')`）で区間が早期終了し残骸 SQL が C ソースに残る。snippet 用 `exec_spans`（同 39-48）だけが `_blank_literals` 後に当てて正しい＝同一ヒットで snippet と分類/抽出が別区間を見る。

**設計不変条件への影響:** リテラル内 `;` が無い通常の Pro*C では `_blank_literals` 後の区間＝生ソースの区間と一致し、空行化結果もバイト同一＝既存 Pro*C golden（oracle_direct 等）は**不変**。リテラル `;` を含む病的ケースのみ区間が正しくなる（残骸 SQL が消える）。両関数の区間検出を共有 helper に集約（DRY）。

**Files:**
- Modify: `src/grep_analyzer/proc_preprocess.py:13-48`
- Test: `tests/unit/test_proc_preprocess.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

`tests/unit/test_proc_preprocess.py`（新規）:

```python
"""B-2: mask_exec_sql の区間検出をリテラル空白化コピーに統一（文字列内 ; 誤切断）。"""

from grep_analyzer.proc_preprocess import mask_exec_sql, exec_spans


def test_リテラル内セミコロンで区間が途中切断されない():
    src = (
        "int a = 1;\n"
        "EXEC SQL UPDATE t SET note = 'has;semicolon'\n"
        "  WHERE id = :id;\n"
        "int b = 2;\n"
    )
    masked = mask_exec_sql(src)
    # EXEC 区間（2-3行目）は完全に空行化され残骸 SQL が残らない。
    # （"WHERE"/"semicolon" はリテラル ; 以降の残骸＝fix 前は残る＝load-bearing）
    assert "WHERE" not in masked
    assert "semicolon" not in masked
    # 区間外の C コードは保持
    assert "int a = 1;" in masked
    assert "int b = 2;" in masked
    # 行番号保存（総行数不変）
    assert masked.count("\n") == src.count("\n")


def test_exec_spansとmask_exec_sqlが同一区間を見る():
    src = "EXEC SQL SELECT x INTO :v FROM t WHERE c = 'a;b';\n"
    assert exec_spans(src) == [(0, 0)]
    assert "SELECT" not in mask_exec_sql(src)


def test_通常のexec_sqlは従来どおり空行化():
    src = "EXEC SQL SELECT 1 INTO :x FROM dual;\nint y = 0;\n"
    masked = mask_exec_sql(src)
    assert "SELECT" not in masked
    assert "int y = 0;" in masked
    assert masked.count("\n") == src.count("\n")
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest "tests/unit/test_proc_preprocess.py::test_リテラル内セミコロンで区間が途中切断されない" -v`
Expected: FAIL（残骸 `WHERE`/`note` が masked に残る）

- [ ] **Step 3: 最小実装**

`proc_preprocess.py` の `_EXEC_RE` 定義以降（line 13-48）を次に再構成。区間検出をリテラル空白化コピー上の共有 helper `_exec_char_spans` に集約し、`mask_exec_sql` はその区間で原ソースを空行化する。

```python
# `EXEC SQL ... ;` / `EXEC SQL ... END-EXEC` / `EXEC ORACLE ... ;` を行跨ぎで捕捉
_EXEC_RE = re.compile(
    r"\bEXEC\s+(?:SQL|ORACLE)\b.*?(?:;|END-EXEC\b)",
    re.IGNORECASE | re.DOTALL,
)

_PROC_LIT_RE = MASK_PATTERNS["proc"]


def _blank_literals(source: str) -> str:
    return _PROC_LIT_RE.sub(
        lambda match: "".join(c if c == "\n" else " " for c in match.group(0)),
        source)


def _exec_char_spans(source: str) -> list[tuple[int, int]]:
    """EXEC SQL/ORACLE 区間を (start_char, end_char) で返す（唯一の区間検出源）。

    リテラル・コメント空白化コピー上で _EXEC_RE を走らせ、文字列内 ;/END-EXEC の
    誤切断を防ぐ（spec §7 Crit-1）。空白化は長さ保存のため原ソースへ正しく写像できる。
    """
    masked = _blank_literals(source)
    return [(m.start(), m.end()) for m in _EXEC_RE.finditer(masked)]


def mask_exec_sql(source: str) -> str:
    """EXEC SQL/ORACLE 区間を中立化。区間検出は _exec_char_spans（リテラル空白化
    コピー上）に統一し、原ソースの当該区間を改行のみ残して空行化する（行番号不変）。"""
    out: list[str] = []
    last = 0
    for s, e in _exec_char_spans(source):
        out.append(source[last:s])
        out.append("\n" * source.count("\n", s, e))
        last = e
    out.append(source[last:])
    return "".join(out)


def exec_spans(source: str) -> list[tuple[int, int]]:
    """EXEC SQL/ORACLE 区間を (start_line, end_line)（0始まり）で返す。"""
    return [(source.count("\n", 0, s), source.count("\n", 0, e))
            for s, e in _exec_char_spans(source)]
```

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/unit/test_proc_preprocess.py -v`
Expected: PASS（3件）

- [ ] **Step 5: 回帰確認（Pro*C golden バイト不変）**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed（oracle_direct 等 Pro*C 系含む）・全体緑

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/proc_preprocess.py tests/unit/test_proc_preprocess.py
git commit -m "fix(proc): #B-2 EXEC 区間検出をリテラル空白化コピーに統一（文字列内 ; 誤切断の解消・golden 不変）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 3: テスト網の穴埋め

### Task 9: C-1 `force_spill` ノブ追加＋spill 経路の end-to-end バイト同値テスト

**問題（実証済）:** 既存 degrade テストは `--memory-limit 0` を使うが、これは `apply_global_cap` が keep_count を 0 へ潰し indirect 全切り＝**空リスト同士の比較**。`EdgeStore` のディスク往復（`_spill_now`/`sorted_unique` の spilled 分岐）が**出力に効く中間域を一度も通らない**。spill 本体のバグは全テスト緑のまま通る。

**修正方針:** `force_chunks` と同じく**テスト/デバッグ用の決定的ノブ** `force_spill`（>0 でエッジ追加 N 件目から spill）を `EngineOptions` に追加し、`_seed.py` の `EdgeStore` 構築時に `_force_spill_threshold` へ渡す。これで「spill 発火 ∧ 出力非空 ∧ spill なしとバイト同値」を公開経路で凍結できる。

**設計不変条件への影響:** `force_spill` 既定 0＝従来どおり予算ベースのみ＝**本番経路不変**。テストで spill 有無のバイト同値を assert することで spill の出力透過性を恒久的に守る。

**Files:**
- Modify: `src/grep_analyzer/fixedpoint/_options.py:33`、`src/grep_analyzer/fixedpoint/_seed.py:44`
- Test: `tests/integration/test_spill_e2e.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_spill_e2e.py`（新規）:

```python
"""C-1: spill 経路を出力非空のまま通し、spill 有/無のバイト同値を凍結する。"""

import dataclasses

from grep_analyzer.pipeline import _default_opts, run


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    # 定数→変数→使用の多ホップ（別行・min_specificity>=2 を満たす長い識別子）で
    # indirect:constant / indirect:var を複数生む構成＝来歴エッジ>0（spill 経由を要する）。
    (src / "C.java").write_text(
        "class C {\n"
        "  static final int THRESHOLD = 1;\n"
        "  int limit = THRESHOLD;\n"
        "  int total = limit;\n"
        "}\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "THRESHOLD.grep").write_text(
        "C.java:2:  static final int THRESHOLD = 1;\n", "utf-8")
    return src, inp


def test_spill経由でも出力は非空かつspillなしとバイト同値(tmp_path):
    src, inp = _setup(tmp_path)
    base = dataclasses.replace(_default_opts(), spill_dir=tmp_path / "spill")
    (tmp_path / "spill").mkdir()

    out_no = tmp_path / "no"
    assert run(input_dir=inp, output_dir=out_no, source_root=src, opts=base) == 0
    bytes_no = (out_no / "THRESHOLD.tsv").read_bytes()

    out_sp = tmp_path / "sp"
    spilled = dataclasses.replace(base, force_spill=1)        # 1 エッジ目から spill
    assert run(input_dir=inp, output_dir=out_sp, source_root=src, opts=spilled) == 0
    bytes_sp = (out_sp / "THRESHOLD.tsv").read_bytes()

    # 出力は非空（indirect 行が存在）かつ spill 有無でバイト同値
    assert b"indirect" in bytes_no
    assert bytes_sp == bytes_no
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest tests/integration/test_spill_e2e.py -v`
Expected: FAIL（`force_spill` が `EngineOptions` に無く TypeError）

- [ ] **Step 3: 最小実装**

`_options.py` の `force_chunks` の直後（line 33）に追加:

```python
    force_spill: int = 0          # >0 でエッジ N 件目から強制 spill（テスト用・本番 0）
```

`_seed.py:44` の `EdgeStore` 構築を、`force_spill` 指定時に閾値を設定する形へ置換:

```python
    edge_store = EdgeStore(opts.spill_dir, budget)
    if opts.force_spill and opts.force_spill > 0:
        edge_store._force_spill_threshold = opts.force_spill
```

そのうえで `state = ChaseState(... edge_store=edge_store, ...)` に渡すよう、現状の `edge_store=EdgeStore(opts.spill_dir, budget),` を `edge_store=edge_store,` に変更し、`edge_store` の構築を `state = ChaseState(` の前へ移動する。

- [ ] **Step 4: テスト通過を確認**

Run: `python -m pytest tests/integration/test_spill_e2e.py -v`
Expected: PASS

- [ ] **Step 5: 回帰確認**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed・全体緑

- [ ] **Step 6: コミット**

```bash
git add src/grep_analyzer/fixedpoint/_options.py src/grep_analyzer/fixedpoint/_seed.py tests/integration/test_spill_e2e.py
git commit -m "test(spill): #C-1 force_spill ノブ＋spill 経由の非空出力バイト同値を凍結

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: C-2 resume の「実スキップ」を spy で検証

**問題（精読確認）:** `test_resumeで完了kwをスキップ_バイト不変` は出力が決定的ゆえ「再処理しても同一 byte」＝`--resume` が manifest を無視して全件再処理するバグ（スキップ最適化喪失）を検出できない。`is_complete` の単体テストは強いが「完了 → 実際に skip して再書込しない」結線が未検証。

**Files:**
- Test: `tests/integration/test_resume_skip.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

`tests/integration/test_resume_skip.py`（新規）:

```python
"""C-2: resume 完了 kw に対し finalize が呼ばれない（実スキップ）ことを spy で検証。"""

from grep_analyzer import pipeline
from grep_analyzer.cli import main


def _setup(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    (src / "A.java").write_text("class A{ static final int K1=1; }\n", "utf-8")
    inp = tmp_path / "input"; inp.mkdir()
    (inp / "K1.grep").write_text("A.java:1:static final int K1=1;\n", "utf-8")
    return src, inp


def test_resume完了kwはfinalizeを呼ばない(tmp_path, monkeypatch):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0                                    # 1回目で完了

    calls: list[str] = []
    real_finalize = pipeline.output_writer.finalize

    def _spy(output_dir, keyword, rows, opts):
        calls.append(keyword)
        return real_finalize(output_dir, keyword, rows, opts)

    monkeypatch.setattr(pipeline.output_writer, "finalize", _spy)
    assert main(a + ["--resume"]) == 0                     # 2回目は resume
    assert calls == []                                     # 完了 kw は finalize 非呼出＝実スキップ


def test_未完了kwはresumeでも再処理される(tmp_path, monkeypatch):
    src, inp = _setup(tmp_path)
    out = tmp_path / "o"
    a = ["--input", str(inp), "--output", str(out), "--source-root", str(src)]
    assert main(a) == 0
    (out / "K1.manifest.json").unlink()                    # 完了痕跡を消す

    calls: list[str] = []
    real_finalize = pipeline.output_writer.finalize
    monkeypatch.setattr(pipeline.output_writer, "finalize",
                        lambda *x: (calls.append(x[1]), real_finalize(*x))[1])
    assert main(a + ["--resume"]) == 0
    assert calls == ["K1"]                                 # manifest 無し→再処理される
```

- [ ] **Step 2: テスト失敗を確認**

Run: `python -m pytest tests/integration/test_resume_skip.py -v`
Expected: 実装は正しい想定なので、まず spy が正しく結線されるかを確認。もし `test_resume完了kwはfinalizeを呼ばない` が FAIL するなら resume スキップ最適化のバグ（要調査）。両 PASS が期待。

> 注: これは既存実装の挙動を**特性化**するテスト。実装が正しければ両方 PASS する（C-2 は「テストの穴」であり「実装バグ」ではない）。PASS を以て「実スキップが恒久的に守られる」網を張る。万一 FAIL したら resume 経路の実バグを発見したことになり別途修正タスク化する。

- [ ] **Step 3: 回帰確認**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden 46 passed・全体緑

- [ ] **Step 4: コミット**

```bash
git add tests/integration/test_resume_skip.py
git commit -m "test(resume): #C-2 resume の実スキップ（完了 kw は finalize 非呼出）を spy で固定

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: C-3 golden を jobs 横断でもバイト同値照合

**問題（決定性班指摘）:** `tests/golden/test_golden.py` は jobs=1 固定。46 件の精緻な期待値があるのに jobs>1 経路を一切照合していない。並列完了順非依存の決定性は構造的に保証されているが、恒久テストになっていない。

**修正方針:** golden ハーネスに「jobs=2 でも同一 keyword の TSV が jobs=1 とバイト同値」を追加する独立テストを `test_golden.py` に足す（既存の期待値照合は不変・追加のみ）。

**設計不変条件への影響:** 既存テストは無改変、追加のみ。

**Files:**
- Modify: `tests/golden/test_golden.py`（テスト追加）
- Test: 同上

- [ ] **Step 1: テストを追加**

`tests/golden/test_golden.py` の末尾に追記:

```python
def test_golden各ケースはjobs2でもjobs1とバイト同値(golden_case, tmp_path):
    """並列完了順非依存の決定性を全 golden ケースで恒久照合する（C-3）。"""
    opts1 = _opts_for(golden_case)
    out1 = tmp_path / "j1"
    assert run(input_dir=golden_case / "input", output_dir=out1,
               source_root=golden_case / "src", opts=opts1) == 0

    opts2 = dataclasses.replace(_opts_for(golden_case), jobs=2)
    out2 = tmp_path / "j2"
    assert run(input_dir=golden_case / "input", output_dir=out2,
               source_root=golden_case / "src", opts=opts2) == 0

    for expected in sorted((golden_case / "expected").glob("*.tsv")):
        name = expected.name
        assert (out2 / name).read_bytes() == (out1 / name).read_bytes(), name
```

- [ ] **Step 2: テスト実行**

Run: `python -m pytest tests/golden/test_golden.py -k "jobs2" -q`
Expected: PASS（全 golden ケース × jobs 同値）

- [ ] **Step 3: 全体回帰**

Run: `python -m pytest tests/golden -q && python -m pytest -q`
Expected: golden は従来 46＋本テスト分（ケース数ぶん）緑・全体緑

- [ ] **Step 4: コミット**

```bash
git add tests/golden/test_golden.py
git commit -m "test(golden): #C-3 全ケースで jobs=2 と jobs=1 のバイト同値を恒久照合

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Phase 4: ドキュメントの誠実化

### Task 12: E spec/README の over-claim・数値陳腐化の是正

**問題（spec乖離班指摘）:** (1) README「golden 14」は実際 46。(2) spec §4.2「395 passed」・gate doc「244 passed」は実測と乖離（本計画完了後はさらに増える）。(3) spec §8.4「取りこぼしを diagnostics に**必ず明示**」は over-claim（非免除カテゴリは detail_limit で縮約）。(4) 「60GB走査に耐える」の実証は ≤800 ファイル合成のみ。(5) Inv-6 は A-2 の保持上限で病的ケースのみ but-clause が付く。

**設計不変条件への影響:** ドキュメントのみ。コード不変。

**Files:**
- Modify: `README.md`、`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md`

- [ ] **Step 1: README の数値・主張を是正**

`README.md:170` の「golden 14（既定出力 byte 不変の回帰アンカー）」を実数へ:

```markdown
pytest tests/golden -q    # golden（既定出力 byte 不変の回帰アンカー）
```

（`golden 14` の固定数を削り「golden」へ。数値陳腐化を避ける。）

`README.md:43` 周辺の「大規模・実運用に耐える」節に but-clause を追記（誇大の是正）。「クローン即オフライン再現ビルドまで面倒を見る。」の直後に1文追加:

```markdown
  （性能の実証は合成コーパス規模での計測＝`tests/perf`。60GB 級の実コーパスでは
  `--memory-limit`・`_ITEMS_PER_MB` の再較正を推奨。）
```

`README.md:63`「『この値が関わる箇所すべて』を出す**監査・セキュリティ用途**」に注記を追加（§8.4 縮約の運用注意）。同行末に追記:

```markdown
（取りこぼし明細を全件残すには `--diagnostics-detail-limit 0` を指定）
```

- [ ] **Step 2: spec §8.4 の「必ず明示」を縮約規約と整合させる**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` の §8.4 冒頭（`本節を**唯一の正本**とし…` の段落）に、縮約と保持上限の事実を1文追記:

```markdown
> **明示の粒度（2026-05-24 是正）**: 本節カテゴリのうち縮約免除は `symbol_rejected`/
> `getter_setter_no_expand`/`prov_*` のみ（§10.3）。その他の取りこぼし（生成コード
> 除外・decode 置換・symlink dedup・unsupported_shebang 等）は **summary 件数は常に
> 全件**だが、個別明細は `--diagnostics-detail-limit`（既定 1000）で縮約される。全件
> 明細が要る監査では `--diagnostics-detail-limit 0` を指定する。さらにメモリ安全のため
> 1カテゴリの明細保持は内部上限 `_MAX_RETAINED`（既定 20万件）で頭打ちする（カウントは
> 全件・A-2）。**Inv-6（`--diagnostics-detail-limit 0` がバイト同値）は1カテゴリが
> 20万件を超える病的ケースを除き不変**。
```

- [ ] **Step 3: spec のテスト件数ベースラインを「相対表現」へ脱・陳腐化**

`docs/superpowers/specs/2026-05-16-grep-analyzer-design.md` の §4.2「track A G1 再ベースライン」節の「テスト件数ベースラインは **395 passed, 5 skipped**」を、固定数依存を弱める注記へ改める（行末に追記）:

```markdown
（注: 実装の追加に伴い件数は増加する。**ゲートは「全件 passed・golden バイト不変」で
あって固定件数ではない**。最新の実数は `python -m pytest -q` を正本とする。）
```

- [ ] **Step 4: 是正後にビルド健全性を確認**

Run: `python -m pytest -q`
Expected: 全体緑（ドキュメント変更はコード非依存）

- [ ] **Step 5: コミット**

```bash
git add README.md docs/superpowers/specs/2026-05-16-grep-analyzer-design.md
git commit -m "docs: #E spec/README の over-claim・数値陳腐化を是正（§8.4 明示粒度・60GB but-clause・件数相対化）

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## 完了条件（Definition of Done）

- [ ] Task 1〜12 全コミット済。
- [ ] `python -m pytest -q` 緑（従来 437 passed, 9 skipped ＋本計画の新規テスト）。
- [ ] `python -m pytest tests/golden -q` 緑（既存 46 のバイト不変＋jobs 横断）。
- [ ] A-1〜A-4 が「正常系出力バイト不変」を golden で実証。
- [ ] memory に本対応の着手・完了を記録（`ai-review-before-advancing` 運用に沿い、フェーズ移行前に再度の批判的 AI レビューを推奨）。

## Self-Review メモ（spec カバレッジ）

| レビュー指摘 | 対応 Task | 種別 |
|---|---|---|
| A-1 経路爆発 | Task 1 | 有限化（出力不変） |
| A-2 診断蓄積 | Task 2 | OOM 防止（summary 不変） |
| A-4 ReDoS | Task 3 | 有限化（出力不変） |
| A-3 パストラバーサル | Task 4 | セキュリティ（golden 不変） |
| A-5 ワーカ例外 | Task 5 | 耐障害（出力不変） |
| A-6 dir-symlink ループ | Task 6 | 終了性（既定不変） |
| B-1 chaser 過小抽出 | Task 7 | 正確性（golden 不変） |
| B-2 Pro*C 区間 | Task 8 | 正確性（golden 不変） |
| C-1 spill 未検証 | Task 9 | テスト網 |
| C-2 resume 実スキップ | Task 10 | テスト網 |
| C-3 golden jobs 横断 | Task 11 | テスト網 |
| C-4 dir-symlink 終了性 | Task 6 のテスト | テスト網（A-6 と同体） |
| E ドキュメント | Task 12 | 誠実化 |
