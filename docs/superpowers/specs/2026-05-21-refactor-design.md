# grep_analyzer リファクタリング設計（2026-05-21）

## 0. 目的とスコープ

仕様（`docs/superpowers/specs/` 系列の grep_analyzer spec、v10）の挙動を 100% 保ったまま、コードの (a) 構造、(b) 命名、(c) コメントの品質を上げる。

- **挙動変更ゼロ**: TSV 出力 byte、CLI 引数、diagnostics キー、終了コードは不変
- **対象**: `src/grep_analyzer/` 配下の全 Python モジュール（約 2,100 行・29 ファイル）
- **非対象**: spec の改訂、テストデータの追加、性能の能動的改善（性能リグレッション抑止のみ）

Related: spec §5, §8, §9, §11

## 1. 全体不変条件

各 Phase の完了の必要条件として、すべて維持する。

| ID | 内容 |
|---|---|
| Inv-A | TSV 出力の byte 列が現行 golden と完全一致（spec §11 v9 機構で検証） |
| Inv-B | unit / integration / golden / spec §15 ベースラインが全件 pass |
| Inv-C | `cli.py` の引数・終了コード・diagnostics キー名は不変 |
| Inv-D | spec §5.1 / §8.1 で確立済の層分離違反を再導入しない |
| Inv-E | `pyahocorasick` 版差吸収など、現行の決定性ガードを保持 |

## 2. フェーズ構成

```
Phase 1: 規約確定（命名規約 + コメント規約 + Refactoring Discipline）+ [D] regex 集約
Phase 2: [B] chase 言語別分散化 + [E] TSV 書込経路の正本化
Phase 3: [C] snippet 分割 + [A] fixedpoint 分割（ChaseState 化）
Phase 4: 命名・コメントの全モジュール横断適用
```

各 Phase は独立に spec → plan → 実装 → AI レビュー → ユーザーレビューのサイクルを回す。Phase 移行前に批判的 AI レビューを最低 2 巡し、指摘ゼロに収束させる（V5）。

## 3. 命名規約

### N1 フルスペル原則

略語は原則禁止。次のホワイトリストに限り略可。

**ホワイトリスト**: `api`, `id`, `url`, `uri`, `io`, `os`, `re`, `ast`, `cli`, `tsv`, `csv`, `utf`, `sql`, `min`, `max`, `len`, `idx`, `tmp`, `args`, `kwargs`, `enc`（encoding）, `lang`（language）

それ以外の略語は禁止し、フルスペルに置換する。

### N2 置換対象（初期 inventory）

Phase 4 plan で全件 inventory 化する。下表は現状コードから抽出した代表例。

| 現状 | 置換先 | 主な出現箇所 |
|---|---|---|
| `au` | `automaton` | automaton.py, fixedpoint.py |
| `sym` / `syms` | `symbol` / `symbols` | automaton.py, fixedpoint.py |
| `cs` | `chase_symbols` | chase.py, fixedpoint.py |
| `dia` | `dialect` | fixedpoint.py |
| `prog` | `progress` | fixedpoint.py |
| `agg` | `hits_by_relpath` 等の意図名 | fixedpoint.py |
| `meta` | `file_meta_by_relpath` | fixedpoint.py |
| `m` (mask) | `masked_lines` | snippet.py |
| `t` (type/text) | `node_type` / `text` | snippet.py |
| `d` (balance) | `paren_depth` | snippet.py |
| `lp` / `rps` | `lparen` / `rparens` | snippet.py |
| `dn` / `up` | `down_idx` / `up_idx` | snippet.py |
| `ra` / `rb` | `above_count` / `below_count` | snippet.py |
| `_phys` | `_physical_lines` | snippet.py |
| `_err` | `_has_error` | snippet.py |
| `intro` | `introducers` | fixedpoint.py |
| `estore` | `edge_store` | fixedpoint.py |

### N3 述語と動詞の統一

- 真偽返却: `is_*` / `has_*` / `should_*`
- 取得関数: 副作用なし `get_*`、計算重ければ `compute_*` / `build_*`
- 変換関数: `to_*` / `*_from_*` で方向を明示

### N4 ドメイン語彙の表記固定

混在禁止。1 表記に固定する。

- `relpath`（`rel`, `relative_path`, `rel_path` は禁止）
- `lineno`（`line_no`, `line_number`, `linenum` は禁止）
- `keyword`, `symbol`, `occurrence`, `provenance`, `chain`, `hop`, `seed`
- `direct_hit` / `indirect_hit`（`direct` / `indirect` 単独は形容詞用途のみ）

