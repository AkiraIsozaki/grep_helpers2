# grep_analyzer 設計書 (Design Spec)

- 作成日: 2026-05-16
- ステータス: ドラフト（ユーザーレビュー待ち）
- 位置づけ: `docs/product-requirements.md`（PRDメモ）を受けて、ブレインストーミングで確定した設計判断を記録する。PRDの `メモ(聞いたこと)` の各項目はここで解決される。本書が実装計画 (writing-plans) の入力となる。

---

## 1. 目的（PRDの再掲・要約）

Java / C / Pro\*C / SQL / Shell（v1）が混在する大規模レガシーシステムで、特定の文言（文字列値・コード値）を転用・削除しようとする開発者が「その値が今どこでどのように使われているか」を**1件の見落としもなく**把握できるようにする。grepで拾えない**定数経由・getter/setter経由・変数経由の間接参照**まで追跡し、**使われ方を自動分類**し、**横にひと目でわかる要約**を付けたTSVを出力して、数万行規模の手作業目視確認を不要にする。

---

## 2. 確定した制約・前提

### 2.1 実行環境（確定）

| 項目 | 内容 |
|---|---|
| 稼働先 | **オフライン Solaris 10 1/13（s10s_u11wos_24a）SPARC**（Solaris 10 最終リリース Update 11 / 2013-01） |
| ネットワーク | オフライン（外部からの取得不可。すべて同梱して持ち込む） |
| C コンパイラ | `cc` のみ（Oracle Solaris Studio。`gcc` は無い） |
| 既存 Python | Python 2.x のみ（3.x は無い） |
| 開発環境 | Python 3.12 でよい |
| ターゲット | **CPython 3.12 を現地で `cc` ソースビルドする**（PRDメモ通り。後述のリスク扱い） |

### 2.2 この環境から導かれる設計方針

- 純Python・標準ライブラリ中心。外部依存は **pure-Python のみ**（`javalang`, `chardet`）を **vendored wheelhouse** で同梱。ネイティブ拡張は使わない。
- **soot / tree-sitter はスコープ外**（§12 参照）。
- 60GB走査エンジンは純Python（ネイティブ高速ライブラリに依存しない）。

### 2.3 v1 スコープ（確定）

- 対象言語: **Java / C / Pro\*C / SQL / Shell**。
- 残り言語（Kotlin / PL/SQL / TypeScript・JS / Python / Perl / C#・VB.NET / Groovy）は **v2+** で、言語別プラグイン・インタフェース経由で追加。
- v1 で実装する間接参照の段数は §8.3 のポリシーに従う。

---

## 3. 全体アーキテクチャ：2トラック分割

成果物は**独立した2トラック**に分かれる。両者の接点は「ターゲットPythonバージョン」と「純Python依存リスト」のみ。よって別々に spec → plan → implement できる。

- **トラックA — ランタイム・ブートストラップ**（§4）: オフライン Solaris 10 SPARC 上に動作する Python 3 ＋ 依存を用意するビルド/運用作業。高リスク。
- **トラックB — grep_analyzer 本体**（§5〜§11）: 製品価値の本体。純Python。

本書は**トラックB主体**で記述し、トラックAは制約・前提＋別フォローアップspecの種として §4 にまとめる。

---

## 4. トラックA：ランタイム・ブートストラップ

### 4.1 同梱物（リポジトリに格納して持ち込む）

- バージョン固定の **CPython 3.12 ソース** tarball。
- 前提ライブラリのソース tarball: **OpenSSL / zlib / libffi**（必要に応じ `xz` / `bzip2` / `readline`）。
  - 用途: OpenSSL（`ssl`/`hashlib`/`pip`）、zlib（`zlib`/`gzip`）、libffi（`ctypes`）。
- Solaris Studio `cc` 向けの**決定的ビルドスクリプト**（環境変数・`configure` オプション・`Modules/Setup` のSolaris調整を含む）。
- **vendored wheelhouse**: `javalang`, `chardet`（いずれも pure-Python）。

### 4.2 事前調査チェックリスト（運用者が実機で実行）

ビルド着手前に実機で確認し、結果を記録する:

- `uname -a`（OS/カーネル）
- `isainfo -v`（32/64bit, アーキ）
- `cc -V`（Studio バージョン。C11 可否に直結）
- `make` の有無（無ければ代替手順）
- `/usr/include` 等のシステムヘッダの有無
- 空きディスク容量（ソース展開＋ビルド＋成果物）
- CPU コア数（multiprocessing 並列度の既定値に使用）

### 4.3 フィージビリティ・スパイク（必須・最優先）

トラックB本体を信頼する前に、**実機で CPython 3.12 をビルドしスモーク起動できること**を先に確認する。

- 成功基準: ビルドした `python3.12` が起動し、`ssl`/`zlib`/`ctypes` import が通り、wheelhouse から `javalang`/`chardet` を導入できる。
- **フォールバック**: スパイク失敗時は「より古くビルド実績のある 3.x へ降格」。その場合 **トラックBの言語機能レベルも降格**（型構文・新文法の使用を該当バージョン相当に制限）。この依存はリスク登録項目（§13）として明文化する。

