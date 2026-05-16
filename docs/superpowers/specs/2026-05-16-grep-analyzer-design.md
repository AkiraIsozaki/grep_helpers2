# grep_analyzer 設計書 (Design Spec)

- 作成日: 2026-05-16
- 改訂:
  - v1: ブレインストーミング初版
  - v2: AIレビュー反映（Solaris前提）
  - v3: 稼働先をモダンLinux・オフラインへ転換。tree-sitter主軸
  - v4: 2回目AIレビュー反映。Python3.12はターゲット既存（wheelhouseのみ）
  - v5: 3回目AIレビュー反映。停止性論証の修正／ストップリスト循環の解消（v1は静的のみ）／chain正規形／Pro\*C行番号保存／来歴グラフのメモリ／版ピン表現の是正／原子的TSV書込／実装フェーズ分割の追加／PRD版参照の版非依存化
  - v6: 4回目AIレビュー反映。型解決依存getter/setterは不動点投入しない静的規則（汎用getter爆発を構造的に抑止）／chain経路集合の有限化規則（単純パス・循環打切）／停止性前提文の厳密化／encoding正本一元化／part分割境界の決定性。これにより §15 全フェーズの writing-plans 着手ブロッカーを解消
  - **v7（現行）: ユーザー補足反映（Phase 1 完了後）。SQL方言を Oracle に確定（Pro\*C 埋め込みSQLと一貫）。Shell に C系シェル方言（csh/tcsh）を追加（§2.3 の1言語内方言・TSV `language` 語彙は "shell" 不変）。§5.1 にシェバン検出を追加し拡張子なしスクリプトも決定的に判別。§7/§8.1 を Oracle方言・bourne/cshell 二方言に精密化。§12 に「Oracle確定で tree-sitter SQL の却下理由は弱まるが、Oracle/PL-SQL の公式オフライン prebuilt wheel が無く §3/§4 単一トラック前提が採否を決めるため v1 非採用」の再評価を明記、§14 に条件付き将来候補として記録。§15 にフェーズ1.5（決定的コアの方言精密化）を追加（Phase 2 不動点エンジンとは別計画）**
- ステータス: ドラフト（ユーザー再レビュー待ち）
- 位置づけ: `docs/product-requirements.md`（PRD）を受けた確定設計。本書が実装計画 (writing-plans) の入力。**§4.2 ゲートG1 と §15 フェーズ0 は writing-plans 着手前のブロッキング前提**。

---

## 1. 目的と網羅性の約束

Java / C / Pro\*C / SQL / Shell（v1）が混在する大規模レガシーシステムで、特定の文言（文字列値・コード値）を転用・削除する開発者が「その値が今どこでどのように使われているか」を把握できるようにする。grepで拾えない**定数経由・getter/setter経由・変数経由の間接参照**まで追跡し、**使われ方を自動分類**、**横にひと目でわかる要約**付きTSVを出力し、数万行規模の手作業確認を不要にする。

### 網羅性の約束

tree-sitter は正確な構文木を与えるが**型解決・名前解決は行わない**。よって絶対的なゼロ見落としは構造上保証しない。

> 追跡ポリシー（§8）の範囲で**到達可能な間接参照を不動点まで最大限追跡**し、grep単独より網羅性を大幅に向上させる。原理的に追跡不能なクラスと横展開を抑止したシンボルは**§8.4 を正本として diagnostics に必ず明示**し、レビュアーが見落としを認識できる状態にする。

PRD と本書は相互に「設計書（最新版）を正とする」と明記済み（PRD は版非依存参照に修正済み）。齟齬時は本書を正とする。

---

## 2. 確定した制約・前提

### 2.1 実行環境（確定）

| 項目 | 内容 |
|---|---|
| 稼働先 | **モダンLinux・オフライン** |
| ネットワーク | オフライン（依存は wheelhouse 同梱で持ち込む） |
| Python | **3.12 がターゲットに既存**（同梱不要）。開発＝稼働ともに 3.12 |
| ネイティブ依存 | 可（manylinux prebuilt wheel を利用） |
| 配備 | wheelhouse のみ持ち込み → `pip install --no-index`（§4） |
| **要確定欄（実装前ゲート G1）** | **ターゲットの CPUアーキ＝____ / libc＝glibc(≧__) または musl ／ Python ABIタグ＝cp312**。wheel 入手可否を決める（§4） |

### 2.2 設計方針