### N5 適用除外

- 極短一時変数（ループカウンタ、内包表記内、3 行以内のローカル）
- 外部ライブラリ API のシグネチャ要請

## 4. コメント規約

### C1 コメントの存在価値テスト

書く前 / 残す前に必ず:

1. **識別子で伝わるか?** → 伝わるなら命名を直してコメントは書かない／削除
2. **WHAT を説明しているだけか?** → 削除
3. **WHY が非自明か?** → 残す。ただし「何を保証しているか」を明記

### C2 "spec §X" / "phase Y" 言及の扱い

- **削除**: spec / phase 参照しか書いておらず、識別子と直近コードで意図が伝わるもの
- **書換**: spec 参照を「何を保証しているか」の能動文に書き換え、spec 参照は文末 `(see spec §X)` 形式で補足化
- **削除禁止**:
  - 不変条件、停止性保証、決定性根拠
  - workaround の理由
  - 外部ライブラリの版差吸収根拠（例: automaton.py L21-26）

### C3 Module docstring の整理

- 1 文目: モジュールが何を提供するか（spec 番号を含まない自然文）
- 2 文目以降: 主要な不変条件・利用上の注意
- spec 参照は最終行に `Related: spec §X.Y, §Z.W` 形式で集約

### C4 Inline コメントの密度上限

1 関数内に 3 個以上の inline コメントが必要な場合、関数を分割する候補とみなす（pseudo-code 対応など段階説明は例外）。

### C5 TODO / FIXME / Phase / Version マーカーの整理

- `Phase 2a/2b` 等のフェーズマーカー → 全削除（git log で辿れる）
- `TODO` / `FIXME` → GitHub Issue 化してコードからは消す
- `v9` / `v10` 等の version マーカー → spec 側で管理、コードからは消す

### C6 多言語表記

日本語コメントは継続可。規約 C1〜C5 は言語非依存で適用。

## 5. Refactoring Discipline 規約（DRY 誤適用防止）

### R1 DRY の適用判定

集約を提案する前に plan に明文化必須:

1. **同一知識か?** 2 箇所の変更理由が常に一致するか? 片方だけ変わるシナリオが想像できるなら **集約しない**
2. **同じ用語で説明できるか?** 違う名前で呼ぶしかないなら **集約しない**
3. **Rule of Three**: 重複が 2 箇所のみなら集約を保留。3 箇所目が出てから抽象化を検討

### R2 Phase 1 [D] の集約境界

`_patterns.py` 単一ファイルに全 regex を放り込むのを禁止。**用途別サブモジュール**:

```
patterns/
  __init__.py
  snippet_boundaries.py   ← _SQL_CLAUSE / _SH_END（snippet 内境界判定）
  symbol_extraction.py    ← chase の言語別シンボル抽出 regex
  literal_masking.py      ← mask_literals 用の言語別リテラル regex
```

- 各サブモジュールは単一の用途を表す名前
- 用途が違えば「同じ形の regex」が複数サブモジュールに重複していても正しい状態
- import 側は用途を呼び出し名で明示

### R3 Phase 2 [E] の事前検証ゲート

統合作業の前に:

1. 両経路（`pipeline → output_writer.finalize` と `tsv.write_tsv`）を起動し、出力 byte を比較
2. 結果に応じて分岐:
   - **片方が dead code** → 削除で完了（統合ではない）
   - **同じ責務・同じ出力** → 統合する（R1 を満たす）
   - **違う責務** → 統合せず、それぞれに自己説明的な名前を与えて終了

### R4 Phase 3 [A] の Rule of Three

`run_fixedpoint` の単一パス / マルチパス分岐:

- 第一案: 統合せず `_scan_hop_single()` / `_scan_hop_chunked()` の 2 関数で並存
- 第二案: chunks リスト抽象化で統合
- 判定: plan 段階で実装し、差分が "chunks の構築方法" だけに収束する場合のみ統合

## 6. 構造変更の各 Phase 詳細

### Phase 1 — 規約確定 + [D] regex 集約（small・低リスク）

**変更**:
- 命名規約・コメント規約・Refactoring Discipline 規約をこの設計ドキュメントで確定
- 新規サブパッケージ `src/grep_analyzer/patterns/` を作成（R2 に従う）
- 移動対象:
  - `snippet.py:75-77` の `_SQL_CLAUSE`, `_SH_END` → `patterns/snippet_boundaries.py`
  - `chase.py` のシンボル抽出 regex → `patterns/symbol_extraction.py`
  - `chase.py` の `_MASK_RE` 系 → `patterns/literal_masking.py`
