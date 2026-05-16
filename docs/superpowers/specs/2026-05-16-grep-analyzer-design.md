# grep_analyzer 設計書 (Design Spec)

- 作成日: 2026-05-16
- 改訂:
  - v1: ブレインストーミング初版
  - v2: AIクリティカルレビュー反映（Solaris前提）
  - v3: 稼働先をモダンLinux・オフラインへ転換。tree-sitter主軸＋ネイティブ高速スキャン
  - **v4（現行）: 2回目AIレビュー反映。Python3.12はターゲットに既存（wheelhouseのみ持込）。配備ゲート明文化／多ホップ偽陽性・停止性・決定的degrade／決定性の実体化／PRD整合済み化／Pro\*C前処理方式 等**
- ステータス: ドラフト（ユーザー再レビュー待ち）
- 位置づけ: `docs/product-requirements.md`（PRD）を受けた確定設計。本書が実装計画 (writing-plans) の入力。**§4 の前提検証ゲートは writing-plans 着手前のブロッキング前提**。

---

## 1. 目的と網羅性の約束

Java / C / Pro\*C / SQL / Shell（v1）が混在する大規模レガシーシステムで、特定の文言（文字列値・コード値）を転用・削除する開発者が「その値が今どこでどのように使われているか」を把握できるようにする。grepで拾えない**定数経由・getter/setter経由・変数経由の間接参照**まで追跡し、**使われ方を自動分類**、**横にひと目でわかる要約**付きTSVを出力し、数万行規模の手作業確認を不要にする。

### 網羅性の約束

tree-sitter は正確な構文木を与えるが**型解決・名前解決は行わない**。よって絶対的なゼロ見落としは構造上保証しない。約束:

> 追跡ポリシー（§8）の範囲で**到達可能な間接参照を不動点まで最大限追跡**し、grep単独より網羅性を大幅に向上させる。原理的に追跡不能なクラス（§8.4）と、ノイズ抑止のため横展開を抑止したシンボル（§8.3）は**「既知の限界」として diagnostics に必ず明示**し、レビュアーが見落としを認識できる状態にする。

PRD §1 は本節と整合済み（commit `b0b155c`）。両文書で齟齬時は本書を正とする。

---

## 2. 確定した制約・前提

### 2.1 実行環境（確定）

| 項目 | 内容 |
|---|---|
| 稼働先 | **モダンLinux・オフライン** |
| ネットワーク | オフライン（依存は wheelhouse 同梱で持ち込む） |
| Python | **3.12 がターゲットに既存**（同梱不要。ユーザー確定）。開発＝稼働ともに 3.12 |
| ネイティブ依存 | 可（manylinux prebuilt wheel を利用） |
| 配備 | wheelhouse のみ持ち込み → `pip install --no-index`（§4） |
| **要確定欄（実装前ゲート G1）** | **ターゲットの CPUアーキ＝____ / libc＝glibc(≧__) または musl ／ Python ABIタグ＝cp312**。これが wheel 入手可否を決める（§4） |

### 2.2 設計方針

- Python 3.12 標準ライブラリ ＋ prebuilt 外部依存（tree-sitter＋言語grammar、文字コード判定、`pyahocorasick`、任意 ripgrep）を **vendored wheelhouse**（バージョン固定）で同梱。
- **tree-sitter を構文解析の主軸**（§7）。**soot 不採用**（§12）。
- 60GB走査はネイティブ高速手段（§8.2）。本ツールはネットワーク不使用。

### 2.3 v1 スコープ

- 対象言語: **Java / C / Pro\*C / SQL / Shell**。残りは **v2+** で言語別プラグイン経由追加。

---

## 3. アーキテクチャ（単一トラック・条件付き）

単一の成果物（本体＋wheelhouse）。**ただし単一トラック前提は「全必須依存が対象環境向け prebuilt wheel で揃う」場合に限り成立**。揃わない依存があれば §4 のフォールバック経路（限定的ビルド or 代替）が発生する。