- Python 3.12 標準ライブラリ ＋ prebuilt 外部依存（tree-sitter＋言語grammar、文字コード判定、`pyahocorasick`、任意 ripgrep）を **vendored wheelhouse**（完全バージョンピン）で同梱。
- **tree-sitter を構文解析の主軸**（§7）。**soot 不採用**（§12）。
- 60GB走査はネイティブ高速手段（§8.2）。本ツールはネットワーク不使用。

### 2.3 v1 スコープ

- 対象言語: **Java / C / Pro\*C / SQL（= Oracle 方言・Pro\*C 埋め込みSQLと一貫） / Shell**。残りは **v2+** で言語別プラグイン経由追加。
- **Shell は1言語**だが内部に2方言 — **bourne 系**（sh/ksh/bash）と **C系**（csh/tcsh）。方言は分類規則・追跡抽出の選択にのみ用い、TSV `language` 列は "shell" 固定（§5.1/§7/§9）。

---

## 3. アーキテクチャ（単一トラック・条件付き）

単一の成果物（本体＋wheelhouse）。**ただし「全必須依存が対象環境向け prebuilt wheel で揃う」場合に限り単一トラック成立**。揃わない依存があれば §4.2 のフォールバック経路（限定的 sdist ビルド or 代替）が発生する。

---

## 4. オフラインLinux配備と前提検証ゲート

Python 3.12 はターゲットに既存（§2.1）。配備は wheelhouse 持ち込みのみ。

### 4.1 同梱依存（完全バージョンピン。`requirements.lock` で版/ハッシュ固定）

| 依存 | 用途 | 区分 |
|---|---|---|
| `tree-sitter`（Pythonバインディング） | 構文解析ランタイム | 必須 |
| `tree-sitter-java` / `tree-sitter-c`（grammar） | Java / C(Pro\*C基盤) 解析 | 必須 |
| `pyahocorasick`（ネイティブ） | 多シンボル同時走査 | 必須 |
| `chardet`（文字コード判定） | エンコーディング検出 | 必須 |
| `ripgrep` バイナリ（対象アーキ用） | 1次粗フィルタ高速化（任意） | 任意 |

- **py-tree-sitter は 0.x 系であり、破壊的変更はマイナー境界（0.21 等）で発生**する。よって「メジャー版固定」ではなく **`==` による完全版ピン**とし、**grammar も同一系列でピン**、`requirements.lock` に版＋ハッシュを固定する。ロードは **`tree_sitter_<lang>.language()` 経路に確定**（0.21+ API）。バインド版と grammar ABI の整合はスモークで検証（§11）。

### 4.2 前提検証ゲート G1（writing-plans 着手前のブロッキング前提）

1. ターゲットの **CPUアーキ・libc（glibc版 or musl）・cp312** を確定し §2.1 要確定欄を埋める。
2. 開発環境で `pip download --no-deps --platform <対象> --python-version 3.12 --only-binary=:all:` 等により、**全必須依存（tree-sitter本体／java／c grammar／pyahocorasick／chardet）と推移依存の cp312・対象プラットフォーム wheel が取得可能**であることを実証。
3. 取得不能な依存があれば、その依存に限り (a) sdist ビルド用ツールチェーン同梱（単一トラック前提が部分失効・§3）、または (b) 代替実装、を実装計画で意思決定。

→ ゲート未充足のまま writing-plans を確定しない（§15 フェーズ0）。

---

## 5. 本体アーキテクチャ

### 5.1 パイプライン

```
Ingest → Seed化 → 言語ディスパッチ → 分類器(tree-sitter主軸) → 不動点・ターゲットスキャン・エンジン → TSV出力(+診断)
```

- **Ingest**: `input/*.grep` を文字コード判定の上で読込・行パース（§6）。
- **Seed化**: `{keyword, source_path, lineno, raw_line, language, match_span}`。
- **言語ディスパッチ（決定的規則・優先順位順）**:
  1. `--lang-map EXT=LANG` 上書き（拡張子キー）。値 `shell` のときの方言は下記「Shell 方言の確定」に従う。
  2. 拡張子マップ: `.java`→Java、`.sql`→SQL(Oracle)、`.pc`→Pro\*C、`.c`/`.h`→C、`.sh`/`.ksh`/`.bash`→Shell(bourne)、**`.csh`/`.tcsh`→Shell(cshell)**。
  3. **シェバン検出（拡張子が未知または無い場合）**: 第1物理行（先頭の BOM・空白を除去後）が `^#!` のとき interpreter の basename を解析。`#!/usr/bin/env X` は X を interpreter とみなす。`sh`/`bash`/`ksh`/`dash` 系→Shell(bourne)、`csh`/`tcsh`→Shell(cshell)。**シェル以外（`perl`/`python` 等＝§14 将来言語）は Shell に分類せず** `unsupported_shebang` を diagnostics（§10.3）に記録し 5 へ。
  4. 内容ヒューリスティック: `.c`/`.h`/`.pc`/未知 で `EXEC SQL` を含むものは Pro\*C。
  5. 判定不能は diagnostics 記録のうえ **C にフォールバック**。