- 元ファイルは `from grep_analyzer.patterns.<module> import ...` に置換
- **挙動変更ゼロ**

**完了基準**:
- 全 regex 定数が `patterns/` 配下に集約（除外: 関数内の使い捨て regex）
- 全テスト pass

### Phase 2 — レイヤ分離強化

#### [B] chase 言語別分散化（medium）

**Before**:
```
chase.py
  ├─ 言語別 regex（→ Phase 1 で patterns/ に移動済）
  ├─ mask_literals(language, line)        ← 言語別分岐
  └─ extract_chase_symbols(language, dialect, line)  ← 言語別分岐
```

**After**:
```
classifiers/
  ├─ base.py          — 既存。Chase 抽出 IF を追加
  ├─ java_chaser.py   — extract / mask
  ├─ c_chaser.py      — extract / mask（C/Pro*C）
  ├─ shell_chaser.py  — extract / mask（bourne/cshell 分岐含む）
  └─ sql_chaser.py    — extract / mask

chase.py（薄い dispatcher）
  ├─ extract_chase_symbols(language, dialect, line)
  │     → _CHASERS[language].extract(dialect, line)
  └─ mask_literals(language, line)
        → _CHASERS[language].mask(line)
```

**境界**:
- 各 `*_chaser.py` は `patterns/*` のみ依存
- `chase.py` は `classifiers/*` のみ依存（spec §5.1 維持）
- `ChaseSymbols` データクラスは `model.py` へ移動して共有

#### [E] TSV 書込経路の正本化（small〜medium）

**Phase 2 開始前に R3 の事前検証ゲートを通す**。結果に応じて統合 / 削除 / 並存を決定。

統合に進む場合の完了基準:
- TSV 出力ロジックが単一の責任者をもつ
- `_sanitize` が public API（`sanitize_field`）として 1 箇所定義
- Inv-A 維持

### Phase 3 — 大ファイル分割

#### [C] snippet.py 責務分割（medium）

**After**:
```
snippet/
  ├─ __init__.py           — build_snippet（公開エントリ）
  ├─ _clamp.py             — clamp_lines / _render
  ├─ _heuristic_span.py    — heuristic_span / _balanced
  ├─ _ts_span.py           — ts_span / proc_exec_span / _paren_span / _has_error
  └─ _sanitize.py          — _physical_lines / _escape_sep
```

- 公開 API は `from grep_analyzer.snippet import build_snippet` のみ（呼出側無変更）
- tree-sitter 依存は `_ts_span.py` に局所化

#### [A] fixedpoint.py 分割（large・高リスク）

**After**:
```
fixedpoint/
  ├─ __init__.py         — run_fixedpoint（公開エントリ・約 40 行目標）
  ├─ _state.py           — ChaseState データクラス
  ├─ _seed.py            — seed_hits → ChaseState 初期化（hop0→hop1）
  ├─ _scan.py            — _scan_file / _scan_hop_*（worker pool 制御、R4 判定後に統合 or 並存）
  ├─ _ingest.py          — _ingest（旧クロージャの抽出）
  ├─ _budget_control.py  — _apply_global_cap
  └─ _finalize.py        — indirect Hit 列の決定的構築
```

**`ChaseState` 構造（概形）**:

```python
@dataclass
class ChaseState:
    source_root: Path
    options: EngineOptions
    diagnostics: Diagnostics
    policy: SymbolPolicy
    budget: MemoryBudget
    graph: ProvenanceGraph
    edge_store: EdgeStore
    keyword: str
    introducers: dict[str, list[Occurrence]]
    symbol_kind: dict[str, str]
    symbol_hop: dict[str, int]
    chase_active: set[str]
    chase_done: set[str]
    terminal_active: set[str]
    terminal_done: set[str]
    capped: set[str]
    spill_logged: bool
    no_expand_logged: set[str]
    replaced_logged: set[str]
    maxdepth_logged: set[Occurrence]
```

**`run_fixedpoint` after（概形）**:

```python
def run_fixedpoint(seed_hits, source_root, options, diagnostics, *, files=None):
    state = _seed.initialize(seed_hits, source_root, options, diagnostics)
    files = files or list(walk.walk_files(...))
    progress = Progress(options.progress); progress.start(len(files))
    try:
        hop = 1
        while state.chase_active or state.terminal_active:
            _budget_control.apply_cap(state)
            _budget_control.maybe_spill(state, hop)
            results = _scan.scan_hop(state, files, hop)
            _ingest.absorb_results(state, results, hop)
            progress.hop(hop, ...)
            hop += 1
            if hop > options.max_depth: break
        return _finalize.build_indirect_hits(state)
    finally:
        state.edge_store.close()
```