---

## 4. オフラインLinux配備と前提検証ゲート

Python 3.12 はターゲットに既存（§2.1）。配備は wheelhouse 持ち込みのみ。

### 4.1 同梱依存（バージョン固定。確定値は実装計画で `requirements.lock`）

| 依存 | 用途 | 区分 |
|---|---|---|
| `tree-sitter`（Pythonバインディング・**メジャー版固定**） | 構文解析ランタイム | 必須 |
| `tree-sitter-java` / `tree-sitter-c`（grammar・ABI/版固定） | Java / C(Pro\*C基盤) 解析 | 必須 |
| `pyahocorasick`（ネイティブ） | 多シンボル同時走査 | 必須 |
| 文字コード判定（`chardet` をバージョン固定） | エンコーディング検出 | 必須 |
| `ripgrep` バイナリ（対象アーキ用・任意同梱） | 1次粗フィルタ高速化（§8.2） | 任意 |

- **tree-sitter バインディングのロード規約を固定**: py-tree-sitter 0.21+ は `Language`/`Parser` API が破壊的変更（旧 `Language(path, name)` 廃止 → `tree_sitter_<lang>.language()` 経由）。**採用版とロード方式を実装計画で固定し、バインド版と grammar ABI 整合をスモークで検証**。

### 4.2 前提検証ゲート G1（writing-plans 着手前のブロッキング前提）

実装計画確定の前に次を満たすこと:

1. ターゲットの **CPUアーキ・libc（glibc版 or musl）・`python3.12` の ABIタグ（cp312）** を確定し §2.1 要確定欄を埋める。
2. 開発環境で `pip download --no-deps --platform <対象> --python-version 3.12 --only-binary=:all:` 等により、**全必須依存（tree-sitter本体／tree-sitter-java／tree-sitter-c／pyahocorasick／chardet）の cp312・対象プラットフォーム wheel と推移依存が取得可能**であることを実証。
3. 取得不能な依存が1つでもあれば、その依存に限り (a) sdist ビルド用ツールチェーン同梱（単一トラック前提が部分失効・§3）、または (b) 代替実装、を実装計画で意思決定。

→ ゲート未充足のまま writing-plans を確定しない。

---

## 5. 本体アーキテクチャ

### 5.1 パイプライン

```
Ingest → Seed化 → 言語ディスパッチ → 分類器(tree-sitter主軸) → 不動点・ターゲットスキャン・エンジン → TSV出力(+診断)
```

- **Ingest**: `input/*.grep` を文字コード判定の上で読込・行パース（§6）。
- **Seed化**: `{keyword, source_path, lineno, raw_line, language, match_span}`。
- **言語ディスパッチ（決定的規則）**:
  - 拡張子マップ（`.java`→Java、`.sql`→SQL、`.sh`/`.ksh`/`.bash`→Shell、`.pc`→Pro\*C、`.c`/`.h`→C）。
  - **内容ヒューリスティック**: `.c`/`.h`/`.pc` で `EXEC SQL` を含むものは **Pro\*C** と判定。
  - 判定不能は diagnostics 記録のうえ C にフォールバック。CLI で拡張子マップ上書き可（`--lang-map`）。
- **分類器**: §7。**走査エンジン**: §8。**TSV出力**: §9（診断は §10.3）。

### 5.2 言語別プラグイン・インタフェース（v2+ 追加点）

各言語モジュールが実装: `classify(node_or_line, ctx)` / `extract_chase_symbols(seed_or_hit)`（ヒットからも再抽出可＝不動点拡張）/ `tracking_policy`（§8.3）。

---

## 6. 入力契約

