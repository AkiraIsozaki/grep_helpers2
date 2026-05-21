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
| Inv-C | **CLI コマンドライン引数**（`--max-depth` 等のユーザ可視オプション）、終了コード、diagnostics の **キー文字列**（`"prov_max_depth"`, `"symbol_rejected"` 等）は不変。cli.py 内部の Python 関数シグネチャ・ローカル変数名は rename 対象（外部に露出しないため）|
| Inv-D | spec §5.1 / §8.1 で確立済の層分離違反を再導入しない |
| Inv-E | `pyahocorasick` 版差吸収など、現行の決定性ガードを保持 |

## 2. フェーズ構成

```
Phase 1: 規約確定（命名規約 + コメント規約 + Refactoring Discipline）+ [D] regex 集約
Phase 2: [B] chase 言語別分散化 + [E] TSV 書込経路の正本化
Phase 3: [C] snippet 分割 + [A] fixedpoint 分割（ChaseState 化）
Phase 4: 命名・コメントの全モジュール横断適用
```

各 Phase は独立に spec → plan → 実装 → AI レビュー → ユーザーレビューのサイクルを回す。Phase 移行前に批判的 AI レビューを最低 2 巡し、Critical / Major ゼロに収束させる（V5）。

**Phase 順序の正当化**:
- **Phase 1 (regex 集約) を先行**: 各言語固有の regex 定数を `patterns/` に局所化することで、Phase 2 で classifiers/* が「自分の文法定義をどこから取るか」が一意に決まり、分割境界の認知負荷が下がる
- **Phase 2 (層分離強化) を中盤**: Phase 1 で文法定数が局所化された後に dispatcher 化することで、各 *_chaser.py が `patterns/*` のみに依存し、循環依存を構造的に避けられる
- **Phase 3 (大ファイル分割) を後半**: Phase 2 で chase が dispatcher 化された後に fixedpoint を分割することで、fixedpoint/_*.py が classifiers/* に依存する構造が完成形になる
- **Phase 4 (横断 rename) を最後**: Phase 1〜3 で構造が確定したあとに rename を行うことで、(i) 移動先で最終命名を一度に確定でき、(ii) 移動と rename の merge conflict を避けられる。先行 rename → 後続移動の順だと、移動時に名前と内容が二重に変化し diff レビューが困難

## 3. 命名規約

### N1 フルスペル原則

略語は原則禁止。次のホワイトリストに限り略可。

**ホワイトリスト**: `api`, `id`, `url`, `uri`, `io`, `os`, `re`, `ast`, `cli`, `tsv`, `csv`, `utf`, `sql`, `min`, `max`, `len`, `idx`, `tmp`, `args`, `kwargs`, `enc`（encoding）, `lang`（language）

それ以外の略語は禁止し、フルスペルに置換する。

### N2 置換対象（初期 inventory）

下表は現状コードから抽出した **代表例**。最終確定は Phase 4 plan で全件 inventory 化する。
「主な出現箇所」は調査時点の参考。Phase 4 で機械的に再走査する。

| 現状 | 置換先 | 主な出現箇所 |
|---|---|---|
| `au` | `automaton` | fixedpoint.py:83,87（automaton.py L13 のローカル変数も対象） |
| `sym` / `syms` | `symbol` / `symbols` | automaton.py, fixedpoint.py |
| `cs` | `chase_symbols` | chase.py, fixedpoint.py |
| `dia` | `dialect` | fixedpoint.py |
| `prog` | `progress` | fixedpoint.py |
| `agg` | `hits_by_relpath` 等の意図名 | fixedpoint.py L273-288（マルチパス分岐内ローカル、定義から最終参照まで 16 物理行で N5 除外境界の 3 行を大幅に超える） |
| `meta` | `file_meta_by_relpath` | fixedpoint.py L274-286（同上、ループ内頻繁参照） |
| `m` (mask) | `masked_lines` | snippet.py |
| `t` (type/text) | `node_type` / `text` | snippet.py |
| `d` (balance) | `paren_depth` | snippet.py |
| `lp` / `rps` | `lparen` / `rparens` | snippet.py |
| `dn` / `up` | `down_idx` / `up_idx` | snippet.py |
| `ra` / `rb` | `above_count` / `below_count` | snippet.py |
| `_phys` | `_physical_lines` | snippet.py |
| `_err` | `_has_error` | snippet.py |
| `intro` (=introduction) | `introducers` | fixedpoint.py — 略語のため対象 |
| `estore` (=edge store) | `edge_store` | fixedpoint.py — 略語のため対象 |

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

**除外対象**（命名見直しを行わない）:
- 内包表記 / ジェネレータ式内の束縛変数（`[x for x in xs]` の `x`）
- ループカウンタの慣用識別子（`for i in range(...)` の `i`/`j`/`k`）
- アンダースコア単独（`_`）の意図的破棄
- **定義から最終参照までの物理行数（コメント・空行含む）が 3 行以内**のローカル変数（plan で目視判定。AST 解析は不要）

**N5 計数方法（plan で適用する判定規約）**:
- 計数対象は **当該識別子のスコープ内の最初の binding 行から最後の参照行まで**
- 物理行数で計数（コメント行・空行も含む）
- 同名の再 binding がある場合は最初の binding 行から数える
- ループ内で何度も再代入される一時辞書（例: `agg = {}` を毎反復作成）はループ全体を有効範囲とする

**除外しない**（規約対象）:
- 関数引数（公開・内部問わず）
- クラス属性
- モジュールトップレベル定数
- 4 行以上の有効範囲を持つローカル変数
- 複数スコープを跨ぐ変数

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

**前提チェック**:
- aarch64 wheel availability を `pip index versions <pkg>` で各依存パッケージごとに確認、または `pip-compile` で lock 再生成して wheelhouse 構成可能性を確認（pyahocorasick 2.3.1 / tree-sitter 系は memory `dgx-spark-aarch64-wheel-policy.md` で解決済だが、Phase 開始時点で再確認）

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

**事前準備**:
- 現状 `classifiers/__init__.py` は実質空に近い。Phase 2 [B] 着手前に `_CHASERS: dict[str, ChaserProtocol]` registry を追加し、各 `*_chaser.py` を import 時に登録する形を確立する
- `chase.py` 側で `_CHASERS[language].extract(...)` / `_CHASERS[language].mask(...)` を呼ぶ薄い dispatcher 関数を用意
- cyclic import 検査: 各 `*_chaser.py` 追加ごとに `python -c "import grep_analyzer"` が成功することを確認（V3 と連動）

**実装方式の選択肢（Phase 2 plan で確定）**:
- **方式α (eager import)**: `classifiers/__init__.py` で全 `*_chaser.py` を import し、各モジュールが import 副作用で `_CHASERS` に自己登録。利点: lookup 時の追加コスト無し。欠点: 起動時に全 chaser が読まれる
- **方式β (lazy import)**: `chase.py` の dispatcher 内で `if language not in _CHASERS: importlib.import_module(...)`。利点: 必要言語のみロード。欠点: 並列実行時の競合に注意
- 判定: 起動時間と並列安全性を Phase 2 plan で計測し決定（既定は方式α）

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

注: `ChaseState` は **Phase 3 [A] で新規作成する**データクラス。現状の `run_fixedpoint()` 内 14 個の局所変数 + `policy` / `budget` / `graph` / `keyword` / `edge_store` を移植する。下表はマッピング:

| 現状（fixedpoint.py 内） | ChaseState フィールド |
|---|---|
| `policy` (L112) | `policy` |
| `budget` (L113) | `budget` |
| `graph` (L114) | `graph` |
| `keyword` (L115) | `keyword` |
| `intro` (L117) | `introducers` |
| `sym_kind` (L118) | `symbol_kind` |
| `sym_hop` (L119) | `symbol_hop` |
| `estore` (L120) | `edge_store` |
| `spill_logged` (L121) | `spill_logged` |
| `chase_active`/`chase_done` (L122-123) | 同名 |
| `term_active`/`term_done` (L124-125) | `terminal_active` / `terminal_done` |
| `capped` (L126) | `capped` |
| `no_expand_logged`/`replaced_logged`/`maxdepth_logged` (L127-129) | 同名 |
| `rel_to_abs` (L192) | `rel_to_abs` |
| `enc_of` (L217) | `encoding_of` |

最終的なフィールド一覧は Phase 3 plan で確定する。

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
    rel_to_abs: dict[str, Path]            # walk 結果のキャッシュ
    encoding_of: dict[str, tuple[str, bool]]  # rel → (encoding, replaced)
    spill_logged: bool
    no_expand_logged: set[str]
    replaced_logged: set[str]
    maxdepth_logged: set[Occurrence]
```

**multiprocessing pickle 制約（重要）**:
- `_scan_file` のシグネチャ `(rel, abspath, sym_list, lang_map, fallback)` は **変更禁止**
- ChaseState 全体を worker に渡さない（pickling 不能 / 過大）
- `_scan.scan_hop()` の役割は: ChaseState から必要なプリミティブ（`sym_list`, `lang_map`, `fallback_chain`）を抽出して args タプルを作り、`Pool.map(_scan_file, args)` を呼び、結果を ChaseState へ書き戻す
- worker 側（`_scan_file`）は ChaseState を知らず、トップレベル純関数のまま維持（Inv-B/E 維持）

**`rel_to_abs` / `encoding_of` の初期化タイミング（Phase 3 plan で確定）**:
- 現状 `rel_to_abs` は `walk.walk_files()` 結果から L192 で構築、`enc_of`（→ `encoding_of`）は scan 結果から L290 で蓄積
- ChaseState への取り込みで、(i) **main process 側で事前構築**（worker 前に確定し ChaseState に格納）と (ii) **scan_hop 結果からの遅延構築** の 2 方式がある
- pickle 制約上、いずれの場合も worker には ChaseState ではなく必要な値のみ渡す
- 既定方針: `rel_to_abs` は `_seed.initialize()` 内で eager 構築、`encoding_of` は scan_hop 結果から `_ingest.absorb_results()` 内で逐次更新（現行挙動と同等）

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
- `run_fixedpoint` 関数本体が **100 行以下を目標**（実値は plan で確定。80 行は理想値だが、hop ループ本体・budget check・chunking 判定が残るため過度な分割は避ける）

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

各タスク完了時に `tests/golden/` および integration テストを既存機構（spec §11 v9）で実行し、**TSV 出力が既存ベースラインと byte 完全一致**することを確認する。

- 既存 `pytest` 起動でテストパス → Inv-A 満足
- 新規テストは不要
- ベースラインを再生成する場合は spec §15 の手順に従う（このリファクタリングでは原則として再生成は行わない）

### V2 公開 API の差分検査

Phase 4 の rename は呼出側を壊しうるため、各 commit 前に公開 API inventory を before / after で比較。意図的な rename は plan に列挙されたものに限る。

### V3 Import グラフの層分離検証

Phase 2 / 3 完了時に import 関係をグラフ化:

```
cli → pipeline → fixedpoint/_* → classifiers/* → patterns/*
                 → output_writer → tsv → sanitize
```

**依存方向の規約**:
- `patterns/*` は何にも依存しない（葉）
- `classifiers/*` は `patterns/*` のみ依存
- `chase.py`（dispatcher 化後）は `classifiers/*` のみ依存
- `fixedpoint/_*.py`（分割後）は `_state` 経由でやり取り（相互依存禁止）
- すべての依存は **葉からルートへの一方向**（A → B → A の循環禁止）

**禁止する逆依存の具体例**（spec §5.1 / §8.1 の層分離要請に基づく）:
- `classifiers/*_chaser.py` が `fixedpoint`, `pipeline`, `ingest`, `spill` を import すること
- `patterns/*` が `classifiers/*`, `chase.py`, `snippet/*` を import すること
- `snippet/*` が `fixedpoint`, `pipeline` を import すること
- `tsv.py` / `output_writer.py` が `fixedpoint`, `chase.py` を import すること
- `model.py` が下位以外のモジュールを import すること

**検証手段**:
- `grep -r "from grep_analyzer" src/` で依存関係を抽出し、上記規約に違反がないか目視確認
- **cyclic import 実機検証**: `python -c "import grep_analyzer; import grep_analyzer.cli; import grep_analyzer.fixedpoint"` がエラーなく完了することを確認
- pytest collection（`pytest --collect-only`）が import エラーなく完了することを確認

### V4 命名規約の機械チェック（Phase 4 完了時）

```bash
grep -rEn '\b(au|sym|syms|dia|prog|agg)\b' src/
grep -rEn 'Phase ?[0-9][a-z]|spec v[0-9]+|Inv-[0-9]+' src/
```

検出ゼロを Phase 4 完了の必要条件にする。

### V5 Phase 移行ゲート

各 Phase 完了時に:

1. 批判的 AI レビューを起動（できれば異なる視点で並列 2 件）
2. 指摘事項を **Critical / Major / Minor / Suggestion** に分類
3. 反復で **Critical / Major をゼロに収束** させる（最低 2 巡）
4. 収束時点で次 Phase に進む

**深刻度の判定基準**:
- **Critical**: 設計通り進めると確実に Inv 違反 / テスト破綻 / 配備不能になる
- **Major**: 完了基準を満たせない、または plan が書けなくなる
- **Minor**: 改善すべきだが当該 Phase 完了は妨げない
- **Suggestion**: 任意の改善案、採否はその場で判断

**V5 通過の必要十分条件**: Critical / Major の指摘数がゼロ
**Minor / Suggestion の扱い**: V5 通過の妨げではないが、**消えるわけではない**。次 Phase の plan 冒頭に「前 Phase 引き継ぎ事項」として全件記録し、当該 Phase の作業範囲で吸収するか、最終 Phase 4 完了時の総点検で再判定する

### V7 規約の適用順序（Phase 4 内部の順序規定）

N1〜N4 と R1〜R4 は **同 Phase 内で適用順序を持つ**。Phase 4 plan で以下の順序で実施:

1. **N1〜N4 の inventory 化**（全モジュール走査で違反列挙）
2. **N1〜N4 の rename 適用**（公開 API → 内部識別子 → test fixture の順）
3. **C1〜C5 の適用**（コメント整理）
4. **R1 (DRY 判定) の再検査**: rename 完了後、同名・同責務に見える構造が新たに発生していないか確認。発生していれば R2〜R4 に従って判定

理由: rename 前の `rel` / `relative_path` / `rel_path` のように N4 違反が混在している段階では、R1 の「同じ用語で説明できるか」を判定できない。表記揺れを先に N4 で潰してから DRY 判定を行う。

**R1 再検査の具体手段**（Phase 4 plan で実施）:

(a) **同名 import 横断検出**: rename 後に同じ識別子名がモジュール間で参照されている箇所を機械抽出。例:
```bash
grep -rEn 'hits_by_relpath|file_meta_by_relpath|introducers|edge_store' src/
```
出現が複数モジュールに跨る場合、(i) 共通定義を 1 モジュールに寄せるべきか、(ii) たまたま同名で責務が違うかを目視判定。

(b) **同責務疑い構造の検出**: 同じ動詞 (`build_*` / `compute_*` / `extract_*`) を持つ複数関数を grep で抽出し、シグネチャと docstring を 1 行で並べて比較。
```bash
grep -rEn 'def (build|compute|extract|sanitize)_' src/
```

(c) (a)(b) のいずれかでヒットがあれば、R1 の 3 判定基準（同一知識か / 同じ用語で説明できるか / Rule of Three）に照らして判定。集約する場合は R2 の用途別サブモジュール原則に従う。

### V6 性能リグレッション抑止

fixedpoint 分割は ChaseState 受け渡しが増えるため、Phase 3 [A] 完了の前後で経過時間を計測する。

**計測手順**:
- 対象データセット: `tests/` 配下で最大サイズの integration ケース（Phase 3 plan で固定 ID を指定）
- 計測コマンド: `time python -m grep_analyzer <args>`（壁時計時間）
- **最低 3 回実行し中央値を採用**（multiprocessing Pool 初期化のばらつき吸収）
- 経路の数は R4（Rule of Three）判定結果に応じる:
  - **R4 で統合した場合**: 1 経路のみ測定
  - **R4 で並存（`_scan_hop_single` / `_scan_hop_chunked` の 2 関数）とした場合**: 2 経路を個別に測定
- 比較は Phase 3 [A] 着手直前の HEAD を baseline とする

**判定基準**:
- 中央値が **baseline + 10% を超える** または **絶対値で +5 秒を超える** 場合は要因解析必須
- 解析の上で許容するか修正するかを Phase 3 plan のレビューで決定

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
