# grep_analyzer 設計書 (Design Spec)

- 作成日: 2026-05-16
- 改訂:
  - v1: ブレインストーミング初版
  - v2: AIクリティカルレビュー反映（Solaris前提）
  - **v3（現行）: 稼働先をSolarisから「モダンLinux・オフライン」へ転換。トラックA（自前ビルド）撤廃、tree-sitter主軸＋ネイティブ高速スキャン採用**
- ステータス: ドラフト（ユーザー再レビュー待ち）
- 位置づけ: `docs/product-requirements.md`（PRDメモ）を受けた確定設計。PRDの `メモ(聞いたこと)` 各項目はここで解決。本書が実装計画 (writing-plans) の入力。

---

## 1. 目的と網羅性の約束

Java / C / Pro\*C / SQL / Shell（v1）が混在する大規模レガシーシステムで、特定の文言（文字列値・コード値）を転用・削除する開発者が「その値が今どこでどのように使われているか」を把握できるようにする。grepで拾えない**定数経由・getter/setter経由・変数経由の間接参照**まで追跡し、**使われ方を自動分類**、**横にひと目でわかる要約**付きTSVを出力し、数万行規模の手作業確認を不要にする。

### 網羅性の約束（PRDからの誠実化）

tree-sitter は正確な構文木を与えるが**型解決・名前解決は行わない**。よって「1件の見落としもなく/ゼロ」という絶対保証は構造的に成立しない。約束を次に置く:

> 追跡ポリシー（§8）の範囲で**到達可能な間接参照を不動点まで最大限追跡**し、grep単独より網羅性を大幅に向上させる。原理的に追跡不能なクラス（§8.4）は**「既知の限界」として diagnostics に明示**し、レビュアーが見落としを認識できる状態にする。

> ⚠ PRD本文の「1件の見落としもなく」「取りこぼしをゼロに」は本specと不整合。**PRD側の文言を本節に合わせ要修正**（§14 フォローアップ）。

---

## 2. 確定した制約・前提

### 2.1 実行環境（確定・v3で全面変更）

| 項目 | 内容 |
|---|---|
| 稼働先 | **モダンLinux・オフライン**（旧Solaris前提は撤廃） |
| ネットワーク | オフライン（依存は同梱して持ち込む。ただしprebuilt wheel運用で容易） |
| Python | **3.12 で開発＝稼働**（言語レベル降格なし。PRDメモの3.7懸念は解消） |
| ネイティブ依存 | **可**（manylinux prebuilt wheel／同梱バイナリを利用） |
| 配備 | §4：自己完結Python 3.12 ＋ manylinux wheelhouse を `pip --no-index` で導入（自前ソースビルド不要） |

### 2.2 設計方針

- Python 3.12 標準ライブラリ ＋ **prebuilt な外部依存**（tree-sitter バインディング＋言語grammar、文字コード判定、高速マッチャ）を **vendored wheelhouse** で同梱（バージョン固定）。
- **tree-sitter を構文解析の主軸**（§7）。**soot はスコープ外**（JVM依存、tree-sitterで代替）（§12）。
- 60GB走査はネイティブ高速手段（§8.2）。
- 本ツールはネットワークを使わない。

### 2.3 v1 スコープ（確定）

- 対象言語: **Java / C / Pro\*C / SQL / Shell**。残り言語は **v2+** で言語別プラグイン経由追加。

---

## 3. アーキテクチャ（単一トラック）

v2 の「2トラック（Solarisブートストラップ＋本体）」は撤廃。配備はオフラインLinuxの軽量パッケージング（§4）に縮小し、本体（§5〜§11）が単一の成果物。

---

## 4. オフラインLinux配備

低リスク。自前ソースビルドは不要。

- **Python 3.12 ランタイム**: 自己完結・再配置可能ビルド（例: python-build-standalone のLinux x86_64/aarch64リリース）を同梱して持ち込む。これによりターゲットに Python が無くても可。
- **依存 wheelhouse**: 開発環境で `pip download`（manylinux・対象Pythonタグ・**推移依存込み**）で構築し同梱。ターゲットで `pip install --no-index --find-links wheelhouse -r requirements.lock`。
- **同梱依存（バージョン固定。確定値は実装計画で lock）**:

| 依存 | 用途 | 区分 |
|---|---|---|
| `tree-sitter`（Pythonバインディング） | 構文解析ランタイム | 必須 |
| `tree-sitter-java` / `tree-sitter-c` 等の言語grammar | Java/C(Pro\*C基盤)解析 | 必須 |
| `pyahocorasick`（ネイティブ） | 多シンボル同時走査の高速化 | 必須 |
| 文字コード判定（`chardet` をバージョン固定。判定の決定性確保のため。代替 `charset-normalizer` も可だが固定運用） | エンコーディング検出 | 必須 |
| （任意）`ripgrep` バイナリ同梱 | 1次粗フィルタの高速化（§8.2） | 任意 |