- **Shell 方言の確定（決定的・言語が Shell に確定した全経路で適用）**: 言語が Shell（上記 1〜3 のどれで確定したかを問わず）になったら、方言を次順で決める。① 第1物理行がシェル系シェバン（`csh`/`tcsh` または `sh`/`bash`/`ksh`/`dash`）ならその方言（拡張子由来の方言より**シェバン優先**。例 `.sh` ＋ `#!/bin/csh` → cshell）。② シェバンが無ければ拡張子（`.csh`/`.tcsh`→cshell、`.sh`/`.ksh`/`.bash`→bourne）。③ どちらも無ければ **bourne 既定**。**重要（言語判定と方言判定は独立）**: 上記手順3のシェバン検出は「言語判定のため、拡張子が未知/無のときだけ」走るが、本「方言の確定」①のシェバン照合は「言語が Shell の全ケース」で走る（`.sh`/`.ksh` 等の既知シェル拡張子でも第1物理行のシェバンを必ず確認して方言を決める）。判定はファイル名と第1物理行のみに依存し走査順非依存（§9 決定性）。
- **分類器**: §7。**走査エンジン**: §8。**TSV出力**: §9（診断は §10.3）。

### 5.2 言語別プラグイン・インタフェース（v2+ 追加点）

各言語モジュールが実装: `classify(node_or_line, ctx)` / `extract_chase_symbols(seed_or_hit)`（ヒットからも再抽出可＝不動点拡張）/ `tracking_policy`（§8.3）。

---

## 6. 入力契約

- `input/<keyword>.grep`（複数可。ファイル名 stem = キーワード）。
- 1行 = `grep -rn` 相当 `path:lineno:content`。`^(?P<path>.*?):(?P<lineno>\d+):(?P<content>.*)$` で**最左の `:<数字>:` 境界**採用（非貪欲）。
- 不一致行は捨てず diagnostics（§10.3）へ。
- CLI `--source-root <60GBツリー>` を tool が走査。`.grep` 自体も文字コード判定対象（§10.1）。

---

## 7. 分類器（tree-sitter主軸）

`confidence` は**ヒット（行）単位**（同一ファイル内で混在し得る）:

- `high` = tree-sitter AST により**構文位置が確定**（意味的同一性は保証しない）。
- `medium` = 正規表現分類。
- `low` = 型解決を要する間接（getter/setter 等）で人間確認前提。

言語別:

- **Java**: tree-sitter-java（Java 8〜17+）。判定軸: 宣言/比較(if・equals)/代入/メソッド引数/return/switch・switch式/アノテーション/文字列連結・text block/ログ・出力。
- **C**: tree-sitter-c。`#define`/初期化/比較/関数引数/`switch case`/文字列。
- **Pro\*C（前処理方式・行番号保存を確定）**: `EXEC SQL ... ;`／`... END-EXEC`／`EXEC ORACLE ...` 区間を**構文中立なプレースホルダ・トークンに置換**して tree-sitter-c の構文を温存。**置換は行数・物理行境界を保存する**（複数行 EXEC SQL は同じ行数ぶんの中立トークン列＋改行で置換。桁ズレは許容するが**行番号は原ソースと不変**）。置換区間内は正規表現で**ホスト変数 `:var`／指示子変数 `:var:ind`／ホスト構造体 `:rec.field`／SQLリテラル**を抽出し同一行へマージ（confidence=medium）。`EXEC SQL INCLUDE`／マクロ展開前ソース／`VARCHAR`擬似型は v1スコープ外＝§8.4 に列挙。
- **SQL（= Oracle 方言・正規表現・confidence=medium。§12 で tree-sitter 非採用を確定）**: Oracle に特化した行正規表現。`:=`＝PL/SQL 代入、`||` 連結／`DECODE(...)`／`CASE WHEN`＝分岐、`WHERE …` の比較演算子＝比較、`INSERT … VALUES`／`UPDATE … SET`＝代入。バインド変数 `:var`／置換変数 `&var` を分類のため認識（追跡投入はしない＝§8.1/§8.4）。**複数行 PL/SQL ブロック（`DECLARE/BEGIN/END`）の構文解析はしない**（§12 の SQL 非パース方針を維持）。Pro\*C 埋め込み SQL と同一の Oracle 方言。
- **Shell（正規表現・confidence=medium・2方言。§5.1 で確定した方言で規則集合を切替）**:
  - **bourne 系**（sh/ksh/bash）: `^\s*\w+=`＝代入、`[ … ]`／`[[ … ]]`＝比較、`case … in`＝分岐、コマンド引数。
  - **C系**（csh/tcsh）: `^\s*set\s+\w+\s*=`／`^\s*setenv\s+\w+`／`^\s*@\s+\w+\s*=`＝代入、`if\s*\(…\)`／`while\s*\(…\)`（`==`/`!=`/`=~`）＝比較、`switch\s*\(…\)` … `case …:` … `breaksw`＝分岐。