**完了基準**:
- 公開関数 `run_fixedpoint` のシグネチャ・戻り値・副作用が完全不変
- 全 Inv 維持
- `run_fixedpoint` 関数本体が 80 行以下（実値は plan で調整可）

### Phase 4 — 命名・コメントの全モジュール横断適用

**作業**:

1. 命名 inventory: Phase 1〜3 完了後のコード全体に対し、N1〜N4 違反を列挙
2. rename 適用順序:
   - 公開 API rename（cli からの呼び出しと合わせて変更）
   - 内部識別子 rename
   - test fixture / 引数名 rename
3. コメント整理: C1〜C5 を全モジュールに適用
4. module docstring 全件改稿: C3 形式に統一

**完了基準**:
- N1〜N4 違反ゼロ（grep ベースで機械チェック）
- C5 違反ゼロ（`Phase ?[0-9][a-z]` 等のマーカーが grep でヒットしない）
- 全 Inv 維持

## 7. 検証戦略

### V1 Inv-A の自動検証

各タスク完了時:

1. 現行 main の HEAD を退避
2. ベースライン: golden + integration の出力 byte をハッシュ化
3. 変更を適用
4. ハッシュ再生成
5. 差分ゼロを確認

既存 spec §11 v9 の golden 比較機構を使う（新規テスト不要）。

### V2 公開 API の差分検査

Phase 4 の rename は呼出側を壊しうるため、各 commit 前に公開 API inventory を before / after で比較。意図的な rename は plan に列挙されたものに限る。

### V3 Import グラフの層分離検証

Phase 2 / 3 完了時に import 関係をグラフ化:

```
cli → pipeline → fixedpoint/_* → classifiers/* → patterns/*
                 → output_writer → tsv → sanitize
```

- `patterns/*` は何にも依存しない（葉）
- `classifiers/*` は `patterns/*` のみ依存
- `chase.py`（dispatcher 化後）は `classifiers/*` のみ依存
- `fixedpoint/_*.py`（分割後）は `_state` 経由でやり取り（相互依存禁止）

`grep -r "from grep_analyzer" src/` で機械的に確認。

### V4 命名規約の機械チェック（Phase 4 完了時）

```bash
grep -rEn '\b(au|sym|syms|dia|prog|agg)\b' src/
grep -rEn 'Phase ?[0-9][a-z]|spec v[0-9]+|Inv-[0-9]+' src/
```

検出ゼロを Phase 4 完了の必要条件にする。

### V5 Phase 移行ゲート

memory `ai-review-before-advancing.md` 準拠。各 Phase 完了時に:

1. 批判的 AI レビューを起動
2. 指摘事項を列挙
3. 指摘ゼロに収束するまで反復（最低 2 巡）
4. 収束時点で次 Phase に進む

### V6 性能リグレッション抑止

fixedpoint 分割は ChaseState 受け渡しが増えるため、Phase 3 [A] 完了の前後で経過時間を計測。10% 超のリグレッションは要因解析を必須化。計測は `time python -m grep_analyzer ...` の壁時計時間で十分。

## 8. 完了条件まとめ

全 Phase 完了時に以下が同時成立:

- 全 Inv（A〜E）維持
- N1〜N4 違反ゼロ、C1〜C5 違反ゼロ
- import グラフが Section 7 V3 の階層に従う
- 性能リグレッション 10% 以内
- 各 Phase の AI レビューが指摘ゼロに収束済

## 付録 — spec 用語の英日対応表

| 英 | 日 | 備考 |
|---|---|---|
| automaton | オートマトン | pyahocorasick |
| symbol | シンボル | spec 全域 |
| occurrence | 出現 / 出現箇所 | provenance ノード |
| introducer | 発見元 | spec §8.2 |
| chase | 追跡 | constant/var の多ホップ追跡 |
| seed | seed | 翻訳しない |
| hop | hop | 翻訳しない（hop 数の文脈で日本語訳しづらい） |
| direct hit | direct ヒット | spec §5.1 |
| indirect hit | indirect ヒット | spec §5.1 / §8.1 |
| chain | chain | 来歴経路 |
| dialect | 方言 | shell の bourne/cshell |
| span | スパン / 範囲 | snippet 切り出し範囲 |
| clamp | 縮約 | snippet §9 |
| spill | スピル | EdgeStore のディスク退避 |