- 配備検証: ターゲット相当環境で wheelhouse 導入＋ `--help` ＋ 小サンプル実行が通ること（実装計画のスモーク手順）。

---

## 5. 本体アーキテクチャ

### 5.1 パイプライン

```
Ingest → Seed化 → 言語ディスパッチ → 分類器(tree-sitter主軸) → 不動点・ターゲットスキャン・エンジン → TSV出力(+診断)
```

- **Ingest**: `input/*.grep` を文字コード判定の上で読込・行パース（§6）。
- **Seed化**: `{keyword, source_path, lineno, raw_line, language, match_span}`。
- **言語ディスパッチ**: 拡張子/ヒューリスティックで言語モジュール選択。
- **分類器**: §7。**走査エンジン**: §8。**TSV出力**: §9（診断は §10.3）。

### 5.2 言語別プラグイン・インタフェース（v2+ 追加点）

各言語モジュールは共通インタフェースを実装:

- `classify(node_or_line, file_context) -> Category`
- `extract_chase_symbols(seed_or_hit) -> set[Symbol]`（ヒットからも再抽出可＝不動点拡張のため）
- `tracking_policy`（§8.3）

---

## 6. 入力契約

- `input/<keyword>.grep`（複数可。ファイル名 stem = キーワード）。
- 1行 = `grep -rn` 相当 `path:lineno:content`。パース規則:
  - `^(?P<path>.*?):(?P<lineno>\d+):(?P<content>.*)$` で**最左の `:<数字>:` 境界**を採用（非貪欲）。Windowsパス・数値始まりcontent・`:`含有パスの誤分割を回避。
  - 不一致行は捨てず diagnostics（§10.3）へ。
- 別途 CLI `--source-root <60GBツリー>` を tool が走査。
- `.grep` 自体も文字コードバラバラ前提 → 入力もエンコーディング判定対象（§10.1）。

---

## 7. 分類器（tree-sitter主軸）

`confidence` の意味:

- `high` = **tree-sitter AST により構文位置が確定**（if条件/return/引数/宣言 等が確実）。**意味的同一性（その変数が本当に当該値を保持する型か）は保証しない**（tree-sitterは型解決をしないため）。
- `medium` = 正規表現分類。
- `low` = 型解決を要する間接（getter/setter 等）で人間確認前提。

言語別:

- **Java**: tree-sitter-java で AST解析（**Java 8〜17+ を正確にパース。v2のjavalang/Java8限界(R4)は解消**）。判定軸: 宣言 / 比較（if・equals）/ 代入 / メソッド引数 / return / switch・switch式 / アノテーション / 文字列連結・text block / ログ・出力。
- **C**: tree-sitter-c で AST解析。`#define` / 初期化 / 比較 / 関数引数 / `switch case` / 文字列。
- **Pro\*C**: tree-sitter-c を基盤にしつつ、`EXEC SQL ... END-EXEC` ブロックとホスト変数（`:var`）は前処理＋正規表現で補完（tree-sitter-c はProC拡張を解さないため）。
- **SQL**: 正規表現（tree-sitter SQL grammar は方言差が大きく不採用）。リテラル比較 / `INSERT`・`UPDATE` 値 / `CASE WHEN` / 変数代入。
- **Shell**: 正規表現（小規模で十分。tree-sitter-bash はv2+で検討可）。変数代入 / 比較 / `case` / コマンド引数。

`category` は**二層**: 言語横断の共通上位（比較/代入/引数/宣言/出力/分岐）＋言語固有サブ。Excelフィルタが言語をまたいで機能（PRD主目的）。サブ語彙は実装計画で確定。

---

## 8. 不動点・ターゲットスキャン・エンジン（網羅性優先）

ユーザー決定: **網羅性を上げるため追跡を強化し、性能犠牲を許容**（モダンLinux＋ネイティブで犠牲は小さい）。

### 8.1 アルゴリズム

1. seed/既存ヒットから各言語モジュールが「追跡シンボル」を抽出（リテラルを束ねる定数識別子、連鎖代入先、getter/setter名、SQL/Shellの変数代入）。
2. シンボル集合を **`pyahocorasick` オートマトン**に投入（多シンボル同時・ネイティブ高速）。
3. ソースツリーをストリーミング走査。`multiprocessing` でファイル並列。任意で `ripgrep` 同梱バイナリを1次粗フィルタに使い候補ファイルを絞ってから精査。
4. 新規シンボルが出れば追加し**不動点（新規が枯れる）まで反復**。多ホップ定数・連鎖代入も追う。
5. 暴走防止: シンボル循環検出、設定可能 `--max-depth`（既定は十分大、超過時 diagnostics 明示で打ち切り）、シンボル集合サイズ上限（超過時 degrade＋警告）。
6. 各間接ヒットを分類し、起点seedへの**来歴チェーン**を記録。