`category` は**二層**: 共通上位（比較/代入/引数/宣言/出力/分岐）＋言語固有サブ。サブ語彙の確定は §15 フェーズで段階導入（§9/§11 の churn 回避）。

---

## 8. 不動点・ターゲットスキャン・エンジン（網羅性優先・偽陽性は抑止）

ユーザー決定: **網羅性優先・性能犠牲許容**。ただし**偽陽性ノイズは許容しない**（PRDの目視削減目的を守る）。

### 8.1 アルゴリズムと停止性

1. seed/既存ヒットから各言語モジュールが追跡シンボルを抽出（定数識別子、連鎖代入先、getter/setter名、SQL/Shell変数代入）。SQL(Oracle) は同一ファイル内 PL/SQL `var := 式` の左辺、Shell(bourne) は `var=` の左辺、Shell(cshell) は `set var =`／`setenv VAR`／`@ var =` の左辺を `indirect:var` 追跡シンボルとする。Oracle のバインド変数 `:var`／置換変数 `&var` は外部・ホスト境界のため追跡投入しない（Pro\*C ホスト変数と同様＝§8.4）。
2. **シンボル採否ポリシー（§8.3）適用後**に採用シンボルを `pyahocorasick` オートマトンへ。
3. ソースツリーをストリーミング走査（`multiprocessing` ファイル並列、任意 `ripgrep` 1次粗フィルタ）。
4. 新規シンボルが出れば追加し**不動点（新規が枯れる）まで反復**。多ホップ定数・連鎖代入も追う。
5. **停止性（正当性の根拠）**: 追跡シンボルは**すべてソースツリー上に字句出現する識別子**である（実行時合成名は §8.4 で除外）。`extract_chase_symbols` は**原ソースの字句**に対して抽出する（Pro\*C は §7 の置換前ソース基準。中立プレースホルダ・トークンは追跡対象にしない／ホスト変数は `:` を剥がした原識別子を採用）。ソースツリーは有限なので**追跡シンボルの母集合は有限**。`extract_chase_symbols` による採用集合は反復で縮小しない（**単調増加**）。有限母集合＋単調増加 → **高々 |母集合| ステップで飽和し不動点に到達**。`--max-depth`・集合サイズ上限は正当性の根拠ではなく**安全弁**（暴走時の打ち切り）。
6. 暴走防止: シンボル循環検出、シンボリックリンク・ループ検出（§8.2）、`--max-depth` 到達は diagnostics 明示で打ち切り。
7. 各間接ヒットを分類し、起点seedへの**来歴**を記録（来歴の集約は §8.2）。

### 8.2 性能・資源設計

- ネイティブ Aho-Corasick（`pyahocorasick`）＋任意 `ripgrep` 1次フィルタ＋`multiprocessing`。
- **差分走査の正確な効果（誠実化）**: 新規シンボルは前パスで未ヒットの任意ファイルに出現しうるため**新規シンボル分は全ツリー走査が必要**。ファイル→該当行ローカリゼーション保持で省けるのは「**確定済みシンボルの再ヒット再走査**」のみ。「段数≠走査回数」はこの限定的効果を指す。
- **来歴グラフのメモリ（ワーカ横断集約）**: 来歴は本質的にグローバル有向グラフ。ファイル並列ワーカは担当ファイルのみ見るため、ワーカは `(発見元シンボル, 発見シンボル, file, lineno)` のエッジ断片のみ返し、**集約フェーズで来歴グラフを合成**。来歴グラフのメモリは Aho-Corasick 常駐とは別物として `--memory-limit` の対象に含め、上限超過時はディスクスピル。
- degrade 優先順位: `--memory-limit` 超過時は **(優先1) §8.3 の決定的シンボル切り捨て**（再走査を増やさず決定性維持）→ (優先2) 来歴グラフのスピル → **(最終手段) オートマトン分割（=複数パス再走査）**。最大走査パス数の上限を実装計画で明示。
- ファイルサイズ上限＋バイナリ判定 skip、include/exclude glob（**生成コード既定除外**・除外は diagnostics 記録）。
- **シンボリックリンク既定で辿らない**（`--follow-symlinks` 任意）。inode/実パス正規化で同一実体の二重走査を排除（重複時の代表選択＝正規化パス辞書順で決定的）。リンクループは検出して打ち切り。
- **進捗ログ**: 標準エラーへ定期進捗（処理済みファイル数/バイト、現ホップ、シンボル集合サイズ、ETA）。`--progress` で粒度調整。