- `input/<keyword>.grep`（複数可。ファイル名 stem = キーワード）。
- 1行 = `grep -rn` 相当 `path:lineno:content`。`^(?P<path>.*?):(?P<lineno>\d+):(?P<content>.*)$` で**最左の `:<数字>:` 境界**採用（非貪欲）。Windowsパス・数値始まりcontent・`:`含有パスの誤分割回避。
- 不一致行は捨てず diagnostics（§10.3）へ。
- CLI `--source-root <60GBツリー>` を tool が走査。`.grep` 自体も文字コード判定対象（§10.1）。

---

## 7. 分類器（tree-sitter主軸）

`confidence` は**ヒット（行）単位**（言語単位ではない。同一ファイル内で混在し得る。例 Pro\*C: C構文部=high、EXEC SQL補完部=medium）:

- `high` = tree-sitter AST により**構文位置が確定**（意味的同一性＝その変数が当該値を保持する型かは保証しない）。
- `medium` = 正規表現分類。
- `low` = 型解決を要する間接（getter/setter 等）で人間確認前提。

言語別:

- **Java**: tree-sitter-java（Java 8〜17+ を正確にパース）。判定軸: 宣言/比較(if・equals)/代入/メソッド引数/return/switch・switch式/アノテーション/文字列連結・text block/ログ・出力。
- **C**: tree-sitter-c。`#define`/初期化/比較/関数引数/`switch case`/文字列。
- **Pro\*C（前処理方式を確定）**: `EXEC SQL ... ;`／`EXEC SQL ... END-EXEC`／`EXEC ORACLE ...` 区間を **構文中立なプレースホルダ・トークンに置換**して tree-sitter-c の構文を壊さず温存。置換した区間内は別途正規表現で **ホスト変数 `:var`／指示子変数 `:var:ind`／ホスト構造体 `:rec.field`／SQLリテラル** を抽出し、同一行情報にマージ（confidence=medium）。`EXEC SQL INCLUDE`／プリプロセッサマクロ展開前ソース／`VARCHAR` 擬似型は **v1スコープ外＝§8.4 既知の限界に列挙**。
- **SQL**: 正規表現（方言差大のため tree-sitter SQL 不採用）。リテラル比較/`INSERT`・`UPDATE`値/`CASE WHEN`/変数代入。
- **Shell**: 正規表現。変数代入/比較/`case`/コマンド引数。

`category` は**二層**: 共通上位（比較/代入/引数/宣言/出力/分岐）＋言語固有サブ。サブ語彙は実装計画で確定。

---

## 8. 不動点・ターゲットスキャン・エンジン（網羅性優先・偽陽性は抑止）

ユーザー決定: **網羅性優先・性能犠牲許容**。ただし**性能犠牲許容 ≠ 偽陽性ノイズ許容**（PRDの目視削減目的を守る）。

### 8.1 アルゴリズムと停止性

1. seed/既存ヒットから各言語モジュールが追跡シンボルを抽出（リテラルを束ねる定数識別子、連鎖代入先、getter/setter名、SQL/Shellの変数代入）。
2. **シンボル採否ポリシー（§8.3）を適用**してから採用シンボルを `pyahocorasick` オートマトンへ。
3. ソースツリーをストリーミング走査（`multiprocessing` ファイル並列、任意 `ripgrep` 1次粗フィルタ）。
4. 新規シンボルが出れば追加し**不動点（新規が枯れる）まで反復**。多ホップ定数・連鎖代入も追う。
5. **停止性の根拠**: §8.4 で実行時生成名を除外するため新規シンボルは原理的に有限集合。抽出関数は単調（既存集合から減らさない）。よって有限ステップで不動点に到達。加えて `--max-depth` と集合サイズ上限が二重の安全弁。
6. 暴走防止: シンボル循環検出、**シンボリックリンク・ループ検出**（§8.2）、`--max-depth` 到達は diagnostics 明示で打ち切り。
7. 各間接ヒットを分類し、起点seedへの**来歴チェーン**を記録。

### 8.2 性能・資源設計（モダンLinux）