### 4.4 リスク

CPython 3.12 を Solaris 10 1/13 SPARC ＋ 旧 Studio `cc` ＋ オフラインでビルドするのは高リスク（`configure`/`Modules/Setup` の Solaris 対応、OpenSSL/zlib/libffi のソースビルド、SPARC エンディアン、Studio バージョン依存）。§4.3 のスパイクとフォールバックで保護する。

---

## 5. トラックB：アーキテクチャ

### 5.1 パイプライン

```
Ingest → Seed化 → 言語ディスパッチ → 分類器 → 有界段階ターゲットスキャン・エンジン → TSV出力(+診断)
```

- **Ingest**: `input/*.grep` を読み込み、文字コード判定の上で行をパース。
- **Seed化**: `{keyword, source_path, lineno, raw_line, language, match_span}` のseedレコード集合を構築。
- **言語ディスパッチ**: 拡張子/ヒューリスティックで言語モジュールを選択。
- **分類器**: §7。
- **走査エンジン**: §8。
- **TSV出力**: §9。診断は別ファイル（§10.3）。

### 5.2 言語別プラグイン・インタフェース

各言語モジュールは共通インタフェースを実装する（v2+ の言語追加点）:

- `classify(line, file_context) -> Category` — 使われ方の分類。
- `extract_chase_symbols(seed) -> set[Symbol]` — 間接参照で追跡すべきシンボル抽出。
- `indirect_depth_policy` — 段数打ち切りポリシー（§8.3）。

---

## 6. 入力契約

- `input/<keyword>.grep`（複数可。ファイル名 stem = キーワード）。
- 1行 = `path:lineno:content`（`grep -rn` 相当）。
  - パース: 先頭2つの `:` で分割し、`lineno` が整数であることを検証（パスに `:` を含むケースに耐性）。
  - 形式不一致行は**黙って捨てず**、診断（§10.3）へ記録。
- 別途 CLI で `--source-root <60GBツリーのパス>` を受け取り、tool が走査する。
- `.grep` 自体も文字コードがバラバラな前提 → 入力もエンコーディング判定対象（§10.1）。

---

## 7. 分類器（言語別）

`category` は「使われ方」の機械判定。`confidence` は AST=high / regex=medium / fallback=low。

- **Java**: `javalang` で**該当行を含むファイル全体**をAST解析。判定例: 宣言 / 比較（`if`・`equals`）/ 代入 / メソッド引数 / `return` / `switch-case` / アノテーション / 文字列連結 / ログ・出力。AST解析失敗時は正規表現フォールバック。
- **C / Pro\*C**: 正規表現。`#define` / 変数初期化 / 比較 / 関数引数 / `switch case` / 文字列。Pro\*C は `EXEC SQL` ホスト変数パターンを追加。
- **SQL**: 正規表現。リテラル比較（`WHERE col = 'X'`）/ `INSERT`・`UPDATE` 値 / `CASE WHEN` / 変数代入。
- **Shell**: 正規表現。変数代入 / 比較（`[ "$x" = "X" ]`）/ `case` 分岐 / コマンド引数。

> category の正確な語彙（enum）は実装計画で各言語モジュール単位に確定する。本書ではv1の判定軸を上記に固定する。

---

## 8. 有界段階ターゲットスキャン・エンジン

### 8.1 アルゴリズム

1. seed から各言語モジュールが「追跡シンボル」を抽出（Java/C/Pro\*C＝リテラルを束ねる定数識別子・getter/setter名 / SQL・Shell＝同一ファイル内の変数代入）。
2. 現在のシンボル集合を**単一の結合マッチャ**に変換（純Python。大規模時は純Python実装の Aho-Corasick、小規模は連結正規表現）。
3. ソースツリーを **multiprocessing で1回ストリーミング走査**（バイナリ/巨大ファイル skip、include/exclude glob 尊重、行単位ストリーム、ファイル全体スラップしない）。
4. ヒットを分類し、新規シンボルがあれば §8.3 の段数内で次段へ。
5. 各間接ヒットは起点seedへの**来歴チェーン**を記録（起点→経由→ヒット）。

### 8.2 性能（60GB / SPARC）

- 走査パス数を**有界**に保つ（§8.3）ことで I/O を有界化。
- `multiprocessing.Pool` の並列度は検出コア数を既定値。
- ファイルサイズ上限＋バイナリ判定で skip。
- 結合マッチャは事前コンパイル。
- 進捗/ETA を stderr に出力。
- 再開チェックポイントは **v1 では必須でない（YAGNI）**。ただし設計上排除しない。

### 8.3 段数打ち切りポリシー（PRD準拠）

- **Java / Groovy**: 最大4段（直接 ＋ 間接 ＋ getter/setter経由）。
- **C / Pro\*C / Kotlin / C#・VB.NET / PL/SQL / TypeScript・JS / Python / Perl**: 直接参照 ＋ 定数経由のクロスファイル間接（1ホップ）。
- **Shell / SQL**: 直接参照 ＋ 同一ファイル内変数代入の間接。

（v1対象は Java / C / Pro\*C / SQL / Shell。他はv2+で同ポリシーを適用。）