### 8.3 シンボル採否ポリシー（偽陽性抑止・v1は静的のみ）

不動点追跡へ投入する前にシンボルを篩い、汎用名の横展開爆発を防ぐ。**v1 のストップリストは事前フル走査を要しない静的ソースのみ**で構成（「プロジェクト頻出トップN」の動的算出は事前60GB走査が必要で §8.2 の性能前提と循環し非決定的になるため v1スコープ外＝§14）:

- **型解決依存シンボルの非投入規則（汎用getter爆発の構造的抑止・PRD生命線）**: `extract_chase_symbols` が **getter/setter（メソッド名）として抽出したシンボル**は、tree-sitter が型解決をしない以上、呼び出し元オブジェクトの型同定が不能で `getName`/`getValue` 等が60GBで爆発する。よってこれらは**不動点追跡集合へ投入しない**（横展開しない）。**多ホップ追跡の対象は constant / var 経由のみ**。getter/setter は §8.4 のとおり direct 一致のみ `ref_kind=indirect:getter|setter` / `confidence=low` で報告し、横展開しなかった旨を §8.4 正本として diagnostics に記録。動的トップN無しでも汎用getter爆発を構造的に止める。
- **静的ストップリスト**: ① 言語キーワード／予約語、② 最小長しきい値未満の識別子（`--min-specificity`）、③ ユーザ提供 `--stoplist` ファイル（静的）。これらに該当するシンボルは**追跡集合に入れず、direct一致のみ報告して横展開しない**。
- 集合サイズ上限超過時の切り捨ては**決定的**: シンボルを `(発見ホップ数, 識別子長, 文字列辞書順)` で安定ソートし上限内を採用。
- 横展開を抑止・切り捨てたシンボルは**§8.4 を正本として全件 diagnostics に列挙**。

### 8.4 既知の取りこぼし・抑止の正本（diagnostics に必ず明示）

本節を**唯一の正本**とし、§1/§8.3/§10.3 はここを参照する（重複記述を排除）:

- **型解決を要する getter/setter**: `obj.getX()` の `obj` 型同定不可。同名メソッド全件 `confidence=low`、意味的同一性は人間判断。
- **リフレクション / 動的呼び出し**。
- **実行時の文字列連結・整形で生成される名前**。
- **Pro\*C の `EXEC SQL INCLUDE`・マクロ展開前ソース・`VARCHAR`擬似型**。
- **正規表現方式言語（SQL/Shell）の限界**: 動的生成SQL・heredoc・`eval`・複数行マクロは構文追跡不可。
- **Oracle 固有の追跡境界**: バインド変数 `:var`／置換変数 `&var`／動的SQL（`EXECUTE IMMEDIATE`・文字列連結で組み立てる SQL）・複数行 PL/SQL ブロック内の連鎖は構文追跡不可（§7/§8.1）。**トリガ相関名 `:new`/`:old` および修飾代入 `rec.field := …` の左辺は v1 既知境界**: §8.1 抽出は限定子を剥がした末尾識別子（例 `:new.col := 1`→`col`）を決定的に採るが、相関名・レコードフィールドの意味的同一性は保証しない。汎用名の横展開は Phase 2 の §8.3 静的ストップリストで抑止する前提（v1 はこの挙動を仕様として固定＝誤検出ではない）。
- **C系シェル（csh/tcsh）の限界**: `eval`／`source`／`alias`／バッククォート合成経由は追跡不可。`.cshrc`/`.login` 等の設定ドットファイル（拡張子なし＋典型シェバンなし）は v1 スコープ外。
- **非シェルのシェバン**: `perl`/`python` 等（§14 将来言語）は Shell に分類せず `unsupported_shebang` として記録（§5.1）。
- **生成コード**（既定除外。除外した旨を記録）。
- **§8.3 で横展開を抑止／集合上限で切り捨てたシンボル**（全件列挙）。

diagnostics 出力規約は §10.3。

---

## 9. TSV 出力スキーマ