- ネイティブ Aho-Corasick（`pyahocorasick`）＋任意 `ripgrep` 1次フィルタ＋`multiprocessing`。**段数 ≠ 走査回数**: シンボル集合の差分のみ後続反復対象にできるよう、ファイル→該当行ローカリゼーションを保持し全60GB再読込を避ける。
- ファイルサイズ上限＋バイナリ判定 skip、include/exclude glob（**生成コードは既定除外**。除外は diagnostics 記録）。
- **シンボリックリンク既定で辿らない**（`--follow-symlinks` 任意）。inode/実パス正規化で**同一実体の二重走査を排除**（重複時の代表選択＝正規化パス辞書順で決定的）。リンクループは検出して打ち切り。
- **メモリ×シンボル集合**: Aho-Corasick常駐メモリは集合サイズに概ね比例。`--memory-limit` 超過時の degrade は **(優先1) §8.3 の決定的シンボル切り捨て**（再走査を増やさない・決定性維持）を採り、**オートマトン分割（=複数パス再走査）は最終手段**とする。最大走査パス数の上限を実装計画で明示。目安式（集合サイズ→概算メモリ）と既定上限を実装計画で数値化。
- **進捗ログ**: 長時間実行のため標準エラーへ定期進捗（処理済みファイル数/バイト、現ホップ、シンボル集合サイズ、ETA）。`--progress` で粒度調整。

### 8.3 シンボル採否ポリシー（偽陽性抑止・誠実化）

不動点追跡に投入する前にシンボルを篩い、汎用名による横展開爆発を防ぐ:

- **最小特異性しきい値**: 短すぎる識別子・言語キーワード類似・プロジェクト頻出トップNのストップリストに該当するシンボルは**追跡集合に入れず、direct一致のみ報告して横展開しない**。
- しきい値・ストップリストは設定可能（`--stoplist` / `--min-specificity`）。
- **横展開を抑止したシンボルは全件 diagnostics に列挙**（§8.4と同じ誠実化思想。レビュアーが「ここは展開していない」を認識できる）。
- 集合サイズ上限超過時の切り捨ては**決定的**: シンボルを `(発見ホップ数, 特異性スコア, 文字列辞書順)` で安定ソートし上限内を採用。打ち切りシンボルは全件 diagnostics。

### 8.4 既知の取りこぼしクラス（diagnostics に必ず明示）

- **型解決を要する getter/setter**: `obj.getX()` の `obj` の型同定不可。同名メソッドは全件 `confidence=low`、意味的同一性は人間判断。
- **リフレクション / 動的呼び出し**。
- **実行時の文字列連結・整形で生成される名前**。
- **Pro\*C の `EXEC SQL INCLUDE`・マクロ展開前ソース・`VARCHAR`擬似型**（§7 でスコープ外とした分）。
- **正規表現方式言語（SQL/Shell）の限界**: 動的生成SQL・heredoc・`eval`・複数行マクロは構文追跡不可。
- **生成コード**（既定除外。除外した旨を記録）。
- §8.3 で横展開を抑止したシンボル（再掲・必ず列挙）。

---

## 9. TSV 出力スキーマ

`output/<keyword>.tsv`（キーワード1件＝1ファイル）。タブ区切り、フィールド内タブ/改行サニタイズ。既定 **UTF-8 with BOM**（Excel互換）、`--output-encoding`（例 `cp932`）で変更可。

| 列 | 内容 |
|---|---|
| `keyword` | 調査対象の文言 |
| `language` | 判定言語 |
| `file` | **`--source-root` からの正規化相対パス・`/`区切り固定** |
| `lineno` | 行番号 |
| `ref_kind` | `direct` / `indirect:constant` / `indirect:getter` / `indirect:setter` / `indirect:var` |
| `category` | 共通上位カテゴリ（§7） |
| `category_sub` | 言語固有サブカテゴリ |
| `usage_summary` | ★ひと目要約（例:「定数 STATUS_OK 経由で if 比較」） |
| `via_symbol` | 経由シンボル（direct は空） |
| `chain` | 来歴（起点→経由→ヒット。多ホップ可） |
| `snippet` | 該当行（タブ/改行除去） |
| `encoding` | 判定文字コード（置換発生時「要確認」フラグ） |
| `confidence` | `high`/`medium`/`low`（ヒット単位） |