---

## 9. TSV 出力スキーマ

`output/<keyword>.tsv`（キーワード1件＝1ファイル）。タブ区切り、フィールド内タブ/改行はサニタイズ。出力文字コードの既定は **UTF-8 with BOM**（Excelが文字化けせず開ける）。`--output-encoding`（例: `cp932`）で変更可。

| 列 | 内容 |
|---|---|
| `keyword` | 調査対象の文言 |
| `language` | 判定言語 |
| `file` | ファイルパス |
| `lineno` | 行番号 |
| `ref_kind` | `direct` / `indirect:constant` / `indirect:getter` / `indirect:setter` / `indirect:var` |
| `category` | 使われ方分類（§7） |
| `usage_summary` | ★ひと目でわかる1行要約（例:「定数 STATUS_OK 経由で if 比較」）= PRDの「横にひと目でわかる単位」 |
| `via_symbol` | 経由シンボル（定数名/getter名等。direct は空） |
| `chain` | 来歴（起点→経由→ヒット。例: `keyword→STATUS_OK→isOk()`） |
| `snippet` | 該当行（タブ/改行除去） |
| `encoding` | 判定された文字コード（要確認フラグ付き） |
| `confidence` | `high`(AST) / `medium`(regex) / `low`(fallback) |

---

## 10. 横断事項

### 10.1 文字コード

- vendored `chardet` で判定 → 決定的フォールバック鎖: `utf-8` → 検出結果 → `cp932`/`euc-jp` 候補 → `latin-1`（最終手段・置換）。
- **decode で絶対に落とさない**。置換が発生したら `encoding` 列＋診断に「要確認」フラグ。
- 入力 `.grep` と走査対象ソースの両方に適用。
- → PRDメモ「文字コード判定はあったほうが安全」を解決。

### 10.2 性能

§8.2 参照。

### 10.3 エラー処理

- 壊れたgrep行 / 読めないファイル / decode失敗 / `javalang` パース失敗 / `--source-root` 不在 / 権限拒否 → すべて **diagnostics ファイルへ集約**（非致命）。
- 部分的に失敗しても**使えるTSVを出す**（部分成功）。
- 終了コードで「致命」と「警告のみ」を区別。

### 10.4 CLI

```
grep_analyzer --input ./input --output ./output --source-root <tree> \
  [--jobs N] [--include GLOB] [--exclude GLOB] [--encoding-fallback ...]
```

- `input/` に複数 `<keyword>.grep` 可。出力はキーワード毎にTSV ＋ 全体で1つの診断ファイル。

---

## 11. テスト方針（リポジトリ規約準拠）

`.claude/skills/writing-tests.md` に従う（古典学派 + TDD、日本語テスト名、層の縄張り）。

- `tests/unit/`: 分類器・追跡シンボル抽出・grep行パース・文字コードフォールバックの細かい仕様。
- `tests/integration/`: CLI契約・複数keyword・エラー経路・オプション相互作用（in-process 既定）。
- `tests/golden/`: サンプルソースツリー → TSV 完全一致による回帰検出。
- `tests/handcrafted/`: 分類精度ダッシュボード（pass/fail ゲートではない）。
- `tests/test_smoke.py`: `import` ＋ `--help` exit 0。
- 本ツールに LLM は無いため、規約の「LLM client のみ stub」項は N/A。外部I/O境界（ファイル/サブプロセス）は本物、ドメイン層は本物。

---

## 12. スコープ外・却下した代替案

- **soot**: JVM 依存。オフライン Solaris 10 SPARC で JVM 前提を満たすのは高リスク。Java AST 需要は pure-Python の `javalang` で充足。→ 不採用。
- **tree-sitter**: ネイティブ拡張のビルドが必要。SPARC prebuilt は存在せず、現地 `cc` ビルドは CPython 同様の高リスク。→ 不採用。
- → PRDメモ「sootやtree-sitterも有効活用できないかな？」への回答。

---

## 13. リスクと未決事項

| # | 項目 | 対応 |
|---|---|---|
| R1 | CPython 3.12 を Solaris 10 SPARC + 旧Studio cc + オフラインでビルドできない可能性 | §4.3 フィージビリティ・スパイクを最優先実施。失敗時は古い3.xへ降格＋ツールの言語レベルも降格 |
| R2 | OpenSSL/zlib/libffi のソースビルド失敗 | 同梱バージョンを実機検証で確定。スパイクに含める |
| R3 | 60GB走査の所要時間が許容外 | 段数打ち切り＋並列＋skipで有界化。実機計測でチューニング項目を洗い出す |
| R4 | 正規表現分類の誤判定 | handcrafted ダッシュボードで精度を継続監視 |
| Q1 | Studio `cc` バージョン / SPARC 32-64bit / make の有無 | §4.2 事前調査チェックリストで確定（実機作業） |

---

## 14. 今後（v2+）

- 残り言語（Kotlin / PL/SQL / TS・JS / Python / Perl / C#・VB.NET / Groovy）を §5.2 のプラグイン・インタフェース経由で追加。
- トラックA（ブートストラップ）は本書とは別の spec → plan → implement サイクルで詳細化する。