`output/<keyword>.tsv`。タブ区切り、フィールド内タブ/改行サニタイズ。既定 **UTF-8 with BOM**（Excel互換）。**非UTF-8出力（`--output-encoding cp932` 等）時は BOM を付与しない**。

| 列 | 内容 |
|---|---|
| `keyword` | 調査対象の文言 |
| `language` | 判定言語（Shell は方言不問で "shell" 固定。bourne/cshell は分類・追跡の内部属性＝§5.1/§7） |
| `file` | **`--source-root` からの正規化相対パス・`/`区切り固定** |
| `lineno` | 行番号（Pro\*C も原ソース基準・§7 行番号保存） |
| `ref_kind` | `direct` / `indirect:constant` / `indirect:getter` / `indirect:setter` / `indirect:var` |
| `category` | 共通上位カテゴリ（§7） |
| `category_sub` | 言語固有サブ（§15 で段階導入。**golden 初版は空固定**で churn 回避） |
| `usage_summary` | ★ひと目要約 |
| `via_symbol` | 経由シンボル（direct は空） |
| `chain` | 来歴の正規形（下記） |
| `snippet` | 該当行（タブ/改行除去） |
| `encoding` | 判定文字コード（置換時の「要確認」規約は §10.1 を正本とする） |
| `confidence` | `high`/`medium`/`low`（ヒット単位） |

**chain 正規形（決定性のため必須）**: 各ホップを `symbol@<relpath>:<lineno>` とし ` -> ` で連結（起点→経由→ヒット）。**経路集合の生成・有限化規則**: chain は来歴グラフ上の**単純パス**（同一エッジ・同一シンボルを二度通らない）に限り列挙する。循環は最初の再訪エッジで打ち切り §8.4 正本として diagnostics 記録。`--max-depth` 超過パスも打ち切り。これにより経路集合は**有限かつ決定的**。**同一ヒット（同一snippet行）へ異なる単純パスで到達した場合は経路ごとに別行**（この場合の行重複を許容し、§9 決定性ソートで安定化。重複許容を本スキーマの仕様とする）。

**ref_kind × 言語マッピング:**

| 言語 | constant | var | getter/setter |
|---|---|---|---|
| Java | `static final` 定数 | 非finalフィールド/ローカル | `indirect:getter`/`indirect:setter` |
| C/Pro\*C | `#define`・`const` | 非const変数 | — |
| SQL(Oracle) | — | 同一ファイル PL/SQL `:=` 代入=`indirect:var`（バインド/置換変数は対象外＝§8.4） | — |
| Shell(bourne) | `readonly` 等 | `var=` 代入=`indirect:var` | — |
| Shell(cshell) | — （確実な定数階層なし） | `set`／`setenv`／`@` 代入=`indirect:var` | — |

**決定性（golden前提・必須）**: 出力は**全列を含む全順序**で安定ソート（キー順 `(file, lineno, ref_kind, via_symbol, chain, category, category_sub, confidence, usage_summary, snippet)`）。`multiprocessing` 完了順・走査順に依存しない。

**規模対策**: 1キーワードが Excel 上限（約104万行）超見込みなら `<keyword>.partNN.tsv` 分割＋diagnostics警告。**分割は全順序安定ソート後の順次チャンク**で行う（境界は決定的。golden が割れない）。

---

## 10. 横断事項

### 10.1 文字コード

- バージョン固定 `chardet` で検出 → 決定的フォールバック鎖。**判定は当該ファイル全バイトを対象に1回**（チャンク境界依存を排除）。対象は §8.2 ファイルサイズ上限内。
- **decodeで絶対に落とさない**。置換発生時 `encoding` 列＋diagnostics に「要確認」。
- 入力 `.grep` と走査対象ソース両方に適用。→ PRDメモ「文字コード判定」を解決。

### 10.2 性能

§8.2。

### 10.3 エラー処理・診断・中断/再開

- 壊れたgrep行 / 読めないファイル / decode失敗 / tree-sitter部分パース失敗（部分木で継続）/ `--source-root` 不在 / 権限拒否 / max-depth到達 / 生成コード除外 / §8.4 の各クラス → **diagnostics へ集約**（非致命）。
- **diagnosticsスキーマ**: 先頭に**カテゴリ別件数サマリ**、続いて詳細。詳細上限超過時は**カテゴリ別集約＋代表サンプル**に縮約（上限は設定可能）。
- **TSV 原子性**: 各キーワードTSVは**一時ファイルへ書き出し→`fsync`→`rename`**で原子的に確定。`--resume` は**rename済みのみを完了**とみなす（部分書き込みファイルを完了と誤認しない）。
- **中断/再開**: v1は**キーワード単位 resume 必須**（`--resume` で完了キーワードはスキップ）。**キーワード内チェックポイントは v1スコープ外＝受容リスク**（§14）。
- 終了コードで「致命」と「警告のみ」を区別。