### 8.2 性能設計（モダンLinux・ネイティブ）

- ネイティブ Aho-Corasick（`pyahocorasick`）＋任意 `ripgrep` 1次フィルタ＋`multiprocessing` で 60GB を実用時間内に走査（旧SPARC前提の悲観見積りは撤廃。実測ベンチを実装計画のスモーク/性能テストに含める）。
- ファイルサイズ上限＋バイナリ判定 skip、include/exclude glob（生成コードのデフォルト除外ポリシーは実装計画で定義し、除外時は diagnostics 記録）。
- **段数 ≠ 走査回数**: シンボル集合の差分のみを後続反復対象にできるよう、ファイル→該当行のローカリゼーションを保持し全60GB再読込を避ける。
- **メモリ上限**: 設定可能。超過時はオートマトン分割／中間結果のディスクスピルで degrade（クラッシュさせない）。

### 8.3 追跡ポリシー（不動点・網羅優先）

- 全言語: 直接参照 ＋ 間接参照を**不動点まで多ホップ追跡**（定数→定数、連鎖代入、Java/Groovyは getter/setter 経由も）。
- 終了条件: 不動点／`--max-depth` 到達（diagnostics明示）／安全上限到達。
- Shell/SQL の同一ファイル内変数、C/Pro\*C の `#define`・連鎖代入もホップ対象。

### 8.4 既知の取りこぼしクラス（原理的限界・diagnostics に必ず明示）

tree-sitter で構文精度は大幅向上するが、**型/名前解決をしない**ため次は原理的に追えない。取りこぼしたら黙らせず列挙する:

- **型解決を要する getter/setter**: `obj.getX()` の `obj` の型同定は不可。同名メソッドは全件 `confidence=low` で出すが意味的同一性は人間判断。
- **リフレクション / 動的呼び出し**。
- **実行時に文字列連結・整形で生成される名前**。
- **生成コード**（include/exclude除外時はその旨を記録）。

（v2の「javalang/Java8パース失敗」限界は tree-sitter 採用で**解消**したため削除。）

---

## 9. TSV 出力スキーマ

`output/<keyword>.tsv`（キーワード1件＝1ファイル）。タブ区切り、フィールド内タブ/改行サニタイズ。既定 **UTF-8 with BOM**（Excel互換）、`--output-encoding`（例 `cp932`）で変更可。

| 列 | 内容 |
|---|---|
| `keyword` | 調査対象の文言 |
| `language` | 判定言語 |
| `file` | ファイルパス |
| `lineno` | 行番号 |
| `ref_kind` | `direct` / `indirect:constant` / `indirect:getter` / `indirect:setter` / `indirect:var` |
| `category` | 共通上位カテゴリ（§7） |
| `category_sub` | 言語固有サブカテゴリ |
| `usage_summary` | ★ひと目要約（例:「定数 STATUS_OK 経由で if 比較」）= PRDの「横にひと目でわかる単位」 |
| `via_symbol` | 経由シンボル（direct は空） |
| `chain` | 来歴（起点→経由→ヒット。多ホップ可） |
| `snippet` | 該当行（タブ/改行除去） |
| `encoding` | 判定文字コード（置換発生時「要確認」フラグ） |
| `confidence` | `high`(AST構文位置) / `medium`(regex) / `low`(型解決依存) |

**ref_kind × 言語マッピング:**

| 言語 | constant | var | getter/setter |
|---|---|---|---|
| Java | `static final` 定数 | 非finalフィールド/ローカル | `indirect:getter`/`indirect:setter` |
| C/Pro\*C | `#define`・`const` | 非const変数 | — |
| SQL | — | 同一ファイル変数代入=`indirect:var` | — |
| Shell | readonly等 | 変数代入=`indirect:var` | — |

**決定性（golden前提・必須）**: 出力は **(file, lineno, ref_kind, via_symbol, chain) で安定ソート**。`multiprocessing` 完了順に依存しない。

**規模対策**: 1キーワードの行数が Excel 上限（約104万行）を超える見込みなら `<keyword>.partNN.tsv` 分割＋diagnostics警告。

---

## 10. 横断事項

### 10.1 文字コード