**ref_kind × 言語マッピング:**

| 言語 | constant | var | getter/setter |
|---|---|---|---|
| Java | `static final` 定数 | 非finalフィールド/ローカル | `indirect:getter`/`indirect:setter` |
| C/Pro\*C | `#define`・`const` | 非const変数 | — |
| SQL | — | 同一ファイル変数代入=`indirect:var` | — |
| Shell | readonly等 | 変数代入=`indirect:var` | — |

**決定性（golden前提・必須）**: 出力は**全列を含む全順序**で安定ソート（推奨キー順 `(file, lineno, ref_kind, via_symbol, chain, category, category_sub, confidence, snippet)`、末尾に決定的タイブレーク）。`multiprocessing` 完了順・走査順に依存しない。`file` は上記正規化相対パス。

**規模対策**: 1キーワードの行数が Excel 上限（約104万行）超見込みなら `<keyword>.partNN.tsv` 分割＋diagnostics警告。

---

## 10. 横断事項

### 10.1 文字コード

- バージョン固定判定器で検出 → 決定的フォールバック鎖: `utf-8` → 検出結果 → `cp932`/`euc-jp` 候補 → `latin-1`（最終・置換）。
- **判定は当該ファイルの全バイトを対象に1回**実施（チャンク境界依存を排除し決定性を判定器版だけに依存させない。対象は §8.2 のファイルサイズ上限内）。
- **decodeで絶対に落とさない**。置換発生時 `encoding` 列＋diagnostics に「要確認」。
- 入力 `.grep` と走査対象ソース両方に適用。→ PRDメモ「文字コード判定」を解決。

### 10.2 性能

§8.2。

### 10.3 エラー処理・診断・中断/再開

- 壊れたgrep行 / 読めないファイル / decode失敗 / tree-sitter部分パース失敗（部分木で継続）/ `--source-root` 不在 / 権限拒否 / max-depth到達 / 生成コード除外 / 横展開抑止シンボル / リンクループ → **diagnostics へ集約**（非致命）。
- **diagnosticsスキーマ**: 先頭に**カテゴリ別件数サマリ**、続いて詳細。詳細が上限超過時は**カテゴリ別集約＋代表サンプル**にして肥大化を防ぐ（上限は設定可能）。
- **中断/再開の意思決定**: v1は **キーワード単位 resume を必須**（`--resume` で完了キーワードはスキップ、キーワード単位コミットで処理済みTSVは保全）。**キーワード内（ホップ/ファイル単位）チェックポイントは v1スコープ外＝受容するリスクとして明記**（1キーワードが長時間化し途中で落ちると当該キーワードは再実行）。
- 終了コードで「致命」と「警告のみ」を区別。

### 10.4 CLI

```
grep_analyzer --input ./input --output ./output --source-root <tree> \
  [--jobs N] [--include GLOB] [--exclude GLOB] [--lang-map EXT=LANG,...] \
  [--max-depth N] [--memory-limit MB] [--min-specificity X] [--stoplist FILE] \
  [--encoding-fallback utf-8,cp932,euc-jp,latin-1] [--output-encoding cp932] \
  [--use-ripgrep] [--follow-symlinks] [--resume] [--progress LEVEL]
```

- `--encoding-fallback` は**カンマ区切りで鎖を完全置換**（未指定時は §10.1 既定鎖）。
- `input/` に複数 `<keyword>.grep` 可。出力はキーワード毎TSV ＋ 全体 diagnostics 1ファイル。

---

## 11. テスト方針（リポジトリ規約準拠）