### 10.4 CLI

```
grep_analyzer --input ./input --output ./output --source-root <tree> \
  [--jobs N] [--include GLOB] [--exclude GLOB] [--lang-map EXT=LANG,...] \
  [--max-depth N] [--memory-limit MB] [--min-specificity X] [--stoplist FILE] \
  [--encoding-fallback cp932,euc-jp,latin-1] [--output-encoding cp932] \
  [--use-ripgrep] [--follow-symlinks] [--resume] [--progress LEVEL]
```

- **文字コード解決順は常に「① chardet 検出を最初に試行 → ② フォールバック候補鎖」**。`--encoding-fallback` は**②の候補鎖のみを置換**（検出ステップは常に最初に実行され、CLIでは無効化しない）。未指定時は §10.1 既定鎖。
- `input/` に複数 `<keyword>.grep` 可。出力はキーワード毎TSV ＋ 全体 diagnostics 1ファイル。

---

## 11. テスト方針（リポジトリ規約準拠）

`.claude/skills/writing-tests.md` 準拠（古典学派 + TDD、日本語テスト名、層の縄張り）。

- `tests/unit/`: 分類器（tree-sitterクエリ）・追跡シンボル抽出・シンボル採否（静的ストップリスト）・grep行パース・文字コードフォールバック・**不動点停止性（有限母集合で飽和）**・Pro\*C行番号保存・chain正規形。
- `tests/integration/`: CLI契約・複数keyword・エラー経路・`--resume`原子性・オプション相互作用（in-process 既定）。
- `tests/golden/`: 合成小規模代表ツリーで TSV 完全一致。**カバレッジ原則**: 言語×ref_kind は必須網羅、文字コード/多ホップは pairwise 直交。**必須回帰ケースを名指し**: 汎用名の横展開抑止、決定性タイブレーク（chain複数経路の別行）、Pro\*C `EXEC SQL` 内ホスト変数＋行番号保存、symlink重複排除、文字コード混在（**期待文字コード判定値を pin**）、**Oracle 方言（`:=` 代入・`DECODE`/`CASE WHEN`）**、**C系シェル（`set var =`・拡張子なし＋`#!/bin/csh` でのシェバン判別）**、**拡張子なし bourne（`#!/bin/sh` でのシェバン判別）**、**非シェルシェバンの `unsupported_shebang` 診断**。`category_sub` は初版**空固定**。
- `tests/handcrafted/`: 分類精度ダッシュボード（非ゲート）。
- `tests/test_smoke.py`: `import` ＋ `--help` exit 0 ＋ **tree-sitter バインド/grammar ABI 整合確認**。
- `tests/perf/`: 独自マーカ `@pytest.mark.perf`。handcrafted 同様**ダッシュボード（非ゲート・CI停止しない）**。§8.2 参照基準を回帰検知ベースラインとして記録（絶対SLAではない）。
- LLM無しのため規約のLLM項はN/A。外部I/O境界（ファイル/サブプロセス/ripgrep）は本物。

---

## 12. スコープ外・却下した代替案

- **soot**: JVM依存。tree-sitterで代替。→ 不採用。
- **tree-sitter SQL grammar**: 当初の却下理由は「方言差大」。**v7 再評価: SQL=Oracle 確定により当該理由は弱まり、tree-sitter 化で分類精度（medium→high）と複数行 PL/SQL の §8.1 抽出精度は原理的に向上する。しかし採否を決めるのは精度ではなく §3/§4 のオフライン単一トラック前提**＝Java/C のような Oracle/PL-SQL の公式・abi3・manylinux prebuilt（py-tree-sitter 0.21系ピン整合）grammar が存在せず、採用は sdist ビルド（§3 前提部分失効）・ABI 不整合（R1）・§4.2 相当の新規 G1 を要する。効果も限定的（支配的偽陽性は §8.3/§8.4 の多ホップ getter 爆発であり SQL 行分類ではない）。**よって v1 は SQL=正規表現を維持**し、tree-sitter Oracle/PL-SQL 化は §14 の条件付き将来候補とする。
- → PRDメモ「sootやtree-sitterも有効活用できないか」への回答: **tree-sitter採用（Java/C/Pro\*C基盤）／soot不採用**。

---

## 13. リスクと未決事項