- バージョン固定の判定器で検出 → 決定的フォールバック鎖: `utf-8` → 検出結果 → `cp932`/`euc-jp` 候補 → `latin-1`（最終・置換）。
- **decodeで絶対に落とさない**。置換発生時 `encoding` 列＋diagnostics に「要確認」。
- 判定器をバージョン固定する理由: 同一バイト列で判定が非決定的だと golden（完全一致）が壊れるため。
- 入力 `.grep` と走査対象ソース両方に適用。→ PRDメモ「文字コード判定」を解決。

### 10.2 性能

§8.2。

### 10.3 エラー処理・中断

- 壊れたgrep行 / 読めないファイル / decode失敗 / tree-sitterパース失敗（部分木で継続）/ `--source-root` 不在 / 権限拒否 / max-depth到達 / 生成コード除外 → **diagnostics へ集約**（非致命）。部分成功でも使えるTSVを出す。
- **キーワード単位コミット**: 1キーワード完了ごとに当該TSVを確定保存。長時間実行の途中中断でも処理済み分は保全。
- 終了コードで「致命」と「警告のみ」を区別。

### 10.4 CLI

```
grep_analyzer --input ./input --output ./output --source-root <tree> \
  [--jobs N] [--include GLOB] [--exclude GLOB] [--max-depth N] \
  [--memory-limit MB] [--encoding-fallback ...] [--output-encoding cp932] \
  [--use-ripgrep]
```

- `input/` に複数 `<keyword>.grep` 可。出力はキーワード毎TSV ＋ 全体 diagnostics 1ファイル。

---

## 11. テスト方針（リポジトリ規約準拠）

`.claude/skills/writing-tests.md` 準拠（古典学派 + TDD、日本語テスト名、層の縄張り）。

- `tests/unit/`: 分類器（tree-sitterクエリ）・追跡シンボル抽出・grep行パース（Windowsパス/数値始まりcontent/`:`含有パス）・文字コードフォールバック・不動点終了条件。
- `tests/integration/`: CLI契約・複数keyword・エラー経路・中断挙動・オプション相互作用（in-process 既定）。
- `tests/golden/`: **合成された小規模代表ツリー**（各言語 × 各 ref_kind × 文字コード混在 × 多ホップ の最小事例。git管理可能サイズ）→ TSV 完全一致。決定性ソート（§9）前提。
- `tests/handcrafted/`: 分類精度ダッシュボード（pass/fail ゲートではない）。
- `tests/test_smoke.py`: `import` ＋ `--help` exit 0。
- `tests/perf/`（任意・no_external相当）: 大規模合成ツリーでの走査時間ベンチ（CI停止判断はしない）。本物60GBは持ち出さない前提。
- 本ツールにLLMは無いため規約のLLM項はN/A。外部I/O境界（ファイル/サブプロセス/ripgrep）は本物。

---

## 12. スコープ外・却下した代替案

- **soot**: JVM依存。tree-sitter で代替。→ 不採用。
- **tree-sitter SQL grammar**: 方言差大 → SQLは正規表現。
- → PRDメモ「sootやtree-sitterも有効活用できないか」への回答: **tree-sitter採用（Java/C/Pro\*C基盤）／soot不採用**。

---

## 13. リスクと未決事項

| # | 重大度 | 項目 | 対応 |
|---|---|---|---|
| R1 | Medium | tree-sitter 言語grammarの版差・Java最新構文の網羅 | grammarバージョン固定（§4）。代表ファイルでパース検証を実装計画スモークに含める |
| R2 | Medium | Pro\*C（EXEC SQL/ホスト変数）は tree-sitter-c で解せない | 前処理＋正規表現で補完（§7）。golden に Pro\*C 事例を含める |
| R3 | Medium | 60GB走査の実時間（モダンLinuxでも要計測） | ネイティブ＋並列＋差分走査（§8.2）。`tests/perf/` で実測、本番相当データでベンチ |
| R4 | Medium | 型解決不能 getter 等の偽陽性 | §8.4 既知限界を diagnostics 明示・confidence=low。handcrafted で精度監視 |
| R5 | Low | オフラインターゲットへの Python 配備手段 | 自己完結Python同梱（§4）。ターゲットOS/アーキを実装計画で確定 |
| R6 | Low | wheelhouse 推移依存欠落で導入失敗 | `pip download` で推移依存込み・`requirements.lock` 固定（§4） |

---

## 14. 今後（v2+）

- 残り言語（Kotlin / PL/SQL / TS・JS / Python / Perl / C#・VB.NET / Groovy）を §5.2 プラグイン経由で追加（tree-sitter grammar が揃う言語はAST化容易）。
- **PRD本文の網羅性文言（§1）を本specに合わせ修正**（フォローアップ）。
- Shell を tree-sitter-bash 化（任意）。