`.claude/skills/writing-tests.md` 準拠（古典学派 + TDD、日本語テスト名、層の縄張り）。

- `tests/unit/`: 分類器（tree-sitterクエリ）・追跡シンボル抽出・**シンボル採否ポリシー**・grep行パース（Windowsパス/数値始まり/`:`含有）・文字コードフォールバック・不動点停止性。
- `tests/integration/`: CLI契約・複数keyword・エラー経路・`--resume`挙動・オプション相互作用（in-process 既定）。
- `tests/golden/`: **合成された小規模代表ツリー**で TSV 完全一致。**カバレッジ設計原則**: 「言語 × ref_kind は必須網羅、文字コード/多ホップは pairwise で直交配置」。**必須回帰ケースを名指しで含む**: 汎用名の横展開抑止、決定性タイブレーク、Pro\*C `EXEC SQL` 内ホスト変数、シンボリックリンク重複排除、文字コード混在。決定性ソート（§9）前提。
- `tests/handcrafted/`: 分類精度ダッシュボード（pass/fail ゲートではない）。
- `tests/test_smoke.py`: `import` ＋ `--help` exit 0 ＋ tree-sitter バインド/grammar ABI 整合確認。
- `tests/perf/`: **`@pytest.mark.perf` の独自マーカ**（規約の `no_external` 流用はしない）。**handcrafted と同じくダッシュボード（pass/fail非ゲート・CI停止しない）**。§8.2 の参照基準（基準ハード・データ規模・目標時間オーダ）を**回帰検知のベースライン**として記録（絶対SLAではない）。
- 本ツールにLLMは無いため規約のLLM項はN/A。外部I/O境界（ファイル/サブプロセス/ripgrep）は本物。

---

## 12. スコープ外・却下した代替案

- **soot**: JVM依存。tree-sitterで代替。→ 不採用。
- **tree-sitter SQL grammar**: 方言差大 → SQLは正規表現。
- → PRDメモ「sootやtree-sitterも有効活用できないか」への回答: **tree-sitter採用（Java/C/Pro\*C基盤）／soot不採用**。

---

## 13. リスクと未決事項

| # | 重大度 | 項目 | 対応 |
|---|---|---|---|
| R1 | High | 必須依存（tree-sitter本体/各grammar/pyahocorasick/chardet）の cp312・対象アーキ wheel 入手性・**py-tree-sitter 0.21+ API破壊変更** | §4.2 ゲートG1で実証。バインド版＋ロード方式固定、ABI整合をスモーク検証。未入手依存は sdistビルド or 代替を実装計画で決定 |
| R2 | High | 多ホップ追跡の偽陽性爆発（汎用名）／停止性／決定的degrade | §8.3 採否ポリシー＋停止性根拠＋決定的切り捨て。抑止は全件diagnostics |
| R3 | Medium | 60GB走査の実時間／メモリ×巨大シンボル集合 | §8.2 ネイティブ＋差分走査＋degrade優先順位。`tests/perf/` で実測ベースライン |
| R4 | Medium | 型解決不能 getter 等の偽陽性（残存） | §8.4 既知限界を diagnostics 明示・confidence=low。handcrafted監視 |
| R5 | Medium | Pro\*C 前処理の取りこぼし（INCLUDE等） | §7 前処理方式確定（プレースホルダ置換）。スコープ外分は §8.4 明示。golden に Pro\*C 事例 |
| R6 | Low | ターゲットOS/アーキ未確定（§2.1要確定欄） | §4.2 G1 で確定（実装前ゲート） |

---

## 14. 今後（v2+）

- 残り言語（Kotlin / PL/SQL / TS・JS / Python / Perl / C#・VB.NET / Groovy）を §5.2 プラグイン経由で追加。
- Shell を tree-sitter-bash 化（任意）。
- キーワード内チェックポイント（§10.3 でv1スコープ外とした再開粒度の精緻化）。