| # | 重大度 | 項目 | 対応 |
|---|---|---|---|
| R1 | High | 必須依存の cp312・対象アーキ wheel 入手性／py-tree-sitter 0.x 破壊変更 | §4.2 G1で実証。完全版ピン＋ロード方式固定、ABI整合をスモーク |
| R2 | High | 多ホップ偽陽性（汎用getter等）／停止性／決定的degrade | §8.3 型解決依存getter/setterは不動点非投入（構造的抑止）＋静的採否＋決定的切り捨て、§8.1停止性論証、§8.4 全件diagnostics |
| R3 | Medium | 60GB実時間／Aho-Corasick＋来歴グラフのメモリ | §8.2 差分走査の限定効果明記＋来歴グラフをmemory-limit対象。`tests/perf/` 実測 |
| R4 | Medium | 型解決不能 getter 等の残存偽陽性 | §8.4 明示・confidence=low。handcrafted監視 |
| R5 | Medium | Pro\*C 前処理の取りこぼし・行番号ズレ | §7 行番号保存を確定。スコープ外分は §8.4。golden に Pro\*C＋行番号ケース |
| R6 | **High** | ターゲットOS/アーキ未確定（§2.1要確定欄） | **§4.2 G1 のブロッキング前提（未充足なら writing-plans 不可・§15 フェーズ0）** |

---

## 14. 今後（v2+）

- 残り言語（Kotlin / PL/SQL / TS・JS / Python / Perl / C#・VB.NET / Groovy）を §5.2 プラグイン経由で追加。
- Shell を tree-sitter-bash 化（任意）。
- **tree-sitter Oracle/PL-SQL grammar 採用**（SQL 分類 medium→high・§8.1 複数行 PL/SQL 抽出精度向上）。**前提条件: §4.2 G1 相当の検証で、py-tree-sitter ピン版（0.21系）ABI と整合する Oracle/PL-SQL grammar の cp312・対象 manylinux prebuilt wheel がオフライン取得可能であること**。不可なら sdist ビルド可否を §3/§4.2 と合わせ意思決定（§12 の再評価を参照）。
- **「プロジェクト頻出トップN」動的ストップリスト**（v1静的のみ。動的化は事前走査の決定的母数定義とともに v2+）。
- キーワード内チェックポイント（再開粒度の精緻化）。

---

## 15. 実装フェーズ分割（writing-plans の前提）

単一実装計画は非現実的。次のフェーズ順で計画する（決定性基盤を間接追跡より先に固める）:

- **フェーズ0（ゲート・着手前提）**: §4.2 G1 充足（wheel 実証・対象アーキ/libc確定）。本フェーズ未通過なら以降着手不可。
- **フェーズ1（決定的コア）**: Ingest / grep行パース / 文字コード / 言語ディスパッチ / 分類器（tree-sitter, Pro\*C行番号保存）/ TSVスキーマ / golden 基盤。**multiホップなし・direct のみで完全決定性と golden を先に確立**。
- **フェーズ1.5（決定的コアの方言精密化・v7 追加）**: §5.1 シェバン検出（拡張子なし判別）＋`.csh`/`.tcsh`、§7 SQL=Oracle 方言精密化・Shell の bourne/cshell 二方言、§8.1 用の Oracle/csh 追跡シンボル抽出規則、対応 golden の決定的拡張。**direct のみ・完全決定性を維持**したまま、Phase 2 の追跡正しさ前提（Oracle/csh 代入抽出）を確立。Phase 2 とは別計画。
- **フェーズ2（不動点エンジン）**: §8.1 反復＋§8.3 採否＋§8.2 来歴集約/性能/degrade。フェーズ1（＋1.5）の決定性基盤上で偽陽性抑止・停止性を実測検証。chain複数経路の決定性を golden で固定。**着手前提: §4.1 `pyahocorasick` の §4.2 G1 相当 wheel 実証（Phase 1 ゲートで未検証＝`phase0-gate-result.md` 申し送り）**。
- **フェーズ3（規模・運用）**: 60GB perf ベースライン、`--resume` 原子性、diagnostics 集約、規模分割。

理由: フェーズ1で「direct のみで完全決定的」を確立する前に多ホップを実装すると、chain/採否/並列集約の非決定性が golden を破壊し続け、writing-tests.md の「大量churn＝構造を疑う」状態に恒常的に陥るため。フェーズ1.5 を Phase 2 の前段に独立させるのも同じ理由 — Oracle/csh の代入抽出（§8.1 の追跡入力）が誤ったまま多ホップを実装すると、Phase 2 の追跡 golden が誤りを恒久固定してしまうため、決定的コアの方言正しさを多ホップ前に確定する。
